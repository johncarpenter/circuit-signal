"""
Tool: detect_deviations (Mode 2)

Compare recent data against the baseline established in Mode 1.
Uses a 3-stage cascade:
  Stage 1: Statistical screening (rolling z-scores, IQR)
  Stage 2: Matrix Profile contextual anomaly detection (stumpy)
  Stage 3: Change point detection on residuals (ruptures)
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import ruptures as rpt
from scipy import stats as scipy_stats

from circuit_core.signal_analysis.ingest import load_data, parse_timestamps, parse_duration

logger = logging.getLogger("signal-discovery.deviations")

SENSITIVITY_THRESHOLDS = {
    "low": 3.0,
    "medium": 2.5,
    "high": 2.0,
}


def _safe_stump(values: np.ndarray, m: int, timeout: int = 120) -> np.ndarray | None:
    """Run stumpy.stump in an isolated subprocess via subprocess.Popen.

    Uses subprocess (not multiprocessing) to avoid issues with spawning
    processes from non-main threads (e.g. asyncio.to_thread).
    Data is exchanged via temporary .npy files.
    """
    in_file = None
    out_file = None
    try:
        # Write input to temp file
        in_file = tempfile.NamedTemporaryFile(suffix=".npy", delete=False)
        np.save(in_file, values)
        in_file.close()

        out_file = tempfile.NamedTemporaryFile(suffix=".npy", delete=False)
        out_path = out_file.name
        out_file.close()

        script = (
            "import sys, resource, numpy as np\n"
            "resource.setrlimit(resource.RLIMIT_AS, (1024*1024*1024, 1024*1024*1024))\n"  # 1GB cap
            "values = np.load(sys.argv[1])\n"
            "m = int(sys.argv[2])\n"
            "import stumpy\n"
            "mp = stumpy.stump(values, m=m)\n"
            "np.save(sys.argv[3], mp[:, 0].astype(float))\n"
        )

        proc = subprocess.run(
            [sys.executable, "-c", script, in_file.name, str(m), out_path],
            capture_output=True,
            timeout=timeout,
        )

        if proc.returncode != 0:
            stderr = proc.stderr.decode(errors="replace").strip()
            logger.warning(
                "Matrix Profile subprocess failed (exit %d): %s",
                proc.returncode,
                stderr[-200:] if stderr else "(no output)",
            )
            return None

        result = np.load(out_path)
        return result

    except subprocess.TimeoutExpired:
        logger.warning("Matrix Profile timed out after %ds", timeout)
        return None
    except Exception as e:
        logger.warning("Matrix Profile failed: %s", e)
        return None
    finally:
        if in_file:
            Path(in_file.name).unlink(missing_ok=True)
        if out_file:
            Path(out_path).unlink(missing_ok=True)


def run_deviations(
    data_path: str,
    timestamp_col: str,
    baseline_path: str,
    lookback_window: str = "90d",
    sensitivity: str = "medium",
    value_cols: list[str] | None = None,
) -> dict:
    """Run Mode 2 deviation detection."""

    bl_path = Path(baseline_path)
    if not (bl_path / "manifest.json").exists():
        return {"error": f"No baseline found at {baseline_path}. Run discover_baseline first."}

    # Load manifest
    with open(bl_path / "manifest.json") as f:
        manifest = json.load(f)

    # Load data
    df, _ = load_data(data_path)
    df = parse_timestamps(df, timestamp_col)

    # Determine columns to check
    baselined_cols = manifest.get("columns_analyzed", [])
    if value_cols:
        cols = [c for c in value_cols if c in baselined_cols]
    else:
        cols = baselined_cols

    # Aggregate transactional data to match baseline frequency
    baseline_freq = manifest.get("frequency", None)
    RESAMPLE_MAP = {
        "sub_hourly": "1min", "hourly": "1h", "daily": "1D",
        "weekly": "1W", "monthly": "1ME", "quarterly": "1QE", "yearly": "1YE",
    }
    resample_rule = RESAMPLE_MAP.get(baseline_freq)
    if resample_rule and cols and len(df) > 0:
        time_span = (df.index.max() - df.index.min()).total_seconds()
        expected_periods = {
            "sub_hourly": time_span / 60, "hourly": time_span / 3600,
            "daily": time_span / 86400, "weekly": time_span / 604800,
            "monthly": time_span / 2592000,
        }.get(baseline_freq, len(df))
        if expected_periods > 0 and len(df) > expected_periods * 2:
            logger.info("Aggregating %d rows to %s for deviation detection", len(df), baseline_freq)
            df = df[cols].resample(resample_rule).sum()
            df = df.loc[df.index.notna()]

    if not cols:
        return {"error": "No matching columns between data and baseline."}

    # Determine analysis window (defaults to 90d; else branch is a safety fallback
    # in case lookback_window is explicitly passed as None by callers)
    if lookback_window:
        window_delta = parse_duration(lookback_window)
        window_start = df.index.max() - window_delta
        analysis_df = df[df.index >= window_start]
    else:
        # Fallback: use everything after baseline end
        baseline_end = pd.Timestamp(manifest["time_range"]["end"], tz="UTC")
        analysis_df = df[df.index > baseline_end]
        if len(analysis_df) == 0:
            # If no new data, analyze the last 20% of the dataset
            cutoff = int(len(df) * 0.8)
            analysis_df = df.iloc[cutoff:]

    z_threshold = SENSITIVITY_THRESHOLDS.get(sensitivity, 2.5)

    # Detect deviations per column
    all_deviations = []
    for col in cols:
        if col not in analysis_df.columns:
            continue

        try:
            col_deviations = _detect_column_deviations(
                series=analysis_df[col].dropna(),
                col_name=col,
                baseline_dir=bl_path,
                z_threshold=z_threshold,
                full_series=df[col].dropna(),
            )
            all_deviations.extend(col_deviations)
        except Exception as e:
            logger.warning(f"Deviation detection failed for '{col}': {e}")
            all_deviations.append({
                "column": col,
                "type": "error",
                "severity": "low",
                "narrative": f"Detection failed: {e}",
            })

    # Sort by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    all_deviations.sort(key=lambda d: severity_order.get(d.get("severity", "low"), 4))

    # Summary
    by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for d in all_deviations:
        sev = d.get("severity", "low")
        if sev in by_severity:
            by_severity[sev] += 1

    affected_cols = list(set(d["column"] for d in all_deviations if d.get("type") != "error"))

    summary_narrative = _build_summary_narrative(all_deviations, by_severity, affected_cols)

    return {
        "analysis_window": {
            "start": analysis_df.index.min().isoformat() if len(analysis_df) > 0 else None,
            "end": analysis_df.index.max().isoformat() if len(analysis_df) > 0 else None,
        },
        "deviations": all_deviations,
        "summary": {
            "total_deviations": len([d for d in all_deviations if d.get("type") != "error"]),
            "by_severity": by_severity,
            "most_affected_columns": affected_cols[:5],
            "narrative": summary_narrative,
        },
    }


def _detect_column_deviations(
    series: pd.Series,
    col_name: str,
    baseline_dir: Path,
    z_threshold: float,
    full_series: pd.Series,
) -> list[dict]:
    """
    Run the 3-stage detection cascade on a single column.
    """
    deviations = []

    # Load baseline residual profile
    col_baseline_path = baseline_dir / "columns" / f"{col_name}.json"
    if col_baseline_path.exists():
        with open(col_baseline_path) as f:
            col_baseline = json.load(f)
        baseline_std = col_baseline.get("residual_profile", {}).get("std", None)
        baseline_trend_rate = col_baseline.get("trend", {}).get("rate_per_period", 0)
    else:
        baseline_std = series.std()
        baseline_trend_rate = 0

    # Load baseline residual series if available
    resid_path = baseline_dir / "decompositions" / f"{col_name}_residual.parquet"
    if resid_path.exists():
        baseline_residual = pd.read_parquet(resid_path)["value"]
    else:
        baseline_residual = None

    # Load baseline trend for comparison
    trend_path = baseline_dir / "decompositions" / f"{col_name}_trend.parquet"
    if trend_path.exists():
        baseline_trend = pd.read_parquet(trend_path)["value"]
    else:
        baseline_trend = None

    # ===== STAGE 1: Statistical screening =====
    if baseline_std and baseline_std > 0:
        rolling_mean = series.rolling(window=max(len(series) // 10, 3), center=True).mean()
        rolling_mean = rolling_mean.ffill().bfill()
        z_scores = (series - rolling_mean) / baseline_std

        outlier_mask = z_scores.abs() > z_threshold
        outlier_points = series[outlier_mask]

        for ts, val in outlier_points.items():
            z = float(z_scores.loc[ts])
            deviations.append({
                "column": col_name,
                "type": "point_anomaly",
                "severity": _severity_from_z(abs(z)),
                "timestamp_range": {"start": ts.isoformat(), "end": ts.isoformat()},
                "details": {
                    "expected_value": round(float(rolling_mean.loc[ts]), 4),
                    "observed_value": round(float(val), 4),
                    "deviation_magnitude": round(float(val - rolling_mean.loc[ts]), 4),
                    "z_score": round(z, 2),
                    "confidence": round(min(1.0, abs(z) / 5.0), 3),
                },
                "persistence": "transient",
                "narrative": (
                    f"Point anomaly in '{col_name}' at {ts.isoformat()}: "
                    f"observed {round(float(val), 2)} vs expected {round(float(rolling_mean.loc[ts]), 2)} "
                    f"(z-score: {round(z, 2)})"
                ),
            })

    # ===== STAGE 2: Matrix Profile (contextual anomalies) =====
    # Runs in a subprocess to isolate SIGILL/crashes from numba JIT.
    # Skip entirely when DISABLE_MATRIX_PROFILE=1 (saves ~500MB+ from numba/LLVM JIT).
    # Z-score screening (Stage 1) and ruptures change points (Stage 3) provide
    # sufficient deviation detection for most use cases.
    MAX_MP_LENGTH = 2000
    skip_mp = os.environ.get("DISABLE_MATRIX_PROFILE", "").strip() in ("1", "true", "yes")
    if skip_mp:
        logger.info(f"Matrix Profile disabled via DISABLE_MATRIX_PROFILE — skipping Stage 2 for '{col_name}'")
    elif len(full_series) >= 20:
        mp_series = full_series.iloc[-MAX_MP_LENGTH:] if len(full_series) > MAX_MP_LENGTH else full_series
        m = max(len(mp_series) // 20, 4)  # subsequence length
        mp_values = _safe_stump(mp_series.values.astype(float), m=m, timeout=60)

        if mp_values is not None:
            try:
                mp_threshold = np.percentile(mp_values, 95)

                # Find discords in the analysis window
                analysis_start_idx = mp_series.index.get_indexer([series.index.min()], method="nearest")[0]
                for i in range(max(0, analysis_start_idx), len(mp_values)):
                    if mp_values[i] > mp_threshold:
                        ts = mp_series.index[i]
                        if ts >= series.index.min():
                            discord_score = float(mp_values[i])
                            normalized = (discord_score - mp_threshold) / (mp_values.max() - mp_threshold + 1e-10)
                            deviations.append({
                                "column": col_name,
                                "type": "regime_change",
                                "severity": "medium" if normalized < 0.5 else "high",
                                "timestamp_range": {
                                    "start": ts.isoformat(),
                                    "end": mp_series.index[min(i + m, len(mp_series) - 1)].isoformat(),
                                },
                                "details": {
                                    "expected_value": None,
                                    "observed_value": None,
                                    "deviation_magnitude": round(normalized, 4),
                                    "z_score": None,
                                    "confidence": round(min(1.0, normalized), 3),
                                },
                                "persistence": "sustained",
                                "narrative": (
                                    f"Contextual anomaly detected in '{col_name}' starting {ts.isoformat()}: "
                                    f"this pattern subsequence has no close historical match "
                                    f"(discord score: {round(discord_score, 2)})"
                                ),
                            })
            except Exception as e:
                logger.debug(f"Matrix Profile analysis failed for '{col_name}': {e}")

    # ===== STAGE 3: Change point detection on recent data =====
    if len(series) >= 15:
        try:
            values = series.values.astype(float)
            algo = rpt.Pelt(model="rbf", min_size=max(len(values) // 10, 5))
            penalty = np.log(len(values)) * values.std() ** 2
            cps = algo.fit_predict(values, pen=penalty)

            for cp_idx in cps[:-1]:
                if 0 < cp_idx < len(values):
                    before = values[max(0, cp_idx - 5) : cp_idx]
                    after = values[cp_idx : min(len(values), cp_idx + 5)]
                    magnitude = float(after.mean() - before.mean())
                    ts = series.index[cp_idx]

                    deviations.append({
                        "column": col_name,
                        "type": "trend_shift",
                        "severity": _severity_from_magnitude(abs(magnitude), baseline_std or 1.0),
                        "timestamp_range": {"start": ts.isoformat(), "end": ts.isoformat()},
                        "details": {
                            "expected_value": round(float(before.mean()), 4),
                            "observed_value": round(float(after.mean()), 4),
                            "deviation_magnitude": round(magnitude, 4),
                            "z_score": round(magnitude / (baseline_std or 1.0), 2),
                            "confidence": 0.75,
                        },
                        "persistence": "sustained",
                        "narrative": (
                            f"Trend shift detected in '{col_name}' at {ts.isoformat()}: "
                            f"mean shifted from {round(float(before.mean()), 2)} to "
                            f"{round(float(after.mean()), 2)} "
                            f"(change of {round(magnitude, 2)})"
                        ),
                    })
        except Exception as e:
            logger.debug(f"Change point detection failed for '{col_name}': {e}")

    # Deduplicate — if a point anomaly and a regime change overlap, keep the higher-severity one
    deviations = _deduplicate_deviations(deviations)

    return deviations


def _severity_from_z(z: float) -> str:
    if z >= 4.0:
        return "critical"
    elif z >= 3.0:
        return "high"
    elif z >= 2.5:
        return "medium"
    else:
        return "low"


def _severity_from_magnitude(magnitude: float, baseline_std: float) -> str:
    ratio = magnitude / baseline_std
    if ratio >= 3.0:
        return "critical"
    elif ratio >= 2.0:
        return "high"
    elif ratio >= 1.0:
        return "medium"
    else:
        return "low"


def _deduplicate_deviations(deviations: list[dict]) -> list[dict]:
    """Remove overlapping deviations, keeping the higher-severity one."""
    if len(deviations) <= 1:
        return deviations

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    deviations.sort(key=lambda d: severity_order.get(d.get("severity", "low"), 4))

    seen_timestamps = set()
    unique = []
    for d in deviations:
        ts_key = d.get("timestamp_range", {}).get("start", "")
        if ts_key not in seen_timestamps:
            seen_timestamps.add(ts_key)
            unique.append(d)

    return unique


def _build_summary_narrative(deviations: list[dict], by_severity: dict, affected_cols: list[str]) -> str:
    """Build an executive summary of all deviations."""
    total = sum(by_severity.values())
    if total == 0:
        return "No significant deviations detected. All metrics are behaving within expected baseline patterns."

    parts = [f"Detected {total} deviation{'s' if total > 1 else ''}."]

    if by_severity["critical"] > 0:
        parts.append(f"{by_severity['critical']} critical finding{'s' if by_severity['critical'] > 1 else ''} requiring immediate attention.")

    if affected_cols:
        parts.append(f"Most affected metric{'s' if len(affected_cols) > 1 else ''}: {', '.join(affected_cols[:3])}.")

    # Count by type
    type_counts = {}
    for d in deviations:
        t = d.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    if "trend_shift" in type_counts:
        parts.append(f"{type_counts['trend_shift']} structural trend shift{'s' if type_counts['trend_shift'] > 1 else ''}.")
    if "regime_change" in type_counts:
        parts.append(f"{type_counts['regime_change']} contextual pattern anomal{'ies' if type_counts['regime_change'] > 1 else 'y'}.")

    return " ".join(parts)
