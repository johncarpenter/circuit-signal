"""
Signal Discovery MCP Server

Exposes four tools via MCP:
  1. inspect_dataset   — quick data profiling
  2. discover_baseline — Mode 1: decompose to find "normal"
  3. detect_deviations — Mode 2: flag what's different
  4. project_forecast  — Mode 3: project forward with scenarios
"""

import json
import logging

from mcp.server.fastmcp import FastMCP

from signal_discovery.tools.inspect import run_inspect
from signal_discovery.tools.baseline import run_baseline
from signal_discovery.tools.deviations import run_deviations
from signal_discovery.tools.forecast import run_forecast

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("signal-discovery")

mcp = FastMCP(
    "Signal Discovery",
    instructions="Autonomous time-series signal discovery: baseline patterns, deviation detection, and forecasting",
)


@mcp.tool()
def inspect_dataset(data_path: str, sample_rows: int = 5) -> str:
    """
    Quick exploratory scan of a dataset. Returns column info, data types,
    timestamp candidates, basic stats, and sample rows.

    Args:
        data_path: Path to CSV, Parquet, or JSON file
        sample_rows: Number of sample rows to return (default 5)
    """
    result = run_inspect(data_path=data_path, sample_rows=sample_rows)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def discover_baseline(
    data_path: str,
    timestamp_col: str,
    value_cols: list[str] | None = None,
    freq: str | None = None,
    output_dir: str | None = None,
) -> str:
    """
    Mode 1: Decompose time series to establish baseline patterns.
    Discovers trend, seasonality, and residual characteristics for each
    numeric column. Saves baseline artifacts for use by detect_deviations
    and project_forecast.

    Args:
        data_path: Path to CSV, Parquet, or JSON file
        timestamp_col: Name of the timestamp column
        value_cols: Columns to analyze (null = auto-detect all numeric)
        freq: Frequency hint: 'hourly','daily','weekly','monthly' (null = auto-detect)
        output_dir: Where to save baseline artifacts (default: ./.signal-baselines/)
    """
    result = run_baseline(
        data_path=data_path, timestamp_col=timestamp_col,
        value_cols=value_cols, freq=freq, output_dir=output_dir,
    )
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def detect_deviations(
    data_path: str,
    timestamp_col: str,
    baseline_path: str,
    lookback_window: str = "90d",
    sensitivity: str = "medium",
    value_cols: list[str] | None = None,
) -> str:
    """
    Mode 2: Compare recent data against the baseline from Mode 1.
    Detects trend shifts, seasonal anomalies, point anomalies, and regime changes
    using a 3-stage cascade (z-scores → Matrix Profile → change point detection).

    Args:
        data_path: Path to data file
        timestamp_col: Name of timestamp column
        baseline_path: Path to Mode 1 baseline artifacts directory
        lookback_window: How far back to analyze: '7d','30d','90d' (default: '90d')
        sensitivity: Detection sensitivity: 'low','medium','high'
        value_cols: Columns to check (null = all baselined columns)
    """
    result = run_deviations(
        data_path=data_path, timestamp_col=timestamp_col,
        baseline_path=baseline_path, lookback_window=lookback_window,
        sensitivity=sensitivity, value_cols=value_cols,
    )
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def project_forecast(
    data_path: str,
    timestamp_col: str,
    baseline_path: str,
    value_cols: list[str] | None = None,
    horizon: str = "30d",
    scenarios: bool = True,
    confidence_levels: list[float] | None = None,
) -> str:
    """
    Mode 3: Generate confidence-bounded projections with scenario variants.
    Includes backtest accuracy metrics and trustworthy horizon estimates.

    Args:
        data_path: Path to data file
        timestamp_col: Name of timestamp column
        baseline_path: Path to Mode 1 baseline artifacts
        value_cols: Columns to forecast (null = all baselined)
        horizon: Forecast horizon: '7d','30d','90d','365d'
        scenarios: Generate deviation-adjusted scenarios (default true)
        confidence_levels: Confidence intervals (default [0.80, 0.95])
    """
    result = run_forecast(
        data_path=data_path, timestamp_col=timestamp_col,
        baseline_path=baseline_path, value_cols=value_cols,
        horizon=horizon, scenarios=scenarios,
        confidence_levels=confidence_levels or [0.80, 0.95],
    )
    return json.dumps(result, indent=2, default=str)


def main():
    """Run the MCP server via stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
