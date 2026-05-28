import json
import logging
import tempfile
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)


async def run_profile(ctx, dataset_id: str):
    """Stage 1-2: TDV profiling + entity normalization.

    1. Load dataset record from PostgreSQL to get file_refs
    2. Download uploaded files from MinIO to a temp directory
    3. Run TDV Profiler (Stage 1)
    4. Run Entity Normalizer (Stage 2)
    5. Upload TDV graph + norm graphs to MinIO
    6. Update dataset.profile and dataset.status in PostgreSQL
    7. Publish progress events to Redis
    """
    from circuit_worker.db import get_session
    from circuit_worker.storage import storage
    from circuit_worker.progress import ProgressPublisher

    publisher = ProgressPublisher(ctx["redis"])
    logger.info("Starting profile task for dataset %s", dataset_id)

    try:
        # 1. Load dataset from PostgreSQL
        with get_session() as session:
            from sqlalchemy import text

            row = session.execute(
                text(
                    "SELECT id, name, file_refs, config FROM datasets WHERE id = :id"
                ),
                {"id": dataset_id},
            ).fetchone()

            if not row:
                raise ValueError(f"Dataset {dataset_id} not found")

            dataset_name = row.name
            file_refs = (
                row.file_refs
                if isinstance(row.file_refs, list)
                else json.loads(row.file_refs)
            )
            dataset_config = row.config or {}

            # Update status to profiling
            session.execute(
                text(
                    "UPDATE datasets SET status = 'profiling', updated_at = now() "
                    "WHERE id = :id"
                ),
                {"id": dataset_id},
            )
            session.commit()

        await publisher.publish(run_id=dataset_id, stage="profiling", percent=0.1)

        # 2. Download files from MinIO to temp directory
        with tempfile.TemporaryDirectory(prefix="circuit_profile_") as tmpdir:
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            local_paths = storage.download_dataset_files(dataset_id, str(data_dir))
            if not local_paths:
                raise ValueError(
                    f"No files found in MinIO for dataset {dataset_id}"
                )

            logger.info("Downloaded %d files to %s", len(local_paths), data_dir)
            await publisher.publish(
                run_id=dataset_id, stage="profiling", percent=0.2
            )

            # 3. Run TDV Profiler (Stage 1)
            from circuit_core.data_prep.pipeline import (
                PipelineConfig,
                PreparationPipeline,
            )

            pipeline_config = PipelineConfig(
                data_lake_dir=str(data_dir),
                output_dir=str(output_dir),
                normalization_mode=dataset_config.get(
                    "normalization_mode", "rules"
                ),
                fuzzy_threshold=dataset_config.get("fuzzy_threshold", 80),
                normalize_columns=dataset_config.get("normalize_columns", []),
                skip_columns=dataset_config.get("skip_columns", []),
            )

            pipeline = PreparationPipeline(pipeline_config)
            stage1_result = pipeline.run_stage1_profile()
            logger.info("Stage 1 complete: %s", stage1_result)
            await publisher.publish(
                run_id=dataset_id, stage="profiling", percent=0.5
            )

            # 4. Run Entity Normalizer (Stage 2)
            stage2_result = pipeline.run_stage2_normalize()
            logger.info("Stage 2 complete: %s", stage2_result)
            await publisher.publish(
                run_id=dataset_id, stage="normalizing", percent=0.8
            )

            # 5. Upload graphs to MinIO
            for graph_file in output_dir.glob("*.json"):
                key = f"graphs/{dataset_id}/{graph_file.name}"
                storage.upload_file(
                    key, str(graph_file), content_type="application/json"
                )

            # 6. Build profile data for PostgreSQL
            profile_data = {
                "stage1": stage1_result,
                "stage2": stage2_result,
                "tdv_graph_ref": f"graphs/{dataset_id}/tdv_graph.json",
            }

            # Add norm graph refs
            norm_refs = {}
            for graph_file in output_dir.glob("norm_graph_*.json"):
                col_name = graph_file.stem.replace("norm_graph_", "")
                norm_refs[col_name] = (
                    f"graphs/{dataset_id}/{graph_file.name}"
                )
            profile_data["norm_graph_refs"] = norm_refs

            # 7. Update dataset in PostgreSQL
            with get_session() as session:
                from sqlalchemy import text

                session.execute(
                    text(
                        "UPDATE datasets SET profile = :profile, status = 'profiled', "
                        "updated_at = now() WHERE id = :id"
                    ),
                    {
                        "id": dataset_id,
                        "profile": json.dumps(profile_data, default=str),
                    },
                )
                session.commit()

        await publisher.publish(run_id=dataset_id, stage="profiled", percent=1.0)
        logger.info("Profile task completed for dataset %s", dataset_id)
        return {"status": "profiled", "dataset_id": dataset_id}

    except Exception as e:
        logger.error(
            "Profile task failed for dataset %s: %s",
            dataset_id,
            traceback.format_exc(),
        )

        # Update dataset status to error
        try:
            with get_session() as session:
                from sqlalchemy import text

                session.execute(
                    text(
                        "UPDATE datasets SET status = 'error', updated_at = now() "
                        "WHERE id = :id"
                    ),
                    {"id": dataset_id},
                )
                session.commit()
        except Exception:
            logger.error("Failed to update dataset status to error")

        await publisher.publish(
            run_id=dataset_id, stage="error", percent=0.0
        )
        raise
