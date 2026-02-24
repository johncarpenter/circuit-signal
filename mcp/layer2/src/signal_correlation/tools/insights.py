"""
Tools: query_insights, explain_insight

Retrieve, filter, and deep-dive into discovered cross-dataset insights.
"""

import json
import logging

from signal_correlation.store import SignalStore

logger = logging.getLogger("signal-correlation.insights")


def run_query_insights(
    store: SignalStore,
    source_ids: list[str] | None = None,
    min_actionability: float = 0.0,
    min_strength: float = 0.0,
    tags: list[str] | None = None,
    time_window: dict | None = None,
    limit: int = 20,
    sort_by: str = "actionability",
) -> dict:
    """Query previously discovered insights with filters."""

    insights = store.query_insights(
        source_ids=source_ids,
        min_actionability=min_actionability,
        min_strength=min_strength,
        limit=limit,
        sort_by=sort_by,
    )

    # Format for output
    formatted = []
    for ins in insights:
        formatted.append({
            "insight_id": ins["insight_id"],
            "title": ins.get("title"),
            "correlation_types": ins.get("correlation_types", []),
            "strength": ins.get("strength"),
            "actionability_score": ins.get("actionability"),
            "lag_structure": ins.get("lag_structure"),
            "suggested_actions": ins.get("suggested_actions", []),
            "narrative": ins.get("narrative"),
        })

    return {
        "insights": formatted,
        "total_matching": len(formatted),
        "returned": len(formatted),
    }


def run_explain_insight(
    store: SignalStore,
    insight_id: str,
) -> dict:
    """Deep-dive into a specific insight with full signal chain and evidence."""

    insight = store.get_insight(insight_id)
    if not insight:
        return {"error": f"Insight '{insight_id}' not found."}

    # Load the signals in this insight
    signal_ids = insight.get("signal_ids", [])
    all_signals = store.get_signals()
    sig_lookup = {s["signal_id"]: s for s in all_signals}

    signals_detail = []
    for sid in signal_ids:
        sig = sig_lookup.get(sid)
        if not sig:
            continue

        # Get source name
        source = store.get_source(sig["source_id"])
        source_name = source["name"] if source else sig["source_id"]

        signals_detail.append({
            "signal_id": sid,
            "source_id": sig["source_id"],
            "source_name": source_name,
            "column": sig["column_name"],
            "signal_type": sig["signal_type"],
            "severity": sig.get("severity"),
            "timestamp_range": {
                "start": str(sig.get("ts_start")) if sig.get("ts_start") else None,
                "end": str(sig.get("ts_end")) if sig.get("ts_end") else None,
            },
            "magnitude": sig.get("magnitude"),
            "original_narrative": sig.get("narrative"),
        })

    # Load the correlations in this insight
    correlations = store.get_correlations(insight_id=insight_id)
    correlations_detail = []
    for corr in correlations:
        correlations_detail.append({
            "from_signal": corr.get("signal_a_id"),
            "to_signal": corr.get("signal_b_id"),
            "type": corr.get("correlation_type"),
            "strength": corr.get("strength"),
            "lag": corr.get("lag_description"),
            "evidence": corr.get("evidence"),
        })

    # Build the graph path description
    graph_path = _describe_graph_path(signals_detail, correlations_detail)

    # Confidence assessment
    confidence_assessment = _assess_confidence(
        signals_detail, correlations_detail, insight
    )

    # Actionability detail
    actionability_detail = {
        "score": insight.get("actionability"),
        "reasoning": _actionability_reasoning(insight, signals_detail),
        "suggested_actions": insight.get("suggested_actions", []),
        "estimated_impact": None,
    }

    return {
        "insight": {
            "insight_id": insight_id,
            "title": insight.get("title"),
            "narrative": insight.get("narrative"),
            "signals": signals_detail,
            "correlations": correlations_detail,
            "graph_path": graph_path,
            "confidence_assessment": confidence_assessment,
            "actionability": actionability_detail,
        }
    }


def _describe_graph_path(signals: list[dict], correlations: list[dict]) -> str:
    """Describe the multi-hop path through the signal graph."""
    if not correlations:
        return "No correlation path available."

    # Build adjacency for narrative
    parts = []
    for corr in correlations:
        from_sig = next((s for s in signals if s["signal_id"] == corr["from_signal"]), None)
        to_sig = next((s for s in signals if s["signal_id"] == corr["to_signal"]), None)

        from_label = f"{from_sig['column']} ({from_sig['source_id']})" if from_sig else corr["from_signal"]
        to_label = f"{to_sig['column']} ({to_sig['source_id']})" if to_sig else corr["to_signal"]

        link_type = corr.get("type", "correlated")
        strength = corr.get("strength", 0)
        lag = corr.get("lag")

        link_desc = f"{from_label} → [{link_type}, r={round(strength, 2)}"
        if lag:
            link_desc += f", {lag}"
        link_desc += f"] → {to_label}"
        parts.append(link_desc)

    return " | ".join(parts)


def _assess_confidence(
    signals: list[dict],
    correlations: list[dict],
    insight: dict,
) -> dict:
    """Assess overall confidence and identify weakest links."""

    corr_strengths = [c.get("strength", 0) for c in correlations if c.get("strength")]

    if not corr_strengths:
        return {
            "overall_confidence": 0.0,
            "weakest_link": "No correlations to assess",
            "data_sufficiency": "Unknown",
            "alternative_explanations": [],
        }

    overall = float(min(corr_strengths))  # Chain is as strong as weakest link
    weakest_corr = min(correlations, key=lambda c: c.get("strength", 0))

    from_sig = next((s for s in signals if s["signal_id"] == weakest_corr.get("from_signal")), None)
    to_sig = next((s for s in signals if s["signal_id"] == weakest_corr.get("to_signal")), None)

    weakest_desc = (
        f"The {weakest_corr.get('type')} link between "
        f"'{from_sig['column'] if from_sig else '?'}' and "
        f"'{to_sig['column'] if to_sig else '?'}' "
        f"(strength: {round(weakest_corr.get('strength', 0), 2)})"
    )

    # Data sufficiency
    n_signals = len(signals)
    n_sources = len(set(s["source_id"] for s in signals))
    if n_signals >= 5 and n_sources >= 3:
        data_suff = "Strong — multiple signals across multiple sources support this finding"
    elif n_signals >= 3 and n_sources >= 2:
        data_suff = "Moderate — finding is supported but more data would increase confidence"
    else:
        data_suff = "Limited — this finding rests on few signals and should be validated"

    # Alternative explanations
    alternatives = [
        "Shared external driver (e.g., seasonal event, holiday, weather) affecting all sources simultaneously",
        "Data collection artifact — changes in how data is captured rather than genuine behavioral change",
    ]
    corr_types = set(c.get("type") for c in correlations)
    if "temporal_co_occurrence" in corr_types and "lagged_correlation" not in corr_types:
        alternatives.append(
            "Coincidental timing — signals may be independent events that happened to overlap"
        )
    if "spatial_alignment" in corr_types:
        alternatives.append(
            "Spatial confound — geographic proximity may reflect shared demographics rather than causal link"
        )

    return {
        "overall_confidence": round(overall, 3),
        "weakest_link": weakest_desc,
        "data_sufficiency": data_suff,
        "alternative_explanations": alternatives,
    }


def _actionability_reasoning(insight: dict, signals: list[dict]) -> str:
    """Explain why the actionability score is what it is."""
    score = insight.get("actionability", 0)
    parts = []

    n_sources = len(set(s["source_id"] for s in signals))
    if n_sources >= 3:
        parts.append(f"Spans {n_sources} data sources (high cross-domain coverage)")
    elif n_sources == 2:
        parts.append(f"Spans {n_sources} data sources (moderate coverage)")

    severities = [s.get("severity") for s in signals if s.get("severity")]
    if "critical" in severities:
        parts.append("Contains critical-severity signals")
    elif "high" in severities:
        parts.append("Contains high-severity signals")

    corr_types = insight.get("correlation_types", [])
    if "lagged_correlation" in corr_types:
        parts.append("Includes lagged relationship (potential predictive value)")

    if score >= 0.75:
        parts.append("Overall: HIGH — strong candidate for operational action")
    elif score >= 0.5:
        parts.append("Overall: MODERATE — warrants further investigation")
    else:
        parts.append("Overall: LOW — monitor for persistence before acting")

    return ". ".join(parts) + "."
