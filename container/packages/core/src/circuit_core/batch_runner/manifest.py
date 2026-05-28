"""YAML manifest parsing and validation for batch runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class NormalizationConfig:
    enabled: bool = False
    lookup_sql: dict[str, str] = field(default_factory=dict)
    enrichment_columns: list[str] = field(default_factory=list)
    hierarchy_levels: list[str] = field(default_factory=list)


@dataclass
class CleanConfig:
    auto_detect: bool = True
    apply_operations: list[dict] | None = None


@dataclass
class DeviationConfig:
    lookback_window: str = "90d"
    sensitivity: str = "medium"


@dataclass
class ScenarioDef:
    name: str
    segment_by: str | list[str]
    min_segment_size: int = 50


@dataclass
class Manifest:
    data_path: str
    dataset_name: str
    timestamp_col: str
    scenarios: list[ScenarioDef]
    freq: str | None = None
    value_cols: list[str] | None = None
    clean: CleanConfig = field(default_factory=CleanConfig)
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    deviations: DeviationConfig = field(default_factory=DeviationConfig)
    correlate: bool = False


def load_manifest(path: str | Path) -> Manifest:
    """Load and validate a batch runner manifest from YAML."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    with open(p) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError("Manifest must be a YAML mapping")

    # Resolve data_path relative to manifest directory
    manifest_dir = p.parent
    data_path = raw.get("data_path")
    if not data_path:
        raise ValueError("Manifest must specify 'data_path'")
    resolved_data = (manifest_dir / data_path).resolve()
    if not resolved_data.exists():
        raise FileNotFoundError(f"Data file not found: {resolved_data} (from data_path: {data_path})")

    dataset_name = raw.get("dataset_name")
    if not dataset_name:
        raise ValueError("Manifest must specify 'dataset_name'")

    timestamp_col = raw.get("timestamp_col")
    if not timestamp_col:
        raise ValueError("Manifest must specify 'timestamp_col'")

    # Parse scenarios
    raw_scenarios = raw.get("scenarios", [])
    if not raw_scenarios:
        raise ValueError("Manifest must define at least one scenario")

    scenarios = []
    for s in raw_scenarios:
        if not isinstance(s, dict) or "name" not in s or "segment_by" not in s:
            raise ValueError(f"Each scenario needs 'name' and 'segment_by', got: {s}")
        scenarios.append(ScenarioDef(
            name=s["name"],
            segment_by=s["segment_by"],
            min_segment_size=s.get("min_segment_size", 50),
        ))

    # Parse clean config
    raw_clean = raw.get("clean", {})
    clean = CleanConfig(
        auto_detect=raw_clean.get("auto_detect", True),
        apply_operations=raw_clean.get("apply_operations"),
    )

    # Parse normalization config
    raw_norm = raw.get("normalization", {})
    normalization = NormalizationConfig(
        enabled=raw_norm.get("enabled", False),
        lookup_sql=raw_norm.get("lookup_sql", {}),
        enrichment_columns=raw_norm.get("enrichment_columns", []),
        hierarchy_levels=raw_norm.get("hierarchy_levels", []),
    )

    # Parse deviation config
    raw_dev = raw.get("deviations", {})
    deviations = DeviationConfig(
        lookback_window=raw_dev.get("lookback_window", "90d"),
        sensitivity=raw_dev.get("sensitivity", "medium"),
    )

    return Manifest(
        data_path=str(resolved_data),
        dataset_name=dataset_name,
        timestamp_col=timestamp_col,
        scenarios=scenarios,
        freq=raw.get("freq"),
        value_cols=raw.get("value_cols"),
        clean=clean,
        normalization=normalization,
        deviations=deviations,
        correlate=raw.get("correlate", False),
    )
