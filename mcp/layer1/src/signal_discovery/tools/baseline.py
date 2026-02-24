"""
Tool: discover_baseline (Mode 1)

Decompose time series to establish "what normal looks like."
For each numeric column: STL/MSTL decomposition → trend, seasonality, residual.
Persists baseline artifacts for Mode 2 and Mode 3 to reference.
"""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import ruptures as rpt
from scipy import stats as scipy_stats
from statsmodels.tsa.seasonal import STL, MSTL
from statsmodels.tsa.stattools import adfuller

from signal_discovery.ingest import (
    load_data,
    parse_timestamps,
    detect_frequency,
    get_seasonal_periods,
    find_numeric_columns,
    data_quality_report,
    file_hash,
)

logger = logging.getLogger("signal-discovery.baseline")


def run_baseline(
    data_path: str,
    timestamp_col: str,
    value_cols: list[str] | None = None,
    freq: str | None = None,
    output_dir: str | None = None,
) -> dict:
    """Run Mode 1 baseline discovery."""

    # --- Load and prepare data ---
    df, fmt = load_data(data_path)
    df = parse_timestamps(df, timestamp_col)

    detected_freq = freq or detect_frequency(df)
    seasonal_periods = get_seasonal_periods(detected_freq)

    # --- Select columns ---
    if value_cols is None:
        value_cols = find_numeric_columns(df)
    else:
        # Validate requested columns exist
        missing = [c for c in value_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Columns not found in data: {missing}")

    if not value_cols:
        return {"error": "No analyzable numeric columns found in dataset."}

    # --- Data quality ---
    quality = data_quality_report(df[value_cols])

    # --- Decompose each column ---
    baselines = []
    for col in value_cols:
        try:
            result = _decompose_column(df[col].dropna(), detected_freq, seasonal_periods)
            baselines.append(result)
        except Exception as e:
            logger.warning(f"Failed to decompose column '{col}': {e}")
            baselines.append({
                "column": col,
                "error": str(e),
                "variance_explained": None,
                "narrative": f"Could not decompose '{col}': {e}",
            })

    # --- Persist baselines ---
    output_path = Path(output_dir or ".signal-baselines")
    _save_baselines(
        output_path=output_path,
        baselines=baselines,
        df=df,
        data_path=data_path,
        detected_freq=detected_freq,
        value_cols=value_cols,
    )

    # --- Build response ---
    dataset_summary = {
        "rows": len(df),
        "time_range": {
            "start": df.index.min().isoformat(),
            "end": df.index.max().isoformat(),
        },
        "frequency_detected": detected_freq,
        "columns_analyzed": len(value_cols),
        "data_quality": quality,
    }

    # --- Generate visual report (non-blocking) ---
    report_path = None
    try:
        from signal_discovery.tools.report import generate_baseline_report
        report_path = generate_baseline_report(
            baselines=baselines,
            dataset_summary=dataset_summary,
            data_path=data_path,
            detected_freq=detected_freq,
            df=df,
        )
    except Exception as e:
        logger.warning(f"Baseline report generation failed (non-blocking): {e}")

    result = {
        "dataset_summary": dataset_summary,
        "baselines": baselines,
        "baseline_path": str(output_path.resolve()),
    }
    if report_path:
        result["report_path"] = report_path

    return result


def _decompose_column(
    series: pd.Series,
    freq: str,
    seasonal_periods: list[dict],
) -> dict:
    """
    Decompose a single column's time series.

    Tries MSTL for multiple seasonal periods, falls back to STL for single period,
    and further falls back to simple trend extraction if data is insufficient.
    """
    col_name = series.name
    n = len(series)

    # Fill any internal gaps via linear interpolation for decomposition
    series_clean = series.interpolate(method="linear").ffill().bfill()

    # --- Determine decomposition approach ---
    usable_periods = [sp for sp in seasonal_periods if sp["period"] * 2 <= n]

    if not usable_periods:
        # Not enough data for any seasonal decomposition — just do trend
        return _trend_only_decomposition(series_clean, col_name)

    # --- Run decomposition ---
    if len(usable_periods) == 1:
        period = usable_periods[0]["period"]
        try:
            stl = STL(series_clean, period=period, robust=True)
            result = stl.fit()
            trend = result.trend
            seasonal_component = result.seasonal
            residual = result.resid
            seasonal_info = [_seasonal_summary(seasonal_component, usable_periods[0], freq)]
        except Exception as e:
            logger.warning(f"STL failed for {col_name}, falling back to trend-only: {e}")
            return _trend_only_decomposition(series_clean, col_name)
    else:
        periods = [sp["period"] for sp in usable_periods]
        try:
            mstl = MSTL(series_clean, periods=periods)
            result = mstl.fit()
            trend = result.trend
            residual = result.resid
            # MSTL returns multiple seasonal columns
            seasonal_info = []
            for i, sp in enumerate(usable_periods):
                if hasattr(result, "seasonal") and isinstance(result.seasonal, pd.DataFrame):
                    s_col = result.seasonal.iloc[:, i] if i < result.seasonal.shape[1] else None
                else:
                    s_col = result.seasonal
                if s_col is not None:
                    seasonal_info.append(_seasonal_summary(s_col, sp, freq))
            seasonal_component = result.seasonal
        except Exception as e:
            logger.warning(f"MSTL failed for {col_name}, trying STL: {e}")
            period = usable_periods[0]["period"]
            stl = STL(series_clean, period=period, robust=True)
            result = stl.fit()
            trend = result.trend
            seasonal_component = result.seasonal
            residual = result.resid
            seasonal_info = [_seasonal_summary(seasonal_component, usable_periods[0], freq)]

    # --- Variance explained ---
    total_var = series_clean.var()
    resid_var = residual.var()
    variance_explained = 1.0 - (resid_var / total_var) if total_var > 0 else 0.0

    # --- Trend analysis ---
    trend_info = _analyze_trend(trend)

    # --- Residual profile ---
    resid_profile = _analyze_residual(residual)

    # --- Narrative ---
    narrative = _build_narrative(col_name, trend_info, seasonal_info, variance_explained, resid_profile)

    return {
        "column": col_name,
        "variance_explained": round(float(variance_explained), 4),
        "trend": trend_info,
        "seasonality": seasonal_info,
        "residual_profile": resid_profile,
        "narrative": narrative,
        # Internal data for persistence (not shown to user, used by save)
        "_trend_values": trend.tolist(),
        "_residual_values": residual.tolist(),
        "_index": [t.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00") for t in series_clean.index],
    }


def _trend_only_decomposition(series: pd.Series, col_name: str) -> dict:
    """Fallback when there isn't enough data for seasonal decomposition."""
    from scipy.signal import savgol_filter

    n = len(series)
    window = min(max(n // 5, 3), n)
    if window % 2 == 0:
        window -= 1
    window = max(window, 3)

    try:
        trend = pd.Series(
            savgol_filter(series.values, window_length=window, polyorder=2),
            index=series.index,
        )
    except Exception:
        trend = series.rolling(window=max(n // 10, 2), center=True).mean().ffill().bfill()

    residual = series - trend
    total_var = series.var()
    resid_var = residual.var()
    variance_explained = 1.0 - (resid_var / total_var) if total_var > 0 else 0.0
    trend_info = _analyze_trend(trend)
    resid_profile = _analyze_residual(residual)

    return {
        "column": col_name,
        "variance_explained": round(float(variance_explained), 4),
        "trend": trend_info,
        "seasonality": [],
        "residual_profile": resid_profile,
        "narrative": (
            f"Insufficient data for seasonal decomposition of '{col_name}'. "
            f"Trend is {trend_info['direction']} with {round(variance_explained*100, 1)}% "
            f"of variance explained by trend alone."
        ),
        "_trend_values": trend.tolist(),
        "_residual_values": residual.tolist(),
        "_index": [t.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00") for t in series.index],
    }


def _analyze_trend(trend: pd.Series) -> dict:
    """Analyze the trend component: direction, rate, and change points."""
    n = len(trend)
    values = trend.values

    # Direction and rate via linear regression on the trend
    x = np.arange(n)
    slope, intercept, r_value, p_value, std_err = scipy_stats.linregress(x, values)

    if abs(slope) < std_err * 0.5:
        direction = "flat"
    elif slope > 0:
        direction = "increasing"
    else:
        direction = "decreasing"

    # Change point detection on trend
    change_points = []
    if n >= 10:
        try:
            algo = rpt.Pelt(model="rbf", min_size=max(n // 20, 5), jump=max(n // 50, 1))
            result = algo.fit_predict(values, pen=np.log(n) * values.std() ** 2)
            # result contains the indices of change points (last element is n)
            for cp_idx in result[:-1]:
                if 0 < cp_idx < n:
                    # Estimate magnitude as difference in means before/after
                    before_mean = values[max(0, cp_idx - 10) : cp_idx].mean()
                    after_mean = values[cp_idx : min(n, cp_idx + 10)].mean()
                    magnitude = after_mean - before_mean
                    change_points.append({
                        "timestamp": trend.index[cp_idx].isoformat(),
                        "magnitude": round(float(magnitude), 4),
                        "direction": "increase" if magnitude > 0 else "decrease",
                    })
        except Exception as e:
            logger.debug(f"Change point detection failed: {e}")

    return {
        "direction": direction,
        "rate_per_period": round(float(slope), 6),
        "change_points": change_points,
    }


def _seasonal_summary(seasonal: pd.Series, period_info: dict, freq: str) -> dict:
    """Summarize a seasonal component."""
    strength = float(seasonal.std() / (seasonal.std() + 1e-10))

    # Find the phase of the peak
    period = period_info["period"]
    label = period_info["label"]

    # Group by position in the cycle and find the peak
    try:
        if label == "weekly" and freq in ("daily", "hourly"):
            # Group by day of week
            grouped = seasonal.groupby(seasonal.index.dayofweek).mean()
            peak_idx = grouped.idxmax()
            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            peak_phase = day_names[int(peak_idx)]
        elif label == "annual" and freq in ("daily", "weekly", "monthly"):
            grouped = seasonal.groupby(seasonal.index.month).mean()
            peak_idx = grouped.idxmax()
            month_names = [
                "", "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December",
            ]
            peak_phase = month_names[int(peak_idx)]
        elif label == "daily" and freq in ("hourly", "sub_hourly"):
            grouped = seasonal.groupby(seasonal.index.hour).mean()
            peak_idx = grouped.idxmax()
            peak_phase = f"{int(peak_idx):02d}:00"
        else:
            peak_phase = f"position {int(seasonal.values[:period].argmax())}"
    except Exception:
        peak_phase = "unknown"

    return {
        "period": period,
        "period_label": label,
        "strength": round(strength, 4),
        "peak_phase": peak_phase,
    }


def _analyze_residual(residual: pd.Series) -> dict:
    """Profile the residual component."""
    values = residual.dropna().values
    if len(values) < 10:
        return {
            "std": round(float(values.std()), 4) if len(values) > 0 else 0.0,
            "is_stationary": True,
            "distribution": "unknown",
        }

    std = float(values.std())

    # Stationarity test (ADF)
    try:
        adf_result = adfuller(values, autolag="AIC")
        is_stationary = adf_result[1] < 0.05  # p-value
    except Exception:
        is_stationary = True

    # Distribution shape
    skewness = float(scipy_stats.skew(values))
    kurtosis_val = float(scipy_stats.kurtosis(values))

    if abs(skewness) < 0.5 and abs(kurtosis_val) < 1.0:
        distribution = "normal"
    elif abs(skewness) >= 0.5:
        distribution = "skewed"
    else:
        distribution = "heavy-tailed"

    return {
        "std": round(std, 4),
        "is_stationary": bool(is_stationary),
        "distribution": distribution,
        "skewness": round(skewness, 4),
        "kurtosis": round(kurtosis_val, 4),
    }


def _build_narrative(
    col_name: str,
    trend: dict,
    seasonality: list[dict],
    variance_explained: float,
    residual: dict,
) -> str:
    """Compose a plain-English narrative of the decomposition results."""
    parts = [f"'{col_name}':"]

    # Trend
    if trend["direction"] == "flat":
        parts.append("The underlying trend is flat (no significant long-term growth or decline).")
    else:
        parts.append(f"The underlying trend is {trend['direction']}.")

    if trend["change_points"]:
        n_cp = len(trend["change_points"])
        parts.append(f"Detected {n_cp} structural change point{'s' if n_cp > 1 else ''} in the trend.")

    # Seasonality
    if seasonality:
        for s in seasonality:
            parts.append(
                f"Shows {s['period_label']} seasonality (period={s['period']}) "
                f"peaking at {s['peak_phase']}."
            )
    else:
        parts.append("No significant seasonal patterns detected.")

    # Variance explained
    pct = round(variance_explained * 100, 1)
    parts.append(f"Trend + seasonality explain {pct}% of total variance.")

    # Residual
    if pct < 50:
        parts.append(
            "The low explained variance suggests this metric is heavily influenced by "
            "external factors not captured by time alone. Forecasting will have wide uncertainty."
        )
    elif pct > 85:
        parts.append("This is a highly predictable metric — deviations from the baseline are meaningful signals.")

    if not residual["is_stationary"]:
        parts.append("Warning: residuals are non-stationary, indicating the pattern may be evolving over time.")

    return " ".join(parts)


def _save_baselines(
    output_path: Path,
    baselines: list[dict],
    df: pd.DataFrame,
    data_path: str,
    detected_freq: str,
    value_cols: list[str],
) -> None:
    """Persist baseline artifacts to disk."""
    output_path.mkdir(parents=True, exist_ok=True)
    columns_dir = output_path / "columns"
    columns_dir.mkdir(exist_ok=True)
    decomp_dir = output_path / "decompositions"
    decomp_dir.mkdir(exist_ok=True)

    # Manifest
    manifest = {
        "data_path": str(data_path),
        "data_hash": file_hash(data_path),
        "frequency": detected_freq,
        "time_range": {
            "start": df.index.min().isoformat(),
            "end": df.index.max().isoformat(),
        },
        "rows": len(df),
        "columns_analyzed": value_cols,
        "baselines_summary": [],
    }

    for bl in baselines:
        col = bl["column"]

        # Save per-column summary (without internal arrays)
        summary = {k: v for k, v in bl.items() if not k.startswith("_")}
        with open(columns_dir / f"{col}.json", "w") as f:
            json.dump(summary, f, indent=2, default=str)

        manifest["baselines_summary"].append({
            "column": col,
            "variance_explained": bl.get("variance_explained"),
        })

        # Save decomposition time series as parquet
        if "_trend_values" in bl and "_index" in bl:
            idx = pd.to_datetime(bl["_index"])
            trend_df = pd.DataFrame({"value": bl["_trend_values"]}, index=idx)
            trend_df.to_parquet(decomp_dir / f"{col}_trend.parquet")

        if "_residual_values" in bl and "_index" in bl:
            idx = pd.to_datetime(bl["_index"])
            resid_df = pd.DataFrame({"value": bl["_residual_values"]}, index=idx)
            resid_df.to_parquet(decomp_dir / f"{col}_residual.parquet")

    with open(output_path / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    logger.info(f"Baseline artifacts saved to {output_path}")
