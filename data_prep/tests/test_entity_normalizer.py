"""Tests for entity normalizer: text normalization, fuzzy clustering, hierarchy."""

import pytest
from data_prep.entity_normalizer import (
    TextNormalizer,
    FuzzyClusterer,
    HierarchyClassifier,
    NormalizationGraph,
    EntityNormalizationPipeline,
)


# -- TextNormalizer ---------------------------------------------------------

class TestTextNormalizer:
    def test_basic_normalization(self):
        result = TextNormalizer.normalize("Corona_Lt")
        assert result['normalized'] == 'corona light'
        assert result['original'] == 'Corona_Lt'

    def test_pack_info_extraction(self):
        result = TextNormalizer.normalize("Corona Light 12pk")
        assert result['pack_info'] == '12pk'
        assert 'pack' not in result['normalized']
        assert result['normalized'] == 'corona light'

    def test_abbreviation_expansion(self):
        result = TextNormalizer.normalize("bud_lt")
        assert result['normalized'] == 'bud light'

    def test_all_caps(self):
        result = TextNormalizer.normalize("CORONA LT 12PK")
        assert result['normalized'] == 'corona light'
        assert result['pack_info'] is not None

    def test_empty_string(self):
        result = TextNormalizer.normalize("")
        assert result['normalized'] == ''

    def test_none_input(self):
        result = TextNormalizer.normalize(None)
        assert result['normalized'] == 'none'

    def test_tokens_produced(self):
        result = TextNormalizer.normalize("Corona Light")
        assert result['tokens'] == ['corona', 'light']

    def test_separator_normalization(self):
        result = TextNormalizer.normalize("coca-cola_zero")
        assert result['normalized'] == 'coca cola zero'


# -- FuzzyClusterer ---------------------------------------------------------

class TestFuzzyClusterer:
    def test_default_threshold_is_80(self):
        clusterer = FuzzyClusterer()
        assert clusterer.threshold == 80

    def test_exact_matches_cluster_together(self):
        clusterer = FuzzyClusterer(threshold=80)
        clusters = clusterer.cluster(["Corona Light", "corona light", "CORONA LIGHT"])
        assert len(clusters) == 1
        assert len(clusters[0]['members']) == 3

    def test_abbreviation_variants_cluster(self):
        clusterer = FuzzyClusterer(threshold=75)
        clusters = clusterer.cluster(["corona_lt", "Corona Light", "CORONA LT 12PK"])
        # All should end up in one cluster because they normalize to "corona light"
        assert len(clusters) == 1

    def test_distinct_entities_separate(self):
        clusterer = FuzzyClusterer(threshold=80)
        clusters = clusterer.cluster(["Corona Light", "Bud Light", "Miller Lite"])
        assert len(clusters) == 3

    def test_canonical_prefers_title_case(self):
        clusterer = FuzzyClusterer(threshold=80)
        clusters = clusterer.cluster(["CORONA LIGHT", "Corona Light", "corona light"])
        assert clusters[0]['canonical'] == "Corona Light"

    def test_canonical_penalizes_all_caps(self):
        clusterer = FuzzyClusterer(threshold=80)
        clusters = clusterer.cluster(["CORONA LT", "Corona Light"])
        assert clusters[0]['canonical'] == "Corona Light"

    def test_canonical_penalizes_pack_info(self):
        clusterer = FuzzyClusterer(threshold=75)
        clusters = clusterer.cluster(["Corona Light 12pk", "Corona Light", "corona_lt"])
        # "Corona Light" (no pack info) should be preferred over "Corona Light 12pk"
        assert clusters[0]['canonical'] == "Corona Light"

    def test_confidence_single_member(self):
        clusterer = FuzzyClusterer(threshold=80)
        clusters = clusterer.cluster(["UniqueItem"])
        assert clusters[0]['confidence'] == 1.0

    def test_confidence_exact_match(self):
        clusterer = FuzzyClusterer(threshold=80)
        clusters = clusterer.cluster(["corona light", "Corona Light"])
        # Same normalized form -> confidence 1.0
        assert clusters[0]['confidence'] == 1.0


# -- HierarchyClassifier ---------------------------------------------------

class TestHierarchyClassifier:
    def test_rule_based_classification(self):
        classifier = HierarchyClassifier()
        rules = {
            'patterns': [
                {'match': r'corona', 'brand': 'Corona', 'subcategory': 'Lager',
                 'category': 'Beer', 'department': 'Beverages'},
            ],
            'default': {'brand': 'Unknown', 'subcategory': 'Unknown',
                        'category': 'Unknown', 'department': 'Unknown'},
        }
        results = classifier.classify_with_rules(["Corona Light"], rules)
        assert len(results) == 1
        assert results[0]['brand'] == 'Corona'
        assert results[0]['product'] == 'Corona Light'

    def test_unmatched_gets_default(self):
        classifier = HierarchyClassifier()
        rules = {
            'patterns': [],
            'default': {'brand': 'Unknown', 'subcategory': 'Unknown',
                        'category': 'Unknown', 'department': 'Unknown'},
        }
        results = classifier.classify_with_rules(["Mystery Item"], rules)
        assert results[0]['brand'] == 'Unknown'

    def test_no_rules_gives_unclassified(self):
        classifier = HierarchyClassifier()
        results = classifier.classify_with_rules(["Test"], rules=None)
        assert results[0]['brand'] == 'Unclassified'

    def test_empty_rules_gives_unclassified(self):
        classifier = HierarchyClassifier()
        results = classifier.classify_with_rules(["Test"], rules={})
        assert results[0]['brand'] == 'Unclassified'

    def test_llm_prompt_contains_entities(self):
        classifier = HierarchyClassifier()
        prompt = classifier.build_llm_prompt(["Corona", "Bud Light"])
        assert "Corona" in prompt
        assert "Bud Light" in prompt

    def test_parse_llm_response(self):
        classifier = HierarchyClassifier()
        response = '[{"product": "Corona", "brand": "Corona"}]'
        results = classifier.parse_llm_response(response)
        assert len(results) == 1
        assert results[0]['product'] == 'Corona'

    def test_parse_llm_response_with_markdown_fences(self):
        classifier = HierarchyClassifier()
        response = '```json\n[{"product": "Corona"}]\n```'
        results = classifier.parse_llm_response(response)
        assert len(results) == 1


# -- NormalizationGraph -----------------------------------------------------

class TestNormalizationGraph:
    def _build_sample_graph(self):
        graph = NormalizationGraph()
        cluster = {
            'canonical': 'Corona Light',
            'members': [
                {'original': 'corona_lt', 'normalized': 'corona light', 'pack_info': None},
                {'original': 'Corona Light 12pk', 'normalized': 'corona light', 'pack_info': '12pk'},
            ],
            'confidence': 0.95,
        }
        classification = {
            'product': 'Corona Light',
            'brand': 'Corona',
            'subcategory': 'Light Beer',
            'category': 'Beer',
            'department': 'Beverages',
        }
        graph.add_cluster(cluster, classification)
        return graph

    def test_normalize_raw_value(self):
        graph = self._build_sample_graph()
        assert graph.normalize('corona_lt') == 'Corona Light'

    def test_normalize_unknown_value(self):
        graph = self._build_sample_graph()
        assert graph.normalize('unknown_product') is None

    def test_get_hierarchy(self):
        graph = self._build_sample_graph()
        h = graph.get_hierarchy('corona_lt')
        assert h['product'] == 'Corona Light'
        assert h['brand'] == 'Corona'
        assert h['category'] == 'Beer'
        assert h['department'] == 'Beverages'

    def test_get_all_at_level(self):
        graph = self._build_sample_graph()
        brands = graph.get_all_at_level('brand')
        assert 'Corona' in brands

    def test_duckdb_lookup_sql(self):
        graph = self._build_sample_graph()
        sql = graph.build_duckdb_lookup()
        assert 'CREATE OR REPLACE TABLE' in sql
        assert 'corona_lt' in sql

    def test_duckdb_lookup_with_column_name(self):
        graph = self._build_sample_graph()
        sql = graph.build_duckdb_lookup(column_name='name')
        assert '_norm_lookup_name' in sql

    def test_summary(self):
        graph = self._build_sample_graph()
        summary = graph.get_summary()
        assert summary['raw_values'] == 2
        assert summary['canonical_entities'] == 1

    def test_save_and_load(self, tmp_path):
        graph = self._build_sample_graph()
        path = str(tmp_path / 'test_norm.json')
        graph.save(path)

        loaded = NormalizationGraph.load(path)
        assert loaded.normalize('corona_lt') == 'Corona Light'
        h = loaded.get_hierarchy('corona_lt')
        assert h['brand'] == 'Corona'


# -- EntityNormalizationPipeline --------------------------------------------

class TestEntityNormalizationPipeline:
    def test_full_pipeline_with_rules(self):
        raw_values = [
            "corona_lt", "Corona Light", "Corona Light 12pk",
            "bud_lt", "Bud Light", "BUD LIGHT 24PK",
        ]
        rules = {
            'patterns': [
                {'match': r'corona', 'brand': 'Corona', 'subcategory': 'Light Beer',
                 'category': 'Beer', 'department': 'Beverages'},
                {'match': r'bud', 'brand': 'Budweiser', 'subcategory': 'Light Beer',
                 'category': 'Beer', 'department': 'Beverages'},
            ],
            'default': {'brand': 'Unknown', 'subcategory': 'Unknown',
                        'category': 'Unknown', 'department': 'Unknown'},
        }

        pipeline = EntityNormalizationPipeline(fuzzy_threshold=80)
        graph = pipeline.run(raw_values, classification_mode="rules", rules=rules)

        # Should cluster into 2 groups (Corona + Bud)
        summary = graph.get_summary()
        assert summary['canonical_entities'] == 2

        # Lookups should work
        assert graph.normalize('corona_lt') is not None
        assert graph.normalize('bud_lt') is not None

    def test_pipeline_compression(self):
        """16 raw values should compress to fewer canonical entities."""
        raw_values = [
            "corona_lt", "Corona Light", "CORONA LT 12PK", "Corona Light 12pk",
            "corona extra", "Corona Extra 6pk", "CORONA EXTRA", "corona extra",
            "bud_lt", "Bud Light", "BUD LIGHT 24PK", "Bud Lt",
            "miller_lt", "Miller Lite", "MILLER LITE", "Miller Lt 12pk",
        ]

        pipeline = EntityNormalizationPipeline(fuzzy_threshold=80)
        graph = pipeline.run(raw_values, classification_mode="rules")

        summary = graph.get_summary()
        # Should be significantly fewer canonical entities than raw values
        assert summary['canonical_entities'] < len(set(raw_values))
        # At least 3 distinct groups: Corona Light, Corona Extra, Bud Light, Miller
        assert summary['canonical_entities'] <= 6
