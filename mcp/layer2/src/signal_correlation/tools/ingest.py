"""
Tool: ingest_signals

Parse Layer 1 output (Mode 1 baselines or Mode 2 deviations) into
the canonical signal format and store in DuckDB.
"""

import json
import logging
import uuid
from pathlib import Path

from signal_correlation.store import SignalStore

logger = logging.getLogger("signal-correlation.ingest")


def run_ingest_signals(
    store: SignalStore,
    source_id: str,
    signal_type: str = "deviations",
    data: dict | None = None,
    data_path: str | None = None,
    context: dict | None = None,
) -> dict:
    """Ingest Layer 1 signals into the store."""

    # Validate source exists
    source = store.get_source(source_id)
    if not source:
        return {"error": f"Source '{source_id}' not registered. Call register_source first."}

    # Load data
    if data is None and data_path:
        path = Path(data_path)
        if not path.exists():
            return {"error": f"Data file not found: {data_path}"}
        with open(path) as f:
            data = json.load(f)

    if data is None:
        return {"error": "Must provide either 'data' or 'data_path'."}

    # Parse signals based on type
    if signal_type == "deviations":
        signals = _parse_deviations(data, source_id, source)
    elif signal_type == "baseline":
        signals = _parse_baselines(data, source_id, source)
    else:
        return {"error": f"Unknown signal_type: {signal_type}. Use 'deviations' or 'baseline'."}

    if not signals:
        return {
            "source_id": source_id,
            "signals_ingested": 0,
            "by_type": {},
            "time_range": {"start": None, "end": None},
            "total_signals_in_store": store.count_signals(),
            "note": "No signals found in the provided data.",
        }

    # Insert into store
    count = store.insert_signals(signals)

    # Summarize
    by_type = {}
    timestamps = []
    for sig in signals:
        st = sig["signal_type"]
        by_type[st] = by_type.get(st, 0) + 1
        if sig.get("ts_start"):
            timestamps.append(sig["ts_start"])

    return {
        "source_id": source_id,
        "signals_ingested": count,
        "by_type": by_type,
        "time_range": {
            "start": min(timestamps) if timestamps else None,
            "end": max(timestamps) if timestamps else None,
        },
        "total_signals_in_store": store.count_signals(),
    }


def _parse_deviations(data: dict, source_id: str, source: dict) -> list[dict]:
    """Parse Layer 1 Mode 2 deviation output into canonical signals."""
    signals = []
    deviations = data.get("deviations", [])

    # Get geography from source registration
    lat = source.get("latitude")
    lon = source.get("longitude")

    for dev in deviations:
        if dev.get("type") == "error":
            continue

        ts_range = dev.get("timestamp_range", {})
        details = dev.get("details", {})

        signal = {
            "signal_id": f"sig_{uuid.uuid4().hex[:12]}",
            "source_id": source_id,
            "column_name": dev.get("column", "unknown"),
            "signal_type": dev.get("type", "unknown"),
            "severity": dev.get("severity", "low"),
            "ts_start": ts_range.get("start"),
            "ts_end": ts_range.get("end"),
            "magnitude": details.get("deviation_magnitude"),
            "direction": _infer_direction(details),
            "confidence": details.get("confidence", 0.5),
            "latitude": lat,
            "longitude": lon,
            "entity_values": None,
            "metadata": {
                "expected_value": details.get("expected_value"),
                "observed_value": details.get("observed_value"),
                "z_score": details.get("z_score"),
                "persistence": dev.get("persistence"),
            },
            "narrative": dev.get("narrative"),
        }
        signals.append(signal)

    return signals


def _parse_baselines(data: dict, source_id: str, source: dict) -> list[dict]:
    """Parse Layer 1 Mode 1 baseline output into signals representing normal patterns."""
    signals = []
    baselines = data.get("baselines", [])
    time_range = data.get("dataset_summary", {}).get("time_range", {})

    lat = source.get("latitude")
    lon = source.get("longitude")

    for bl in baselines:
        if bl.get("error"):
            continue

        # Create a baseline_pattern signal for each column
        trend = bl.get("trend", {})
        seasonality = bl.get("seasonality", [])

        signal = {
            "signal_id": f"sig_{uuid.uuid4().hex[:12]}",
            "source_id": source_id,
            "column_name": bl.get("column", "unknown"),
            "signal_type": "baseline_pattern",
            "severity": None,
            "ts_start": time_range.get("start"),
            "ts_end": time_range.get("end"),
            "magnitude": bl.get("variance_explained"),
            "direction": trend.get("direction"),
            "confidence": bl.get("variance_explained", 0.5),
            "latitude": lat,
            "longitude": lon,
            "entity_values": None,
            "metadata": {
                "trend_rate": trend.get("rate_per_period"),
                "change_points": trend.get("change_points", []),
                "seasonality": seasonality,
                "residual_profile": bl.get("residual_profile"),
            },
            "narrative": bl.get("narrative"),
        }
        signals.append(signal)

        # Also create signals for any trend change points
        for cp in trend.get("change_points", []):
            cp_signal = {
                "signal_id": f"sig_{uuid.uuid4().hex[:12]}",
                "source_id": source_id,
                "column_name": bl.get("column", "unknown"),
                "signal_type": "trend_shift",
                "severity": "medium",
                "ts_start": cp.get("timestamp"),
                "ts_end": cp.get("timestamp"),
                "magnitude": cp.get("magnitude"),
                "direction": cp.get("direction"),
                "confidence": 0.7,
                "latitude": lat,
                "longitude": lon,
                "entity_values": None,
                "metadata": {"source": "baseline_change_point"},
                "narrative": (
                    f"Historical trend change point in '{bl.get('column')}' at "
                    f"{cp.get('timestamp')}: {cp.get('direction')} of {cp.get('magnitude')}"
                ),
            }
            signals.append(cp_signal)

    return signals


def _infer_direction(details: dict) -> str:
    """Infer direction from deviation details."""
    magnitude = details.get("deviation_magnitude")
    if magnitude is not None:
        return "increase" if magnitude > 0 else "decrease"
    observed = details.get("observed_value")
    expected = details.get("expected_value")
    if observed is not None and expected is not None:
        return "increase" if observed > expected else "decrease"
    return "shift"
