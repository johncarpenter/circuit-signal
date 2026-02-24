"""Tool dispatcher — maps tool names to run_* functions and executes them."""

import asyncio
import json
import logging
import os

# Layer 0
from data_loader.tools.load import run_load
from data_loader.tools.suggest import run_suggest_segments
from data_loader.tools.batch_create import run_create_segments
from data_loader.tools.segments import run_list_segments
from data_loader.tools.export import run_export_segment
from data_loader.tools.clean import run_clean_dataset, run_llm_entity_resolution

# Layer 1
from signal_discovery.tools.inspect import run_inspect
from signal_discovery.tools.baseline import run_baseline
from signal_discovery.tools.deviations import run_deviations
from signal_discovery.tools.forecast import run_forecast

# Layer 2
from signal_correlation.tools.sources import run_register_source, run_list_sources
from signal_correlation.tools.ingest import run_ingest_signals
from signal_correlation.tools.correlate import run_correlate_signals
from signal_correlation.tools.insights import run_query_insights, run_explain_insight

logger = logging.getLogger("signal-app.dispatch")

# Layer 2 tools that need a SignalStore injected
_LAYER2_TOOLS = {
    "register_source",
    "list_sources",
    "ingest_signals",
    "correlate_signals",
    "query_insights",
    "explain_insight",
}


def _call_tool(name: str, params: dict, store, work_dir: str) -> dict:
    """Synchronous tool dispatch — called inside asyncio.to_thread."""

    # --- Layer 0 ---
    if name == "load_dataset":
        return run_load(**params)

    if name == "suggest_segments":
        return run_suggest_segments(**params)

    if name == "create_segments":
        return run_create_segments(**params)

    if name == "list_segments":
        return run_list_segments(**params)

    if name == "export_segment":
        return run_export_segment(**params)

    if name == "clean_dataset":
        return run_clean_dataset(**params)

    if name == "resolve_entities":
        return run_llm_entity_resolution(**params)

    # --- Layer 1 ---
    if name == "inspect_dataset":
        return run_inspect(**params)

    if name == "discover_baseline":
        # Default output_dir to work_dir/.signal-baselines if not provided
        if not params.get("output_dir"):
            params["output_dir"] = os.path.join(work_dir, ".signal-baselines")
        return run_baseline(**params)

    if name == "detect_deviations":
        return run_deviations(**params)

    if name == "project_forecast":
        # Default confidence_levels
        if params.get("confidence_levels") is None:
            params["confidence_levels"] = [0.80, 0.95]
        return run_forecast(**params)

    # --- Layer 2 (inject store, strip db_path) ---
    if name in _LAYER2_TOOLS:
        params.pop("db_path", None)

        if name == "register_source":
            return run_register_source(store=store, **params)

        if name == "list_sources":
            return run_list_sources(store)

        if name == "ingest_signals":
            return run_ingest_signals(store=store, **params)

        if name == "correlate_signals":
            return run_correlate_signals(store=store, **params)

        if name == "query_insights":
            return run_query_insights(store=store, **params)

        if name == "explain_insight":
            return run_explain_insight(store=store, **params)

    raise ValueError(f"Unknown tool: {name}")


async def dispatch_tool(name: str, params: dict, store, work_dir: str) -> str:
    """Async wrapper — runs sync tool code in a thread to keep the event loop free."""
    try:
        result = await asyncio.to_thread(_call_tool, name, params, store, work_dir)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return json.dumps({"error": str(e)}, indent=2)
