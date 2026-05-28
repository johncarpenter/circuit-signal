"""
Plan Builder — creates DataPlans from TDV graph + normalization graphs.

A DataPlan describes how to load, join, normalize, and segment datasets
for downstream analysis (batch_runner / Layer 1).
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from circuit_core.tdv_profiler import DiscriminatorGraph

from circuit_core.data_prep.entity_normalizer import NormalizationGraph

logger = logging.getLogger("data-prep.plan-builder")


@dataclass
class DataPlan:
    """Structured plan for dataset selection, joining, normalization, and segmentation."""

    primary_dataset: Optional[dict] = None
    supplementary_datasets: list[dict] = field(default_factory=list)
    joins: list[dict] = field(default_factory=list)
    filters: list[dict] = field(default_factory=list)
    target_grain: str = "daily"

    # Normalization fields
    normalization_sql: dict[str, str] = field(default_factory=dict)
    segment_by: list[str] = field(default_factory=list)
    segment_estimates: dict[str, int] = field(default_factory=dict)

    def set_primary(self, dataset_id, source_path, time_col, discriminators, values, time_grain=None):
        self.primary_dataset = {
            'dataset_id': dataset_id, 'source_path': source_path,
            'time_col': time_col, 'discriminators': discriminators,
            'values': values, 'time_grain': time_grain,
        }

    def add_supplementary(self, dataset_id, source_path, time_col,
                          join_key, join_type='left', time_grain=None, values=None):
        self.supplementary_datasets.append({
            'dataset_id': dataset_id, 'source_path': source_path,
            'time_col': time_col, 'join_key': join_key,
            'join_type': join_type, 'time_grain': time_grain,
            'values': values or [],
        })

    def add_filter(self, column, operator, value):
        self.filters.append({'column': column, 'operator': operator, 'value': value})

    def describe(self) -> str:
        lines = ["DATA PLAN", "=" * 50]
        if self.primary_dataset:
            p = self.primary_dataset
            lines.append(f"\nPRIMARY: {p['dataset_id']}")
            lines.append(f"  Time: {p['time_col']} ({p['time_grain']})")
            lines.append(f"  Discriminators: {', '.join(p['discriminators'])}")
            lines.append(f"  Values: {', '.join(p['values'])}")

        for s in self.supplementary_datasets:
            lines.append(f"\nSUPPLEMENTARY: {s['dataset_id']}")
            lines.append(f"  Join on: {s['join_key']} ({s['join_type']})")
            lines.append(f"  Time: {s['time_col']} ({s['time_grain']})")
            lines.append(f"  Values: {', '.join(s['values'])}")

        if self.filters:
            lines.append(f"\nFILTERS:")
            for f in self.filters:
                lines.append(f"  {f['column']} {f['operator']} {f['value']}")

        if self.normalization_sql:
            lines.append(f"\nNORMALIZATION:")
            for col, sql in self.normalization_sql.items():
                lines.append(f"  {col}: lookup table ready")

        if self.segment_by:
            lines.append(f"\nSEGMENT BY: {', '.join(self.segment_by)}")

        if self.segment_estimates:
            lines.append(f"\nSEGMENT ESTIMATES:")
            for level, count in self.segment_estimates.items():
                lines.append(f"  {level}: ~{count} segments")

        return '\n'.join(lines)


class PlanBuilder:
    """Uses the TDV graph and optional normalization graphs to build DataPlans."""

    def __init__(self, graph: DiscriminatorGraph, profiles: dict,
                 norm_graphs: dict[str, NormalizationGraph] = None):
        """
        Args:
            graph: TDV discriminator graph
            profiles: Dataset profiles from GraphStore.load()
            norm_graphs: Dict of {column_name: NormalizationGraph} for each
                         discriminator column that has been normalized.
        """
        self.graph = graph
        self.profiles = profiles
        self.norm_graphs = norm_graphs or {}

    def build_plan_for_value(self, target_value: str, target_disc: str = None) -> DataPlan:
        """Build a plan centered on a discriminator value (e.g., 'Bud Light')."""
        plan = DataPlan()
        matches = self.graph.find_datasets_for_value(target_value, target_disc)
        if not matches:
            return plan

        direct = [m for m in matches if m['match_type'] == 'direct']
        if not direct:
            return plan

        best = max(direct, key=lambda m: len(self.profiles.get(m['dataset_id'], {}).get('discriminators', [])))
        best_profile = self.profiles[best['dataset_id']]

        plan.set_primary(
            dataset_id=best['dataset_id'],
            source_path=best_profile['source_path'],
            time_col=best_profile.get('primary_time_col'),
            discriminators=best_profile.get('discriminators', []),
            values=best_profile.get('values', []),
            time_grain=self._get_time_grain(best['dataset_id']),
        )
        plan.add_filter(best['matched_column'], '=', target_value)

        # Find supplementary datasets via shared discriminators
        primary_discs = set(best_profile.get('discriminators', []))
        seen = {best['dataset_id']}

        for rel in self.graph.find_related_datasets(best['dataset_id']):
            rel_id = rel['dataset_id']
            if rel_id in seen:
                continue
            seen.add(rel_id)

            rel_profile = self.profiles.get(rel_id, {})
            if not rel_profile.get('is_temporal'):
                continue

            plan.add_supplementary(
                dataset_id=rel_id,
                source_path=rel_profile['source_path'],
                time_col=rel_profile.get('primary_time_col'),
                join_key=rel['shared_discriminator'],
                time_grain=self._get_time_grain(rel_id),
                values=rel_profile.get('values', []),
            )

        # Add normalization SQL if available
        self._apply_normalization(plan)

        return plan

    def build_plan_for_datasets(self, dataset_ids: list[str]) -> DataPlan:
        """Build a plan for explicitly selected datasets."""
        plan = DataPlan()
        if not dataset_ids:
            return plan

        p = self.profiles[dataset_ids[0]]
        plan.set_primary(
            dataset_id=dataset_ids[0], source_path=p['source_path'],
            time_col=p.get('primary_time_col'),
            discriminators=p.get('discriminators', []),
            values=p.get('values', []),
            time_grain=self._get_time_grain(dataset_ids[0]),
        )

        for ds_id in dataset_ids[1:]:
            join_info = self.graph.find_join_path(dataset_ids[0], ds_id)
            if not join_info:
                logger.warning("No join path from %s to %s", dataset_ids[0], ds_id)
                continue
            rel_profile = self.profiles[ds_id]
            join_key = (join_info['shared_discriminators'][0]
                        if join_info['join_type'] == 'direct'
                        else join_info.get('from_discriminator'))

            plan.add_supplementary(
                dataset_id=ds_id, source_path=rel_profile['source_path'],
                time_col=rel_profile.get('primary_time_col'),
                join_key=join_key,
                time_grain=self._get_time_grain(ds_id),
                values=rel_profile.get('values', []),
            )

        # Add normalization SQL if available
        self._apply_normalization(plan)

        return plan

    def estimate_segments(self, plan: DataPlan) -> dict[str, int]:
        """
        Estimate segment counts for each hierarchy level in the normalization.

        Keys are "{source_col}_{level}" to match the enrichment column naming
        convention (e.g. "description_product", "name_brand").  Also keeps
        bare level keys with the max across all source columns for backward
        compatibility.

        Returns dict like {'description_product': 15, 'product': 15, ...}
        """
        estimates = {}
        for col_name, norm_graph in self.norm_graphs.items():
            summary = norm_graph.get_summary()
            # Keyed by source_col + level
            product_count = summary.get('canonical_entities', 0)
            estimates[f"{col_name}_product"] = product_count
            # Bare level: keep the max across all source columns
            estimates['product'] = max(estimates.get('product', 0), product_count)
            for level, count in summary.get('hierarchy_levels', {}).items():
                estimates[f"{col_name}_{level}"] = count
                estimates[level] = max(estimates.get(level, 0), count)

        plan.segment_estimates = estimates
        return estimates

    def _apply_normalization(self, plan: DataPlan):
        """Populate plan.normalization_sql from available norm_graphs."""
        if not self.norm_graphs or not plan.primary_dataset:
            return

        primary_discs = plan.primary_dataset.get('discriminators', [])

        for col_name, norm_graph in self.norm_graphs.items():
            if col_name not in primary_discs:
                continue

            lookup_sql = norm_graph.build_duckdb_lookup(column_name=col_name)
            if lookup_sql.startswith("--"):
                continue

            plan.normalization_sql[col_name] = lookup_sql

            # Set segment_by to use normalized hierarchy column names
            # Include all levels (product is the leaf, most useful for segmentation)
            for level in norm_graph.levels:
                prefixed = f"norm_{col_name}_{level}"
                if prefixed not in plan.segment_by:
                    plan.segment_by.append(prefixed)

        if self.norm_graphs:
            self.estimate_segments(plan)

    def _get_time_grain(self, ds_id):
        node = self.graph.graph.nodes.get(f"ds:{ds_id}", {})
        return node.get('time_grain', 'daily')
