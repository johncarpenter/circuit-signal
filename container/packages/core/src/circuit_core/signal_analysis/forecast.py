"""
Tool: project_forecast (Mode 3)

Generate confidence-bounded projections with scenario variants.
Uses baseline decomposition from Mode 1 and, optionally, active deviations
from Mode 2 to produce forecasts with uncertainty intervals.

Includes backtest accuracy metrics (MAPE, CI coverage).

NOTE: This tool requires the 'prophet' optional dependency.
If Prophet is not installed, it falls back to a simpler
trend-extrapolation + seasonal projection approach.
"""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from circuit_core.signal_analysis.ingest import load_data, parse_timestamps, parse_duration

logger = logging.getLogger("signal-discovery.forecast")

# Defer Prophet import to avoid loading cmdstan at module import time.
# This saves ~500MB of memory for processes that only need baseline/deviations.
HAS_PROPHET = False
Prophet = None  # type: ignore[assignment]


def run_forecast(
    data_path: str,
    timestamp_col: str,
    baseline_path: str,
    value_cols: list[str] | None = None,
    horizon: str = "30d",
    scenarios: bool = True,
    confidence_levels: list[float] | None = None,
) -> dict:
    """Run Mode 3 forecasting."""

    bl_path = Path(baseline_path)
    if not (bl_path / "manifest.json").exists():
        return {"error": f"No baseline found at {baseline_path}. Run discover_baseline first."}

    with open(bl_path / "manifest.json") as f:
        manifest = json.load(f)

    df, _ = load_data(data_path)
    df = parse_timestamps(df, timestamp_col)

    confidence_levels = confidence_levels or [0.80, 0.95]
    horizon_delta = parse_duration(horizon)

    # Determine columns
    baselined_cols = manifest.get("columns_analyzed", [])
    if value_cols:
        cols = [c for c in value_cols if c in baselined_cols and c in df.columns]
    else:
        cols = [c for c in baselined_cols if c in df.columns]

    if not cols:
        return {"error": "No matching columns between data and baseline."}

    forecasts = []
    for col in cols:
        try:
            result = _forecast_column(
                series=df[col].dropna(),
                col_name=col,
                baseline_dir=bl_path,
                horizon_delta=horizon_delta,
                confidence_levels=confidence_levels,
                scenarios=scenarios,
            )
            forecasts.append(result)
        except Exception as e:
            logger.warning(f"Forecasting failed for '{col}': {e}")
            forecasts.append({
                "column": col,
                "error": str(e),
                "narrative": f"Forecasting failed for '{col}': {e}",
            })

    return {"forecasts": forecasts}


def _check_prophet():
    """Load Prophet on first call, not at import time."""
    global HAS_PROPHET, Prophet
    if not HAS_PROPHET:
        try:
            from prophet import Prophet as _Prophet  # noqa: F811
            Prophet = _Prophet
            HAS_PROPHET = True
            logger.info("Prophet loaded — using full forecasting.")
        except ImportError:
            logger.info("Prophet not installed. Using fallback trend+seasonal extrapolation.")
    return HAS_PROPHET


def _forecast_column(
    series: pd.Series,
    col_name: str,
    baseline_dir: Path,
    horizon_delta: pd.Timedelta,
    confidence_levels: list[float],
    scenarios: bool,
) -> dict:
    """Generate forecast for a single column."""

    if _check_prophet():
        return _prophet_forecast(
            series, col_name, baseline_dir, horizon_delta, confidence_levels, scenarios
        )
    else:
        return _fallback_forecast(
            series, col_name, baseline_dir, horizon_delta, confidence_levels, scenarios
        )


def _prophet_forecast(
    series: pd.Series,
    col_name: str,
    baseline_dir: Path,
    horizon_delta: pd.Timedelta,
    confidence_levels: list[float],
    scenarios: bool,
) -> dict:
    """Forecast using Prophet."""

    # Prophet expects 'ds' and 'y' columns
    prophet_df = pd.DataFrame({
        "ds": series.index.tz_localize(None) if series.index.tz else series.index,
        "y": series.values,
    })

    # Determine horizon in periods
    freq = pd.infer_freq(series.index)
    if freq is None:
        # Estimate from median delta
        median_delta = pd.Series(series.index).diff().dropna().median()
        horizon_periods = max(1, int(horizon_delta / median_delta))
        freq_str = "D"  # Default
    else:
        freq_str = freq
        try:
            horizon_periods = max(1, int(horizon_delta / pd.tseries.frequencies.to_offset(freq)))
        except Exception:
            horizon_periods = max(1, int(horizon_delta.days))

    all_scenarios = []

    # --- Baseline forecast ---
    # Use the widest CI for Prophet, we'll compute narrower ones from the distribution
    model = Prophet(
        interval_width=max(confidence_levels),
        yearly_seasonality="auto",
        weekly_seasonality="auto",
        daily_seasonality="auto",
    )
    model.fit(prophet_df)
    future = model.make_future_dataframe(periods=horizon_periods, freq=freq_str)
    forecast = model.predict(future)

    # Extract forecast-only rows
    forecast_only = forecast.iloc[len(prophet_df):]

    predictions = []
    for _, row in forecast_only.iterrows():
        pred = {
            "timestamp": row["ds"].isoformat(),
            "point_forecast": round(float(row["yhat"]), 4),
        }
        # Compute CIs from the posterior distribution
        std_est = (row["yhat_upper"] - row["yhat_lower"]) / (2 * scipy_stats.norm.ppf((1 + max(confidence_levels)) / 2))
        for cl in confidence_levels:
            z = scipy_stats.norm.ppf((1 + cl) / 2)
            cl_label = str(int(cl * 100))
            pred[f"ci_{cl_label}_lower"] = round(float(row["yhat"] - z * std_est), 4)
            pred[f"ci_{cl_label}_upper"] = round(float(row["yhat"] + z * std_est), 4)
        predictions.append(pred)

    all_scenarios.append({
        "name": "baseline",
        "description": "Forecast assuming historical patterns continue unchanged",
        "predictions": predictions,
    })

    # --- Deviation-adjusted scenario ---
    if scenarios:
        try:
            deviation_scenario = _build_deviation_scenario(
                series, col_name, baseline_dir, forecast_only, confidence_levels
            )
            if deviation_scenario:
                all_scenarios.append(deviation_scenario)
        except Exception as e:
            logger.debug(f"Could not build deviation scenario for '{col_name}': {e}")

    # --- Backtest accuracy ---
    accuracy = _backtest_accuracy(prophet_df, model, confidence_levels, horizon_periods)

    # --- Narrative ---
    narrative = _forecast_narrative(col_name, predictions, accuracy, all_scenarios)

    return {
        "column": col_name,
        "scenarios": all_scenarios,
        "accuracy_profile": accuracy,
        "narrative": narrative,
    }


def _fallback_forecast(
    series: pd.Series,
    col_name: str,
    baseline_dir: Path,
    horizon_delta: pd.Timedelta,
    confidence_levels: list[float],
    scenarios: bool,
) -> dict:
    """Simple trend + noise forecast when Prophet is not available."""

    n = len(series)
    values = series.values.astype(float)

    # Linear trend
    x = np.arange(n)
    slope, intercept, _, _, _ = scipy_stats.linregress(x, values)
    residuals = values - (slope * x + intercept)
    resid_std = float(residuals.std())

    # Project forward
    median_delta = pd.Series(series.index).diff().dropna().median()
    horizon_periods = max(1, int(horizon_delta / median_delta))

    predictions = []
    for i in range(1, horizon_periods + 1):
        future_x = n + i - 1
        point = slope * future_x + intercept
        ts = series.index[-1] + median_delta * i

        pred = {
            "timestamp": ts.isoformat(),
            "point_forecast": round(float(point), 4),
        }
        for cl in confidence_levels:
            z = scipy_stats.norm.ppf((1 + cl) / 2)
            # Uncertainty grows with sqrt of steps ahead
            uncertainty = resid_std * np.sqrt(i) * z
            cl_label = str(int(cl * 100))
            pred[f"ci_{cl_label}_lower"] = round(float(point - uncertainty), 4)
            pred[f"ci_{cl_label}_upper"] = round(float(point + uncertainty), 4)
        predictions.append(pred)

    # Trustworthy horizon: where 80% CI width exceeds 50% of mean value
    mean_val = abs(values.mean())
    trustworthy = horizon_periods
    if mean_val > 0:
        for i in range(1, horizon_periods + 1):
            ci_width = 2 * resid_std * np.sqrt(i) * scipy_stats.norm.ppf(0.9)
            if ci_width > 0.5 * mean_val:
                trustworthy = i
                break

    trustworthy_str = f"{int(trustworthy * median_delta.days)} days" if median_delta.days > 0 else f"{trustworthy} periods"

    return {
        "column": col_name,
        "scenarios": [{
            "name": "baseline",
            "description": "Linear trend extrapolation (Prophet not available)",
            "predictions": predictions,
        }],
        "accuracy_profile": {
            "backtest_mape": None,
            "backtest_coverage_80": None,
            "backtest_coverage_95": None,
            "trustworthy_horizon": trustworthy_str,
            "note": "Install 'prophet' for full backtest accuracy metrics",
        },
        "narrative": (
            f"Fallback forecast for '{col_name}' using linear trend extrapolation. "
            f"Trend: {'+' if slope > 0 else ''}{round(slope, 4)} per period. "
            f"Residual std: {round(resid_std, 4)}. "
            f"Forecast is trustworthy for approximately {trustworthy_str}. "
            f"Install Prophet for more sophisticated forecasting with seasonal awareness."
        ),
    }


def _build_deviation_scenario(
    series: pd.Series,
    col_name: str,
    baseline_dir: Path,
    forecast_baseline: pd.DataFrame,
    confidence_levels: list[float],
) -> dict | None:
    """
    Build a 'what-if current deviation persists' scenario.
    Compares recent data trend to baseline trend and applies the difference.
    """
    # Load baseline trend rate
    col_path = baseline_dir / "columns" / f"{col_name}.json"
    if not col_path.exists():
        return None

    with open(col_path) as f:
        col_baseline = json.load(f)

    baseline_rate = col_baseline.get("trend", {}).get("rate_per_period", 0)

    # Compute recent trend rate (last 20% of data)
    recent = series.iloc[-max(len(series) // 5, 10):]
    x = np.arange(len(recent))
    recent_slope, _, _, _, _ = scipy_stats.linregress(x, recent.values.astype(float))

    # If recent trend is significantly different from baseline
    rate_diff = recent_slope - baseline_rate
    if abs(rate_diff) < abs(baseline_rate) * 0.1:
        return None  # Not different enough to warrant a scenario

    # Apply deviation adjustment to baseline forecast
    predictions = []
    for i, (_, row) in enumerate(forecast_baseline.iterrows()):
        adjustment = rate_diff * (i + 1)
        point = float(row["yhat"]) + adjustment

        pred = {
            "timestamp": row["ds"].isoformat(),
            "point_forecast": round(point, 4),
        }
        # Widen CIs slightly for the deviation scenario (more uncertainty)
        std_est = (row["yhat_upper"] - row["yhat_lower"]) / (2 * scipy_stats.norm.ppf(0.9))
        for cl in confidence_levels:
            z = scipy_stats.norm.ppf((1 + cl) / 2)
            cl_label = str(int(cl * 100))
            pred[f"ci_{cl_label}_lower"] = round(float(point - z * std_est * 1.2), 4)
            pred[f"ci_{cl_label}_upper"] = round(float(point + z * std_est * 1.2), 4)
        predictions.append(pred)

    direction = "upward" if rate_diff > 0 else "downward"
    return {
        "name": "deviation_adjusted",
        "description": (
            f"Assumes the current {direction} trend deviation "
            f"(+{round(rate_diff, 4)}/period vs baseline) persists through the forecast horizon"
        ),
        "predictions": predictions,
    }


def _backtest_accuracy(
    df: pd.DataFrame,
    model,
    confidence_levels: list[float],
    horizon_periods: int,
) -> dict:
    """
    Walk-forward backtest to assess forecast accuracy.
    Uses the last 20% of data as the test set.
    """
    n = len(df)
    test_size = min(max(n // 5, 10), horizon_periods, n // 2)
    if test_size < 5:
        return {
            "backtest_mape": None,
            "backtest_coverage_80": None,
            "backtest_coverage_95": None,
            "trustworthy_horizon": "insufficient data for backtest",
        }

    train = df.iloc[:-test_size]
    test = df.iloc[-test_size:]

    try:
        bt_model = Prophet(interval_width=0.95, yearly_seasonality="auto", weekly_seasonality="auto")
        bt_model.fit(train)
        future = bt_model.make_future_dataframe(periods=test_size)
        forecast = bt_model.predict(future)
        forecast_test = forecast.iloc[-test_size:]

        # MAPE
        actuals = test["y"].values
        predicted = forecast_test["yhat"].values
        nonzero_mask = actuals != 0
        if nonzero_mask.any():
            mape = float(np.mean(np.abs((actuals[nonzero_mask] - predicted[nonzero_mask]) / actuals[nonzero_mask])) * 100)
        else:
            mape = None

        # CI coverage
        coverage_80 = None
        coverage_95 = None

        in_95 = ((actuals >= forecast_test["yhat_lower"].values) & (actuals <= forecast_test["yhat_upper"].values))
        coverage_95 = round(float(in_95.mean()), 3)

        # Estimate 80% CI from the 95% CI
        center = forecast_test["yhat"].values
        half_width_95 = (forecast_test["yhat_upper"].values - forecast_test["yhat_lower"].values) / 2
        z_95 = scipy_stats.norm.ppf(0.975)
        z_80 = scipy_stats.norm.ppf(0.9)
        half_width_80 = half_width_95 * (z_80 / z_95)
        in_80 = ((actuals >= center - half_width_80) & (actuals <= center + half_width_80))
        coverage_80 = round(float(in_80.mean()), 3)

        # Trustworthy horizon: find where cumulative MAPE exceeds threshold
        cum_errors = np.abs((actuals - predicted) / (actuals + 1e-10))
        trustworthy_idx = test_size
        for i in range(len(cum_errors)):
            if cum_errors[i] > 0.25:  # 25% error threshold
                trustworthy_idx = max(1, i)
                break

        freq = pd.infer_freq(df["ds"])
        if freq and "D" in str(freq):
            trustworthy_str = f"{trustworthy_idx} days"
        else:
            trustworthy_str = f"{trustworthy_idx} periods"

        return {
            "backtest_mape": round(mape, 2) if mape is not None else None,
            "backtest_coverage_80": coverage_80,
            "backtest_coverage_95": coverage_95,
            "trustworthy_horizon": trustworthy_str,
        }

    except Exception as e:
        logger.debug(f"Backtest failed: {e}")
        return {
            "backtest_mape": None,
            "backtest_coverage_80": None,
            "backtest_coverage_95": None,
            "trustworthy_horizon": f"backtest failed: {e}",
        }


def _forecast_narrative(
    col_name: str,
    predictions: list[dict],
    accuracy: dict,
    scenarios: list[dict],
) -> str:
    """Build forecast narrative."""
    parts = [f"Forecast for '{col_name}':"]

    if predictions:
        first = predictions[0]
        last = predictions[-1]
        parts.append(
            f"Projecting from {first['timestamp'][:10]} to {last['timestamp'][:10]} "
            f"({len(predictions)} periods)."
        )
        parts.append(f"Starting forecast: {first['point_forecast']}, ending: {last['point_forecast']}.")

    mape = accuracy.get("backtest_mape")
    if mape is not None:
        parts.append(f"Backtest MAPE: {mape}%.")

    horizon = accuracy.get("trustworthy_horizon")
    if horizon:
        parts.append(f"Forecast is reliable for approximately {horizon}.")

    if len(scenarios) > 1:
        parts.append(
            f"A deviation-adjusted scenario is also provided, showing "
            f"what happens if the current trend deviation persists."
        )

    return " ".join(parts)
