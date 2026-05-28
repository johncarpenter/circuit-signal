"""Signal registry — embedding extraction and database registration.

Orchestrates seasonal array extraction, shape/deviation/text embedding
computation, and text description generation for signal INSERT records.
"""

import logging

from circuit_core.signal_registry.describe import generate_description
from circuit_core.signal_registry.embeddings import (
    compute_deviation_embedding,
    compute_shape_embedding,
    compute_text_embedding,
)
from circuit_core.signal_registry.extract import extract_seasonal_arrays

logger = logging.getLogger(__name__)


def prepare_signal_record(
    result_json: dict,
    freq: str,
    dataset_name: str = "",
    segment_id: str = "",
) -> dict:
    """Orchestrate extract + embeddings + describe for one segment result.

    Args:
        result_json: The full result dict for a segment (baseline + deviations).
        freq: Temporal grain string (e.g. "daily", "hourly").
        dataset_name: Name of the dataset.
        segment_id: Segment identifier.

    Returns:
        Dict with keys ready for INSERT: seasonal_weekly, seasonal_hourly,
        seasonal_monthly, shape_embedding, deviation_embedding, text_description,
        text_embedding.
    """
    baseline = result_json.get("baseline", {})
    deviations = result_json.get("deviations", {})

    # Navigate nested baseline structure: baseline.baselines[0] has primary column
    baselines_list = baseline.get("baselines", [])
    bl0 = baselines_list[0] if baselines_list else {}
    trend_info = bl0.get("trend", {})
    residual_info = bl0.get("residual_profile", {})
    seasonality_list = bl0.get("seasonality", [])
    ds_summary = baseline.get("dataset_summary", {})

    # Navigate nested deviations structure
    dev_summary = deviations.get("summary", {})
    dev_list = deviations.get("deviations", [])
    dev_count = dev_summary.get("total_deviations", len(dev_list))
    by_severity = dev_summary.get("by_severity", {})
    critical_count = by_severity.get("critical", 0)
    total_points = ds_summary.get("rows", 1)

    # 1. Extract seasonal arrays from primary column's seasonality
    seasonal_arrays = extract_seasonal_arrays(bl0)

    # 2. Build metrics dict for shape embedding
    seasonality_strength = seasonality_list[0].get("strength") if seasonality_list else None
    metrics = {
        "trend_slope": trend_info.get("rate_per_period"),
        "seasonality_strength": seasonality_strength,
        "residual_std": residual_info.get("std"),
        "deviation_density": dev_count / max(total_points, 1),
        "deviation_count_90d": dev_count,
        "critical_pct": critical_count / max(dev_count, 1) if dev_count > 0 else 0.0,
        "row_count": total_points,
        "temporal_grain": freq,
        "trend_direction": trend_info.get("direction", "flat"),
        "variance_explained": bl0.get("variance_explained"),
        "residual_kurtosis": residual_info.get("kurtosis"),
    }

    # 3. Compute shape embedding (54-dim)
    shape_embedding = None
    try:
        shape_embedding = compute_shape_embedding(seasonal_arrays, metrics)
    except Exception as e:
        logger.warning("Shape embedding failed for %s: %s", segment_id, e)

    # 4. Compute deviation embedding (47-dim)
    deviation_embedding = None
    try:
        deviation_embedding = compute_deviation_embedding(deviations)
    except Exception as e:
        logger.warning("Deviation embedding failed for %s: %s", segment_id, e)

    # Change points come from baseline trend, not deviations
    change_points = trend_info.get("change_points", [])

    # 5. Build signal data for description
    signal_data = {
        "segment": segment_id,
        "dataset_name": dataset_name,
        "trend_slope": trend_info.get("rate_per_period"),
        "seasonality_strength": seasonality_strength,
        "seasonal_weekly": seasonal_arrays.get("weekly"),
        "seasonal_monthly": seasonal_arrays.get("monthly"),
        "deviation_count_90d": dev_count,
        "critical_pct": metrics["critical_pct"],
        "change_points": change_points,
    }
    text_description = generate_description(signal_data)

    # 6. Compute text embedding (384-dim)
    text_embedding = None
    if text_description:
        try:
            text_embedding = compute_text_embedding(text_description)
            if not text_embedding:
                text_embedding = None
        except Exception as e:
            logger.warning("Text embedding failed for %s: %s", segment_id, e)

    return {
        "seasonal_weekly": seasonal_arrays.get("weekly"),
        "seasonal_hourly": seasonal_arrays.get("hourly"),
        "seasonal_monthly": seasonal_arrays.get("monthly"),
        "shape_embedding": shape_embedding,
        "deviation_embedding": deviation_embedding,
        "text_description": text_description,
        "text_embedding": text_embedding,
    }
