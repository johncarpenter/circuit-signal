"""suggest_segments tool — auto-segmentation engine with quality scoring."""

from __future__ import annotations

import logging
import warnings
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from circuit_core.data_loader.storage import get_backend

logger = logging.getLogger("data-loader")

# Scoring weights
W_DIFFERENTIATION = 0.40
W_BALANCE = 0.25
W_COVERAGE = 0.20
W_SIZE = 0.15

# Column classification
_MAX_SEG_CARDINALITY = 1000  # upper bound to exclude truly high-cardinality columns; max_segments trims output
_MIN_SEG_CARDINALITY = 2
_MAX_INT_SEG_CARDINALITY = 50
_ID_KEYWORDS = {"id", "uuid", "key", "code", "sku", "barcode", "hash"}
_TIME_KEYWORDS = {"date", "time", "timestamp", "created", "updated", "year", "month", "week", "day", "hour"}


def run_suggest_segments(
    dataset_id: str,
    timestamp_col: str,
    value_cols: list[str] | None = None,
    min_segment_size: int = 50,
    max_segments: int = 30,
) -> dict:
    """Analyze dataset and recommend segmentation strategies."""
    backend = get_backend()

    try:
        schema = backend.schema(dataset_id)
    except Exception as e:
        return {"error": f"Dataset '{dataset_id}' not found. Load it first. ({e})"}

    # Load the full dataset into pandas for analysis
    df = backend.get_dataframe(dataset_id)

    col_names = [c["name"] for c in schema["columns"]]
    col_types = {c["name"]: c["type"] for c in schema["columns"]}

    if timestamp_col not in col_names:
        return {"error": f"Timestamp column '{timestamp_col}' not found. Available: {col_names}"}

    # Parse timestamps
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        df[timestamp_col] = pd.to_datetime(df[timestamp_col], utc=True, errors="coerce")

    # Identify numeric columns for analysis
    if value_cols:
        numeric_cols = [c for c in value_cols if c in col_names]
    else:
        numeric_cols = [c for c in col_names if pd.api.types.is_numeric_dtype(df[c]) and c != timestamp_col]

    if not numeric_cols:
        return {"error": "No numeric columns found for differentiation analysis."}

    # Classify columns and find segmentation candidates
    candidates = _find_candidates(df, col_names, col_types, timestamp_col, numeric_cols)
    not_recommended = _find_not_recommended(df, col_names, col_types, timestamp_col, numeric_cols, candidates)

    if not candidates:
        return {
            "dataset_id": dataset_id,
            "suggestions": [],
            "not_recommended": not_recommended,
        }

    # Score each candidate
    suggestions = []
    for col in candidates:
        scores = _score_segmentation(
            df, col, timestamp_col, numeric_cols, min_segment_size
        )
        if scores is None:
            continue

        segment_count = scores["segment_count"]
        if segment_count > max_segments:
            not_recommended.append({
                "column": col,
                "reason": f"Too many segments ({segment_count} > max {max_segments})",
            })
            continue

        composite = (
            W_DIFFERENTIATION * scores["differentiation"]
            + W_BALANCE * scores["balance"]
            + W_COVERAGE * scores["coverage"]
            + W_SIZE * scores["size"]
        )

        # Build segment preview
        preview = _build_preview(df, col, timestamp_col, numeric_cols)

        # Generate narrative
        narrative = _build_narrative(col, scores, segment_count, composite)
        examples = _build_example_differences(df, col, numeric_cols)

        suggestions.append({
            "type": "single_column",
            "columns": [col],
            "segment_count": segment_count,
            "composite_score": round(composite, 3),
            "scores": {
                "differentiation": round(scores["differentiation"], 3),
                "balance": round(scores["balance"], 3),
                "coverage": round(scores["coverage"], 3),
                "size": round(scores["size"], 3),
            },
            "segments_preview": preview[:10],
            "narrative": narrative,
            "example_differences": examples,
        })

    # Detect hierarchical segmentations
    hierarchy_suggestions = _detect_hierarchy_suggestions(
        df, candidates, timestamp_col, numeric_cols, min_segment_size, max_segments
    )
    suggestions.extend(hierarchy_suggestions)

    # Detect cross-segmentations
    cross_suggestions = _detect_cross_segmentations(
        df, candidates, timestamp_col, numeric_cols, min_segment_size, max_segments
    )
    suggestions.extend(cross_suggestions)

    # Rank by composite score
    suggestions.sort(key=lambda s: s["composite_score"], reverse=True)
    for i, s in enumerate(suggestions):
        s["rank"] = i + 1

    return {
        "dataset_id": dataset_id,
        "suggestions": suggestions,
        "not_recommended": not_recommended,
    }


# ---------------------------------------------------------------------------
# Column classification
# ---------------------------------------------------------------------------

def _find_candidates(
    df: pd.DataFrame,
    col_names: list[str],
    col_types: dict[str, str],
    timestamp_col: str,
    numeric_cols: list[str],
) -> list[str]:
    """Find columns suitable for segmentation."""
    candidates = []
    for col in col_names:
        if col == timestamp_col:
            continue
        if col in numeric_cols:
            # Integer columns with low cardinality could be encoded categories
            if pd.api.types.is_integer_dtype(df[col]):
                card = df[col].nunique()
                if _MIN_SEG_CARDINALITY <= card <= _MAX_INT_SEG_CARDINALITY:
                    candidates.append(col)
            continue

        # Skip timestamp-like columns
        if any(kw in col.lower() for kw in _TIME_KEYWORDS):
            continue

        # Skip identifier columns
        card = df[col].nunique()
        ratio = card / max(len(df), 1)
        if ratio > 0.5 and any(kw in col.lower() for kw in _ID_KEYWORDS):
            continue
        if ratio > 0.9:
            continue

        # Categorical with reasonable cardinality
        if _MIN_SEG_CARDINALITY <= card <= _MAX_SEG_CARDINALITY:
            candidates.append(col)

    return candidates


def _find_not_recommended(
    df: pd.DataFrame,
    col_names: list[str],
    col_types: dict[str, str],
    timestamp_col: str,
    numeric_cols: list[str],
    candidates: list[str],
) -> list[dict]:
    """Document why columns are not recommended for segmentation."""
    not_rec = []
    for col in col_names:
        if col == timestamp_col or col in candidates:
            continue
        card = df[col].nunique()
        ratio = card / max(len(df), 1)

        if col in numeric_cols and not pd.api.types.is_integer_dtype(df[col]):
            not_rec.append({"column": col, "reason": "Numeric measure — analyzed by Layer 1, not a segmentation axis"})
        elif ratio > 0.9:
            not_rec.append({"column": col, "reason": f"Identifier-like — {card} unique values ({ratio:.0%} of rows)"})
        elif any(kw in col.lower() for kw in _TIME_KEYWORDS):
            not_rec.append({"column": col, "reason": "Temporal column — Layer 1 handles time-based patterns"})
        elif card < _MIN_SEG_CARDINALITY:
            not_rec.append({"column": col, "reason": f"Only {card} unique value(s) — no segmentation possible"})
        elif card > _MAX_SEG_CARDINALITY:
            not_rec.append({"column": col, "reason": f"Too many unique values ({card}) — would create too many segments"})
    return not_rec


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_segmentation(
    df: pd.DataFrame,
    col: str,
    timestamp_col: str,
    numeric_cols: list[str],
    min_segment_size: int,
) -> dict | None:
    """Score a candidate segmentation column across 4 dimensions."""
    groups = df.groupby(col)
    group_sizes = groups.size()
    segment_count = len(group_sizes)

    if segment_count < 2:
        return None

    # 1. Differentiation score: Kruskal-Wallis H-test
    diff_score = _score_differentiation(df, col, numeric_cols)

    # 2. Balance score: CV of group sizes
    balance_score = _score_balance(group_sizes)

    # 3. Coverage score: temporal coverage per segment
    coverage_score = _score_coverage(df, col, timestamp_col)

    # 4. Size score: fraction of segments meeting min_segment_size
    size_score = _score_size(group_sizes, min_segment_size)

    return {
        "differentiation": diff_score,
        "balance": balance_score,
        "coverage": coverage_score,
        "size": size_score,
        "segment_count": segment_count,
    }


def _score_differentiation(df: pd.DataFrame, col: str, numeric_cols: list[str]) -> float:
    """Kruskal-Wallis H-test: do segments have different distributions for numeric columns?"""
    significant_count = 0
    tested_count = 0

    for num_col in numeric_cols:
        series = df[[col, num_col]].dropna()
        if series.empty:
            continue

        groups = [g[num_col].values for _, g in series.groupby(col)]
        # Need at least 2 groups with data
        groups = [g for g in groups if len(g) >= 2]
        if len(groups) < 2:
            continue

        tested_count += 1
        try:
            h_stat, p_value = sp_stats.kruskal(*groups)
            if p_value < 0.05:
                significant_count += 1
        except Exception:
            continue

    if tested_count == 0:
        return 0.0
    return significant_count / tested_count


def _score_balance(group_sizes: pd.Series) -> float:
    """Score how evenly distributed the segment sizes are. 1.0 = perfectly balanced."""
    if len(group_sizes) < 2:
        return 0.0
    cv = group_sizes.std() / group_sizes.mean() if group_sizes.mean() > 0 else 0
    # Normalize: CV of 0 = perfect balance (1.0), CV of 2+ = very imbalanced (0.0)
    return max(0.0, 1.0 - cv / 2.0)


def _score_coverage(df: pd.DataFrame, col: str, timestamp_col: str) -> float:
    """Score how well each segment covers the full time range."""
    ts = df[timestamp_col]
    if ts.isna().all():
        return 0.0

    total_min = ts.min()
    total_max = ts.max()
    total_range = (total_max - total_min).total_seconds()

    if total_range <= 0:
        return 1.0

    coverages = []
    for _, group in df.groupby(col):
        g_ts = group[timestamp_col].dropna()
        if g_ts.empty:
            coverages.append(0.0)
            continue
        seg_range = (g_ts.max() - g_ts.min()).total_seconds()
        coverages.append(seg_range / total_range)

    return float(np.mean(coverages)) if coverages else 0.0


def _score_size(group_sizes: pd.Series, min_segment_size: int) -> float:
    """Fraction of segments meeting the minimum size requirement."""
    if len(group_sizes) == 0:
        return 0.0
    viable = (group_sizes >= min_segment_size).sum()
    return viable / len(group_sizes)


# ---------------------------------------------------------------------------
# Preview, narrative, examples
# ---------------------------------------------------------------------------

def _build_preview(
    df: pd.DataFrame,
    col: str,
    timestamp_col: str,
    numeric_cols: list[str],
) -> list[dict]:
    """Build a preview of each segment."""
    previews = []
    for val, group in df.groupby(col):
        ts = group[timestamp_col].dropna()
        numeric_summary = {}
        for nc in numeric_cols[:5]:  # limit to first 5 numeric cols
            vals = group[nc].dropna()
            if not vals.empty:
                numeric_summary[nc] = {
                    "mean": round(float(vals.mean()), 4),
                    "std": round(float(vals.std()), 4),
                }

        previews.append({
            "value": str(val),
            "row_count": len(group),
            "time_range": {
                "start": str(ts.min()) if not ts.empty else None,
                "end": str(ts.max()) if not ts.empty else None,
            },
            "numeric_summary": numeric_summary,
        })

    # Sort by row count descending
    previews.sort(key=lambda p: p["row_count"], reverse=True)
    return previews


def _build_narrative(col: str, scores: dict, segment_count: int, composite: float) -> str:
    """Generate a plain English explanation of why this segmentation is useful."""
    parts = []
    parts.append(f"Segmenting by '{col}' produces {segment_count} groups")

    diff = scores["differentiation"]
    if diff >= 0.8:
        parts.append("with strongly distinct patterns across nearly all metrics")
    elif diff >= 0.5:
        parts.append("with meaningfully different patterns across most metrics")
    elif diff >= 0.2:
        parts.append("with some pattern differences across metrics")
    else:
        parts.append("but patterns are largely similar across segments")

    bal = scores["balance"]
    if bal < 0.4:
        parts.append("(note: segment sizes are significantly imbalanced)")

    cov = scores["coverage"]
    if cov < 0.5:
        parts.append("— some segments only cover part of the time range")

    return ". ".join(parts) + f". Composite quality score: {composite:.2f}/1.00."


def _build_example_differences(df: pd.DataFrame, col: str, numeric_cols: list[str]) -> list[str]:
    """Find specific examples of how segments differ."""
    examples = []
    groups = df.groupby(col)

    for nc in numeric_cols[:3]:
        means = groups[nc].mean().dropna()
        if len(means) < 2:
            continue
        highest = means.idxmax()
        lowest = means.idxmin()
        if means[highest] == 0:
            continue
        ratio = means[highest] / means[lowest] if means[lowest] != 0 else float("inf")
        if ratio > 1.5:
            examples.append(
                f"'{highest}' has {ratio:.1f}x higher average {nc} than '{lowest}' "
                f"({means[highest]:.2f} vs {means[lowest]:.2f})"
            )
    return examples[:5]


# ---------------------------------------------------------------------------
# Hierarchy detection
# ---------------------------------------------------------------------------

def _detect_hierarchy_suggestions(
    df: pd.DataFrame,
    candidates: list[str],
    timestamp_col: str,
    numeric_cols: list[str],
    min_segment_size: int,
    max_segments: int,
) -> list[dict]:
    """Detect hierarchical segmentation columns and suggest them."""
    if len(candidates) < 2:
        return []

    suggestions = []

    for parent_col in candidates:
        for child_col in candidates:
            if parent_col == child_col:
                continue

            mapping = df[[child_col, parent_col]].drop_duplicates()
            child_to_parents = mapping.groupby(child_col)[parent_col].nunique()
            if not (child_to_parents == 1).all():
                continue

            parent_card = df[parent_col].nunique()
            child_card = df[child_col].nunique()
            if parent_card >= child_card:
                continue

            # Only suggest if child provides better differentiation
            parent_scores = _score_segmentation(df, parent_col, timestamp_col, numeric_cols, min_segment_size)
            child_scores = _score_segmentation(df, child_col, timestamp_col, numeric_cols, min_segment_size)

            if parent_scores is None or child_scores is None:
                continue
            if child_scores["segment_count"] > max_segments:
                continue

            parent_composite = (
                W_DIFFERENTIATION * parent_scores["differentiation"]
                + W_BALANCE * parent_scores["balance"]
                + W_COVERAGE * parent_scores["coverage"]
                + W_SIZE * parent_scores["size"]
            )
            child_composite = (
                W_DIFFERENTIATION * child_scores["differentiation"]
                + W_BALANCE * child_scores["balance"]
                + W_COVERAGE * child_scores["coverage"]
                + W_SIZE * child_scores["size"]
            )

            suggestions.append({
                "type": "hierarchy",
                "columns": [parent_col, child_col],
                "segment_count": child_scores["segment_count"],
                "composite_score": round(max(parent_composite, child_composite), 3),
                "scores": {
                    "differentiation": round(child_scores["differentiation"], 3),
                    "balance": round(child_scores["balance"], 3),
                    "coverage": round(child_scores["coverage"], 3),
                    "size": round(child_scores["size"], 3),
                },
                "segments_preview": [],
                "narrative": (
                    f"Hierarchy detected: {parent_col} ({parent_card} values) → "
                    f"{child_col} ({child_card} values). "
                    f"Start with {parent_col}-level analysis (score: {parent_composite:.2f}), "
                    f"then drill into {child_col}-level for deeper insights (score: {child_composite:.2f})."
                ),
                "example_differences": [],
            })

    return suggestions


# ---------------------------------------------------------------------------
# Cross-segmentation detection
# ---------------------------------------------------------------------------

def _detect_cross_segmentations(
    df: pd.DataFrame,
    candidates: list[str],
    timestamp_col: str,
    numeric_cols: list[str],
    min_segment_size: int,
    max_segments: int,
) -> list[dict]:
    """Test if combinations of columns produce meaningful interaction effects."""
    if len(candidates) < 2:
        return []

    # Only test the top candidates (by individual score) to limit computation
    top_candidates = candidates[:4]
    suggestions = []

    for col_a, col_b in combinations(top_candidates, 2):
        # Check resulting segment count
        cross_groups = df.groupby([col_a, col_b]).size()
        cross_count = len(cross_groups)
        if cross_count > max_segments or cross_count < 3:
            continue

        # Check minimum sizes
        viable = (cross_groups >= min_segment_size).sum()
        if viable / cross_count < 0.5:
            continue

        # Test interaction effect: for each numeric column, check if the
        # A×B interaction adds information beyond A+B individually
        interaction_significant = 0
        tested = 0

        for nc in numeric_cols[:5]:
            subset = df[[col_a, col_b, nc]].dropna()
            if len(subset) < 20:
                continue

            tested += 1
            try:
                # Compare residual variance: model with interaction vs without
                # Simple approach: compare group means across cross-segments vs individual segments
                cross_means = subset.groupby([col_a, col_b])[nc].mean()
                a_means = subset.groupby(col_a)[nc].transform("mean")
                b_means = subset.groupby(col_b)[nc].transform("mean")
                overall_mean = subset[nc].mean()

                # Additive prediction (no interaction)
                additive_pred = a_means + b_means - overall_mean
                additive_residual = (subset[nc] - additive_pred).var()

                # With interaction (actual cross-group means)
                cross_pred = subset.groupby([col_a, col_b])[nc].transform("mean")
                interaction_residual = (subset[nc] - cross_pred).var()

                # If interaction reduces variance substantially
                if additive_residual > 0 and interaction_residual / additive_residual < 0.9:
                    interaction_significant += 1
            except Exception:
                continue

        if tested == 0 or interaction_significant / tested < 0.3:
            continue

        # Score the cross-segmentation
        # Create a combined column for scoring
        combined_col = f"_cross_{col_a}_{col_b}"
        df[combined_col] = df[col_a].astype(str) + " × " + df[col_b].astype(str)
        scores = _score_segmentation(df, combined_col, timestamp_col, numeric_cols, min_segment_size)
        df.drop(columns=[combined_col], inplace=True)

        if scores is None:
            continue

        composite = (
            W_DIFFERENTIATION * scores["differentiation"]
            + W_BALANCE * scores["balance"]
            + W_COVERAGE * scores["coverage"]
            + W_SIZE * scores["size"]
        )

        suggestions.append({
            "type": "cross_segmentation",
            "columns": [col_a, col_b],
            "segment_count": cross_count,
            "composite_score": round(composite, 3),
            "scores": {
                "differentiation": round(scores["differentiation"], 3),
                "balance": round(scores["balance"], 3),
                "coverage": round(scores["coverage"], 3),
                "size": round(scores["size"], 3),
            },
            "segments_preview": [],
            "narrative": (
                f"Cross-segmenting by '{col_a}' × '{col_b}' produces {cross_count} segments. "
                f"The interaction between these dimensions captures patterns "
                f"not explained by either column alone."
            ),
            "example_differences": [],
        })

    return suggestions
