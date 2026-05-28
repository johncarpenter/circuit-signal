"""
Graph Store — serialization for TDV and normalization graphs.

Handles saving/loading the TDV profiler graph (tdv_graph.json) and
the entity normalization graph (norm_graph.json).
"""

import json
import logging
from pathlib import Path

from networkx.readwrite import json_graph

from tdv_profiler import (
    DataLakeScanner,
    DiscriminatorGraph,
    DatasetProfile,
    ColumnProfile,
    ColumnRole,
)
from data_prep.entity_normalizer import NormalizationGraph

logger = logging.getLogger("data-prep.graph-store")


class GraphStore:
    VERSION = "1.0"

    # -- TDV graph ----------------------------------------------------------

    @staticmethod
    def save(scanner: DataLakeScanner, output_path: str, metadata: dict = None):
        """Save a TDV profiler graph to JSON."""
        graph_data = json_graph.node_link_data(scanner.graph.graph)
        profiles_data = {}
        for ds_id, p in scanner.profiles.items():
            profiles_data[ds_id] = {
                'dataset_id': p.dataset_id, 'source_path': p.source_path,
                'row_count': p.row_count, 'is_temporal': p.is_temporal,
                'primary_time_col': p.primary_time_col,
                'discriminators': p.discriminators, 'values': p.values,
                'tdv_signature': p.tdv_signature,
                'columns': [c.to_dict() for c in p.columns],
            }

        with open(output_path, 'w') as f:
            json.dump({'version': GraphStore.VERSION, 'metadata': metadata or {},
                       'graph': graph_data, 'profiles': profiles_data}, f, indent=2, default=str)
        logger.info("TDV graph saved: %s (%.1f KB)", output_path,
                     Path(output_path).stat().st_size / 1024)

    @staticmethod
    def load(input_path: str) -> tuple[DiscriminatorGraph, dict]:
        """Load a TDV profiler graph from JSON."""
        with open(input_path, 'r') as f:
            data = json.load(f)

        graph = DiscriminatorGraph()
        graph.graph = json_graph.node_link_graph(data['graph'], directed=True)

        profiles = data.get('profiles', {})

        for ds_id, pd in profiles.items():
            cols = [ColumnProfile(
                name=c['name'], role=ColumnRole(c['role']), dtype=c['dtype'],
                cardinality=c['cardinality'], null_pct=c['null_pct'],
                sample_values=c['sample_values'], time_grain=c.get('time_grain'),
                time_range=c.get('time_range'), cardinality_ratio=c.get('cardinality_ratio'),
                distinct_values=c.get('distinct_values'), is_continuous=c.get('is_continuous'),
                value_stats=c.get('value_stats'))
                for c in pd.get('columns', [])]
            dp = DatasetProfile(
                dataset_id=ds_id, source_path=pd['source_path'],
                row_count=pd['row_count'], columns=cols,
                is_temporal=pd['is_temporal'],
                primary_time_col=pd.get('primary_time_col'),
                discriminators=pd.get('discriminators', []),
                values=pd.get('values', []))
            graph._dataset_profiles[ds_id] = dp

        return graph, profiles

    # -- Normalization graph ------------------------------------------------

    @staticmethod
    def save_norm(norm_graph: NormalizationGraph, output_path: str):
        """Save a NormalizationGraph to JSON."""
        norm_graph.save(output_path)

    @staticmethod
    def load_norm(input_path: str) -> NormalizationGraph:
        """Load a NormalizationGraph from JSON."""
        return NormalizationGraph.load(input_path)
