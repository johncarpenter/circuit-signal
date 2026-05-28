"""
TDV Profiler & Discriminator Graph Network
==========================================
Scans a data lake and classifies datasets by Time-Discriminator-Value (TDV) pattern.
Builds a graph network of discriminator relationships.
"""

import duckdb
import networkx as nx
import numpy as np
import pandas as pd
import json
import hashlib
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
from pathlib import Path
from collections import defaultdict


class ColumnRole(Enum):
    TIME = "time"
    DISCRIMINATOR = "discriminator"
    VALUE = "value"
    IDENTIFIER = "identifier"
    UNKNOWN = "unknown"


@dataclass
class ColumnProfile:
    name: str
    role: ColumnRole
    dtype: str
    cardinality: int
    null_pct: float
    sample_values: list
    time_grain: Optional[str] = None
    time_range: Optional[tuple] = None
    cardinality_ratio: Optional[float] = None
    distinct_values: Optional[list] = None
    is_continuous: Optional[bool] = None
    value_stats: Optional[dict] = None

    def to_dict(self):
        d = asdict(self)
        d['role'] = self.role.value
        return d


@dataclass
class DatasetProfile:
    dataset_id: str
    source_path: str
    row_count: int
    columns: list[ColumnProfile]
    is_temporal: bool = False
    primary_time_col: Optional[str] = None
    discriminators: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)

    @property
    def tdv_signature(self) -> str:
        t = sum(1 for c in self.columns if c.role == ColumnRole.TIME)
        d = sum(1 for c in self.columns if c.role == ColumnRole.DISCRIMINATOR)
        v = sum(1 for c in self.columns if c.role == ColumnRole.VALUE)
        return f"T{t}-D{d}-V{v}"


class TDVProfiler:
    DISCRIMINATOR_MAX_CARDINALITY_RATIO = 0.05
    DISCRIMINATOR_MAX_ABSOLUTE = 500
    IDENTIFIER_MIN_CARDINALITY_RATIO = 0.50
    VALUE_MIN_VARIANCE_COEFFICIENT = 0.01

    def __init__(self, db=None):
        self.db = db or duckdb.connect()

    def profile_dataset(self, source_path: str, dataset_id: str = None) -> DatasetProfile:
        if dataset_id is None:
            dataset_id = hashlib.md5(source_path.encode()).hexdigest()[:12]

        safe_id = dataset_id.replace("-", "_").replace(" ", "_")
        view_name = f'"_profile_{safe_id}"'
        ext = Path(source_path).suffix.lower()

        if ext == '.csv':
            self.db.execute(f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM read_csv_auto('{source_path}')")
        elif ext in ('.parquet', '.pq'):
            self.db.execute(f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM read_parquet('{source_path}')")
        else:
            raise ValueError(f"Unsupported: {ext}")

        row_count = self.db.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()[0]
        col_info = self.db.execute(f"DESCRIBE {view_name}").fetchall()

        columns = []
        for col_name, col_type, *_ in col_info:
            profile = self._profile_column(view_name, col_name, col_type, row_count)
            columns.append(profile)

        ds = DatasetProfile(dataset_id=dataset_id, source_path=source_path,
                            row_count=row_count, columns=columns)

        time_cols = [c for c in columns if c.role == ColumnRole.TIME]
        value_cols = [c for c in columns if c.role == ColumnRole.VALUE]
        disc_cols = [c for c in columns if c.role == ColumnRole.DISCRIMINATOR]

        ds.is_temporal = len(time_cols) > 0 and len(value_cols) > 0
        ds.primary_time_col = time_cols[0].name if time_cols else None
        ds.discriminators = [c.name for c in disc_cols]
        ds.values = [c.name for c in value_cols]

        self.db.execute(f"DROP VIEW IF EXISTS {view_name}")
        return ds

    def _profile_column(self, view, col_name, col_type, total_rows):
        safe_col = f'"{col_name}"'
        stats = self.db.execute(f"""
            SELECT COUNT(DISTINCT {safe_col}), COUNT(*) - COUNT({safe_col}), COUNT(*)
            FROM {view}
        """).fetchone()
        cardinality, null_count, total = stats
        null_pct = null_count / max(total, 1)
        cardinality_ratio = cardinality / max(total_rows, 1)

        try:
            samples = [str(s[0]) for s in self.db.execute(
                f"SELECT DISTINCT {safe_col} FROM {view} WHERE {safe_col} IS NOT NULL LIMIT 10"
            ).fetchall()]
        except:
            samples = []

        # TIME detection
        if self._is_time_column(col_type, samples):
            grain, time_range = self._detect_time_props(view, safe_col, col_type)
            return ColumnProfile(name=col_name, role=ColumnRole.TIME, dtype=col_type,
                                 cardinality=cardinality, null_pct=null_pct,
                                 sample_values=samples, time_grain=grain, time_range=time_range)

        # DISCRIMINATOR detection
        if self._is_discriminator(col_type, cardinality, cardinality_ratio):
            distinct_vals = samples
            if cardinality <= self.DISCRIMINATOR_MAX_ABSOLUTE:
                try:
                    distinct_vals = [str(v[0]) for v in self.db.execute(
                        f"SELECT DISTINCT {safe_col} FROM {view} WHERE {safe_col} IS NOT NULL ORDER BY {safe_col}"
                    ).fetchall()]
                except:
                    pass
            return ColumnProfile(name=col_name, role=ColumnRole.DISCRIMINATOR, dtype=col_type,
                                 cardinality=cardinality, null_pct=null_pct,
                                 sample_values=samples, cardinality_ratio=cardinality_ratio,
                                 distinct_values=distinct_vals)

        # VALUE detection
        if self._is_value_column(view, safe_col, col_type, cardinality_ratio):
            stats_dict = self._get_value_stats(view, safe_col)
            return ColumnProfile(name=col_name, role=ColumnRole.VALUE, dtype=col_type,
                                 cardinality=cardinality, null_pct=null_pct,
                                 sample_values=samples, is_continuous=cardinality_ratio > 0.01,
                                 value_stats=stats_dict)

        # IDENTIFIER
        if cardinality_ratio > self.IDENTIFIER_MIN_CARDINALITY_RATIO:
            return ColumnProfile(name=col_name, role=ColumnRole.IDENTIFIER, dtype=col_type,
                                 cardinality=cardinality, null_pct=null_pct,
                                 sample_values=samples, cardinality_ratio=cardinality_ratio)

        return ColumnProfile(name=col_name, role=ColumnRole.UNKNOWN, dtype=col_type,
                             cardinality=cardinality, null_pct=null_pct,
                             sample_values=samples, cardinality_ratio=cardinality_ratio)

    def _is_time_column(self, col_type, samples):
        col_type_lower = col_type.lower()
        if any(t in col_type_lower for t in ['date', 'time', 'timestamp']):
            return True
        if 'varchar' in col_type_lower or 'text' in col_type_lower:
            if not samples:
                return False
            success = sum(1 for s in samples[:5] if self._try_parse_date(s))
            return success / min(len(samples), 5) > 0.8
        # For integers, require YYYYMMDD range specifically (not small ints like pack_size)
        if any(t in col_type_lower for t in ['int', 'bigint']):
            for s in samples[:5]:
                try:
                    val = int(s)
                    if 19000101 <= val <= 20991231:
                        return True
                except:
                    pass
        return False

    def _try_parse_date(self, s):
        try:
            pd.to_datetime(s)
            return True
        except:
            return False

    def _detect_time_props(self, view, safe_col, col_type):
        try:
            col_type_lower = col_type.lower()
            cast = safe_col if any(t in col_type_lower for t in ['date', 'time', 'timestamp']) else f"TRY_CAST({safe_col} AS TIMESTAMP)"

            result = self.db.execute(f"SELECT MIN({cast}), MAX({cast}) FROM {view} WHERE {cast} IS NOT NULL").fetchone()
            time_range = (str(result[0]), str(result[1]))

            grain_r = self.db.execute(f"""
                WITH diffs AS (
                    SELECT EXTRACT(EPOCH FROM ({cast} - LAG({cast}) OVER (ORDER BY {cast}))) as d
                    FROM {view} WHERE {cast} IS NOT NULL
                )
                SELECT MEDIAN(d) FROM diffs WHERE d > 0
            """).fetchone()

            median_s = grain_r[0] if grain_r[0] else None
            if median_s is None: grain = "unknown"
            elif median_s < 3600: grain = "hourly"
            elif median_s < 86400: grain = "daily"
            elif median_s < 604800: grain = "weekly"
            elif median_s < 2592000: grain = "monthly"
            else: grain = "quarterly_or_longer"

            return grain, time_range
        except:
            return None, None

    def _is_discriminator(self, col_type, cardinality, ratio):
        if cardinality < 2:
            return False
        if cardinality > self.DISCRIMINATOR_MAX_ABSOLUTE:
            return False
        col_lower = col_type.lower()
        is_string = any(t in col_lower for t in ['varchar', 'text', 'enum', 'bool'])
        # String columns with low absolute cardinality are almost always discriminators
        # (handles small datasets where ratio can be misleadingly high)
        if is_string and cardinality <= 50:
            return True
        # Boolean-like columns
        if cardinality <= 5:
            return True
        # For larger cardinalities, use ratio check
        if ratio > self.DISCRIMINATOR_MAX_CARDINALITY_RATIO:
            return False
        if is_string:
            return True
        # Integer category codes: very low cardinality only
        if any(t in col_lower for t in ['int', 'smallint', 'tinyint']) and cardinality < 10 and ratio < 0.01:
            return True
        return False

    def _is_value_column(self, view, safe_col, col_type, cardinality_ratio):
        if not any(t in col_type.lower() for t in ['int', 'bigint', 'float', 'double', 'decimal', 'numeric', 'real']):
            return False
        # Float/double types are almost always measurements, never IDs
        is_float = any(t in col_type.lower() for t in ['float', 'double', 'decimal', 'numeric', 'real'])
        if is_float:
            return True  # floats are values, not identifiers
        # For integers, high cardinality might mean it's an ID
        if cardinality_ratio > self.IDENTIFIER_MIN_CARDINALITY_RATIO:
            return False
        try:
            cv = self.db.execute(f"""
                SELECT STDDEV(CAST({safe_col} AS DOUBLE)) / NULLIF(ABS(AVG(CAST({safe_col} AS DOUBLE))), 0)
                FROM {view} WHERE {safe_col} IS NOT NULL
            """).fetchone()[0]
            return (cv or 0) > self.VALUE_MIN_VARIANCE_COEFFICIENT
        except:
            return True

    def _get_value_stats(self, view, safe_col):
        try:
            s = self.db.execute(f"""
                SELECT AVG(CAST({safe_col} AS DOUBLE)), STDDEV(CAST({safe_col} AS DOUBLE)),
                       MIN(CAST({safe_col} AS DOUBLE)), MAX(CAST({safe_col} AS DOUBLE)),
                       MEDIAN(CAST({safe_col} AS DOUBLE))
                FROM {view} WHERE {safe_col} IS NOT NULL
            """).fetchone()
            return {k: round(v, 4) if v else None for k, v in
                    zip(['mean', 'std', 'min', 'max', 'median'], s)}
        except:
            return {}


class DiscriminatorGraph:
    def __init__(self):
        self.graph = nx.DiGraph()
        self._dataset_profiles = {}

    def add_dataset(self, profile, db, max_cooccurrence_pairs=5000):
        self._dataset_profiles[profile.dataset_id] = profile

        self.graph.add_node(f"ds:{profile.dataset_id}", node_type="DATASET",
                            source_path=profile.source_path, row_count=profile.row_count,
                            is_temporal=profile.is_temporal, tdv_signature=profile.tdv_signature,
                            primary_time_col=profile.primary_time_col,
                            time_grain=next((c.time_grain for c in profile.columns if c.role == ColumnRole.TIME), None))

        for disc_col in profile.columns:
            if disc_col.role != ColumnRole.DISCRIMINATOR:
                continue
            disc_id = f"disc:{disc_col.name}"
            if not self.graph.has_node(disc_id):
                self.graph.add_node(disc_id, node_type="DISCRIMINATOR",
                                    column_name=disc_col.name, datasets=[])
            self.graph.nodes[disc_id]['datasets'] = list(set(
                self.graph.nodes[disc_id].get('datasets', []) + [profile.dataset_id]))

            self.graph.add_edge(f"ds:{profile.dataset_id}", disc_id,
                                edge_type="DATASET_HAS_DISCRIMINATOR")

            if disc_col.distinct_values:
                for val in disc_col.distinct_values:
                    val_id = f"val:{disc_col.name}={val}"
                    if not self.graph.has_node(val_id):
                        self.graph.add_node(val_id, node_type="VALUE",
                                            discriminator=disc_col.name, value=val)
                    self.graph.add_edge(disc_id, val_id, edge_type="DISCRIMINATOR_HAS_VALUE")

        for val_col in profile.columns:
            if val_col.role == ColumnRole.VALUE:
                vid = f"valcol:{val_col.name}"
                if not self.graph.has_node(vid):
                    self.graph.add_node(vid, node_type="VALUE_COLUMN",
                                        column_name=val_col.name, stats=val_col.value_stats)
                self.graph.add_edge(f"ds:{profile.dataset_id}", vid,
                                    edge_type="DATASET_HAS_VALUE_COL")

        if len(profile.discriminators) >= 2:
            self._discover_cooccurrence(profile, db)

    def _discover_cooccurrence(self, profile, db):
        source = profile.source_path
        ext = Path(source).suffix.lower()
        read = f"read_csv_auto('{source}')" if ext == '.csv' else f"read_parquet('{source}')"

        for i, col_a in enumerate(profile.discriminators):
            for col_b in profile.discriminators[i + 1:]:
                try:
                    fd = db.execute(f"""
                        WITH m AS (SELECT DISTINCT "{col_a}" a, "{col_b}" b FROM {read}
                                   WHERE "{col_a}" IS NOT NULL AND "{col_b}" IS NOT NULL)
                        SELECT COUNT(*), COUNT(DISTINCT a), COUNT(DISTINCT b) FROM m
                    """).fetchone()
                    total, da, db_ = fd

                    if total == da and da > db_:
                        self._add_hierarchy(db, read, col_a, col_b)
                    elif total == db_ and db_ > da:
                        self._add_hierarchy(db, read, col_b, col_a)
                except Exception as e:
                    print(f"  Warning: {col_a}×{col_b}: {e}")

    def _add_hierarchy(self, db, read_expr, child_col, parent_col):
        mappings = db.execute(f"""
            SELECT DISTINCT "{child_col}" c, "{parent_col}" p FROM {read_expr}
            WHERE "{child_col}" IS NOT NULL AND "{parent_col}" IS NOT NULL
        """).fetchall()
        for cv, pv in mappings:
            self.graph.add_edge(f"val:{child_col}={cv}", f"val:{parent_col}={pv}",
                                edge_type="CHILD_OF",
                                child_discriminator=child_col,
                                parent_discriminator=parent_col)

    def find_datasets_for_value(self, value, discriminator_col=None):
        results = []
        for nid, data in self.graph.nodes(data=True):
            if data.get('node_type') != 'VALUE' or data.get('value') != value:
                continue
            if discriminator_col and data.get('discriminator') != discriminator_col:
                continue

            disc_node = self._get_parent_disc(nid)
            if disc_node:
                for ds_id in self.graph.nodes[disc_node].get('datasets', []):
                    results.append({'dataset_id': ds_id, 'match_type': 'direct',
                                    'matched_column': self.graph.nodes[disc_node]['column_name'],
                                    'matched_value': value})

            for parent in self._traverse_up(nid):
                pd_node = self._get_parent_disc(parent)
                if pd_node:
                    for ds_id in self.graph.nodes[pd_node].get('datasets', []):
                        if not any(r['dataset_id'] == ds_id for r in results):
                            results.append({'dataset_id': ds_id, 'match_type': 'hierarchical_up',
                                            'matched_column': self.graph.nodes[pd_node]['column_name'],
                                            'matched_value': self.graph.nodes[parent].get('value')})
        return results

    def find_join_path(self, ds_a, ds_b):
        a_discs, b_discs = set(), set()
        for _, t, d in self.graph.edges(f"ds:{ds_a}", data=True):
            if d.get('edge_type') == 'DATASET_HAS_DISCRIMINATOR': a_discs.add(t)
        for _, t, d in self.graph.edges(f"ds:{ds_b}", data=True):
            if d.get('edge_type') == 'DATASET_HAS_DISCRIMINATOR': b_discs.add(t)

        shared = a_discs & b_discs
        if shared:
            return {'join_type': 'direct',
                    'shared_discriminators': [self.graph.nodes[d]['column_name'] for d in shared],
                    'datasets': [ds_a, ds_b]}

        for da in a_discs:
            for db_ in b_discs:
                path = self._find_bridge(da, db_)
                if path:
                    return {'join_type': 'hierarchical',
                            'from_discriminator': self.graph.nodes[da]['column_name'],
                            'to_discriminator': self.graph.nodes[db_]['column_name'],
                            'bridge_path': path, 'datasets': [ds_a, ds_b]}
        return None

    def find_related_datasets(self, dataset_id):
        related = []
        ds_node = f"ds:{dataset_id}"
        if not self.graph.has_node(ds_node):
            return related
        for _, t, d in self.graph.edges(ds_node, data=True):
            if d.get('edge_type') == 'DATASET_HAS_DISCRIMINATOR':
                for other in self.graph.nodes[t].get('datasets', []):
                    if other != dataset_id:
                        related.append({'dataset_id': other,
                                        'shared_discriminator': self.graph.nodes[t]['column_name']})
        return related

    def get_summary(self):
        datasets, discriminators = [], []
        for nid, data in self.graph.nodes(data=True):
            if data.get('node_type') == 'DATASET':
                ds_id = nid.replace('ds:', '')
                p = self._dataset_profiles.get(ds_id)
                datasets.append({'id': ds_id, 'source': data.get('source_path'),
                                 'rows': data.get('row_count'), 'is_temporal': data.get('is_temporal'),
                                 'signature': data.get('tdv_signature'),
                                 'time_col': data.get('primary_time_col'),
                                 'time_grain': data.get('time_grain'),
                                 'discriminators': p.discriminators if p else [],
                                 'values': p.values if p else []})
            elif data.get('node_type') == 'DISCRIMINATOR':
                vc = sum(1 for _, _, d in self.graph.edges(nid, data=True)
                         if d.get('edge_type') == 'DISCRIMINATOR_HAS_VALUE')
                discriminators.append({'column': data.get('column_name'),
                                       'datasets': data.get('datasets', []),
                                       'value_count': vc})

        hierarchies = []
        seen = set()
        for _, _, data in self.graph.edges(data=True):
            if data.get('edge_type') == 'CHILD_OF':
                pair = (data.get('child_discriminator'), data.get('parent_discriminator'))
                if pair not in seen:
                    hierarchies.append({'child': pair[0], 'parent': pair[1]})
                    seen.add(pair)

        return {'datasets': datasets, 'discriminators': discriminators,
                'hierarchies': hierarchies,
                'nodes': self.graph.number_of_nodes(),
                'edges': self.graph.number_of_edges()}

    def get_hierarchy(self, disc_col):
        disc_node = f"disc:{disc_col}"
        if not self.graph.has_node(disc_node):
            return {}
        hierarchy = defaultdict(list)
        for _, target, data in self.graph.edges(disc_node, data=True):
            if data.get('edge_type') == 'DISCRIMINATOR_HAS_VALUE':
                val = self.graph.nodes[target].get('value')
                for _, parent, ed in self.graph.edges(target, data=True):
                    if ed.get('edge_type') == 'CHILD_OF':
                        pv = self.graph.nodes[parent].get('value')
                        pd = ed.get('parent_discriminator')
                        hierarchy[f"{pd}={pv}"].append(f"{disc_col}={val}")
        return dict(hierarchy)

    def _get_parent_disc(self, val_node):
        for s, _, d in self.graph.in_edges(val_node, data=True):
            if d.get('edge_type') == 'DISCRIMINATOR_HAS_VALUE': return s
        return None

    def _traverse_up(self, node, visited=None):
        if visited is None: visited = set()
        visited.add(node)
        parents = []
        for _, t, d in self.graph.edges(node, data=True):
            if d.get('edge_type') == 'CHILD_OF' and t not in visited:
                parents.append(t)
                parents.extend(self._traverse_up(t, visited))
        return parents

    def _find_bridge(self, disc_a, disc_b):
        a_vals = [t for _, t, d in self.graph.edges(disc_a, data=True)
                  if d.get('edge_type') == 'DISCRIMINATOR_HAS_VALUE'][:5]
        b_vals = [t for _, t, d in self.graph.edges(disc_b, data=True)
                  if d.get('edge_type') == 'DISCRIMINATOR_HAS_VALUE'][:5]
        for av in a_vals:
            for bv in b_vals:
                try:
                    return nx.shortest_path(self.graph, av, bv)
                except nx.NetworkXNoPath:
                    continue
        return None


class DataLakeScanner:
    SUPPORTED = {'.csv', '.parquet', '.pq'}  # exclude .json to avoid scanning graph.json

    def __init__(self, db=None):
        self.db = db or duckdb.connect()
        self.profiler = TDVProfiler(self.db)
        self.graph = DiscriminatorGraph()
        self.profiles = {}

    def scan_directory(self, directory, recursive=True):
        path = Path(directory)
        files = [f for f in path.glob('**/*' if recursive else '*')
                 if f.suffix.lower() in self.SUPPORTED]

        results = {'scanned': 0, 'temporal': 0, 'non_temporal': 0, 'errors': []}
        for fp in sorted(files):
            try:
                ds_id = fp.stem
                print(f"Profiling: {fp.name}...", end=" ")
                profile = self.profiler.profile_dataset(str(fp), ds_id)
                self.profiles[ds_id] = profile
                self.graph.add_dataset(profile, self.db)
                tag = 'TEMPORAL' if profile.is_temporal else 'non-temporal'
                print(f"[{profile.tdv_signature}] {tag}")
                results['scanned'] += 1
                results['temporal' if profile.is_temporal else 'non_temporal'] += 1
            except Exception as e:
                print(f"ERROR: {e}")
                results['errors'].append({'file': str(fp), 'error': str(e)})
        return results


def create_demo_data(output_dir="/tmp/demo_lake"):
    import os
    os.makedirs(output_dir, exist_ok=True)
    np.random.seed(42)

    # POS — smaller: 3 months, fewer SKUs
    dates = pd.date_range('2024-01-01', '2024-03-31', freq='D')
    stores = ['Store_NYC', 'Store_LA', 'Store_CHI']
    skus = ['BUD-LT-12', 'MILLER-LT-12', 'CORONA-12']
    brands = {'BUD-LT-12': 'Bud Light', 'MILLER-LT-12': 'Miller Lite', 'CORONA-12': 'Corona'}
    categories = {'Bud Light': 'Domestic Beer', 'Miller Lite': 'Domestic Beer', 'Corona': 'Import Beer'}
    regions = {'Store_NYC': 'Northeast', 'Store_LA': 'West', 'Store_CHI': 'Midwest'}

    rows = []
    for date in dates:
        for store in stores:
            for sku in skus:
                rows.append({'transaction_date': date, 'store_id': store, 'sku': sku,
                             'brand': brands[sku], 'category': categories[brands[sku]],
                             'region': regions[store],
                             'units_sold': np.random.poisson(20) + 1,
                             'revenue': round(np.random.uniform(15, 80), 2)})
    pd.DataFrame(rows).to_csv(f"{output_dir}/pos_transactions.csv", index=False)

    # Weather — daily by region
    weather = []
    for date in dates:
        for region in ['Northeast', 'West', 'Midwest']:
            weather.append({'date': date, 'region': region,
                            'avg_temp_f': round(np.random.normal(55, 15), 1),
                            'precipitation_in': round(max(0, np.random.exponential(0.2)), 2)})
    pd.DataFrame(weather).to_csv(f"{output_dir}/weather_daily.csv", index=False)

    # Marketing — weekly by brand
    weeks = pd.date_range('2024-01-01', '2024-03-31', freq='W-MON')
    mkt = []
    for week in weeks:
        for brand in ['Bud Light', 'Miller Lite', 'Corona']:
            mkt.append({'week_start': week, 'brand': brand,
                        'tv_spend': round(np.random.uniform(5000, 50000), 2),
                        'digital_spend': round(np.random.uniform(2000, 20000), 2)})
    pd.DataFrame(mkt).to_csv(f"{output_dir}/marketing_spend.csv", index=False)

    # Product master (non-temporal reference)
    pd.DataFrame([{'sku': s, 'brand': brands[s], 'category': categories[brands[s]],
                    'pack_size': int(s.split('-')[-1]), 'unit_cost': round(np.random.uniform(5, 20), 2)}
                   for s in skus]).to_csv(f"{output_dir}/product_master.csv", index=False)

    # Store directory (non-temporal reference)
    pd.DataFrame([{'store_id': s, 'region': regions[s], 'state': st, 'sqft': sq}
                   for s, st, sq in [('Store_NYC', 'NY', 12000), ('Store_LA', 'CA', 15000),
                                     ('Store_CHI', 'IL', 10000)]
                   ]).to_csv(f"{output_dir}/store_directory.csv", index=False)

    print(f"Created 5 demo datasets in {output_dir}")
    return output_dir