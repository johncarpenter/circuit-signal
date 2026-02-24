"""
Data cleaning and normalization tools.

Three strategies layered:

1. STRUCTURAL CLEANING (rule-based, no LLM):
   - Whitespace/case normalization
   - Timezone conversion
   - Numeric coercion (strip currency symbols, commas)
   - Null handling

2. FUZZY ENTITY RESOLUTION (rapidfuzz, no LLM):
   - Cluster similar categorical values using token_sort_ratio
   - Groups typos, case variants, abbreviations
   - Fast, deterministic, handles 80% of cases

3. LLM-ASSISTED ENTITY RESOLUTION (Anthropic API):
   - Sends distinct values to Claude for semantic grouping
   - Handles equivalences fuzzy matching misses
   - Only for columns with ≤200 distinct values
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict

from data_loader.storage import StorageBackend, get_backend

logger = logging.getLogger("data-loader.clean")


# =============================================================================
# Main entry: clean_dataset
# =============================================================================

def run_clean_dataset(
    dataset_id: str,
    operations: list[dict] | None = None,
    auto_detect: bool = True,
    apply: bool = False,
) -> dict:
    """
    Analyze data quality issues and optionally apply fixes.

    Two modes:
      1. Plan mode (apply=False): detect issues, return a cleaning plan
      2. Apply mode (apply=True): execute the provided operations
    """
    backend = get_backend()

    if not backend.table_exists(dataset_id):
        return {"error": f"Dataset '{dataset_id}' not loaded."}

    if apply and operations:
        return _apply_operations(backend, dataset_id, operations)

    if auto_detect:
        return _detect_issues(backend, dataset_id)

    return {"error": "Provide either auto_detect=True or apply=True with operations."}


# =============================================================================
# Issue Detection (Plan Mode)
# =============================================================================

def _detect_issues(backend: StorageBackend, dataset_id: str) -> dict:
    """Scan the dataset for cleaning opportunities."""
    schema = backend.schema(dataset_id)
    row_count = schema["row_count"]
    columns = schema["columns"]

    issues = []
    operations = []

    for col_info in columns:
        col_name = col_info["name"]
        col_type = col_info["type"].lower()

        # --- Null analysis ---
        null_result = _check_nulls(backend, dataset_id, col_name, row_count)
        if null_result:
            issues.append(null_result)

        # --- String column checks ---
        if _is_string_type(col_type):
            # Whitespace / case issues
            ws = _detect_whitespace_issues(backend, dataset_id, col_name)
            if ws:
                issues.append(ws["issue"])
                operations.append(ws["operation"])

            # Fuzzy duplicate detection
            fuzzy = _detect_fuzzy_duplicates(backend, dataset_id, col_name)
            if fuzzy:
                issues.append(fuzzy["issue"])
                operations.append(fuzzy["operation"])

            # Numeric values stored as strings
            numeric = _detect_numeric_strings(backend, dataset_id, col_name)
            if numeric:
                issues.append(numeric["issue"])
                operations.append(numeric["operation"])

        # --- Timezone detection for datetime columns ---
        if _is_datetime_type(col_type):
            tz = _detect_timezone_issues(backend, dataset_id, col_name)
            if tz:
                issues.append(tz["issue"])
                operations.append(tz["operation"])

    return {
        "dataset_id": dataset_id,
        "row_count": row_count,
        "issues_found": len(issues),
        "issues": issues,
        "suggested_operations": operations,
        "narrative": _summarize_issues(issues),
    }


def _is_string_type(col_type: str) -> bool:
    return any(t in col_type for t in ("varchar", "text", "string", "object"))


def _is_datetime_type(col_type: str) -> bool:
    return any(t in col_type for t in ("timestamp", "date", "time", "datetime"))


def _check_nulls(backend: StorageBackend, dataset_id: str, col_name: str, row_count: int) -> dict | None:
    """Check for high null rates in a column."""
    if row_count == 0:
        return None

    try:
        df = backend.get_dataframe(dataset_id, columns=[col_name])
        null_count = int(df[col_name].isna().sum())
    except Exception:
        return None

    null_pct = null_count / row_count
    if null_pct > 0.5:
        return {
            "column": col_name,
            "issue": "high_null_rate",
            "severity": "warning",
            "detail": f"{round(null_pct * 100, 1)}% null values ({null_count} rows)",
            "suggestion": "Consider dropping this column or investigating why it's mostly empty",
        }
    return None


def _detect_whitespace_issues(backend: StorageBackend, dataset_id: str, col_name: str) -> dict | None:
    """Check for leading/trailing whitespace and mixed case in categorical values."""
    values_list = backend.unique_values(dataset_id, col_name)
    values = [v["value"] for v in values_list if v["value"] is not None]

    if not values:
        return None

    # Check for whitespace
    ws_count = sum(1 for v in values if v != v.strip())

    # Check for mixed case (same value, different casing)
    normalized_groups: dict[str, list[str]] = defaultdict(list)
    for v in values:
        normalized_groups[v.strip().lower()].append(v)

    case_groups = {k: v for k, v in normalized_groups.items() if len(v) > 1}

    if ws_count == 0 and not case_groups:
        return None

    # Build mapping: pick most common variant as canonical
    counts_by_value = {v["value"]: v["count"] for v in values_list}
    mapping = {}
    examples = []

    for _normalized, variants in list(case_groups.items())[:20]:
        best = max(variants, key=lambda v: counts_by_value.get(v, 0))
        examples.append(f"{variants} -> '{best}'")
        for v in variants:
            if v != best:
                mapping[v] = best

    detail_parts = []
    if ws_count > 0:
        detail_parts.append(f"{ws_count} values have leading/trailing whitespace")
    if case_groups:
        detail_parts.append(f"{len(case_groups)} values have mixed casing")

    return {
        "issue": {
            "column": col_name,
            "issue": "whitespace_and_case",
            "severity": "high",
            "detail": "; ".join(detail_parts),
            "examples": examples[:5],
        },
        "operation": {
            "type": "normalize_text",
            "column": col_name,
            "actions": ["trim", "case_normalize"],
            "mapping": mapping if mapping else None,
            "description": f"Trim whitespace and normalize casing in '{col_name}'",
        },
    }


def _detect_fuzzy_duplicates(backend: StorageBackend, dataset_id: str, col_name: str) -> dict | None:
    """Find near-duplicate values using fuzzy string matching."""
    values_list = backend.unique_values(dataset_id, col_name)
    cardinality = len(values_list)

    if cardinality < 2 or cardinality > 200:
        return None

    values = [v["value"] for v in values_list if v["value"] is not None]
    clusters = _fuzzy_cluster(values, threshold=82)

    # Filter to clusters with multiple members
    dup_clusters = {k: v for k, v in clusters.items() if len(v) > 1}

    if not dup_clusters:
        return None

    examples = []
    mapping = {}
    for canonical, members in list(dup_clusters.items())[:10]:
        if len(members) > 1:
            examples.append(f"{members} -> '{canonical}'")
            for m in members:
                if m != canonical:
                    mapping[m] = canonical

    return {
        "issue": {
            "column": col_name,
            "issue": "fuzzy_duplicates",
            "severity": "high",
            "detail": f"{len(dup_clusters)} groups of near-duplicate values detected",
            "examples": examples[:5],
            "cluster_count": len(dup_clusters),
        },
        "operation": {
            "type": "entity_resolution",
            "column": col_name,
            "method": "fuzzy",
            "mapping": mapping,
            "description": f"Merge near-duplicate values in '{col_name}'",
        },
    }


def _detect_timezone_issues(backend: StorageBackend, dataset_id: str, col_name: str) -> dict | None:
    """Check for timezone-naive timestamps or potential timezone mismatches."""
    try:
        df = backend.get_dataframe(dataset_id, columns=[col_name], limit=10)
    except Exception:
        return None

    if df.empty:
        return None

    values = [str(v) for v in df[col_name].dropna().head(10)]
    if not values:
        return None

    has_tz = any("+" in v or "Z" in v or "UTC" in v for v in values)
    looks_utc = any(v.endswith("00:00:00") or v.endswith("+00:00") or v.endswith("Z") for v in values)

    if not has_tz and not looks_utc:
        return None

    return {
        "issue": {
            "column": col_name,
            "issue": "timezone",
            "severity": "medium",
            "detail": "Timestamps appear to be UTC. If your data represents local events, timezone conversion may be needed.",
            "sample_values": values[:3],
        },
        "operation": {
            "type": "timezone_convert",
            "column": col_name,
            "from_tz": "UTC",
            "to_tz": None,  # User must specify target timezone
            "description": f"Convert '{col_name}' from UTC to local timezone (specify target)",
        },
    }


def _detect_numeric_strings(backend: StorageBackend, dataset_id: str, col_name: str) -> dict | None:
    """Detect string columns that contain numeric values with formatting."""
    try:
        df = backend.get_dataframe(dataset_id, columns=[col_name], limit=50)
    except Exception:
        return None

    values = [str(v) for v in df[col_name].dropna().unique()[:50]]
    if not values:
        return None

    numeric_pattern = re.compile(r'^[\$\u00a3\u20ac\u00a5]?\s*[\d,.\s]+\s*%?$')
    matches = sum(1 for v in values if numeric_pattern.match(v.strip()))

    if matches < len(values) * 0.7:
        return None

    return {
        "issue": {
            "column": col_name,
            "issue": "numeric_as_string",
            "severity": "medium",
            "detail": "Column appears to contain formatted numbers stored as strings",
            "sample_values": values[:5],
        },
        "operation": {
            "type": "coerce_numeric",
            "column": col_name,
            "strip_chars": ["$", "\u00a3", "\u20ac", "\u00a5", ",", "%", " "],
            "description": f"Convert '{col_name}' from formatted strings to numeric values",
        },
    }


# =============================================================================
# Apply Operations
# =============================================================================

_APPLY_HANDLERS = {
    "normalize_text": "_apply_text_normalization",
    "entity_resolution": "_apply_entity_mapping",
    "timezone_convert": "_apply_timezone_convert",
    "coerce_numeric": "_apply_numeric_coercion",
    "drop_column": "_apply_drop_column",
    "fill_nulls": "_apply_fill_nulls",
}


def _apply_operations(backend: StorageBackend, dataset_id: str, operations: list[dict]) -> dict:
    """Apply a list of cleaning operations to the dataset.

    Requires the DuckDB backend — mutations use SQL UPDATE/ALTER statements.
    """
    applied = []
    errors = []

    for op in operations:
        try:
            op_type = op.get("type")

            if op_type == "normalize_text":
                _apply_text_normalization(backend, dataset_id, op)
            elif op_type == "entity_resolution":
                _apply_entity_mapping(backend, dataset_id, op)
            elif op_type == "timezone_convert":
                _apply_timezone_convert(backend, dataset_id, op)
            elif op_type == "coerce_numeric":
                _apply_numeric_coercion(backend, dataset_id, op)
            elif op_type == "drop_column":
                _apply_drop_column(backend, dataset_id, op)
            elif op_type == "fill_nulls":
                _apply_fill_nulls(backend, dataset_id, op)
            else:
                errors.append(f"Unknown operation type: {op_type}")
                continue

            applied.append(op.get("description", op_type))

        except NotImplementedError:
            errors.append(f"Operation '{op.get('type')}' requires DuckDB backend (install duckdb>=0.9)")
        except Exception as e:
            errors.append(f"Failed to apply {op.get('type', '?')}: {e}")

    schema = backend.schema(dataset_id)

    return {
        "dataset_id": dataset_id,
        "operations_applied": len(applied),
        "operations_failed": len(errors),
        "applied": applied,
        "errors": errors if errors else None,
        "row_count": schema["row_count"],
    }


def _apply_text_normalization(backend: StorageBackend, dataset_id: str, op: dict):
    """Apply trim + case normalization via DuckDB SQL."""
    col = op["column"]
    safe_col = f'"{col}"'
    actions = op.get("actions", [])
    mapping = op.get("mapping")

    if "trim" in actions:
        backend.query_sql(
            f'UPDATE "{dataset_id}" SET {safe_col} = TRIM({safe_col}) '
            f"WHERE {safe_col} IS NOT NULL"
        )
    if mapping:
        for old_val, new_val in mapping.items():
            backend.query_sql(
                f"UPDATE \"{dataset_id}\" SET {safe_col} = '{_escape_sql(new_val)}' "
                f"WHERE {safe_col} = '{_escape_sql(old_val)}'"
            )


def _apply_entity_mapping(backend: StorageBackend, dataset_id: str, op: dict):
    """Apply entity resolution mapping via DuckDB SQL."""
    col = op["column"]
    safe_col = f'"{col}"'
    mapping = op.get("mapping", {})

    for old_val, new_val in mapping.items():
        if old_val != new_val:
            backend.query_sql(
                f"UPDATE \"{dataset_id}\" SET {safe_col} = '{_escape_sql(new_val)}' "
                f"WHERE {safe_col} = '{_escape_sql(old_val)}'"
            )


def _apply_timezone_convert(backend: StorageBackend, dataset_id: str, op: dict):
    """Convert timestamp timezone via DuckDB SQL."""
    col = op["column"]
    safe_col = f'"{col}"'
    from_tz = op.get("from_tz", "UTC")
    to_tz = op.get("to_tz")

    if not to_tz:
        raise ValueError("Target timezone (to_tz) must be specified")

    backend.query_sql(
        f'UPDATE "{dataset_id}" SET {safe_col} = '
        f"timezone('{to_tz}', timezone('{from_tz}', {safe_col})) "
        f"WHERE {safe_col} IS NOT NULL"
    )


def _apply_numeric_coercion(backend: StorageBackend, dataset_id: str, op: dict):
    """Convert formatted string numbers to numeric via DuckDB SQL."""
    col = op["column"]
    safe_col = f'"{col}"'
    strip_chars = op.get("strip_chars", ["$", ",", " "])

    # Build replacement chain
    expr = safe_col
    for char in strip_chars:
        expr = f"REPLACE({expr}, '{char}', '')"

    new_col = f"{col}_numeric"
    safe_new = f'"{new_col}"'

    backend.query_sql(f'ALTER TABLE "{dataset_id}" ADD COLUMN IF NOT EXISTS {safe_new} DOUBLE')
    backend.query_sql(f'UPDATE "{dataset_id}" SET {safe_new} = TRY_CAST({expr} AS DOUBLE)')
    backend.query_sql(f'ALTER TABLE "{dataset_id}" DROP COLUMN {safe_col}')
    backend.query_sql(f'ALTER TABLE "{dataset_id}" RENAME COLUMN {safe_new} TO {safe_col}')


def _apply_drop_column(backend: StorageBackend, dataset_id: str, op: dict):
    """Drop a column from the dataset."""
    col = op["column"]
    backend.query_sql(f'ALTER TABLE "{dataset_id}" DROP COLUMN "{col}"')


def _apply_fill_nulls(backend: StorageBackend, dataset_id: str, op: dict):
    """Fill null values with a specified strategy via DuckDB SQL."""
    col = op["column"]
    safe_col = f'"{col}"'
    strategy = op.get("strategy", "drop_rows")

    if strategy == "drop_rows":
        backend.query_sql(f'DELETE FROM "{dataset_id}" WHERE {safe_col} IS NULL')
    elif strategy == "fill_value":
        value = op.get("value")
        backend.query_sql(
            f"UPDATE \"{dataset_id}\" SET {safe_col} = '{_escape_sql(str(value))}' "
            f"WHERE {safe_col} IS NULL"
        )
    elif strategy == "fill_mean":
        result = backend.query_sql(f'SELECT AVG({safe_col}) FROM "{dataset_id}"')
        mean = result.iloc[0, 0]
        if mean is not None:
            backend.query_sql(
                f'UPDATE "{dataset_id}" SET {safe_col} = {mean} WHERE {safe_col} IS NULL'
            )
    elif strategy == "fill_forward":
        backend.query_sql(f"""
            UPDATE "{dataset_id}" SET {safe_col} = sub.filled FROM (
                SELECT rowid, LAST_VALUE({safe_col} IGNORE NULLS) OVER (ORDER BY rowid) as filled
                FROM "{dataset_id}"
            ) sub WHERE "{dataset_id}".rowid = sub.rowid AND {safe_col} IS NULL
        """)


def _escape_sql(value: str) -> str:
    """Escape single quotes for SQL string literals."""
    return value.replace("'", "''")


# =============================================================================
# LLM Entity Resolution
# =============================================================================

def run_llm_entity_resolution(
    dataset_id: str,
    column: str,
    context: str | None = None,
    model: str = "claude-sonnet-4-20250514",
) -> dict:
    """
    Use LLM to resolve entity names in a categorical column.

    Sends all distinct values to Claude and asks it to group them
    into canonical entities. Handles semantic equivalence that fuzzy
    matching misses.
    """
    backend = get_backend()

    if not backend.table_exists(dataset_id):
        return {"error": f"Dataset '{dataset_id}' not loaded."}

    values_list = backend.unique_values(dataset_id, column)

    if len(values_list) > 200:
        return {
            "error": f"Column '{column}' has {len(values_list)} distinct values "
                     "- too many for LLM resolution. Use fuzzy matching or filter first."
        }

    values_with_counts = [{"value": v["value"], "count": v["count"]} for v in values_list]

    context_str = f"\nContext: {context}" if context else ""

    prompt = f"""Here are the distinct values from a data column called '{column}' with their occurrence counts:
{context_str}

{json.dumps(values_with_counts, indent=2)}

Some of these values likely refer to the same entity but are spelled differently (typos, abbreviations, \
formatting differences, package size variants, etc.).

Group these values into canonical entities. For each group, pick the clearest canonical name \
(prefer the most common spelling, properly capitalized).

Respond with ONLY a JSON object mapping every original value to its canonical form:
{{"original_value": "canonical_value", ...}}

Rules:
- Every original value must appear as a key
- Values that are already correct map to themselves
- Use proper capitalization for canonical names
- If you're not sure two values are the same entity, keep them separate
- Preserve meaningful distinctions (e.g. "Bud Light" and "Budweiser" are different products)
"""

    try:
        from anthropic import Anthropic
        client = Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        mapping = json.loads(text)

    except Exception as e:
        return {"error": f"LLM entity resolution failed: {e}"}

    # Analyze the mapping
    groups: dict[str, list[str]] = defaultdict(list)
    for original, canonical in mapping.items():
        groups[canonical].append(original)

    merged_groups = {k: v for k, v in groups.items() if len(v) > 1}
    counts_by_value = {v["value"]: v["count"] for v in values_with_counts}

    return {
        "column": column,
        "method": "llm",
        "original_cardinality": len(values_with_counts),
        "resolved_cardinality": len(groups),
        "merged_groups": len(merged_groups),
        "groups": {
            k: {
                "canonical": k,
                "members": v,
                "total_rows": sum(counts_by_value.get(m, 0) for m in v),
            }
            for k, v in merged_groups.items()
        },
        "mapping": mapping,
        "operation": {
            "type": "entity_resolution",
            "column": column,
            "method": "llm",
            "mapping": {k: v for k, v in mapping.items() if k != v},
            "description": (
                f"LLM-resolved entity names in '{column}': "
                f"{len(values_with_counts)} values -> {len(groups)} canonical entities"
            ),
        },
    }


# =============================================================================
# Fuzzy Matching Engine
# =============================================================================

def _fuzzy_cluster(values: list[str], threshold: int = 82) -> dict[str, list[str]]:
    """
    Cluster similar strings using fuzzy matching.

    Uses token_sort_ratio which handles word reordering:
    "Bud Light 12pk" vs "12pk Bud Light" -> high similarity

    Returns: {canonical_name: [member1, member2, ...]}
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        return _basic_cluster(values, threshold)

    assigned: set[str] = set()
    clusters: dict[str, list[str]] = {}

    sorted_values = sorted(values, key=len, reverse=True)

    for value in sorted_values:
        if value in assigned:
            continue

        group = [value]
        assigned.add(value)

        for other in sorted_values:
            if other in assigned:
                continue
            score = fuzz.token_sort_ratio(value.lower(), other.lower())
            if score >= threshold:
                group.append(other)
                assigned.add(other)

        canonical = _pick_canonical_from_list(group)
        clusters[canonical] = group

    return clusters


def _basic_cluster(values: list[str], threshold: int = 82) -> dict[str, list[str]]:
    """Fallback clustering without rapidfuzz — simple normalized comparison."""
    from difflib import SequenceMatcher

    assigned: set[str] = set()
    clusters: dict[str, list[str]] = {}

    for value in values:
        if value in assigned:
            continue

        group = [value]
        assigned.add(value)

        for other in values:
            if other in assigned:
                continue
            ratio = SequenceMatcher(None, value.lower(), other.lower()).ratio() * 100
            if ratio >= threshold:
                group.append(other)
                assigned.add(other)

        canonical = _pick_canonical_from_list(group)
        clusters[canonical] = group

    return clusters


def _pick_canonical_from_list(group: list[str]) -> str:
    """Pick canonical name from a group — prefer properly capitalized, longest."""
    if len(group) == 1:
        return group[0]

    scores = []
    for v in group:
        score = 0.0
        if v == v.title() or (v[0].isupper() and not v.isupper()):
            score += 2
        if v.isupper():
            score -= 1
        if v.islower():
            score -= 0.5
        score += len(v) * 0.01
        scores.append((v, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[0][0]


# =============================================================================
# Narrative
# =============================================================================

def _summarize_issues(issues: list[dict]) -> str:
    """Generate a plain-English summary of detected issues."""
    if not issues:
        return "No data quality issues detected. The dataset appears clean."

    parts = [f"Found {len(issues)} data quality issue{'s' if len(issues) > 1 else ''}:"]

    high = [i for i in issues if i.get("severity") == "high"]
    medium = [i for i in issues if i.get("severity") == "medium"]
    warning = [i for i in issues if i.get("severity") == "warning"]

    if high:
        parts.append(f"  {len(high)} high severity - these will likely affect segmentation quality")
        for i in high:
            parts.append(f"    - {i['column']}: {i['detail']}")

    if medium:
        parts.append(f"  {len(medium)} medium severity - worth fixing for cleaner analysis")

    if warning:
        parts.append(f"  {len(warning)} warnings - informational, may not need action")

    parts.append("\nRecommendation: review the suggested operations and apply those that make sense for your analysis goal.")

    return "\n".join(parts)
