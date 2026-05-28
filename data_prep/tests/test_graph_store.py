"""Tests for graph store: round-trip serialization of TDV and norm graphs."""

import json
import pytest

from tdv_profiler import DataLakeScanner
from tdv_profiler.profiler import create_demo_data
from data_prep.graph_store import GraphStore
from data_prep.entity_normalizer import NormalizationGraph


class TestTDVGraphRoundTrip:
    def test_save_and_load(self, tmp_path):
        # Create demo data and scan
        data_dir = str(tmp_path / "lake")
        create_demo_data(data_dir)

        scanner = DataLakeScanner()
        scanner.scan_directory(data_dir)

        # Save
        graph_path = str(tmp_path / "tdv_graph.json")
        GraphStore.save(scanner, graph_path)

        # Load
        graph, profiles = GraphStore.load(graph_path)

        # Verify profiles round-tripped
        assert len(profiles) > 0
        assert 'pos_transactions' in profiles

        pos = profiles['pos_transactions']
        assert pos['is_temporal'] is True
        assert pos['row_count'] > 0
        assert 'brand' in pos.get('discriminators', [])

    def test_save_with_metadata(self, tmp_path):
        data_dir = str(tmp_path / "lake")
        create_demo_data(data_dir)

        scanner = DataLakeScanner()
        scanner.scan_directory(data_dir)

        graph_path = str(tmp_path / "tdv_graph.json")
        GraphStore.save(scanner, graph_path, metadata={'version': '1.0', 'source': 'test'})

        with open(graph_path) as f:
            data = json.load(f)
        assert data['metadata']['source'] == 'test'


class TestNormGraphRoundTrip:
    def test_save_and_load(self, tmp_path):
        # Build a norm graph
        ng = NormalizationGraph()
        cluster = {
            'canonical': 'Corona Light',
            'members': [
                {'original': 'corona_lt', 'normalized': 'corona light', 'pack_info': None},
                {'original': 'Corona Light', 'normalized': 'corona light', 'pack_info': None},
            ],
            'confidence': 0.95,
        }
        classification = {
            'product': 'Corona Light', 'brand': 'Corona',
            'subcategory': 'Light Beer', 'category': 'Beer',
            'department': 'Beverages',
        }
        ng.add_cluster(cluster, classification)

        # Save via GraphStore
        path = str(tmp_path / "norm_graph.json")
        GraphStore.save_norm(ng, path)

        # Load via GraphStore
        loaded = GraphStore.load_norm(path)

        assert loaded.normalize('corona_lt') == 'Corona Light'
        h = loaded.get_hierarchy('corona_lt')
        assert h['brand'] == 'Corona'
        assert h['category'] == 'Beer'

    def test_json_is_valid(self, tmp_path):
        ng = NormalizationGraph()
        ng.add_cluster({
            'canonical': 'Test',
            'members': [{'original': 'test', 'normalized': 'test', 'pack_info': None}],
            'confidence': 1.0,
        })

        path = str(tmp_path / "norm.json")
        GraphStore.save_norm(ng, path)

        with open(path) as f:
            data = json.load(f)
        assert data['version'] == '1.0'
        assert 'graph' in data
        assert 'raw_to_canonical' in data
