"""Parallel layer1 execution using ProcessPoolExecutor."""

from __future__ import annotations

import gc
import logging
import multiprocessing
import time
import traceback
from concurrent.futures import BrokenExecutor, ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field

logger = logging.getLogger("batch-runner.parallel")


@dataclass
class WorkItem:
    """A single segment to process through layer1."""
    scenario_name: str
    segment_id: str
    segment_label: str
    data_path: str
    timestamp_col: str
    value_cols: list[str] | None
    freq: str | None
    baseline_output_dir: str
    result_output_path: str
    lookback_window: str = "90d"
    sensitivity: str = "medium"


@dataclass
class WorkResult:
    """Result from processing a single segment."""
    scenario_name: str
    segment_id: str
    success: bool
    baseline_path: str | None = None
    deviations_count: int = 0
    duration_seconds: float = 0.0
    error: str | None = None
    baseline_result: dict = field(default_factory=dict)
    deviations_result: dict = field(default_factory=dict)


def _run_single_segment(item: WorkItem) -> WorkResult:
    """Worker function — runs baseline + deviations for one segment.

    This runs in a child process. Imports layer1 here to avoid DuckDB singleton.
    """
    start = time.time()

    try:
        from signal_discovery.tools.baseline import run_baseline
        from signal_discovery.tools.deviations import run_deviations

        # Run baseline (Mode 1) — skip matplotlib reports in batch mode
        baseline_result = run_baseline(
            data_path=item.data_path,
            timestamp_col=item.timestamp_col,
            value_cols=item.value_cols,
            freq=item.freq,
            output_dir=item.baseline_output_dir,
            skip_report=True,
        )

        if "error" in baseline_result:
            return WorkResult(
                scenario_name=item.scenario_name,
                segment_id=item.segment_id,
                success=False,
                error=f"Baseline failed: {baseline_result['error']}",
                duration_seconds=time.time() - start,
            )

        baseline_path = baseline_result.get("baseline_path", item.baseline_output_dir)

        # Strip bulky internal arrays — already persisted to parquet by _save_baselines.
        # Keeping them in the result dict wastes memory (100K+ floats per column).
        for bl in baseline_result.get("baselines", []):
            bl.pop("_trend_values", None)
            bl.pop("_residual_values", None)
            bl.pop("_index", None)

        # Free baseline memory before running deviations
        gc.collect()

        # Run deviations (Mode 2)
        deviations_result = run_deviations(
            data_path=item.data_path,
            timestamp_col=item.timestamp_col,
            baseline_path=baseline_path,
            lookback_window=item.lookback_window,
            sensitivity=item.sensitivity,
            value_cols=item.value_cols,
        )

        deviations_count = 0
        if "error" not in deviations_result:
            deviations_count = deviations_result.get("summary", {}).get("total_deviations", 0)

        return WorkResult(
            scenario_name=item.scenario_name,
            segment_id=item.segment_id,
            success=True,
            baseline_path=baseline_path,
            deviations_count=deviations_count,
            duration_seconds=time.time() - start,
            baseline_result=baseline_result,
            deviations_result=deviations_result,
        )

    except Exception as e:
        return WorkResult(
            scenario_name=item.scenario_name,
            segment_id=item.segment_id,
            success=False,
            error=str(e),
            duration_seconds=time.time() - start,
        )


def _run_sequential(items: list[WorkItem]) -> list[WorkResult]:
    """Fallback: run segments sequentially in-process."""
    results: list[WorkResult] = []
    total = len(items)
    for i, item in enumerate(items, 1):
        logger.info("[%d/%d] %s/%s — running in-process...", i, total, item.scenario_name, item.segment_id)
        result = _run_single_segment(item)
        status = "ok" if result.success else f"FAILED: {result.error}"
        logger.info(
            "[%d/%d] %s/%s — %s (%.1fs)",
            i, total, result.scenario_name, result.segment_id,
            status, result.duration_seconds,
        )
        results.append(result)
    return results


def run_layer1_parallel(
    items: list[WorkItem],
    max_workers: int = 4,
) -> list[WorkResult]:
    """Run layer1 baseline + deviations in parallel across segments."""
    if not items:
        return []

    total = len(items)

    # When using a single worker, skip the process pool entirely.
    # Spawn context creates a full Python interpreter copy (~1-2 GB for
    # numpy/pandas/statsmodels), and _safe_stump spawns yet another process.
    # Running in-process avoids that overhead.
    if max_workers <= 1:
        logger.info("Running %d segments sequentially (single worker)", total)
        return _run_sequential(items)

    logger.info("Dispatching %d segments across %d workers", total, max_workers)

    # Use explicit spawn context — don't rely on global set_start_method
    # which silently fails if the method was already frozen (e.g. by fork default on Linux).
    # Spawn gives clean child processes without DuckDB singleton leakage.
    ctx = multiprocessing.get_context("spawn")

    results: list[WorkResult] = []
    pool_broken = False

    try:
        with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as executor:
            future_to_item = {
                executor.submit(_run_single_segment, item): item
                for item in items
            }

            for i, future in enumerate(as_completed(future_to_item), 1):
                item = future_to_item[future]
                try:
                    result = future.result()
                except BrokenExecutor as e:
                    logger.error(
                        "Process pool broken: %s. Remaining segments will run sequentially.",
                        e,
                    )
                    pool_broken = True
                    break
                except Exception as e:
                    logger.error(
                        "Worker exception for %s/%s: %s\n%s",
                        item.scenario_name, item.segment_id, e,
                        traceback.format_exc(),
                    )
                    result = WorkResult(
                        scenario_name=item.scenario_name,
                        segment_id=item.segment_id,
                        success=False,
                        error=f"Process error: {e}",
                    )

                status = "ok" if result.success else f"FAILED: {result.error}"
                logger.info(
                    "[%d/%d] %s/%s — %s (%.1fs)",
                    i, total, result.scenario_name, result.segment_id,
                    status, result.duration_seconds,
                )
                results.append(result)

    except BrokenExecutor as e:
        logger.error("Process pool failed to start: %s", e)
        pool_broken = True

    if pool_broken:
        # Collect items that haven't been processed yet
        completed_keys = {(r.scenario_name, r.segment_id) for r in results}
        remaining = [
            item for item in items
            if (item.scenario_name, item.segment_id) not in completed_keys
        ]
        logger.info(
            "Falling back to sequential execution for %d/%d remaining segments",
            len(remaining), total,
        )
        results.extend(_run_sequential(remaining))

    return results
