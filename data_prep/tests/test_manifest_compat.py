"""Tests for backward compatibility: existing manifests load with normalization disabled."""

import pytest
from pathlib import Path
import sys

# Add batch_runner to path so we can import manifest without full install
batch_runner_src = Path(__file__).resolve().parent.parent.parent / "batch_runner" / "src"
sys.path.insert(0, str(batch_runner_src))

from batch_runner.manifest import load_manifest, Manifest, NormalizationConfig


class TestManifestCompat:
    def test_existing_beer_manifest_loads(self):
        """Existing beer scenarios.yaml should load with normalization disabled."""
        manifest_path = Path(__file__).resolve().parent.parent.parent / "data" / "beer" / "scenarios.yaml"
        if not manifest_path.exists():
            pytest.skip("Beer manifest not found")

        manifest = load_manifest(str(manifest_path))
        assert manifest.dataset_name == "beer"
        assert manifest.normalization.enabled is False
        assert manifest.normalization.lookup_sql == {}

    def test_normalization_config_defaults(self):
        """NormalizationConfig should default to disabled."""
        config = NormalizationConfig()
        assert config.enabled is False
        assert config.lookup_sql == {}
        assert config.enrichment_columns == []
        assert config.hierarchy_levels == []

    def test_manifest_has_normalization_field(self):
        """Manifest dataclass should have a normalization field."""
        manifest_path = Path(__file__).resolve().parent.parent.parent / "data" / "beer" / "scenarios.yaml"
        if not manifest_path.exists():
            pytest.skip("Beer manifest not found")

        manifest = load_manifest(str(manifest_path))
        assert hasattr(manifest, 'normalization')
        assert isinstance(manifest.normalization, NormalizationConfig)

    def test_manifest_with_normalization_yaml(self, tmp_path):
        """A manifest with normalization section should parse correctly."""
        # Create a small test CSV
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("date,name,amount\n2024-01-01,A,10\n2024-01-02,B,20\n")

        # Create manifest with normalization
        manifest_yaml = tmp_path / "test.yaml"
        manifest_yaml.write_text(f"""
data_path: "{csv_path.name}"
dataset_name: "test"
timestamp_col: "date"
scenarios:
  - name: by_name
    segment_by: name
normalization:
  enabled: true
  lookup_sql:
    name: "CREATE TABLE _norm_lookup_name AS SELECT 'A' raw_value, 'Alpha' product"
  enrichment_columns:
    - norm_name_product
  hierarchy_levels:
    - product
    - brand
""")

        manifest = load_manifest(str(manifest_yaml))
        assert manifest.normalization.enabled is True
        assert 'name' in manifest.normalization.lookup_sql
        assert manifest.normalization.enrichment_columns == ['norm_name_product']
        assert manifest.normalization.hierarchy_levels == ['product', 'brand']
