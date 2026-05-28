"""Signal analysis tools: baseline, deviations, forecast, and inspect."""

from circuit_core.signal_analysis.baseline import run_baseline
from circuit_core.signal_analysis.deviations import run_deviations
from circuit_core.signal_analysis.inspect import run_inspect


def run_forecast(*args, **kwargs):
    """Lazy wrapper — imports Prophet only when forecast is actually called."""
    from circuit_core.signal_analysis.forecast import run_forecast as _run
    return _run(*args, **kwargs)


__all__ = [
    "run_baseline",
    "run_deviations",
    "run_forecast",
    "run_inspect",
]
