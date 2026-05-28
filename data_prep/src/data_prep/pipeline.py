"""
Preparation Pipeline — orchestrates profiling, normalization, and plan building.

Stages:
    1. Profile: Scan data directory with TDV profiler -> tdv_graph.json
    2. Normalize: Extract discriminator values, cluster + classify -> norm_graph.json
    3. Plan: Load both graphs, build DataPlan with normalization SQL
    4. Generate manifest: Convert DataPlan to batch_runner Manifest
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import duckdb
import yaml

from tdv_profiler import DataLakeScanner, ColumnRole

from data_prep.entity_normalizer import EntityNormalizationPipeline, NormalizationGraph
from data_prep.graph_store import GraphStore
from data_prep.plan_builder import DataPlan, PlanBuilder

logger = logging.getLogger("data-prep.pipeline")


@dataclass
class PipelineConfig:
    """Configuration for the full data preparation pipeline."""
    data_lake_dir: str
    output_dir: str
    normalization_mode: str = "rules"
    fuzzy_threshold: int = 80
    hierarchy_levels: list[str] = field(default_factory=lambda: [
        'product', 'brand', 'subcategory', 'category', 'department',
    ])
    segment_by: list[str] = field(default_factory=list)
    normalize_columns: list[str] = field(default_factory=list)
    skip_columns: list[str] = field(default_factory=list)
    rules: dict = field(default_factory=dict)
    rules_path: Optional[str] = None
    context: str = "retail product catalog"
    llm_classify_fn: Optional[object] = None


class PreparationPipeline:
    """Orchestrates the full data preparation flow: profile -> normalize -> plan."""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._scanner: Optional[DataLakeScanner] = None
        self._norm_graphs: dict[str, NormalizationGraph] = {}
        self._plan: Optional[DataPlan] = None
        self._dataset_descriptor: Optional[dict] = self._load_dataset_descriptor()

    def _load_dataset_descriptor(self) -> Optional[dict]:
        """Load dataset.yaml from the data directory if it exists."""
        descriptor_path = Path(self.config.data_lake_dir) / "dataset.yaml"
        if not descriptor_path.exists():
            return None
        with open(descriptor_path) as f:
            desc = yaml.safe_load(f)
        logger.info("Loaded dataset descriptor: %s", descriptor_path)
        return desc

    def _build_llm_context(self) -> str:
        """Build a context string for LLM classification from the dataset descriptor."""
        if not self._dataset_descriptor:
            return self.config.context

        desc = self._dataset_descriptor
        parts = []
        if desc.get('domain'):
            parts.append(desc['domain'])
        if desc.get('industry'):
            parts.append(f"industry: {desc['industry']}")
        if desc.get('geography'):
            parts.append(f"geography: {desc['geography']}")
        if desc.get('description'):
            parts.append(desc['description'].strip())
        if desc.get('currency'):
            parts.append(f"Currency: {desc['currency']}")

        # Add per-dataset context
        for ds_id, ds_info in desc.get('datasets', {}).items():
            if isinstance(ds_info, dict) and ds_info.get('description'):
                parts.append(f"Dataset '{ds_id}': {ds_info['description'].strip()}")

        return "\n".join(parts) if parts else self.config.context

    # -- Stage 1: Profile ---------------------------------------------------

    def run_stage1_profile(self) -> dict:
        """Scan data directory with TDV profiler and save tdv_graph.json."""
        logger.info("Stage 1: Profiling data lake at %s", self.config.data_lake_dir)

        self._scanner = DataLakeScanner()
        scan_result = self._scanner.scan_directory(self.config.data_lake_dir)

        graph_path = str(self.output_dir / "tdv_graph.json")
        GraphStore.save(self._scanner, graph_path)

        summary = self._scanner.graph.get_summary()
        logger.info(
            "Profile complete: %d datasets, %d discriminators, %d hierarchies",
            len(summary['datasets']),
            len(summary['discriminators']),
            len(summary['hierarchies']),
        )

        return {
            'graph_path': graph_path,
            'datasets': len(summary['datasets']),
            'discriminators': len(summary['discriminators']),
            'hierarchies': len(summary['hierarchies']),
            'scan_result': scan_result,
        }

    # -- Stage 2: Normalize -------------------------------------------------

    def run_stage2_normalize(self, tdv_graph_path: str = None) -> dict:
        """
        Extract discriminator values from datasets and run entity normalization.

        Reads discriminator columns from the TDV graph, extracts distinct values
        via DuckDB, runs EntityNormalizationPipeline, and saves norm_graph.json
        per column.

        When config.normalize_columns is set, those columns are normalized from
        every dataset that contains them (regardless of profiler role). Otherwise
        falls back to profiler-tagged discriminator columns.
        """
        logger.info("Stage 2: Entity normalization (mode=%s)", self.config.normalization_mode)

        # Build context from dataset descriptor (or fall back to config default)
        llm_context = self._build_llm_context()
        logger.info("LLM context: %s", llm_context[:120] + "..." if len(llm_context) > 120 else llm_context)

        # Load TDV graph if not already loaded from Stage 1
        if tdv_graph_path is None:
            tdv_graph_path = str(self.output_dir / "tdv_graph.json")

        graph, profiles = GraphStore.load(tdv_graph_path)

        # Load rules from file if specified
        rules = self.config.rules
        if self.config.rules_path:
            with open(self.config.rules_path) as f:
                rules = json.load(f)

        # Build per-dataset column lists to normalize
        explicit_cols = self.config.normalize_columns
        db = duckdb.connect()
        results = {}

        for ds_id, profile_data in profiles.items():
            source_path = profile_data.get('source_path', '')

            if not source_path or not Path(source_path).exists():
                logger.warning("Dataset %s source not found: %s", ds_id, source_path)
                continue

            # Use explicit columns if provided, otherwise profiler discriminators
            if explicit_cols:
                # Check which explicit columns actually exist in this dataset
                all_col_names = [c['name'] for c in profile_data.get('columns', [])]
                cols_to_normalize = [c for c in explicit_cols if c in all_col_names]
            else:
                cols_to_normalize = profile_data.get('discriminators', [])

            for col_name in cols_to_normalize:
                if col_name in self.config.skip_columns:
                    logger.info("Skipping column '%s' (in skip_columns)", col_name)
                    continue

                if col_name in self._norm_graphs:
                    continue  # Already normalized from another dataset

                logger.info("Extracting values for '%s' from %s", col_name, ds_id)

                # Extract distinct values via DuckDB
                ext = Path(source_path).suffix.lower()
                read_fn = f"read_csv_auto('{source_path}')" if ext == '.csv' else f"read_parquet('{source_path}')"
                try:
                    raw_values = [
                        str(r[0]) for r in
                        db.execute(f'SELECT DISTINCT "{col_name}" FROM {read_fn} WHERE "{col_name}" IS NOT NULL').fetchall()
                    ]
                except Exception as e:
                    logger.warning("Failed to extract '%s' from %s: %s", col_name, ds_id, e)
                    continue

                if not raw_values:
                    continue

                # When explicit columns span multiple datasets, merge values
                # from all datasets that have this column
                if explicit_cols:
                    for other_ds_id, other_profile in profiles.items():
                        if other_ds_id == ds_id:
                            continue
                        other_cols = [c['name'] for c in other_profile.get('columns', [])]
                        if col_name not in other_cols:
                            continue
                        other_path = other_profile.get('source_path', '')
                        if not other_path or not Path(other_path).exists():
                            continue
                        other_ext = Path(other_path).suffix.lower()
                        other_fn = f"read_csv_auto('{other_path}')" if other_ext == '.csv' else f"read_parquet('{other_path}')"
                        try:
                            extra = [
                                str(r[0]) for r in
                                db.execute(f'SELECT DISTINCT "{col_name}" FROM {other_fn} WHERE "{col_name}" IS NOT NULL').fetchall()
                            ]
                            raw_values.extend(extra)
                            logger.info("Merged %d values from %s for '%s'", len(extra), other_ds_id, col_name)
                        except Exception as e:
                            logger.warning("Failed to extract '%s' from %s: %s", col_name, other_ds_id, e)

                logger.info("Found %d distinct values for '%s'", len(set(raw_values)), col_name)

                # Run normalization pipeline
                pipeline = EntityNormalizationPipeline(
                    fuzzy_threshold=self.config.fuzzy_threshold,
                    hierarchy_levels=self.config.hierarchy_levels,
                )
                norm_graph = pipeline.run(
                    raw_values=raw_values,
                    classification_mode=self.config.normalization_mode,
                    rules=rules,
                    llm_classify_fn=self.config.llm_classify_fn,
                    context=llm_context,
                )

                # Save per-column norm graph
                norm_path = str(self.output_dir / f"norm_graph_{col_name}.json")
                GraphStore.save_norm(norm_graph, norm_path)
                self._norm_graphs[col_name] = norm_graph

                results[col_name] = {
                    'norm_graph_path': norm_path,
                    'raw_values': len(set(raw_values)),
                    'summary': norm_graph.get_summary(),
                }

        db.close()

        return {
            'columns_normalized': len(results),
            'columns': results,
        }

    # -- Stage 3: Plan ------------------------------------------------------

    def run_stage3_plan(self, tdv_graph_path: str = None,
                        dataset_ids: list[str] = None) -> DataPlan:
        """
        Load TDV + norm graphs and build a DataPlan with normalization SQL.
        """
        logger.info("Stage 3: Building data plan")

        if tdv_graph_path is None:
            tdv_graph_path = str(self.output_dir / "tdv_graph.json")

        graph, profiles = GraphStore.load(tdv_graph_path)

        # Load any norm graphs that were saved but not in memory
        if not self._norm_graphs:
            for ng_path in self.output_dir.glob("norm_graph_*.json"):
                col_name = ng_path.stem.replace("norm_graph_", "")
                self._norm_graphs[col_name] = GraphStore.load_norm(str(ng_path))
                logger.info("Loaded norm graph for '%s'", col_name)

        builder = PlanBuilder(graph, profiles, norm_graphs=self._norm_graphs)

        if dataset_ids:
            self._plan = builder.build_plan_for_datasets(dataset_ids)
        else:
            # Use all temporal datasets as primary candidates
            temporal_ids = [
                ds_id for ds_id, p in profiles.items()
                if p.get('is_temporal', False)
            ]
            if temporal_ids:
                self._plan = builder.build_plan_for_datasets(temporal_ids)
            else:
                self._plan = DataPlan()

        # Save plan summary
        plan_path = self.output_dir / "data_plan.json"
        plan_data = {
            'primary_dataset': self._plan.primary_dataset,
            'supplementary_datasets': self._plan.supplementary_datasets,
            'normalization_sql': self._plan.normalization_sql,
            'segment_by': self._plan.segment_by,
            'segment_estimates': self._plan.segment_estimates,
        }
        with open(plan_path, 'w') as f:
            json.dump(plan_data, f, indent=2, default=str)
        logger.info("Plan saved to %s", plan_path)

        return self._plan

    # -- Generate Manifest --------------------------------------------------

    def generate_manifest(self, plan: DataPlan = None,
                          timestamp_col: str = None,
                          dataset_name: str = None,
                          data_path: str = None) -> dict:
        """
        Convert a DataPlan into a batch_runner-compatible manifest dict.

        This can be saved to YAML and loaded by batch_runner.
        """
        if plan is None:
            plan = self._plan
        if plan is None:
            raise ValueError("No plan available. Run run_stage3_plan() first.")

        primary = plan.primary_dataset or {}

        manifest = {
            'data_path': data_path or primary.get('source_path', ''),
            'dataset_name': dataset_name or primary.get('dataset_id', 'unnamed'),
            'timestamp_col': timestamp_col or primary.get('time_col', ''),
            'freq': primary.get('time_grain'),
            'value_cols': primary.get('values'),
            'clean': {'auto_detect': True},
            'normalization': {
                'enabled': bool(plan.normalization_sql),
                'lookup_sql': plan.normalization_sql,
                'enrichment_columns': plan.segment_by,
                'hierarchy_levels': self.config.hierarchy_levels,
            },
            'deviations': {
                'lookback_window': '90d',
                'sensitivity': 'medium',
            },
            'correlate': False,
            'scenarios': [],
        }

        # Build scenarios from segment_by columns, skipping levels with <=1 segment
        if plan.segment_by:
            for col in plan.segment_by:
                # Extract the source column and hierarchy level from the enrichment column
                # e.g. "norm_name_brand" -> source="name", level="brand"
                parts = col.split("_", 2)  # ["norm", "colname", "level"]
                level = parts[-1] if len(parts) >= 3 else col
                # Try specific key first (e.g. "name_brand"), fall back to bare level
                source_col = parts[1] if len(parts) >= 3 else None
                specific_key = f"{source_col}_{level}" if source_col else None
                estimated = (
                    plan.segment_estimates.get(specific_key, 0) if specific_key
                    else 0
                ) or plan.segment_estimates.get(level, 0)
                if estimated <= 1:
                    logger.info("Skipping scenario by_%s (%d segment — not useful)", col, estimated)
                    continue
                manifest['scenarios'].append({
                    'name': f"by_{col}",
                    'segment_by': col,
                    'min_segment_size': 50,
                })
        elif self.config.segment_by:
            for col in self.config.segment_by:
                manifest['scenarios'].append({
                    'name': f"by_{col}",
                    'segment_by': col,
                    'min_segment_size': 50,
                })
        else:
            # Fallback: use primary discriminators
            for disc in primary.get('discriminators', []):
                manifest['scenarios'].append({
                    'name': f"by_{disc}",
                    'segment_by': disc,
                    'min_segment_size': 50,
                })

        return manifest
