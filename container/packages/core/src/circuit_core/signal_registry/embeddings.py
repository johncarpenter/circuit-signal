"""Compute embedding vectors for signal similarity search.

Shape embedding: 54-dim (weekly[7] + hourly[24] + monthly[12] + scalars[11])
Deviation embedding: 47-dim (severity_dist[4] + dayofweek_dist[7] + month_dist[12]
    + zscore_stats[4] + type_dist[3] + interarrival_stats[4] + changepoint_features[3]
    + density_features[2] + window_hist[8])
Text embedding: 384-dim via sentence-transformers (lazy-loaded singleton)
"""

import logging
import math

import numpy as np

logger = logging.getLogger(__name__)

# Lazy-loaded sentence-transformers model
_text_model = None
_text_model_name = None


def compute_shape_embedding(seasonal_arrays: dict, metrics: dict) -> list[float]:
    """Build a 54-dim shape embedding from seasonal arrays and scalar metrics.

    Components:
        weekly[7] + hourly[24] + monthly[12] + scalars[11] = 54
    Scalars: trend_slope, seasonality_strength, residual_std, deviation_density,
        deviation_count_90d, critical_pct, row_count_log, temporal_grain_encoded,
        trend_direction, variance_explained, residual_kurtosis
    """
    # Seasonal components (zero-filled if missing)
    weekly = seasonal_arrays.get("weekly") or [0.0] * 7
    hourly = seasonal_arrays.get("hourly") or [0.0] * 24
    monthly = seasonal_arrays.get("monthly") or [0.0] * 12

    # Normalize each seasonal component to unit range
    weekly = _normalize_array(weekly)
    hourly = _normalize_array(hourly)
    monthly = _normalize_array(monthly)

    # Scalar features (11 dims)
    row_count = metrics.get("row_count") or 1
    trend_slope = metrics.get("trend_slope") or 0.0
    grain_map = {"sub_hourly": 0.0, "hourly": 0.2, "daily": 0.4, "weekly": 0.6, "monthly": 0.8, "quarterly": 0.9, "yearly": 1.0}
    trend_dir_map = {"decreasing": -1.0, "flat": 0.0, "increasing": 1.0}

    scalars = [
        _clip(trend_slope, -10, 10) / 10.0,
        _clip(metrics.get("seasonality_strength") or 0.0, 0, 1),
        _clip(metrics.get("residual_std") or 0.0, 0, 100) / 100.0,
        _clip(metrics.get("deviation_density") or 0.0, 0, 1),
        _clip(metrics.get("deviation_count_90d") or 0, 0, 500) / 500.0,
        _clip(metrics.get("critical_pct") or 0.0, 0, 1),
        math.log1p(row_count) / 15.0,  # log scale, ~15 for 3M rows
        grain_map.get(metrics.get("temporal_grain", "daily"), 0.4),
        trend_dir_map.get(metrics.get("trend_direction", "flat"), 0.0),
        _clip(metrics.get("variance_explained") or 0.0, 0, 1),
        _clip(metrics.get("residual_kurtosis") or 0.0, -5, 20) / 20.0,
    ]

    embedding = weekly + hourly + monthly + scalars
    assert len(embedding) == 54, f"Shape embedding must be 54-dim, got {len(embedding)}"
    return [round(float(v), 6) for v in embedding]


def compute_deviation_embedding(deviations_result: dict) -> list[float]:
    """Build a 47-dim deviation embedding from deviation analysis results.

    Components:
        severity_dist[4] + dayofweek_dist[7] + month_dist[12] + zscore_stats[4]
        + type_dist[3] + interarrival_stats[4] + changepoint_features[3]
        + density_features[2] + window_hist[8] = 47
    """
    deviations = deviations_result.get("deviations", [])
    change_points = deviations_result.get("change_points", [])
    n_dev = len(deviations)

    # severity_dist[4]: proportion in [low, medium, high, critical]
    severity_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for d in deviations:
        sev = d.get("severity", "medium")
        if sev in severity_counts:
            severity_counts[sev] += 1
    severity_dist = _to_distribution(list(severity_counts.values()))

    # Parse timestamps from deviation timestamp_range for temporal distributions
    from datetime import datetime as _dt
    parsed_dates = []
    for d in deviations:
        ts_str = (d.get("timestamp_range") or {}).get("start")
        if ts_str:
            try:
                parsed_dates.append(_dt.fromisoformat(ts_str.replace("Z", "+00:00")))
            except (ValueError, TypeError):
                pass

    # dayofweek_dist[7]
    dow_counts = [0] * 7
    for dt in parsed_dates:
        dow_counts[dt.weekday()] += 1
    dow_dist = _to_distribution(dow_counts)

    # month_dist[12]
    month_counts = [0] * 12
    for dt in parsed_dates:
        month_counts[dt.month - 1] += 1
    month_dist = _to_distribution(month_counts)

    # zscore_stats[4]: mean, std, max, skew of z-scores
    # z_score lives at d["details"]["z_score"]
    zscores = []
    for d in deviations:
        z = (d.get("details") or {}).get("z_score")
        if z is not None:
            zscores.append(abs(float(z)))
    if zscores:
        arr = np.array(zscores)
        zscore_stats = [
            _clip(float(arr.mean()), 0, 10) / 10.0,
            _clip(float(arr.std()), 0, 5) / 5.0,
            _clip(float(arr.max()), 0, 20) / 20.0,
            _clip(float(_skew(arr)), -3, 3) / 3.0,
        ]
    else:
        zscore_stats = [0.0] * 4

    # type_dist[3]: proportion of [point_anomaly, regime_change, trend_shift]
    # Map actual deviation types to embedding categories
    _type_map = {"point_anomaly": "spike", "regime_change": "shift", "trend_shift": "shift"}
    type_counts = {"spike": 0, "dip": 0, "shift": 0}
    for d in deviations:
        raw_type = d.get("type", "point_anomaly")
        mapped = _type_map.get(raw_type, "spike")
        type_counts[mapped] += 1
    type_dist = _to_distribution(list(type_counts.values()))

    # interarrival_stats[4]: mean, std, min, max of gaps between deviations
    # Use ordinal timestamps from parsed dates
    ordinals = sorted(dt.toordinal() for dt in parsed_dates)
    if len(ordinals) >= 2:
        gaps = [ordinals[i + 1] - ordinals[i] for i in range(len(ordinals) - 1)]
        gaps_arr = np.array(gaps, dtype=float)
        max_gap = max(float(gaps_arr.max()), 1.0)
        interarrival_stats = [
            float(gaps_arr.mean()) / max_gap,
            float(gaps_arr.std()) / max_gap if max_gap > 0 else 0.0,
            float(gaps_arr.min()) / max_gap,
            1.0,  # max/max = 1
        ]
    else:
        interarrival_stats = [0.0] * 4

    # changepoint_features[3]: count, mean_magnitude, max_magnitude
    cp_mags = [abs(cp.get("magnitude", 0.0)) for cp in change_points]
    if cp_mags:
        max_mag = max(max(cp_mags), 1e-10)
        changepoint_features = [
            _clip(len(cp_mags), 0, 20) / 20.0,
            float(np.mean(cp_mags)) / max_mag,
            1.0,
        ]
    else:
        changepoint_features = [0.0] * 3

    # density_features[2]: deviation_density, critical_ratio
    total_points = deviations_result.get("total_observations", 1)
    density_features = [
        _clip(n_dev / max(total_points, 1), 0, 1),
        _clip(severity_counts.get("critical", 0) / max(n_dev, 1), 0, 1),
    ]

    # window_hist[8]: deviation count binned into 8 equal time windows
    if len(ordinals) >= 2:
        t_min, t_max = min(ordinals), max(ordinals)
        span = t_max - t_min
        if span > 0:
            window_hist = [0] * 8
            for t in ordinals:
                bucket = min(int((t - t_min) / span * 8), 7)
                window_hist[bucket] += 1
            window_hist = _to_distribution(window_hist)
        else:
            window_hist = [0.0] * 8
    else:
        window_hist = [0.0] * 8

    embedding = (
        severity_dist + dow_dist + month_dist + zscore_stats
        + type_dist + interarrival_stats + changepoint_features
        + density_features + window_hist
    )
    assert len(embedding) == 47, f"Deviation embedding must be 47-dim, got {len(embedding)}"
    return [round(float(v), 6) for v in embedding]


def compute_text_embedding(text: str, model_name: str = "all-MiniLM-L6-v2") -> list[float]:
    """Compute 384-dim text embedding using sentence-transformers (lazy-loaded singleton)."""
    global _text_model, _text_model_name

    if _text_model is None or _text_model_name != model_name:
        try:
            from sentence_transformers import SentenceTransformer
            _text_model = SentenceTransformer(model_name)
            _text_model_name = model_name
            logger.info("Loaded sentence-transformers model: %s", model_name)
        except ImportError:
            logger.warning("sentence-transformers not installed, skipping text embedding")
            return []

    embedding = _text_model.encode(text, normalize_embeddings=True)
    return [round(float(v), 6) for v in embedding]


# --- Helpers ---

def _normalize_array(arr: list[float]) -> list[float]:
    """Normalize to [0, 1] range."""
    mn, mx = min(arr), max(arr)
    span = mx - mn
    if span < 1e-10:
        return [0.0] * len(arr)
    return [(v - mn) / span for v in arr]


def _to_distribution(counts: list[int | float]) -> list[float]:
    """Convert counts to a probability distribution."""
    total = sum(counts)
    if total == 0:
        return [0.0] * len(counts)
    return [c / total for c in counts]


def _clip(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(val)))


def _skew(arr: np.ndarray) -> float:
    """Compute skewness."""
    n = len(arr)
    if n < 3:
        return 0.0
    mean = arr.mean()
    std = arr.std()
    if std < 1e-10:
        return 0.0
    return float(((arr - mean) ** 3).mean() / (std ** 3))
