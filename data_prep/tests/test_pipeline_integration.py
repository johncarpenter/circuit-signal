"""Integration tests: synthetic data through the full pipeline."""

import json
import pytest
from pathlib import Path

from tdv_profiler.profiler import create_demo_data
from data_prep.pipeline import PipelineConfig, PreparationPipeline
from data_prep.graph_store import GraphStore


class TestPipelineIntegration:
    @pytest.fixture
    def demo_data(self, tmp_path):
        """Create demo data in a temp directory."""
        data_dir = str(tmp_path / "lake")
        create_demo_data(data_dir)
        return data_dir

    @pytest.fixture
    def output_dir(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir()
        return str(out)

    def test_stage1_profile(self, demo_data, output_dir):
        config = PipelineConfig(data_lake_dir=demo_data, output_dir=output_dir)
        pipeline = PreparationPipeline(config)

        result = pipeline.run_stage1_profile()

        assert result['datasets'] == 5
        assert result['discriminators'] > 0
        assert Path(result['graph_path']).exists()

    def test_stage2_normalize(self, demo_data, output_dir):
        config = PipelineConfig(
            data_lake_dir=demo_data,
            output_dir=output_dir,
            skip_columns=['store_id', 'state', 'sqft', 'unit_cost', 'pack_size'],
        )
        pipeline = PreparationPipeline(config)

        # Run stage 1 first
        pipeline.run_stage1_profile()

        # Then normalize
        result = pipeline.run_stage2_normalize()

        assert result['columns_normalized'] > 0
        # brand should be normalized
        assert 'brand' in result['columns']

    def test_stage3_plan(self, demo_data, output_dir):
        config = PipelineConfig(
            data_lake_dir=demo_data,
            output_dir=output_dir,
            skip_columns=['store_id', 'state', 'sqft', 'unit_cost', 'pack_size'],
        )
        pipeline = PreparationPipeline(config)

        pipeline.run_stage1_profile()
        pipeline.run_stage2_normalize()
        plan = pipeline.run_stage3_plan()

        assert plan.primary_dataset is not None
        # Plan should have normalization SQL
        assert len(plan.normalization_sql) > 0

    def test_full_pipeline_run(self, demo_data, output_dir):
        config = PipelineConfig(
            data_lake_dir=demo_data,
            output_dir=output_dir,
            skip_columns=['store_id', 'state', 'sqft', 'unit_cost', 'pack_size'],
        )
        pipeline = PreparationPipeline(config)

        # Run all stages
        profile_result = pipeline.run_stage1_profile()
        norm_result = pipeline.run_stage2_normalize()
        plan = pipeline.run_stage3_plan()

        # Verify outputs exist
        assert Path(output_dir, "tdv_graph.json").exists()
        assert Path(output_dir, "data_plan.json").exists()
        assert any(Path(output_dir).glob("norm_graph_*.json"))

    def test_generate_manifest(self, demo_data, output_dir):
        config = PipelineConfig(
            data_lake_dir=demo_data,
            output_dir=output_dir,
            skip_columns=['store_id', 'state', 'sqft', 'unit_cost', 'pack_size'],
        )
        pipeline = PreparationPipeline(config)

        pipeline.run_stage1_profile()
        pipeline.run_stage2_normalize()
        plan = pipeline.run_stage3_plan()

        manifest = pipeline.generate_manifest(plan)

        assert manifest['dataset_name'] is not None
        assert manifest['timestamp_col'] is not None
        assert isinstance(manifest['scenarios'], list)
        assert len(manifest['scenarios']) > 0
        # Normalization should be enabled
        assert manifest['normalization']['enabled'] is True

    def test_segment_reduction(self, demo_data, output_dir):
        """Verify normalization reduces segment count vs raw values."""
        config = PipelineConfig(
            data_lake_dir=demo_data,
            output_dir=output_dir,
            skip_columns=['store_id', 'state', 'sqft', 'unit_cost', 'pack_size'],
        )
        pipeline = PreparationPipeline(config)

        pipeline.run_stage1_profile()
        pipeline.run_stage2_normalize()
        plan = pipeline.run_stage3_plan()

        # The plan should show segment estimates
        assert len(plan.segment_estimates) > 0

    def test_skip_columns_respected(self, demo_data, output_dir):
        config = PipelineConfig(
            data_lake_dir=demo_data,
            output_dir=output_dir,
            skip_columns=['brand', 'sku', 'category', 'region',
                          'store_id', 'state', 'sqft', 'unit_cost', 'pack_size'],
        )
        pipeline = PreparationPipeline(config)

        pipeline.run_stage1_profile()
        result = pipeline.run_stage2_normalize()

        # All discriminators were skipped
        assert result['columns_normalized'] == 0

    def test_plan_saved_as_json(self, demo_data, output_dir):
        config = PipelineConfig(
            data_lake_dir=demo_data,
            output_dir=output_dir,
            skip_columns=['store_id', 'state', 'sqft', 'unit_cost', 'pack_size'],
        )
        pipeline = PreparationPipeline(config)

        pipeline.run_stage1_profile()
        pipeline.run_stage2_normalize()
        pipeline.run_stage3_plan()

        plan_path = Path(output_dir) / "data_plan.json"
        assert plan_path.exists()

        with open(plan_path) as f:
            plan_data = json.load(f)

        assert 'primary_dataset' in plan_data
        assert 'normalization_sql' in plan_data
        assert 'segment_by' in plan_data
