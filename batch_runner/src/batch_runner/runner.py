"""Orchestration: load -> clean -> segment -> dispatch -> collect."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from batch_runner.manifest import Manifest, ScenarioDef
from batch_runner.parallel import WorkItem, WorkResult, run_layer1_parallel

logger = logging.getLogger("batch-runner.runner")


def run_batch(
    manifest: Manifest,
    run_dir: Path,
    max_workers: int = 4,
) -> dict:
    """Run the full batch pipeline.

    Sequential (main process, DuckDB singleton):
        load -> clean -> segment per scenario

    Parallel (ProcessPoolExecutor, spawn mode):
        baseline + deviations per segment
    """
    start_time = time.time()
    errors: list[str] = []

    # ── Initialize DuckDB in run_dir (avoids conflicts with MCP server) ─
    _init_backend(run_dir)

    # ── Phase 1: Load dataset (sequential, DuckDB) ──────────────────────
    logger.info("Loading dataset: %s", manifest.data_path)
    from data_loader.tools.load import run_load

    load_result = run_load(manifest.data_path, manifest.dataset_name)
    if "error" in load_result:
        raise RuntimeError(f"Failed to load dataset: {load_result['error']}")

    logger.info(
        "Loaded %s: %d rows, %d columns",
        load_result["dataset_id"],
        load_result["file_info"]["rows"],
        load_result["file_info"]["columns"],
    )

    # ── Phase 2: Clean dataset (sequential, DuckDB) ─────────────────────
    from data_loader.tools.clean import run_clean_dataset

    if manifest.clean.auto_detect:
        logger.info("Auto-detecting data quality issues...")
        detect_result = run_clean_dataset(
            dataset_id=manifest.dataset_name,
            auto_detect=True,
        )
        issues_found = detect_result.get("issues_found", 0)
        logger.info("Detected %d issues", issues_found)

    if manifest.clean.apply_operations:
        logger.info("Applying %d cleaning operations...", len(manifest.clean.apply_operations))
        clean_result = run_clean_dataset(
            dataset_id=manifest.dataset_name,
            operations=manifest.clean.apply_operations,
            apply=True,
        )
        applied = clean_result.get("operations_applied", 0)
        failed = clean_result.get("operations_failed", 0)
        logger.info("Applied %d operations (%d failed)", applied, failed)
        if clean_result.get("errors"):
            for err in clean_result["errors"]:
                errors.append(f"Clean: {err}")

    # ── Phase 2.5: Normalization (sequential, DuckDB) ──────────────────
    _apply_normalization(manifest)

    # ── Phase 3: Segment per scenario (sequential, DuckDB) ──────────────
    from data_loader.tools.batch_create import run_create_segments

    all_work_items: list[WorkItem] = []
    scenario_results: dict[str, dict] = {}

    for scenario in manifest.scenarios:
        logger.info("Segmenting scenario: %s (by %s)", scenario.name, scenario.segment_by)

        scenario_dir = run_dir / scenario.name
        segments_dir = scenario_dir / "segments"
        segments_dir.mkdir(parents=True, exist_ok=True)

        seg_result = run_create_segments(
            dataset_id=manifest.dataset_name,
            segment_by=scenario.segment_by,
            timestamp_col=manifest.timestamp_col,
            value_cols=manifest.value_cols,
            min_segment_size=scenario.min_segment_size,
            export_format="parquet",
            export_dir=str(segments_dir),
        )

        if "error" in seg_result:
            errors.append(f"Segment {scenario.name}: {seg_result['error']}")
            scenario_results[scenario.name] = {"error": seg_result["error"]}
            continue

        n_created = seg_result.get("segments_created", 0)
        n_dropped = seg_result.get("segments_dropped", 0)
        logger.info(
            "Scenario %s: %d segments created, %d dropped (below min_size)",
            scenario.name, n_created, n_dropped,
        )

        scenario_results[scenario.name] = {
            "segments_created": n_created,
            "segments_dropped": n_dropped,
        }

        # Build work items for parallel phase
        baselines_dir = scenario_dir / "baselines"
        results_dir = scenario_dir / "results"
        results_dir.mkdir(parents=True, exist_ok=True)

        for seg in seg_result.get("segments", []):
            if not seg.get("export_path"):
                continue

            segment_id = seg["segment_id"]

            # Skip NaN/NULL catch-all segments — they contain unmatched rows
            # from normalization and are too large / not useful for analysis.
            filter_vals = seg.get("filter_values", {})
            has_nan = any(
                v is None or (isinstance(v, str) and v.lower() in ("nan", "null", "none", ""))
                for v in filter_vals.values()
            )
            if not filter_vals:
                # Fallback: check segment_id
                has_nan = segment_id.endswith("_nan")
            if has_nan:
                logger.info("Skipping catch-all segment %s (filter=%s)", segment_id, filter_vals)
                continue
            baseline_out = str(baselines_dir / segment_id)
            result_out = str(results_dir / f"{segment_id}.json")

            all_work_items.append(WorkItem(
                scenario_name=scenario.name,
                segment_id=segment_id,
                segment_label=seg["label"],
                data_path=seg["export_path"],
                timestamp_col=manifest.timestamp_col,
                value_cols=manifest.value_cols,
                freq=manifest.freq,
                baseline_output_dir=baseline_out,
                result_output_path=result_out,
                lookback_window=manifest.deviations.lookback_window,
                sensitivity=manifest.deviations.sensitivity,
            ))

    # ── Free DuckDB before heavy computation ────────────────────────────
    # Phases 1-3 are done; workers read from exported parquet files.
    # Releasing DuckDB reclaims memory for baseline + deviation processing.
    _cleanup_backend(run_dir)

    # ── Phase 4: Parallel layer1 execution ──────────────────────────────
    logger.info("Dispatching %d segments to %d workers...", len(all_work_items), max_workers)

    work_results = run_layer1_parallel(all_work_items, max_workers=max_workers)

    # ── Phase 5: Collect results ────────────────────────────────────────
    baselines_ok = 0
    deviations_ok = 0

    for result in work_results:
        if result.success:
            baselines_ok += 1
            if result.deviations_result and "error" not in result.deviations_result:
                deviations_ok += 1
        else:
            errors.append(f"{result.scenario_name}/{result.segment_id}: {result.error}")

        # Write per-segment result JSON (report-agent compatible)
        _write_segment_result(result)

    # ── Write batch summary ─────────────────────────────────────────────
    duration = time.time() - start_time

    summary = {
        "run_dir": str(run_dir),
        "manifest_data_path": manifest.data_path,
        "dataset_name": manifest.dataset_name,
        "scenarios_total": len(manifest.scenarios),
        "scenarios_completed": sum(1 for s in scenario_results.values() if "error" not in s),
        "segments_total": len(all_work_items),
        "baselines_succeeded": baselines_ok,
        "deviations_succeeded": deviations_ok,
        "errors": errors if errors else None,
        "duration_seconds": round(duration, 1),
        "scenarios": scenario_results,
    }

    summary_path = run_dir / "batch_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info("Batch summary written to %s", summary_path)

    # Clean up transient DuckDB (it's just a processing cache)
    _cleanup_backend(run_dir)

    return summary


def _apply_normalization(manifest: Manifest) -> None:
    """Apply entity normalization by creating lookup tables and joining hierarchy columns.

    Short-circuits if normalization is not enabled in the manifest.
    For each column in lookup_sql:
      1. Execute the SQL to create a per-column lookup table
      2. LEFT JOIN onto the dataset table, adding norm_{col}_{level} columns
      3. Drop the temporary lookup table
    """
    if not manifest.normalization.enabled:
        return

    if not manifest.normalization.lookup_sql:
        logger.info("Normalization enabled but no lookup_sql provided, skipping")
        return

    import data_loader.storage as storage

    backend = storage._backend
    if backend is None:
        logger.warning("No DuckDB backend available for normalization")
        return

    db = backend._conn
    dataset_table = manifest.dataset_name

    for col_name, lookup_sql in manifest.normalization.lookup_sql.items():
        lookup_table = f"_norm_lookup_{col_name}"

        logger.info("Normalizing column '%s' via lookup table '%s'", col_name, lookup_table)

        # Create the lookup table
        db.execute(lookup_sql)

        # Discover hierarchy level columns from the lookup table
        lookup_cols = db.execute(f"DESCRIBE {lookup_table}").fetchall()
        level_cols = [c[0] for c in lookup_cols if c[0] != 'raw_value']

        # Build SELECT with prefixed hierarchy columns
        join_cols = ", ".join(
            f'_lk."{lc}" AS "norm_{col_name}_{lc}"'
            for lc in level_cols
        )

        # LEFT JOIN onto the dataset
        db.execute(f"""
            CREATE OR REPLACE TABLE {dataset_table} AS
            SELECT t.*, {join_cols}
            FROM {dataset_table} t
            LEFT JOIN {lookup_table} _lk
            ON CAST(t."{col_name}" AS VARCHAR) = CAST(_lk.raw_value AS VARCHAR)
        """)

        # Drop the temporary lookup table
        db.execute(f"DROP TABLE IF EXISTS {lookup_table}")

        row_count = db.execute(f"SELECT COUNT(*) FROM {dataset_table}").fetchone()[0]
        logger.info(
            "Normalization for '%s': added columns [%s], %d rows",
            col_name,
            ", ".join(f"norm_{col_name}_{lc}" for lc in level_cols),
            row_count,
        )


def _write_segment_result(result: WorkResult) -> None:
    """Write a per-segment result JSON compatible with report-agent."""
    output_path = None

    # Find the output path from the work items via the result
    # The result_output_path is stored in the WorkItem but not in WorkResult,
    # so we reconstruct it from baseline_path
    if result.baseline_path:
        # baseline_path is like .../baselines/{segment_id}
        # result goes to .../results/{segment_id}.json
        baseline_dir = Path(result.baseline_path)
        results_dir = baseline_dir.parent.parent / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        output_path = results_dir / f"{result.segment_id}.json"

    if not output_path:
        return

    doc = {
        "segment_id": result.segment_id,
        "scenario_name": result.scenario_name,
        "success": result.success,
        "duration_seconds": round(result.duration_seconds, 2),
    }

    if result.success:
        # Strip internal keys (prefixed with _) from baseline results
        baseline_clean = {
            k: v for k, v in result.baseline_result.items()
            if not k.startswith("_")
        }
        doc["baseline"] = baseline_clean
        doc["deviations"] = result.deviations_result
    else:
        doc["error"] = result.error

    with open(output_path, "w") as f:
        json.dump(doc, f, indent=2, default=str)


def _init_backend(run_dir: Path) -> None:
    """Force the layer0 DuckDB singleton to use a run-specific database.

    This avoids lock conflicts with any running MCP server that holds
    a lock on the default signal.duckdb in the data directory.
    """
    import data_loader.storage as storage

    if storage._backend is not None:
        return  # Already initialized (e.g. tests)

    import duckdb

    db_path = str(run_dir / "batch.duckdb")
    storage._backend = storage.DuckDBBackend(db_path)
    logger.info("Initialized batch DuckDB at %s", db_path)


def _cleanup_backend(run_dir: Path) -> None:
    """Close DuckDB connection and remove the transient database file."""
    import data_loader.storage as storage

    backend = storage._backend
    if backend and hasattr(backend, "_conn"):
        try:
            backend._conn.close()
        except Exception:
            pass
    storage._backend = None

    db_path = run_dir / "batch.duckdb"
    if db_path.exists():
        db_path.unlink()
        logger.info("Removed transient DuckDB: %s", db_path)
    # Also remove WAL file if present
    wal_path = run_dir / "batch.duckdb.wal"
    if wal_path.exists():
        wal_path.unlink()
