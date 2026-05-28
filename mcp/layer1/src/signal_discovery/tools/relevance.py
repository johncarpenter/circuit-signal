"""
Tool: assess_relevance

Pre-flight statistical relevance assessment for time-series segments.
Run this BEFORE discover_baseline to determine which segments have
enough data for meaningful signal discovery and what granularity to use.

Produces per-segment profiles with relevance tiers, recommended
granularity, viable analyses, confidence modifiers, and warnings.
"""

import numpy as np
import pandas as pd

from signal_discovery.ingest import load_data


# ── Relevance tier thresholds ──────────────────────────────────────
# Each tier defines the MINIMUM requirements for that level.
# Checked top-down: first match wins.

TIERS = [
    {
        "name": "HIGH",
        "min_avg_daily_obs": 10,
        "min_day_coverage_pct": 50,
        "min_annual_cycles": 2.0,
        "min_active_days": 365,
    },
    {
        "name": "MEDIUM",
        "min_avg_daily_obs": 3,
        "min_day_coverage_pct": 30,
        "min_annual_cycles": 1.0,
        "min_active_days": 180,
    },
    {
        "name": "LOW",
        "min_avg_daily_obs": 1,
        "min_day_coverage_pct": 10,
        "min_annual_cycles": 0.5,
        "min_active_days": 90,
    },
]

# ── Viable analyses per tier ───────────────────────────────────────

VIABLE_ANALYSES = {
    "HIGH": {
        "trend_decomposition": True,
        "weekly_seasonality": True,
        "annual_seasonality": True,
        "change_point_detection": True,
        "deviation_detection": True,
        "forecasting": True,
        "cross_correlation": True,
    },
    "MEDIUM": {
        "trend_decomposition": True,
        "weekly_seasonality": True,
        "annual_seasonality": True,
        "change_point_detection": True,
        "deviation_detection": True,
        "forecasting": True,
        "cross_correlation": True,
    },
    "LOW": {
        "trend_decomposition": True,
        "weekly_seasonality": False,
        "annual_seasonality": True,
        "change_point_detection": True,
        "deviation_detection": True,
        "forecasting": False,
        "cross_correlation": False,
    },
    "INSUFFICIENT": {
        "trend_decomposition": False,
        "weekly_seasonality": False,
        "annual_seasonality": False,
        "change_point_detection": False,
        "deviation_detection": False,
        "forecasting": False,
        "cross_correlation": False,
    },
}


def _safe(val):
    """Convert numpy/pandas types to JSON-safe Python scalars."""
    if val is None:
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        v = float(val)
        return None if np.isnan(v) or np.isinf(v) else v
    if isinstance(val, (np.bool_,)):
        return bool(val)
    if isinstance(val, pd.Timestamp):
        return val.isoformat()
    return val


def _profile_segment(
    name: str,
    sdf: pd.DataFrame,
    date_col: str,
    value_cols: list[str],
    entity_cols: list[str],
    total_rows: int,
    calendar_days: int,
    total_active_days: int,
) -> dict:
    """Compute statistical profile for a single segment."""

    n = len(sdf)
    pct_of_total = n / total_rows * 100 if total_rows > 0 else 0

    dates = pd.to_datetime(sdf[date_col], format="mixed", utc=True)
    date_only = dates.dt.date
    days_active = date_only.nunique()

    seg_min_date = date_only.min()
    seg_max_date = date_only.max()
    seg_calendar_days = (seg_max_date - seg_min_date).days + 1 if days_active > 1 else 1

    day_coverage_pct = days_active / calendar_days * 100 if calendar_days > 0 else 0

    # Zero-day percentage (within segment's own date range)
    all_dates_in_range = set(pd.date_range(seg_min_date, seg_max_date).date)
    active_dates = set(date_only.unique())
    zero_days = len(all_dates_in_range - active_dates)
    zero_day_pct = zero_days / len(all_dates_in_range) * 100 if all_dates_in_range else 0

    annual_cycles = seg_calendar_days / 365.25

    # Entity coverage
    entity_counts = {}
    for ec in entity_cols:
        if ec in sdf.columns:
            entity_counts[ec] = int(sdf[ec].nunique())

    # Daily aggregation stats
    daily = sdf.groupby(date_only).size()
    avg_daily_obs = float(daily.mean())
    median_daily_obs = float(daily.median())
    std_daily_obs = float(daily.std()) if len(daily) > 1 else 0.0
    cv = std_daily_obs / avg_daily_obs if avg_daily_obs > 0 else float("inf")

    # Percentiles of daily observation counts
    daily_percentiles = {}
    for p in [10, 25, 50, 75, 90]:
        daily_percentiles[f"p{p}"] = _safe(daily.quantile(p / 100))
    daily_percentiles["min"] = _safe(daily.min())
    daily_percentiles["max"] = _safe(daily.max())

    # Value column stats
    value_stats = {}
    for vc in value_cols:
        if vc not in sdf.columns:
            continue
        col = sdf[vc].dropna()
        if len(col) == 0:
            continue
        value_stats[vc] = {
            "count": int(col.count()),
            "mean": _safe(col.mean()),
            "median": _safe(col.median()),
            "std": _safe(col.std()),
            "min": _safe(col.min()),
            "max": _safe(col.max()),
            "zeros_pct": _safe((col == 0).mean() * 100),
            "negative_pct": _safe((col < 0).mean() * 100),
        }

    # Lag-1 autocorrelation of daily counts (rough stationarity signal)
    autocorr_lag1 = None
    if len(daily) > 30:
        try:
            autocorr_lag1 = _safe(daily.autocorr(lag=1))
        except Exception:
            pass

    # ── Determine relevance tier ───────────────────────────────────
    tier = "INSUFFICIENT"
    for t in TIERS:
        if (
            avg_daily_obs >= t["min_avg_daily_obs"]
            and day_coverage_pct >= t["min_day_coverage_pct"]
            and annual_cycles >= t["min_annual_cycles"]
            and days_active >= t["min_active_days"]
        ):
            tier = t["name"]
            break

    # ── Recommended granularity ────────────────────────────────────
    if zero_day_pct > 70:
        rec_granularity = "weekly"
        granularity_reason = f"High zero-day rate ({zero_day_pct:.0f}%) makes daily unreliable"
    elif zero_day_pct > 50:
        rec_granularity = "weekly"
        granularity_reason = f"Zero-day rate ({zero_day_pct:.0f}%) suggests weekly aggregation"
    elif avg_daily_obs < 3:
        rec_granularity = "weekly"
        granularity_reason = f"Low daily volume ({avg_daily_obs:.1f}/day) — weekly smooths noise"
    else:
        rec_granularity = "daily"
        granularity_reason = f"Sufficient daily volume ({avg_daily_obs:.1f}/day)"

    # Override to monthly for very sparse data
    if zero_day_pct > 90 or (days_active < 180 and avg_daily_obs < 1.5):
        rec_granularity = "monthly"
        granularity_reason = f"Very sparse ({days_active} active days, {avg_daily_obs:.1f}/day)"

    # ── Confidence modifier ────────────────────────────────────────
    # 0.0–1.0 scale, used downstream to widen confidence intervals
    conf = 1.0
    if cv > 2.0:
        conf -= 0.25
    elif cv > 1.5:
        conf -= 0.15
    elif cv > 1.0:
        conf -= 0.05

    if zero_day_pct > 50:
        conf -= 0.15
    elif zero_day_pct > 30:
        conf -= 0.05

    if days_active < 365:
        conf -= 0.20
    elif days_active < 730:
        conf -= 0.10

    total_entities = sum(entity_counts.values()) if entity_counts else 0
    if total_entities > 0 and total_entities < 10:
        conf -= 0.10

    conf = max(0.0, min(1.0, conf))

    # ── Warnings ───────────────────────────────────────────────────
    warnings = []
    if avg_daily_obs < 5:
        warnings.append(
            f"Low daily volume ({avg_daily_obs:.1f}/day) — trend detection will be noisy"
        )
    if zero_day_pct > 50:
        warnings.append(
            f"High zero-day rate ({zero_day_pct:.0f}%) — daily granularity may be too fine"
        )
    if cv > 2.0:
        warnings.append(
            f"Very high CV ({cv:.2f}) — variance-dominated, hard to separate signal from noise"
        )
    elif cv > 1.5:
        warnings.append(
            f"High CV ({cv:.2f}) — consider wider confidence intervals"
        )
    if annual_cycles < 2:
        warnings.append(
            f"Only {annual_cycles:.1f} annual cycles — seasonal decomposition less reliable"
        )
    if annual_cycles < 1:
        warnings.append("Less than 1 full year — annual seasonality cannot be estimated")
    for ec, count in entity_counts.items():
        if count < 5:
            warnings.append(
                f"Only {count} unique {ec} values — small sample, results may not generalize"
            )

    viable = VIABLE_ANALYSES.get(tier, VIABLE_ANALYSES["INSUFFICIENT"])

    return {
        "segment": name,
        "sample_size": {
            "rows": n,
            "pct_of_total": round(pct_of_total, 2),
            "days_active": days_active,
            "calendar_days": seg_calendar_days,
            "day_coverage_pct": round(day_coverage_pct, 1),
            "zero_day_pct": round(zero_day_pct, 1),
            "annual_cycles": round(annual_cycles, 2),
            "date_range": {
                "start": str(seg_min_date),
                "end": str(seg_max_date),
            },
        },
        "daily_observations": {
            "mean": round(avg_daily_obs, 2),
            "median": median_daily_obs,
            "std": round(std_daily_obs, 2),
            "cv": round(cv, 3),
            "cv_label": (
                "stable" if cv < 0.8 else "moderate" if cv < 1.5 else "noisy"
            ),
            "distribution": daily_percentiles,
            "autocorrelation_lag1": autocorr_lag1,
        },
        "entity_coverage": entity_counts,
        "value_columns": value_stats,
        "relevance": {
            "tier": tier,
            "confidence_modifier": round(conf, 2),
            "proceed": tier != "INSUFFICIENT",
        },
        "recommendation": {
            "granularity": rec_granularity,
            "granularity_reason": granularity_reason,
            "viable_analyses": viable,
            "warnings": warnings,
        },
    }


def run_relevance(
    data_path: str,
    timestamp_col: str,
    segment_col: str | None = None,
    value_cols: list[str] | None = None,
    entity_cols: list[str] | None = None,
) -> dict:
    """
    Assess statistical relevance of all segments in a dataset.

    Args:
        data_path: Path to CSV, Parquet, or JSON file.
        timestamp_col: Name of the timestamp/datetime column.
        segment_col: Column to segment by (e.g. 'whiskey_brand').
                     If None, profiles the dataset as a single segment.
        value_cols: Numeric columns to profile (e.g. ['amount', 'quantity']).
                    If None, auto-detects numeric columns.
        entity_cols: Entity columns for coverage stats (e.g. ['store_id']).

    Returns:
        Dict with dataset summary, per-segment profiles, and overall
        recommendations suitable for gating downstream pipeline stages.
    """
    df, fmt = load_data(data_path)
    entity_cols = entity_cols or []

    # Auto-detect value columns
    if not value_cols:
        value_cols = [
            c
            for c in df.select_dtypes(include=[np.number]).columns
            if c not in entity_cols and c != segment_col
        ]

    # Parse dates for calendar span
    dates = pd.to_datetime(df[timestamp_col], format="mixed", utc=True)
    all_dates = dates.dt.date
    calendar_days = (all_dates.max() - all_dates.min()).days + 1
    total_active_days = all_dates.nunique()

    total_rows = len(df)

    # ── Profile each segment ──────────────────────────────────────
    segments = []
    if segment_col and segment_col in df.columns:
        groups = df.groupby(segment_col, dropna=False)
        for name, sdf in groups:
            seg_name = str(name) if not pd.isna(name) else "(unbranded)"
            profile = _profile_segment(
                name=seg_name,
                sdf=sdf,
                date_col=timestamp_col,
                value_cols=value_cols,
                entity_cols=entity_cols,
                total_rows=total_rows,
                calendar_days=calendar_days,
                total_active_days=total_active_days,
            )
            segments.append(profile)
        # Sort by rows descending
        segments.sort(key=lambda s: s["sample_size"]["rows"], reverse=True)
    else:
        # Single-segment mode
        profile = _profile_segment(
            name="(all)",
            sdf=df,
            date_col=timestamp_col,
            value_cols=value_cols,
            entity_cols=entity_cols,
            total_rows=total_rows,
            calendar_days=calendar_days,
            total_active_days=total_active_days,
        )
        segments.append(profile)

    # ── Build summary ─────────────────────────────────────────────
    tier_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "INSUFFICIENT": 0}
    proceed_count = 0
    skip_count = 0
    for s in segments:
        tier_counts[s["relevance"]["tier"]] += 1
        if s["relevance"]["proceed"]:
            proceed_count += 1
        else:
            skip_count += 1

    # Tier criteria documentation (embedded in output for transparency)
    tier_criteria = {
        "HIGH": {
            "min_avg_daily_obs": 10,
            "min_day_coverage_pct": 50,
            "min_annual_cycles": 2.0,
            "min_active_days": 365,
            "description": "Robust for daily analysis — trend, seasonality, deviations, forecasting",
        },
        "MEDIUM": {
            "min_avg_daily_obs": 3,
            "min_day_coverage_pct": 30,
            "min_annual_cycles": 1.0,
            "min_active_days": 180,
            "description": "Viable — consider weekly aggregation for noisy segments",
        },
        "LOW": {
            "min_avg_daily_obs": 1,
            "min_day_coverage_pct": 10,
            "min_annual_cycles": 0.5,
            "min_active_days": 90,
            "description": "Weekly aggregation required — limited to trend + basic seasonality",
        },
        "INSUFFICIENT": {
            "description": "Not enough data for meaningful time-series analysis — skip",
        },
    }

    return {
        "dataset": {
            "path": data_path,
            "format": fmt,
            "total_rows": total_rows,
            "total_active_days": total_active_days,
            "calendar_days": calendar_days,
            "date_range": {
                "start": str(all_dates.min()),
                "end": str(all_dates.max()),
            },
            "segment_col": segment_col,
            "value_cols": value_cols,
            "entity_cols": entity_cols,
            "segment_count": len(segments),
        },
        "summary": {
            "by_tier": tier_counts,
            "proceed": proceed_count,
            "skip": skip_count,
        },
        "tier_criteria": tier_criteria,
        "segments": segments,
    }
