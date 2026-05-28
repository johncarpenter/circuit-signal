"""
Entity Normalizer & Hierarchy Classifier
=========================================

Normalizes messy discriminator values into canonical entities, then classifies
them into a hierarchical taxonomy (Product -> Brand -> Category -> Department).

Architecture:
    Phase 1: CLUSTERING  — fuzzy string matching groups raw values
    Phase 2: CLASSIFICATION — rules or LLM assigns hierarchy positions
    Phase 3: GRAPH — builds a NormalizationGraph for Layer 0 ingestion

Dependencies: rapidfuzz, networkx
Optional: anthropic (for LLM classification)
"""

import json
import logging
import re
import networkx as nx
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("data-prep.entity-normalizer")


# =============================================================================
# 1. TEXT NORMALIZATION
# =============================================================================

class TextNormalizer:
    """
    Normalizes raw product/entity names into a consistent format for comparison.

    Handles: case, separators, abbreviations, pack sizes, whitespace.
    """

    ABBREVIATIONS = {
        'lt': 'light',
        'lgt': 'light',
        'lte': 'light',
        'drk': 'dark',
        'org': 'organic',
        'nat': 'natural',
        'orig': 'original',
        'choc': 'chocolate',
        'van': 'vanilla',
        'strw': 'strawberry',
        'blueb': 'blueberry',
        'sm': 'small',
        'md': 'medium',
        'lg': 'large',
        'xl': 'extra large',
        'oz': 'oz',
        'pk': 'pack',
        'ct': 'count',
        'btl': 'bottle',
        'cn': 'can',
        'cs': 'case',
        'bx': 'box',
        'bg': 'bag',
    }

    PACK_PATTERNS = [
        r'(\d+)\s*(?:pk|pack|ct|count)\b',
        r'(\d+\.?\d*)\s*(?:oz|fl\.?\s*oz)\b',
        r'(\d+)\s*(?:ml|l|liter|litre)\b',
        r'(\d+)\s*(?:gal|gallon)\b',
    ]

    @staticmethod
    def normalize(text: str) -> dict:
        """
        Normalize a raw value into components.

        Returns:
            {
                'original': 'Corona_Lt 12pk',
                'normalized': 'corona light',
                'pack_info': '12 pack',
                'tokens': ['corona', 'light'],
            }
        """
        if not text or not isinstance(text, str):
            return {'original': str(text), 'normalized': str(text).lower().strip(),
                    'pack_info': None, 'tokens': []}

        original = text
        t = text.strip()

        # Lowercase
        t = t.lower()

        # Replace separators with spaces
        t = re.sub(r'[_\-/\\|]+', ' ', t)

        # Extract pack info before removing numbers
        pack_info = None
        for pattern in TextNormalizer.PACK_PATTERNS:
            match = re.search(pattern, t, re.IGNORECASE)
            if match:
                pack_info = match.group(0).strip()
                t = t[:match.start()] + t[match.end():]
                break

        # Remove standalone numbers (but keep numbers attached to words like "7up")
        t = re.sub(r'\b\d+\b', '', t)

        # Expand abbreviations
        tokens = t.split()
        expanded = []
        for tok in tokens:
            tok = tok.strip('.,;:!?()')
            if not tok:
                continue
            if tok in TextNormalizer.ABBREVIATIONS:
                expanded.append(TextNormalizer.ABBREVIATIONS[tok])
            else:
                expanded.append(tok)

        normalized = ' '.join(expanded)
        # Collapse multiple spaces
        normalized = re.sub(r'\s+', ' ', normalized).strip()

        return {
            'original': original,
            'normalized': normalized,
            'pack_info': pack_info,
            'tokens': expanded,
        }


# =============================================================================
# 2. FUZZY CLUSTERING
# =============================================================================

class FuzzyClusterer:
    """
    Groups similar normalized values into clusters using fuzzy string matching.

    Uses token-based similarity (token_sort_ratio) which handles reordering
    and partial matches.
    """

    def __init__(self, threshold: int = 80):
        self.threshold = threshold
        self._has_rapidfuzz = False
        try:
            from rapidfuzz import fuzz, process
            self._fuzz = fuzz
            self._process = process
            self._has_rapidfuzz = True
        except ImportError:
            pass

    def cluster(self, values: list[str]) -> list[dict]:
        """
        Cluster a list of raw values into groups of similar entities.

        Returns list of clusters:
            [
                {
                    'canonical': 'Corona Light',
                    'members': [...],
                    'confidence': 0.92,
                },
            ]
        """
        # Step 1: Normalize all values
        normalized = [TextNormalizer.normalize(v) for v in values]

        # Step 2: Group exact normalized matches first (cheap)
        exact_groups = defaultdict(list)
        for norm in normalized:
            exact_groups[norm['normalized']].append(norm)

        # Step 3: Fuzzy match between the group representatives
        group_keys = list(exact_groups.keys())
        clusters = []
        used = set()

        for i, key_a in enumerate(group_keys):
            if key_a in used:
                continue

            cluster_members = list(exact_groups[key_a])
            used.add(key_a)

            for key_b in group_keys[i + 1:]:
                if key_b in used:
                    continue

                score = self._similarity(key_a, key_b)
                if score >= self.threshold:
                    cluster_members.extend(exact_groups[key_b])
                    used.add(key_b)

            canonical = self._pick_canonical(cluster_members)
            confidence = self._cluster_confidence(cluster_members)

            clusters.append({
                'canonical': canonical,
                'members': cluster_members,
                'confidence': confidence,
            })

        return clusters

    def _similarity(self, a: str, b: str) -> float:
        """Compute similarity score between two normalized strings."""
        if self._has_rapidfuzz:
            return self._fuzz.token_sort_ratio(a, b)
        else:
            tokens_a = set(a.split())
            tokens_b = set(b.split())
            if not tokens_a or not tokens_b:
                return 0
            intersection = tokens_a & tokens_b
            union = tokens_a | tokens_b
            return (len(intersection) / len(union)) * 100

    def _pick_canonical(self, members: list[dict]) -> str:
        """
        Pick the best canonical name from cluster members.

        Prefers: longer names (more descriptive), title case, no pack info.
        Penalizes: all-caps, underscores, pack info in name.
        """
        originals = [m['original'] for m in members]

        scored = []
        for orig in originals:
            score = 0
            # Prefer title case or proper capitalization
            if orig[0].isupper() and not orig.isupper():
                score += 10
            # Prefer longer (more descriptive) but not too long
            score += min(len(orig), 30)
            # Penalize all-caps (increased penalty)
            if orig.isupper():
                score -= 15
            # Penalize underscores/separators
            score -= orig.count('_') * 3
            # Penalize pack info in canonical names
            for pattern in TextNormalizer.PACK_PATTERNS:
                if re.search(pattern, orig, re.IGNORECASE):
                    score -= 10
                    break
            scored.append((score, orig))

        scored.sort(reverse=True)
        return scored[0][1]

    def _cluster_confidence(self, members: list[dict]) -> float:
        """Compute confidence that cluster members are truly the same entity."""
        if len(members) <= 1:
            return 1.0

        norms = list(set(m['normalized'] for m in members))
        if len(norms) == 1:
            return 1.0

        scores = []
        for i, a in enumerate(norms):
            for b in norms[i + 1:]:
                scores.append(self._similarity(a, b))

        return round(sum(scores) / len(scores) / 100, 3) if scores else 1.0


# =============================================================================
# 3. HIERARCHY CLASSIFIER
# =============================================================================

class HierarchyClassifier:
    """
    Classifies canonical entities into a hierarchical taxonomy.

    Two modes:
        1. Rule-based: Uses configurable taxonomy rules (fast, no LLM cost)
        2. LLM-assisted: Sends entities to an LLM for classification (accurate)
    """

    DEFAULT_LEVELS = ['product', 'brand', 'subcategory', 'category', 'department']

    def __init__(self, levels: list[str] = None):
        self.levels = levels or self.DEFAULT_LEVELS

    def classify_with_rules(self, entities: list[str],
                            rules: dict = None) -> list[dict]:
        """
        Classify entities using predefined rules.

        Rules format:
            {
                'patterns': [
                    {'match': r'corona|modelo', 'brand': 'Corona', ...},
                ],
                'default': {'brand': 'Unknown', ...},
            }
        """
        if not rules or 'default' not in rules:
            default = {l: 'Unclassified' for l in self.levels[1:]}
            if rules is None:
                rules = {'patterns': [], 'default': default}
            else:
                rules.setdefault('default', default)
                rules.setdefault('patterns', [])

        results = []
        for entity in entities:
            classification = {'product': entity}
            matched = False

            for rule in rules.get('patterns', []):
                if re.search(rule['match'], entity, re.IGNORECASE):
                    for level in self.levels[1:]:
                        classification[level] = rule.get(level, rules['default'].get(level, 'Unknown'))
                    matched = True
                    break

            if not matched:
                for level in self.levels[1:]:
                    classification[level] = rules['default'].get(level, 'Unclassified')

            results.append(classification)

        return results

    def build_llm_prompt(self, entities: list[str],
                         context: str = "retail product catalog",
                         existing_hierarchy: dict = None) -> str:
        """Build a prompt for LLM-assisted classification."""
        levels_desc = ' -> '.join(self.levels)

        existing_ctx = ""
        if existing_hierarchy:
            existing_ctx = f"""
Here is the existing hierarchy that has already been established. Place new entities
into this structure where they fit, and create new branches only when necessary:

{json.dumps(existing_hierarchy, indent=2)}
"""

        prompt = f"""You are classifying entities from a {context} into a hierarchy.

The hierarchy levels are (most specific -> most general): {levels_desc}

{existing_ctx}

Classify each of the following entities. Return a JSON array where each element has
a key for each hierarchy level.

Entities to classify:
{json.dumps(entities, indent=2)}

Rules:
- Every entity must be classified at all levels
- Use consistent naming across entities
- If uncertain, use your best judgment based on common retail categorization
- The product level should be the cleaned/canonical entity name

Return ONLY valid JSON, no other text. Example format:
[
  {{"product": "Corona Light", "brand": "Corona", "subcategory": "Light Beer", "category": "Beer", "department": "Beverages"}},
  {{"product": "Tide Pods", "brand": "Tide", "subcategory": "Laundry Detergent", "category": "Laundry", "department": "Household"}}
]"""
        return prompt

    def parse_llm_response(self, response_text: str) -> list[dict]:
        """Parse LLM classification response."""
        text = response_text.strip()
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        try:
            results = json.loads(text)
            if isinstance(results, list):
                return results
        except json.JSONDecodeError:
            pass

        return []


# =============================================================================
# 4. NORMALIZATION GRAPH
# =============================================================================

class NormalizationGraph:
    """
    Stores the complete normalization mapping as a graph.

    Graph structure:
        RAW_VALUE --(NORMALIZES_TO)--> CANONICAL
        CANONICAL --(CLASSIFIED_AS)--> BRAND --(BELONGS_TO)--> CATEGORY --> DEPARTMENT
    """

    def __init__(self, hierarchy_levels: list[str] = None):
        self.graph = nx.DiGraph()
        self.levels = hierarchy_levels or HierarchyClassifier.DEFAULT_LEVELS
        self._raw_to_canonical = {}

    def add_cluster(self, cluster: dict, classification: dict = None):
        """Add a fuzzy cluster and its classification to the graph."""
        canonical = cluster['canonical']
        canonical_node = f"canonical:{canonical}"

        self.graph.add_node(canonical_node, node_type="CANONICAL",
                            value=canonical, confidence=cluster['confidence'])

        for member in cluster['members']:
            raw = member['original']
            raw_node = f"raw:{raw}"
            self.graph.add_node(raw_node, node_type="RAW_VALUE",
                                value=raw, normalized=member['normalized'],
                                pack_info=member.get('pack_info'))
            self.graph.add_edge(raw_node, canonical_node, edge_type="NORMALIZES_TO")
            self._raw_to_canonical[raw] = canonical
            self._raw_to_canonical[member['normalized']] = canonical

        if classification:
            prev_node = canonical_node
            for level in self.levels[1:]:
                level_value = classification.get(level)
                if not level_value:
                    continue

                level_node = f"{level}:{level_value}"
                if not self.graph.has_node(level_node):
                    self.graph.add_node(level_node, node_type="HIERARCHY",
                                        level=level, value=level_value)

                self.graph.add_edge(prev_node, level_node, edge_type="BELONGS_TO",
                                    from_level=self.levels[self.levels.index(level) - 1],
                                    to_level=level)
                prev_node = level_node

    def normalize(self, raw_value: str) -> Optional[str]:
        """Look up the canonical form of a raw value."""
        if raw_value in self._raw_to_canonical:
            return self._raw_to_canonical[raw_value]

        norm = TextNormalizer.normalize(raw_value)
        if norm['normalized'] in self._raw_to_canonical:
            return self._raw_to_canonical[norm['normalized']]

        return None

    def get_hierarchy(self, raw_value: str) -> Optional[dict]:
        """Get the full hierarchy for a raw value."""
        canonical = self.normalize(raw_value)
        if not canonical:
            return None

        canonical_node = f"canonical:{canonical}"
        if not self.graph.has_node(canonical_node):
            return None

        result = {'product': canonical}

        current = canonical_node
        for level in self.levels[1:]:
            found = False
            for _, target, data in self.graph.edges(current, data=True):
                if data.get('edge_type') == 'BELONGS_TO' and data.get('to_level') == level:
                    result[level] = self.graph.nodes[target]['value']
                    current = target
                    found = True
                    break
            if not found:
                break

        return result

    def get_all_at_level(self, level: str) -> list[str]:
        """Get all distinct values at a hierarchy level."""
        values = []
        for node_id, data in self.graph.nodes(data=True):
            if data.get('node_type') == 'HIERARCHY' and data.get('level') == level:
                values.append(data['value'])
        return sorted(set(values))

    def get_children(self, level: str, value: str) -> list[dict]:
        """Get all children of a hierarchy node."""
        node_id = f"{level}:{value}"
        if not self.graph.has_node(node_id):
            return []

        children = []
        for source, _, data in self.graph.in_edges(node_id, data=True):
            if data.get('edge_type') == 'BELONGS_TO':
                source_data = self.graph.nodes[source]
                children.append({
                    'value': source_data['value'],
                    'level': data.get('from_level'),
                    'node_id': source,
                })
        return children

    def build_duckdb_lookup(self, column_name: str = None) -> str:
        """
        Generate DuckDB SQL that creates a normalization lookup table.

        Args:
            column_name: If provided, the lookup table is named
                         _norm_lookup_{column_name} instead of _normalization_lookup.
        """
        table_name = f"_norm_lookup_{column_name}" if column_name else "_normalization_lookup"

        rows = []
        for raw, canonical in self._raw_to_canonical.items():
            hierarchy = self.get_hierarchy(raw)
            if hierarchy:
                escaped = {k: v.replace("'", "''") for k, v in hierarchy.items()}
                cols = ", ".join([f"'{escaped.get(l, '')}'" for l in self.levels])
                rows.append(f"  ('{raw.replace(chr(39), chr(39)+chr(39))}', {cols})")

        if not rows:
            return "-- No normalization mappings"

        col_names = ", ".join(["raw_value"] + list(self.levels))
        values = ",\n".join(rows)

        return f"""CREATE OR REPLACE TABLE {table_name} AS
SELECT
    col0 AS raw_value,
    {', '.join(f'col{i+1} AS {l}' for i, l in enumerate(self.levels))}
FROM (VALUES
{values}
);"""

    def get_summary(self) -> dict:
        """Summary for display or LLM context."""
        raw_count = sum(1 for _, d in self.graph.nodes(data=True) if d.get('node_type') == 'RAW_VALUE')
        canonical_count = sum(1 for _, d in self.graph.nodes(data=True) if d.get('node_type') == 'CANONICAL')
        hierarchy_counts = defaultdict(int)
        for _, d in self.graph.nodes(data=True):
            if d.get('node_type') == 'HIERARCHY':
                hierarchy_counts[d['level']] += 1

        return {
            'raw_values': raw_count,
            'canonical_entities': canonical_count,
            'hierarchy_levels': dict(hierarchy_counts),
            'compression_ratio': f"{raw_count} -> {canonical_count}" if canonical_count else "N/A",
        }

    def save(self, path: str):
        """Serialize to JSON."""
        from networkx.readwrite import json_graph
        data = {
            'version': '1.0',
            'levels': self.levels,
            'graph': json_graph.node_link_data(self.graph),
            'raw_to_canonical': self._raw_to_canonical,
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        logger.info("Normalization graph saved: %s", path)

    @staticmethod
    def load(path: str) -> 'NormalizationGraph':
        """Deserialize from JSON."""
        from networkx.readwrite import json_graph
        with open(path, 'r') as f:
            data = json.load(f)
        ng = NormalizationGraph(data.get('levels'))
        ng.graph = json_graph.node_link_graph(data['graph'], directed=True)
        ng._raw_to_canonical = data.get('raw_to_canonical', {})
        return ng

    def print_tree(self):
        """Print the hierarchy as an indented tree."""
        top_level = self.levels[-1]
        roots = self.get_all_at_level(top_level)

        for root in roots:
            self._print_node(top_level, root, indent=0)

    def _print_node(self, level, value, indent):
        prefix = "  " * indent + ("└── " if indent > 0 else "")
        logger.info("%s[%s] %s", prefix, level, value)

        children = self.get_children(level, value)
        for child in sorted(children, key=lambda c: c['value']):
            if child['level'] in self.levels:
                self._print_node(child['level'], child['value'], indent + 1)


# =============================================================================
# 5. PIPELINE: Full normalization flow
# =============================================================================

class EntityNormalizationPipeline:
    """
    End-to-end pipeline: raw values -> clusters -> classification -> graph.

    Usage:
        pipeline = EntityNormalizationPipeline()
        graph = pipeline.run(
            raw_values=["corona_lt", "Corona Light 12pk", "BUD LIGHT", ...],
            classification_mode="rules",
            rules={...},
        )
    """

    def __init__(self, fuzzy_threshold: int = 80,
                 hierarchy_levels: list[str] = None):
        self.clusterer = FuzzyClusterer(threshold=fuzzy_threshold)
        self.classifier = HierarchyClassifier(levels=hierarchy_levels)
        self.levels = hierarchy_levels or HierarchyClassifier.DEFAULT_LEVELS

    def run(self, raw_values: list[str],
            classification_mode: str = "rules",
            rules: dict = None,
            llm_classify_fn=None,
            context: str = "retail product catalog") -> NormalizationGraph:
        """
        Run the full normalization pipeline.

        Args:
            raw_values: List of raw discriminator values to normalize
            classification_mode: "rules" or "llm"
            rules: Rule config for rules mode
            llm_classify_fn: Function(prompt) -> JSON string (for llm mode)
            context: Business context description for LLM

        Returns:
            NormalizationGraph with all mappings
        """
        # Deduplicate inputs
        unique_values = sorted(set(raw_values))
        logger.info("Input: %d values (%d unique)", len(raw_values), len(unique_values))

        # Phase 1: Fuzzy clustering
        logger.info("Phase 1: Fuzzy Clustering (threshold=%d)", self.clusterer.threshold)
        clusters = self.clusterer.cluster(unique_values)
        logger.info("Clustered %d values -> %d canonical entities", len(unique_values), len(clusters))
        for c in clusters:
            members = [m['original'] for m in c['members']]
            logger.debug("  '%s' <- %s (confidence: %s)", c['canonical'], members, c['confidence'])

        # Phase 2: Classification
        canonicals = [c['canonical'] for c in clusters]
        logger.info("Phase 2: Hierarchy Classification (%s)", classification_mode)

        if classification_mode == "rules":
            classifications = self.classifier.classify_with_rules(canonicals, rules)
        elif classification_mode == "llm":
            if llm_classify_fn is None:
                logger.warning("No LLM function provided, falling back to rules")
                classifications = self.classifier.classify_with_rules(canonicals, rules)
            else:
                prompt = self.classifier.build_llm_prompt(canonicals, context)
                logger.info("Sending %d entities to LLM for classification...", len(canonicals))
                response = llm_classify_fn(prompt)
                classifications = self.classifier.parse_llm_response(response)
                if not classifications:
                    logger.warning("LLM response parse failed, falling back to rules")
                    classifications = self.classifier.classify_with_rules(canonicals, rules)
        else:
            raise ValueError(f"Unknown classification mode: {classification_mode}")

        for c in classifications:
            hierarchy_str = " -> ".join([f"{l}={c.get(l, '?')}" for l in self.levels])
            logger.debug("  %s", hierarchy_str)

        # Phase 3: Build graph
        logger.info("Phase 3: Building Normalization Graph")
        graph = NormalizationGraph(self.levels)
        for cluster, classification in zip(clusters, classifications):
            graph.add_cluster(cluster, classification)

        summary = graph.get_summary()
        logger.info(
            "Graph built: %d raw -> %d canonical, hierarchy: %s",
            summary['raw_values'], summary['canonical_entities'],
            summary['hierarchy_levels'],
        )

        return graph
