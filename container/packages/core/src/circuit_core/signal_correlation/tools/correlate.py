"""
Tool: correlate_signals

The core correlation engine. Finds relationships between signals from
different data sources using multiple correlation methods:
  1. Temporal co-occurrence
  2. Lagged correlation
  3. Spatial alignment
  4. Entity alignment
  5. Pattern similarity

Then clusters correlated signals into actionable insight narratives.
"""

import logging
import time
import uuid
from itertools import combinations
from math import radians, cos, sin, asin, sqrt

import numpy as np
import pandas as pd
import networkx as nx
from scipy import stats as scipy_stats
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler

from circuit_core.signal_correlation.store import SignalStore

logger = logging.getLogger("signal-correlation.correlate")

SEVERITY_SCORE = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}


def run_correlate_signals(
    store: SignalStore,
    source_ids: list[str] | None = None,
    time_window: dict | None = None,
    correlation_types: list[str] | None = None,
    options: dict | None = None,
) -> dict:
    """Run cross-source signal correlation analysis."""
    start_time = time.time()
    opts = options or {}

    temporal_window = pd.Timedelta(opts.get("temporal_window", "7d"))
    spatial_radius_km = opts.get("spatial_radius_km", 50.0)
    lag_max_periods = opts.get("lag_max_periods", 30)
    min_confidence = opts.get("min_confidence", 0.5)
    do_clustering = opts.get("cluster_signals", True)

    enabled_types = set(correlation_types or [
        "temporal_co_occurrence",
        "lagged_correlation",
        "spatial_alignment",
        "entity_alignment",
        "pattern_similarity",
    ])

    # Clear previous correlations and insights (fresh analysis)
    store.clear_correlations_and_insights()

    # Fetch signals
    signals = store.get_signals(
        source_ids=source_ids,
        ts_start=time_window.get("start") if time_window else None,
        ts_end=time_window.get("end") if time_window else None,
    )

    if len(signals) < 2:
        return {
            "correlations_found": 0,
            "by_type": {},
            "pairwise_correlations": [],
            "insights": [],
            "meta": {
                "sources_analyzed": 0,
                "signals_analyzed": len(signals),
                "analysis_duration_seconds": time.time() - start_time,
            },
        }

    # Group signals by source
    by_source = {}
    for sig in signals:
        sid = sig["source_id"]
        by_source.setdefault(sid, []).append(sig)

    source_pairs = list(combinations(by_source.keys(), 2))
    all_correlations = []
    by_type_counts = {}

    # --- Run correlation methods ---

    if "temporal_co_occurrence" in enabled_types:
        corrs = _temporal_co_occurrence(by_source, source_pairs, temporal_window, min_confidence)
        all_correlations.extend(corrs)
        by_type_counts["temporal_co_occurrence"] = len(corrs)

    if "lagged_correlation" in enabled_types:
        corrs = _lagged_correlation(by_source, source_pairs, lag_max_periods, min_confidence)
        all_correlations.extend(corrs)
        by_type_counts["lagged_correlation"] = len(corrs)

    if "spatial_alignment" in enabled_types:
        corrs = _spatial_alignment(by_source, source_pairs, spatial_radius_km, min_confidence)
        all_correlations.extend(corrs)
        by_type_counts["spatial_alignment"] = len(corrs)

    if "entity_alignment" in enabled_types:
        corrs = _entity_alignment(by_source, source_pairs, min_confidence)
        all_correlations.extend(corrs)
        by_type_counts["entity_alignment"] = len(corrs)

    if "pattern_similarity" in enabled_types:
        corrs = _pattern_similarity(by_source, source_pairs, min_confidence)
        all_correlations.extend(corrs)
        by_type_counts["pattern_similarity"] = len(corrs)

    # Persist correlations
    store.insert_correlations(all_correlations)

    # --- Cluster into insights ---
    insights = []
    if do_clustering and all_correlations:
        insights = _cluster_into_insights(all_correlations, signals, by_source)
        store.insert_insights(insights)

    # Format output
    pairwise_output = []
    for corr in all_correlations[:100]:  # Limit output to top 100
        pairwise_output.append({
            "correlation_id": corr["correlation_id"],
            "signal_a": _signal_summary(corr["signal_a_id"], signals),
            "signal_b": _signal_summary(corr["signal_b_id"], signals),
            "correlation_type": corr["correlation_type"],
            "strength": corr.get("strength"),
            "lag": corr.get("lag_description"),
            "spatial_distance_km": corr.get("spatial_distance_km"),
            "confidence": corr.get("confidence"),
            "narrative": corr.get("narrative"),
        })

    insights_output = []
    for ins in insights:
        insights_output.append({
            "insight_id": ins["insight_id"],
            "title": ins.get("title"),
            "signals_involved": ins.get("signals_involved", []),
            "correlation_types": ins.get("correlation_types", []),
            "strength": ins.get("strength"),
            "lag_structure": ins.get("lag_structure"),
            "actionability_score": ins.get("actionability"),
            "suggested_actions": ins.get("suggested_actions", []),
            "narrative": ins.get("narrative"),
        })

    return {
        "correlations_found": len(all_correlations),
        "by_type": by_type_counts,
        "pairwise_correlations": pairwise_output,
        "insights": insights_output,
        "meta": {
            "sources_analyzed": len(by_source),
            "signals_analyzed": len(signals),
            "analysis_duration_seconds": round(time.time() - start_time, 2),
        },
    }


# =============================================================================
# Correlation Methods
# =============================================================================

def _temporal_co_occurrence(
    by_source: dict,
    source_pairs: list,
    temporal_window: pd.Timedelta,
    min_confidence: float,
) -> list[dict]:
    """Find signals from different sources that co-occur in time."""
    correlations = []

    for src_a, src_b in source_pairs:
        sigs_a = by_source[src_a]
        sigs_b = by_source[src_b]

        for sig_a in sigs_a:
            if sig_a["signal_type"] == "baseline_pattern":
                continue
            ts_a_start = _parse_ts(sig_a.get("ts_start"))
            ts_a_end = _parse_ts(sig_a.get("ts_end")) or ts_a_start
            if ts_a_start is None:
                continue

            for sig_b in sigs_b:
                if sig_b["signal_type"] == "baseline_pattern":
                    continue
                ts_b_start = _parse_ts(sig_b.get("ts_start"))
                ts_b_end = _parse_ts(sig_b.get("ts_end")) or ts_b_start
                if ts_b_start is None:
                    continue

                # Check overlap or proximity
                gap = _time_gap(ts_a_start, ts_a_end, ts_b_start, ts_b_end)
                if gap <= temporal_window:
                    # Compute overlap score
                    overlap = _time_overlap(ts_a_start, ts_a_end, ts_b_start, ts_b_end)
                    max_dur = max(
                        (ts_a_end - ts_a_start).total_seconds(),
                        (ts_b_end - ts_b_start).total_seconds(),
                        1.0,
                    )
                    overlap_score = overlap / max_dur

                    # Confidence based on overlap and individual signal confidence
                    conf_a = sig_a.get("confidence") or 0.5
                    conf_b = sig_b.get("confidence") or 0.5
                    confidence = min(1.0, (0.5 + overlap_score * 0.5) * min(conf_a, conf_b) / 0.5)

                    if confidence >= min_confidence:
                        gap_str = _format_timedelta(gap) if gap.total_seconds() > 0 else "overlapping"
                        correlations.append({
                            "correlation_id": f"corr_{uuid.uuid4().hex[:12]}",
                            "signal_a_id": sig_a["signal_id"],
                            "signal_b_id": sig_b["signal_id"],
                            "source_a_id": src_a,
                            "source_b_id": src_b,
                            "correlation_type": "temporal_co_occurrence",
                            "strength": round(overlap_score, 4),
                            "lag_description": f"Signals are {gap_str}",
                            "lag_periods": None,
                            "spatial_distance_km": None,
                            "confidence": round(confidence, 4),
                            "evidence": f"Time gap: {gap_str}, overlap score: {round(overlap_score, 3)}",
                            "narrative": (
                                f"Temporal co-occurrence: '{sig_a.get('column_name')}' ({src_a}) "
                                f"and '{sig_b.get('column_name')}' ({src_b}) "
                                f"occurred within {gap_str} of each other."
                            ),
                        })

    return correlations


def _lagged_correlation(
    by_source: dict,
    source_pairs: list,
    lag_max: int,
    min_confidence: float,
) -> list[dict]:
    """Find lagged relationships between signal series from different sources."""
    correlations = []

    for src_a, src_b in source_pairs:
        sigs_a = [s for s in by_source[src_a] if s["signal_type"] != "baseline_pattern"]
        sigs_b = [s for s in by_source[src_b] if s["signal_type"] != "baseline_pattern"]

        if len(sigs_a) < 3 or len(sigs_b) < 3:
            continue

        # Create daily signal magnitude series
        series_a = _signals_to_daily_series(sigs_a)
        series_b = _signals_to_daily_series(sigs_b)

        if series_a is None or series_b is None:
            continue

        # Align on common date range
        common_idx = series_a.index.intersection(series_b.index)
        if len(common_idx) < 10:
            continue

        sa = series_a.reindex(common_idx).fillna(0)
        sb = series_b.reindex(common_idx).fillna(0)

        # Cross-correlation
        max_lag = min(lag_max, len(common_idx) // 3)
        best_corr = 0.0
        best_lag = 0

        for lag in range(-max_lag, max_lag + 1):
            if lag < 0:
                x = sa.values[:lag]
                y = sb.values[-lag:]
            elif lag > 0:
                x = sa.values[lag:]
                y = sb.values[:-lag]
            else:
                x = sa.values
                y = sb.values

            if len(x) < 5:
                continue

            corr, p_value = scipy_stats.pearsonr(x, y)
            if abs(corr) > abs(best_corr) and p_value < 0.1:
                best_corr = corr
                best_lag = lag

        if abs(best_corr) >= min_confidence:
            if best_lag > 0:
                lag_desc = f"{src_a} leads {src_b} by {best_lag} days"
            elif best_lag < 0:
                lag_desc = f"{src_b} leads {src_a} by {abs(best_lag)} days"
            else:
                lag_desc = "Simultaneous (no lag)"

            correlations.append({
                "correlation_id": f"corr_{uuid.uuid4().hex[:12]}",
                "signal_a_id": sigs_a[0]["signal_id"],  # Representative signal
                "signal_b_id": sigs_b[0]["signal_id"],
                "source_a_id": src_a,
                "source_b_id": src_b,
                "correlation_type": "lagged_correlation",
                "strength": round(abs(best_corr), 4),
                "lag_description": lag_desc,
                "lag_periods": best_lag,
                "spatial_distance_km": None,
                "confidence": round(abs(best_corr), 4),
                "evidence": f"Cross-correlation r={round(best_corr, 3)} at lag={best_lag} days",
                "narrative": (
                    f"Lagged correlation detected between {src_a} and {src_b}: "
                    f"r={round(best_corr, 3)}. {lag_desc}. "
                    f"{'Positive' if best_corr > 0 else 'Inverse'} relationship."
                ),
            })

    return correlations


def _spatial_alignment(
    by_source: dict,
    source_pairs: list,
    radius_km: float,
    min_confidence: float,
) -> list[dict]:
    """Find cross-source signals that co-occur geographically."""
    correlations = []

    for src_a, src_b in source_pairs:
        sigs_a = [s for s in by_source[src_a] if s.get("latitude") and s.get("longitude")]
        sigs_b = [s for s in by_source[src_b] if s.get("latitude") and s.get("longitude")]

        if not sigs_a or not sigs_b:
            continue

        for sig_a in sigs_a:
            if sig_a["signal_type"] == "baseline_pattern":
                continue
            for sig_b in sigs_b:
                if sig_b["signal_type"] == "baseline_pattern":
                    continue

                dist = _haversine(
                    sig_a["latitude"], sig_a["longitude"],
                    sig_b["latitude"], sig_b["longitude"],
                )

                if dist <= radius_km:
                    # Closer = stronger
                    strength = max(0, 1.0 - (dist / radius_km))
                    confidence = strength * 0.5 + 0.5  # Floor at 0.5

                    if confidence >= min_confidence:
                        correlations.append({
                            "correlation_id": f"corr_{uuid.uuid4().hex[:12]}",
                            "signal_a_id": sig_a["signal_id"],
                            "signal_b_id": sig_b["signal_id"],
                            "source_a_id": src_a,
                            "source_b_id": src_b,
                            "correlation_type": "spatial_alignment",
                            "strength": round(strength, 4),
                            "lag_description": None,
                            "lag_periods": None,
                            "spatial_distance_km": round(dist, 2),
                            "confidence": round(confidence, 4),
                            "evidence": f"Spatial distance: {round(dist, 1)} km (within {radius_km} km radius)",
                            "narrative": (
                                f"Spatial alignment: '{sig_a.get('column_name')}' ({src_a}) "
                                f"and '{sig_b.get('column_name')}' ({src_b}) "
                                f"within {round(dist, 1)} km of each other."
                            ),
                        })

    return correlations


def _entity_alignment(
    by_source: dict,
    source_pairs: list,
    min_confidence: float,
) -> list[dict]:
    """Find cross-source signals affecting the same entities."""
    correlations = []

    for src_a, src_b in source_pairs:
        sigs_a = [s for s in by_source[src_a] if s.get("entity_values")]
        sigs_b = [s for s in by_source[src_b] if s.get("entity_values")]

        if not sigs_a or not sigs_b:
            continue

        for sig_a in sigs_a:
            ev_a = sig_a["entity_values"]
            if isinstance(ev_a, str):
                try:
                    ev_a = __import__("json").loads(ev_a)
                except Exception:
                    continue
            if not ev_a:
                continue

            for sig_b in sigs_b:
                ev_b = sig_b["entity_values"]
                if isinstance(ev_b, str):
                    try:
                        ev_b = __import__("json").loads(ev_b)
                    except Exception:
                        continue
                if not ev_b:
                    continue

                # Find shared keys
                shared_keys = set(ev_a.keys()) & set(ev_b.keys())
                if not shared_keys:
                    continue

                # Check for matching values
                matches = sum(1 for k in shared_keys if ev_a.get(k) == ev_b.get(k))
                if matches > 0:
                    strength = matches / max(len(ev_a), len(ev_b))
                    if strength >= min_confidence:
                        matched = {k: ev_a[k] for k in shared_keys if ev_a.get(k) == ev_b.get(k)}
                        correlations.append({
                            "correlation_id": f"corr_{uuid.uuid4().hex[:12]}",
                            "signal_a_id": sig_a["signal_id"],
                            "signal_b_id": sig_b["signal_id"],
                            "source_a_id": src_a,
                            "source_b_id": src_b,
                            "correlation_type": "entity_alignment",
                            "strength": round(strength, 4),
                            "lag_description": None,
                            "lag_periods": None,
                            "spatial_distance_km": None,
                            "confidence": round(strength, 4),
                            "evidence": f"Shared entities: {matched}",
                            "narrative": (
                                f"Entity alignment: signals from {src_a} and {src_b} "
                                f"affect the same entities: {matched}"
                            ),
                        })

    return correlations


def _pattern_similarity(
    by_source: dict,
    source_pairs: list,
    min_confidence: float,
) -> list[dict]:
    """Compare baseline seasonal patterns across sources."""
    correlations = []

    for src_a, src_b in source_pairs:
        baselines_a = [s for s in by_source[src_a] if s["signal_type"] == "baseline_pattern"]
        baselines_b = [s for s in by_source[src_b] if s["signal_type"] == "baseline_pattern"]

        if not baselines_a or not baselines_b:
            continue

        for bl_a in baselines_a:
            meta_a = bl_a.get("metadata", {})
            if isinstance(meta_a, str):
                try:
                    meta_a = __import__("json").loads(meta_a)
                except Exception:
                    continue
            seas_a = meta_a.get("seasonality", [])

            for bl_b in baselines_b:
                meta_b = bl_b.get("metadata", {})
                if isinstance(meta_b, str):
                    try:
                        meta_b = __import__("json").loads(meta_b)
                    except Exception:
                        continue
                seas_b = meta_b.get("seasonality", [])

                # Compare seasonal patterns with matching periods
                for sa in seas_a:
                    for sb in seas_b:
                        if sa.get("period_label") == sb.get("period_label"):
                            # Both have same seasonal frequency — compare strength and phase
                            strength_sim = 1.0 - abs(
                                (sa.get("strength", 0) - sb.get("strength", 0))
                            )
                            phase_match = 1.0 if sa.get("peak_phase") == sb.get("peak_phase") else 0.3

                            similarity = (strength_sim * 0.4 + phase_match * 0.6)

                            if similarity >= min_confidence:
                                correlations.append({
                                    "correlation_id": f"corr_{uuid.uuid4().hex[:12]}",
                                    "signal_a_id": bl_a["signal_id"],
                                    "signal_b_id": bl_b["signal_id"],
                                    "source_a_id": src_a,
                                    "source_b_id": src_b,
                                    "correlation_type": "pattern_similarity",
                                    "strength": round(similarity, 4),
                                    "lag_description": None,
                                    "lag_periods": None,
                                    "spatial_distance_km": None,
                                    "confidence": round(similarity, 4),
                                    "evidence": (
                                        f"{sa['period_label']} seasonality: "
                                        f"{bl_a['column_name']} peaks at {sa.get('peak_phase')}, "
                                        f"{bl_b['column_name']} peaks at {sb.get('peak_phase')}"
                                    ),
                                    "narrative": (
                                        f"Pattern similarity: '{bl_a['column_name']}' ({src_a}) "
                                        f"and '{bl_b['column_name']}' ({src_b}) share "
                                        f"{sa['period_label']} seasonal patterns"
                                        f"{' with matching phase' if phase_match > 0.5 else ''}."
                                    ),
                                })

    return correlations


# =============================================================================
# Insight Clustering
# =============================================================================

def _cluster_into_insights(
    correlations: list[dict],
    signals: list[dict],
    by_source: dict,
) -> list[dict]:
    """Group correlated signals into insight clusters using a graph approach."""

    # Build signal graph
    G = nx.Graph()
    sig_lookup = {s["signal_id"]: s for s in signals}

    for corr in correlations:
        a_id = corr["signal_a_id"]
        b_id = corr["signal_b_id"]
        G.add_node(a_id)
        G.add_node(b_id)
        G.add_edge(a_id, b_id, weight=corr.get("strength", 0.5), correlation=corr)

    # Extract connected components as candidate clusters
    components = list(nx.connected_components(G))

    insights = []
    for comp in components:
        if len(comp) < 2:
            continue

        comp_signals = [sig_lookup[sid] for sid in comp if sid in sig_lookup]
        comp_edges = [(u, v, d) for u, v, d in G.edges(data=True) if u in comp and v in comp]
        comp_corrs = [d["correlation"] for _, _, d in comp_edges]

        # Compute cluster metrics
        sources_in_cluster = set(s["source_id"] for s in comp_signals)
        total_sources = len(by_source)

        severity_scores = [
            SEVERITY_SCORE.get(s.get("severity", "low"), 0.25)
            for s in comp_signals if s.get("severity")
        ]
        mean_severity = np.mean(severity_scores) if severity_scores else 0.25

        cross_source_diversity = len(sources_in_cluster) / max(total_sources, 1)
        mean_confidence = np.mean([c.get("confidence", 0.5) for c in comp_corrs])
        mean_strength = np.mean([c.get("strength", 0.5) for c in comp_corrs])

        persistence_scores = [
            1.0 if _get_metadata_field(s, "persistence") == "sustained" else 0.5
            for s in comp_signals
        ]
        persistence_score = np.mean(persistence_scores)

        actionability = (
            0.25 * mean_severity
            + 0.30 * cross_source_diversity
            + 0.25 * mean_confidence
            + 0.20 * persistence_score
        )

        # Determine correlation types in this cluster
        corr_types = list(set(c["correlation_type"] for c in comp_corrs))

        # Build lag structure description
        lag_descs = [c.get("lag_description") for c in comp_corrs if c.get("lag_description")]
        lag_structure = "; ".join(lag_descs[:3]) if lag_descs else None

        # Signals involved summary
        signals_involved = [
            {
                "source_id": s["source_id"],
                "column": s["column_name"],
                "signal_type": s["signal_type"],
            }
            for s in comp_signals
        ]

        # Generate title and narrative
        title = _generate_insight_title(comp_signals, sources_in_cluster, corr_types)
        suggested_actions = _generate_actions(comp_signals, sources_in_cluster, corr_types)
        narrative = _generate_insight_narrative(
            comp_signals, comp_corrs, sources_in_cluster,
            mean_strength, actionability, lag_structure,
        )

        insight = {
            "insight_id": f"ins_{uuid.uuid4().hex[:12]}",
            "title": title,
            "signal_ids": [s["signal_id"] for s in comp_signals],
            "correlation_ids": [c["correlation_id"] for c in comp_corrs],
            "correlation_types": corr_types,
            "strength": round(float(mean_strength), 4),
            "actionability": round(float(actionability), 4),
            "lag_structure": lag_structure,
            "suggested_actions": suggested_actions,
            "narrative": narrative,
            "signals_involved": signals_involved,
        }
        insights.append(insight)

    # Sort by actionability
    insights.sort(key=lambda x: x.get("actionability", 0), reverse=True)
    return insights


# =============================================================================
# Narrative Generation
# =============================================================================

def _generate_insight_title(signals: list[dict], sources: set, corr_types: list[str]) -> str:
    """Generate a descriptive title for an insight cluster."""
    columns = list(set(s["column_name"] for s in signals))
    source_list = sorted(sources)

    if len(columns) <= 2:
        col_str = " & ".join(columns)
    else:
        col_str = f"{columns[0]} + {len(columns) - 1} other metrics"

    type_hints = []
    if "temporal_co_occurrence" in corr_types:
        type_hints.append("co-occurring")
    if "lagged_correlation" in corr_types:
        type_hints.append("sequenced")
    if "spatial_alignment" in corr_types:
        type_hints.append("co-located")
    if "pattern_similarity" in corr_types:
        type_hints.append("co-moving")

    type_str = " + ".join(type_hints[:2]) if type_hints else "correlated"

    return f"Cross-source {type_str} signals: {col_str} across {', '.join(source_list)}"


def _generate_actions(signals: list[dict], sources: set, corr_types: list[str]) -> list[str]:
    """Generate suggested actions based on signal domains."""
    actions = []

    # Collect domains from source signals
    domains = set()
    for sig in signals:
        # We don't have domain directly on signals, but we can infer from source_id patterns
        src = sig.get("source_id", "")
        if any(kw in src.lower() for kw in ["pos", "transaction", "sales", "retail"]):
            domains.add("pos")
        elif any(kw in src.lower() for kw in ["book", "ticket", "visit", "experience"]):
            domains.add("bookings")
        elif any(kw in src.lower() for kw in ["web", "search", "digital", "online"]):
            domains.add("digital")
        elif any(kw in src.lower() for kw in ["weather", "temp", "climate"]):
            domains.add("weather")

    if "pos" in domains and "bookings" in domains:
        actions.append("Coordinate promotions between experience venues and nearby retail/hospitality")
        actions.append("Use booking patterns as lead indicators for retail demand forecasting")

    if "bookings" in domains:
        actions.append("Evaluate dynamic pricing opportunities based on correlated demand signals")
        actions.append("Adjust staffing and inventory based on predicted visitor flow")

    if "pos" in domains:
        actions.append("Time promotional campaigns to align with detected demand patterns")

    if "lagged_correlation" in corr_types:
        actions.append("Establish the leading signal as an early warning trigger for downstream operations")

    if "spatial_alignment" in corr_types:
        actions.append("Explore geo-targeted marketing within the correlated spatial region")

    if not actions:
        actions.append("Investigate the correlation further to determine causal mechanism")
        actions.append("Monitor whether the correlation persists over the next analysis period")

    return actions[:5]


def _generate_insight_narrative(
    signals: list[dict],
    correlations: list[dict],
    sources: set,
    strength: float,
    actionability: float,
    lag_structure: str | None,
) -> str:
    """Generate a full narrative for an insight cluster."""
    parts = []

    n_signals = len(signals)
    n_sources = len(sources)
    parts.append(
        f"Cross-dataset insight involving {n_signals} signals from "
        f"{n_sources} data source{'s' if n_sources > 1 else ''} "
        f"({', '.join(sorted(sources))})."
    )

    # Describe the signals
    by_type = {}
    for s in signals:
        st = s["signal_type"]
        by_type.setdefault(st, []).append(s)

    for stype, sigs in by_type.items():
        columns = list(set(s["column_name"] for s in sigs))
        parts.append(f"{len(sigs)} {stype.replace('_', ' ')} signal{'s' if len(sigs) > 1 else ''} "
                      f"in {', '.join(columns[:3])}.")

    # Describe the correlation
    parts.append(f"Overall correlation strength: {round(strength, 2)}.")

    if lag_structure:
        parts.append(f"Temporal sequence: {lag_structure}.")

    # Actionability
    if actionability >= 0.75:
        parts.append("HIGH actionability — this finding spans multiple domains and has strong statistical support.")
    elif actionability >= 0.5:
        parts.append("MODERATE actionability — worth investigating further and monitoring.")
    else:
        parts.append("LOW actionability — interesting pattern but may need more data to confirm.")

    return " ".join(parts)


# =============================================================================
# Helpers
# =============================================================================

def _parse_ts(val) -> pd.Timestamp | None:
    if val is None:
        return None
    try:
        return pd.Timestamp(val)
    except Exception:
        return None


def _time_gap(a_start, a_end, b_start, b_end) -> pd.Timedelta:
    """Compute the gap between two time ranges (0 if overlapping)."""
    if a_end >= b_start and b_end >= a_start:
        return pd.Timedelta(0)
    if a_end < b_start:
        return b_start - a_end
    return a_start - b_end


def _time_overlap(a_start, a_end, b_start, b_end) -> float:
    """Compute overlap duration in seconds."""
    overlap_start = max(a_start, b_start)
    overlap_end = min(a_end, b_end)
    if overlap_start < overlap_end:
        return (overlap_end - overlap_start).total_seconds()
    return 0.0


def _format_timedelta(td: pd.Timedelta) -> str:
    total_seconds = td.total_seconds()
    if total_seconds < 3600:
        return f"{int(total_seconds / 60)} minutes"
    elif total_seconds < 86400:
        return f"{round(total_seconds / 3600, 1)} hours"
    else:
        return f"{round(total_seconds / 86400, 1)} days"


def _haversine(lat1, lon1, lat2, lon2) -> float:
    """Compute great-circle distance in km between two points."""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(a))


def _signals_to_daily_series(signals: list[dict]) -> pd.Series | None:
    """Convert a list of signals into a daily magnitude time series."""
    records = []
    for sig in signals:
        ts = _parse_ts(sig.get("ts_start"))
        if ts is None:
            continue
        mag = sig.get("magnitude") or 1.0
        records.append({"date": ts.normalize(), "magnitude": abs(float(mag))})

    if not records:
        return None

    df = pd.DataFrame(records)
    daily = df.groupby("date")["magnitude"].sum()
    # Reindex to fill gaps
    full_range = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_range, fill_value=0.0)
    return daily


def _signal_summary(signal_id: str, signals: list[dict]) -> dict:
    """Create a brief summary of a signal for output."""
    for sig in signals:
        if sig["signal_id"] == signal_id:
            return {
                "signal_id": signal_id,
                "source_id": sig["source_id"],
                "column": sig["column_name"],
                "type": sig["signal_type"],
            }
    return {"signal_id": signal_id}


def _get_metadata_field(signal: dict, field: str):
    """Safely extract a field from signal metadata."""
    meta = signal.get("metadata", {})
    if isinstance(meta, str):
        try:
            meta = __import__("json").loads(meta)
        except Exception:
            return None
    return meta.get(field) if isinstance(meta, dict) else None
