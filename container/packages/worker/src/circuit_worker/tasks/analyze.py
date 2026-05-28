import json
import logging
import tempfile
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)


async def run_analysis(ctx, run_id: str):
    """Stages 3-6: Plan, batch execution, reporting, signal registration.

    1. Load the analysis_run record from PostgreSQL (get manifest, dataset_id)
    2. Load the dataset record to get file_refs and profile
    3. Download uploaded files from MinIO to a temp directory
    4. Download TDV graph + norm graphs from MinIO (stored during profiling)
    5. Build execution plan (Stage 3) OR use pre-built manifest
    6. Run batch_runner.run_batch() (Stage 4)
    7. Upload results (segments, baselines, results JSONs) to MinIO
    8. Register signals in PostgreSQL (Stage 6)
    9. Update run status throughout
    """
    from sqlalchemy import text

    from circuit_worker.config import config
    from circuit_worker.db import get_session
    from circuit_worker.progress import ProgressPublisher
    from circuit_worker.storage import storage

    publisher = ProgressPublisher(ctx["redis"])
    logger.info("Starting analysis task for run %s", run_id)

    try:
        # 1. Load run and dataset from PostgreSQL
        with get_session() as session:
            run_row = session.execute(
                text(
                    "SELECT id, dataset_id, manifest "
                    "FROM analysis_runs WHERE id = :id"
                ),
                {"id": run_id},
            ).fetchone()

            if not run_row:
                raise ValueError(f"Run {run_id} not found")

            dataset_id = str(run_row.dataset_id)
            run_manifest = (
                run_row.manifest
                if isinstance(run_row.manifest, dict)
                else json.loads(run_row.manifest)
            )

            dataset_row = session.execute(
                text(
                    "SELECT id, name, file_refs, profile, config "
                    "FROM datasets WHERE id = :id"
                ),
                {"id": dataset_id},
            ).fetchone()

            if not dataset_row:
                raise ValueError(f"Dataset {dataset_id} not found")

            dataset_name = dataset_row.name
            file_refs = (
                dataset_row.file_refs
                if isinstance(dataset_row.file_refs, list)
                else json.loads(dataset_row.file_refs)
            )
            profile = dataset_row.profile or {}
            dataset_config = dataset_row.config or {}

            # Update run status
            session.execute(
                text(
                    "UPDATE analysis_runs SET status = 'analyzing', "
                    "started_at = now() WHERE id = :id"
                ),
                {"id": run_id},
            )
            session.commit()

        await publisher.publish(run_id=run_id, stage="downloading", percent=0.05)

        # 2. Download files to temp directory
        with tempfile.TemporaryDirectory(prefix="circuit_analysis_") as tmpdir:
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()
            run_dir = Path(tmpdir) / "run"
            run_dir.mkdir()
            graphs_dir = Path(tmpdir) / "graphs"
            graphs_dir.mkdir()

            # Download data files
            local_paths = storage.download_dataset_files(
                dataset_id, str(data_dir)
            )
            if not local_paths:
                raise ValueError(
                    f"No files found in MinIO for dataset {dataset_id}"
                )

            logger.info("Downloaded %d data files", len(local_paths))

            # Download graphs from profiling (if they exist)
            try:
                tdv_graph_ref = profile.get(
                    "tdv_graph_ref", f"graphs/{dataset_id}/tdv_graph.json"
                )
                storage.download_file(
                    tdv_graph_ref, str(graphs_dir / "tdv_graph.json")
                )

                for col_name, ref in profile.get(
                    "norm_graph_refs", {}
                ).items():
                    storage.download_file(
                        ref, str(graphs_dir / f"norm_graph_{col_name}.json")
                    )
            except Exception as e:
                logger.warning("Could not download graphs: %s", e)

            await publisher.publish(
                run_id=run_id, stage="building_manifest", percent=0.1
            )

            # 3. Build manifest
            manifest = _build_manifest(
                run_manifest=run_manifest,
                local_paths=local_paths,
                dataset_name=dataset_name,
                dataset_config=dataset_config,
                data_dir=data_dir,
                graphs_dir=graphs_dir,
            )

            # Store the resolved manifest back
            with get_session() as session:
                session.execute(
                    text(
                        "UPDATE analysis_runs SET manifest = :manifest "
                        "WHERE id = :id"
                    ),
                    {
                        "id": run_id,
                        "manifest": json.dumps(
                            _manifest_to_dict(manifest), default=str
                        ),
                    },
                )
                session.commit()

            await publisher.publish(
                run_id=run_id, stage="executing", percent=0.15
            )

            # 4. Run batch pipeline (Stage 4)
            from circuit_core.batch_runner.runner import run_batch

            summary = run_batch(
                manifest=manifest,
                run_dir=run_dir,
                max_workers=config.BATCH_PARALLEL_WORKERS,
            )

            logger.info(
                "Batch complete: %d/%d baselines, %d deviations, %.1fs",
                summary["baselines_succeeded"],
                summary["segments_total"],
                summary["deviations_succeeded"],
                summary["duration_seconds"],
            )

            # Update progress
            with get_session() as session:
                session.execute(
                    text(
                        "UPDATE analysis_runs SET progress = :progress "
                        "WHERE id = :id"
                    ),
                    {
                        "id": run_id,
                        "progress": json.dumps(
                            {
                                "segments_total": summary["segments_total"],
                                "baselines_succeeded": summary[
                                    "baselines_succeeded"
                                ],
                                "deviations_succeeded": summary[
                                    "deviations_succeeded"
                                ],
                            }
                        ),
                    },
                )
                session.commit()

            await publisher.publish(
                run_id=run_id, stage="uploading", percent=0.7
            )

            # 5. Upload results to MinIO
            storage.upload_directory(str(run_dir), f"results/{run_id}")
            logger.info("Uploaded results to MinIO: results/%s", run_id)

            await publisher.publish(
                run_id=run_id, stage="registering", percent=0.8
            )

            # 6. Register signals in PostgreSQL
            signals_registered = _register_signals(
                run_dir=run_dir,
                run_id=run_id,
                dataset_id=dataset_id,
                dataset_name=dataset_name,
                manifest=manifest,
            )

            logger.info("Registered %d signals", signals_registered)

            # 7. Mark run as completed
            result_refs = {
                "run_dir": f"results/{run_id}",
                "summary": f"results/{run_id}/batch_summary.json",
            }

            with get_session() as session:
                session.execute(
                    text(
                        "UPDATE analysis_runs SET status = 'completed', "
                        "result_refs = :refs, completed_at = now(), "
                        "progress = :progress WHERE id = :id"
                    ),
                    {
                        "id": run_id,
                        "refs": json.dumps(result_refs),
                        "progress": json.dumps(
                            {
                                "segments_total": summary["segments_total"],
                                "baselines_succeeded": summary[
                                    "baselines_succeeded"
                                ],
                                "deviations_succeeded": summary[
                                    "deviations_succeeded"
                                ],
                                "signals_registered": signals_registered,
                            }
                        ),
                    },
                )
                session.commit()

        await publisher.publish(run_id=run_id, stage="completed", percent=1.0)
        logger.info("Analysis task completed for run %s", run_id)
        return {
            "status": "completed",
            "run_id": run_id,
            "signals_registered": signals_registered,
        }

    except Exception as e:
        logger.error(
            "Analysis task failed for run %s: %s",
            run_id,
            traceback.format_exc(),
        )

        try:
            with get_session() as session:
                session.execute(
                    text(
                        "UPDATE analysis_runs SET status = 'failed', "
                        "error = :error, completed_at = now() WHERE id = :id"
                    ),
                    {"id": run_id, "error": str(e)},
                )
                session.commit()
        except Exception:
            logger.error("Failed to update run status to failed")

        await publisher.publish(run_id=run_id, stage="error", percent=0.0)
        raise


def _build_manifest(
    run_manifest: dict,
    local_paths: list[str],
    dataset_name: str,
    dataset_config: dict,
    data_dir: Path,
    graphs_dir: Path,
):
    """Build a Manifest object from run config or auto-generate from profile."""
    from circuit_core.batch_runner.manifest import (
        CleanConfig,
        DeviationConfig,
        Manifest,
        NormalizationConfig,
        ScenarioDef,
    )

    if run_manifest.get("scenarios"):
        # Use the pre-built manifest supplied by the caller
        scenarios = [
            ScenarioDef(
                name=s["name"],
                segment_by=s["segment_by"],
                min_segment_size=s.get("min_segment_size", 50),
            )
            for s in run_manifest["scenarios"]
        ]

        raw_clean = run_manifest.get("clean", {})
        raw_norm = run_manifest.get("normalization", {})
        raw_dev = run_manifest.get("deviations", {})

        return Manifest(
            data_path=local_paths[0],
            dataset_name=dataset_name,
            timestamp_col=run_manifest.get("timestamp_col", ""),
            scenarios=scenarios,
            freq=run_manifest.get("freq"),
            value_cols=run_manifest.get("value_cols"),
            clean=CleanConfig(
                auto_detect=raw_clean.get("auto_detect", True),
                apply_operations=raw_clean.get("apply_operations"),
            ),
            normalization=NormalizationConfig(
                enabled=raw_norm.get("enabled", False),
                lookup_sql=raw_norm.get("lookup_sql", {}),
                enrichment_columns=raw_norm.get("enrichment_columns", []),
                hierarchy_levels=raw_norm.get("hierarchy_levels", []),
            ),
            deviations=DeviationConfig(
                lookback_window=raw_dev.get("lookback_window", "90d"),
                sensitivity=raw_dev.get("sensitivity", "medium"),
            ),
        )

    # No scenarios provided -- auto-generate from profile via PreparationPipeline
    from circuit_core.data_prep.pipeline import (
        PipelineConfig,
        PreparationPipeline,
    )

    pipeline_config = PipelineConfig(
        data_lake_dir=str(data_dir),
        output_dir=str(graphs_dir),
        normalization_mode=dataset_config.get("normalization_mode", "rules"),
        fuzzy_threshold=dataset_config.get("fuzzy_threshold", 80),
    )
    pipeline = PreparationPipeline(pipeline_config)

    # Build plan from existing graphs
    tdv_graph_path = str(graphs_dir / "tdv_graph.json")
    if Path(tdv_graph_path).exists():
        plan = pipeline.run_stage3_plan(tdv_graph_path=tdv_graph_path)
    else:
        # No graphs -- run profiling first
        pipeline.run_stage1_profile()
        plan = pipeline.run_stage3_plan()

    manifest_dict = pipeline.generate_manifest(
        plan=plan,
        data_path=local_paths[0],
        dataset_name=dataset_name,
    )

    scenarios = [
        ScenarioDef(
            name=s["name"],
            segment_by=s["segment_by"],
            min_segment_size=s.get("min_segment_size", 50),
        )
        for s in manifest_dict.get("scenarios", [])
    ]

    if not scenarios:
        raise ValueError(
            "No scenarios generated from profile -- check dataset configuration"
        )

    raw_clean = manifest_dict.get("clean", {})
    raw_norm = manifest_dict.get("normalization", {})
    raw_dev = manifest_dict.get("deviations", {})

    return Manifest(
        data_path=local_paths[0],
        dataset_name=dataset_name,
        timestamp_col=manifest_dict.get("timestamp_col", ""),
        scenarios=scenarios,
        freq=manifest_dict.get("freq"),
        value_cols=manifest_dict.get("value_cols"),
        clean=CleanConfig(
            auto_detect=raw_clean.get("auto_detect", True),
        ),
        normalization=NormalizationConfig(
            enabled=raw_norm.get("enabled", False),
            lookup_sql=raw_norm.get("lookup_sql", {}),
            enrichment_columns=raw_norm.get("enrichment_columns", []),
            hierarchy_levels=raw_norm.get("hierarchy_levels", []),
        ),
        deviations=DeviationConfig(
            lookback_window=raw_dev.get("lookback_window", "90d"),
            sensitivity=raw_dev.get("sensitivity", "medium"),
        ),
    )


def _register_signals(
    run_dir: Path,
    run_id: str,
    dataset_id: str,
    dataset_name: str,
    manifest,
) -> int:
    """Scan result JSONs and insert signals into PostgreSQL."""
    from sqlalchemy import text

    from circuit_worker.db import get_session

    from circuit_core.signal_registry import prepare_signal_record

    count = 0

    for scenario in manifest.scenarios:
        results_dir = run_dir / scenario.name / "results"
        if not results_dir.exists():
            continue

        for result_file in results_dir.glob("*.json"):
            try:
                with open(result_file) as f:
                    result = json.load(f)

                if not result.get("success"):
                    continue

                segment_id = result["segment_id"]
                baseline = result.get("baseline", {})
                deviations = result.get("deviations", {})

                signal_id = f"{dataset_name}:{scenario.name}:{segment_id}:{run_id}"

                # Extract metrics from nested baseline structure
                # baseline.baselines[0] has the primary column's decomposition
                baselines_list = baseline.get("baselines", [])
                bl0 = baselines_list[0] if baselines_list else {}
                trend_info = bl0.get("trend", {})
                residual_info = bl0.get("residual_profile", {})
                seasonality_list = bl0.get("seasonality", [])
                ds_summary = baseline.get("dataset_summary", {})

                total_points = ds_summary.get("rows", 1)
                trend_slope = trend_info.get("rate_per_period")
                trend_direction = trend_info.get("direction", "flat")
                seasonality_strength = (
                    seasonality_list[0].get("strength")
                    if seasonality_list
                    else None
                )
                residual_std = residual_info.get("std")
                variance_explained = bl0.get("variance_explained")
                residual_kurtosis = residual_info.get("kurtosis")

                # Change points come from baseline trend, not deviations
                change_points = trend_info.get("change_points", [])

                # Deviation metrics from nested structure
                dev_summary = deviations.get("summary", {})
                dev_list = deviations.get("deviations", [])
                dev_count = dev_summary.get(
                    "total_deviations", len(dev_list)
                )
                by_severity = dev_summary.get("by_severity", {})
                critical_count = by_severity.get("critical", 0)
                deviation_density = dev_count / max(total_points, 1)
                critical_pct = (
                    critical_count / max(dev_count, 1)
                    if dev_count > 0
                    else 0.0
                )

                # Determine temporal grain from manifest
                temporal_grain = manifest.freq or "daily"

                segment_by = scenario.segment_by
                if not isinstance(segment_by, str):
                    segment_by = segment_by[0]

                # Build time_range from baseline dataset_summary
                time_range_val = None
                time_range_obj = ds_summary.get("time_range", {})
                ts_start = time_range_obj.get("start")
                ts_end = time_range_obj.get("end")
                if ts_start and ts_end:
                    time_range_val = f"[{ts_start},{ts_end}]"

                # Prepare signal record with embeddings and descriptions
                enriched = prepare_signal_record(
                    result_json=result,
                    freq=temporal_grain,
                    dataset_name=dataset_name,
                    segment_id=segment_id,
                )

                params = {
                    "signal_id": signal_id,
                    "dataset_id": dataset_id,
                    "run_id": run_id,
                    "dataset_name": dataset_name,
                    "segment": segment_id,
                    "segment_by": segment_by,
                    "temporal_grain": temporal_grain,
                    "row_count": total_points,
                    "time_range": time_range_val,
                    "trend_slope": trend_slope,
                    "trend_intercept": None,
                    "seasonality_strength": seasonality_strength,
                    "residual_std": residual_std,
                    "deviation_count_90d": dev_count,
                    "deviation_density": round(deviation_density, 6),
                    "critical_pct": round(critical_pct, 4),
                    "change_points": json.dumps(change_points, default=str)
                    if change_points
                    else None,
                    "tags": json.dumps({"scenario": scenario.name}),
                    # Phase 6: seasonal arrays + embeddings + description
                    "seasonal_weekly": enriched.get("seasonal_weekly"),
                    "seasonal_hourly": enriched.get("seasonal_hourly"),
                    "seasonal_monthly": enriched.get("seasonal_monthly"),
                    "shape_embedding": str(enriched["shape_embedding"])
                    if enriched.get("shape_embedding")
                    else None,
                    "deviation_embedding": str(enriched["deviation_embedding"])
                    if enriched.get("deviation_embedding")
                    else None,
                    "text_description": enriched.get("text_description"),
                    "text_embedding": str(enriched["text_embedding"])
                    if enriched.get("text_embedding")
                    else None,
                }

                with get_session() as session:
                    # Supersede any existing active signal for this
                    # dataset:segment combination
                    session.execute(
                        text(
                            "UPDATE signals SET status = 'superseded', "
                            "superseded_by = :new_id, updated_at = now() "
                            "WHERE dataset_name = :dataset_name "
                            "AND segment = :segment AND status = 'active'"
                        ),
                        {
                            "new_id": signal_id,
                            "dataset_name": dataset_name,
                            "segment": segment_id,
                        },
                    )

                    session.execute(
                        text("""
                            INSERT INTO signals (
                                signal_id, dataset_id, run_id, dataset_name,
                                segment, segment_by, temporal_grain, row_count,
                                time_range, trend_slope, trend_intercept,
                                seasonality_strength, residual_std,
                                deviation_count_90d, deviation_density,
                                critical_pct, change_points, tags,
                                seasonal_weekly, seasonal_hourly,
                                seasonal_monthly, shape_embedding,
                                deviation_embedding, text_description,
                                text_embedding, status
                            ) VALUES (
                                :signal_id, :dataset_id, :run_id,
                                :dataset_name, :segment, :segment_by,
                                :temporal_grain, :row_count, :time_range,
                                :trend_slope, :trend_intercept,
                                :seasonality_strength, :residual_std,
                                :deviation_count_90d, :deviation_density,
                                :critical_pct,
                                CAST(:change_points AS jsonb),
                                CAST(:tags AS jsonb),
                                :seasonal_weekly,
                                :seasonal_hourly, :seasonal_monthly,
                                CAST(:shape_embedding AS vector),
                                CAST(:deviation_embedding AS vector),
                                :text_description,
                                CAST(:text_embedding AS vector), 'active'
                            )
                        """),
                        params,
                    )
                    # Insert individual deviation records
                    for dev in dev_list:
                        ts_range = dev.get("timestamp_range", {})
                        details = dev.get("details", {})
                        ts_start = ts_range.get("start")
                        ts_end = ts_range.get("end")
                        if not ts_start:
                            continue
                        session.execute(
                            text("""
                                INSERT INTO deviations (
                                    signal_id, dataset_id, run_id,
                                    dataset_name, segment, segment_by,
                                    column_name, deviation_type,
                                    severity, persistence,
                                    timestamp_start, timestamp_end,
                                    expected_value, observed_value,
                                    deviation_magnitude, z_score,
                                    confidence, narrative
                                ) VALUES (
                                    :signal_id, :dataset_id, :run_id,
                                    :dataset_name, :segment, :segment_by,
                                    :column_name, :deviation_type,
                                    :severity, :persistence,
                                    :timestamp_start, :timestamp_end,
                                    :expected_value, :observed_value,
                                    :deviation_magnitude, :z_score,
                                    :confidence, :narrative
                                )
                            """),
                            {
                                "signal_id": signal_id,
                                "dataset_id": dataset_id,
                                "run_id": run_id,
                                "dataset_name": dataset_name,
                                "segment": segment_id,
                                "segment_by": segment_by,
                                "column_name": dev.get(
                                    "column", "unknown"
                                ),
                                "deviation_type": dev.get(
                                    "type", "unknown"
                                ),
                                "severity": dev.get("severity", "low"),
                                "persistence": dev.get("persistence"),
                                "timestamp_start": ts_start,
                                "timestamp_end": ts_end or ts_start,
                                "expected_value": details.get(
                                    "expected_value"
                                ),
                                "observed_value": details.get(
                                    "observed_value"
                                ),
                                "deviation_magnitude": details.get(
                                    "deviation_magnitude"
                                ),
                                "z_score": details.get("z_score"),
                                "confidence": details.get("confidence"),
                                "narrative": dev.get("narrative"),
                            },
                        )

                    session.commit()
                    count += 1

            except Exception as e:
                logger.warning(
                    "Failed to register signal from %s: %s",
                    result_file.name,
                    e,
                )

    return count


def _manifest_to_dict(manifest) -> dict:
    """Convert a Manifest dataclass to a JSON-serializable dict."""
    return {
        "data_path": manifest.data_path,
        "dataset_name": manifest.dataset_name,
        "timestamp_col": manifest.timestamp_col,
        "freq": manifest.freq,
        "value_cols": manifest.value_cols,
        "scenarios": [
            {
                "name": s.name,
                "segment_by": s.segment_by,
                "min_segment_size": s.min_segment_size,
            }
            for s in manifest.scenarios
        ],
        "clean": {
            "auto_detect": manifest.clean.auto_detect,
            "apply_operations": manifest.clean.apply_operations,
        },
        "normalization": {
            "enabled": manifest.normalization.enabled,
            "lookup_sql": manifest.normalization.lookup_sql,
            "enrichment_columns": manifest.normalization.enrichment_columns,
            "hierarchy_levels": manifest.normalization.hierarchy_levels,
        },
        "deviations": {
            "lookback_window": manifest.deviations.lookback_window,
            "sensitivity": manifest.deviations.sensitivity,
        },
    }
