"""Tests for DuckDB normalization injection: create table, apply, verify columns."""

import pytest
import duckdb

from data_prep.entity_normalizer import NormalizationGraph, EntityNormalizationPipeline


class TestNormalizationInjection:
    """Test the normalization SQL against a real DuckDB instance."""

    def _create_test_db(self):
        """Create an in-memory DuckDB with test data."""
        db = duckdb.connect()
        db.execute("""
            CREATE TABLE test_data (
                date DATE,
                name VARCHAR,
                amount DOUBLE
            )
        """)
        db.execute("""
            INSERT INTO test_data VALUES
                ('2024-01-01', 'corona_lt', 10.0),
                ('2024-01-02', 'Corona Light', 20.0),
                ('2024-01-03', 'CORONA LT 12PK', 15.0),
                ('2024-01-04', 'bud_lt', 25.0),
                ('2024-01-05', 'Bud Light', 30.0),
                ('2024-01-06', 'BUD LIGHT 24PK', 35.0),
                ('2024-01-07', 'Miller Lite', 18.0),
                ('2024-01-08', 'MILLER LITE', 22.0)
        """)
        return db

    def _build_norm_graph(self):
        """Build a normalization graph with test data."""
        rules = {
            'patterns': [
                {'match': r'corona', 'brand': 'Corona', 'subcategory': 'Light Beer',
                 'category': 'Beer', 'department': 'Beverages'},
                {'match': r'bud', 'brand': 'Budweiser', 'subcategory': 'Light Beer',
                 'category': 'Beer', 'department': 'Beverages'},
                {'match': r'miller', 'brand': 'Miller', 'subcategory': 'Light Beer',
                 'category': 'Beer', 'department': 'Beverages'},
            ],
            'default': {'brand': 'Unknown', 'subcategory': 'Unknown',
                        'category': 'Unknown', 'department': 'Unknown'},
        }

        pipeline = EntityNormalizationPipeline(fuzzy_threshold=75)
        raw_values = [
            'corona_lt', 'Corona Light', 'CORONA LT 12PK',
            'bud_lt', 'Bud Light', 'BUD LIGHT 24PK',
            'Miller Lite', 'MILLER LITE',
        ]
        return pipeline.run(raw_values, classification_mode='rules', rules=rules)

    def test_lookup_table_creates(self):
        db = self._create_test_db()
        graph = self._build_norm_graph()

        lookup_sql = graph.build_duckdb_lookup(column_name='name')
        db.execute(lookup_sql)

        # Verify lookup table exists
        count = db.execute("SELECT COUNT(*) FROM _norm_lookup_name").fetchone()[0]
        assert count > 0

    def test_join_adds_hierarchy_columns(self):
        db = self._create_test_db()
        graph = self._build_norm_graph()

        # Create lookup table
        lookup_sql = graph.build_duckdb_lookup(column_name='name')
        db.execute(lookup_sql)

        # LEFT JOIN onto data
        db.execute("""
            CREATE OR REPLACE TABLE test_data AS
            SELECT t.*, _lk.product AS norm_name_product,
                   _lk.brand AS norm_name_brand,
                   _lk.category AS norm_name_category
            FROM test_data t
            LEFT JOIN _norm_lookup_name _lk
            ON t.name = _lk.raw_value
        """)

        cols = [c[0] for c in db.execute("DESCRIBE test_data").fetchall()]
        assert 'norm_name_product' in cols
        assert 'norm_name_brand' in cols
        assert 'norm_name_category' in cols

    def test_normalized_values_correct(self):
        db = self._create_test_db()
        graph = self._build_norm_graph()

        lookup_sql = graph.build_duckdb_lookup(column_name='name')
        db.execute(lookup_sql)

        db.execute("""
            CREATE OR REPLACE TABLE test_data AS
            SELECT t.*, _lk.brand AS norm_name_brand
            FROM test_data t
            LEFT JOIN _norm_lookup_name _lk
            ON t.name = _lk.raw_value
        """)

        # Check that corona variants all map to Corona
        corona_brands = db.execute(
            "SELECT DISTINCT norm_name_brand FROM test_data WHERE name LIKE '%orona%' OR name LIKE '%corona%'"
        ).fetchall()
        assert len(corona_brands) == 1
        assert corona_brands[0][0] == 'Corona'

    def test_row_count_preserved(self):
        db = self._create_test_db()
        graph = self._build_norm_graph()

        before = db.execute("SELECT COUNT(*) FROM test_data").fetchone()[0]

        lookup_sql = graph.build_duckdb_lookup(column_name='name')
        db.execute(lookup_sql)

        db.execute("""
            CREATE OR REPLACE TABLE test_data AS
            SELECT t.*, _lk.brand AS norm_name_brand
            FROM test_data t
            LEFT JOIN _norm_lookup_name _lk
            ON t.name = _lk.raw_value
        """)

        after = db.execute("SELECT COUNT(*) FROM test_data").fetchone()[0]
        assert after == before

    def test_multiple_columns_separate_lookup_tables(self):
        """Each discriminator column gets its own lookup table."""
        db = duckdb.connect()
        db.execute("""
            CREATE TABLE multi_data (
                date DATE,
                product VARCHAR,
                store VARCHAR,
                amount DOUBLE
            )
        """)
        db.execute("""
            INSERT INTO multi_data VALUES
                ('2024-01-01', 'Corona Light', 'Store_NYC', 10.0),
                ('2024-01-02', 'Bud Light', 'Store_LA', 20.0)
        """)

        # Build separate graphs for product and store
        graph_product = NormalizationGraph()
        graph_product.add_cluster({
            'canonical': 'Corona Light',
            'members': [{'original': 'Corona Light', 'normalized': 'corona light'}],
            'confidence': 1.0,
        }, {'product': 'Corona Light', 'brand': 'Corona'})

        graph_store = NormalizationGraph(hierarchy_levels=['product', 'region'])
        graph_store.add_cluster({
            'canonical': 'Store NYC',
            'members': [{'original': 'Store_NYC', 'normalized': 'store nyc'}],
            'confidence': 1.0,
        }, {'product': 'Store NYC', 'region': 'Northeast'})

        # Create separate lookup tables
        db.execute(graph_product.build_duckdb_lookup(column_name='product'))
        db.execute(graph_store.build_duckdb_lookup(column_name='store'))

        # Both should exist
        assert db.execute("SELECT COUNT(*) FROM _norm_lookup_product").fetchone()[0] > 0
        assert db.execute("SELECT COUNT(*) FROM _norm_lookup_store").fetchone()[0] > 0
