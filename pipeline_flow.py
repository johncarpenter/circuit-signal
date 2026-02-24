"""
Graph-Aware Pipeline Flow
=========================

    ┌─────────────────────────────────────────────────────────┐
    │  SETUP (run once / periodically)                        │
    │                                                         │
    │   Data Lake  ──►  TDV Profiler  ──►  graph.json         │
    │   /lake/*.csv      (scan+classify)    (serialized)      │
    └───────────────────────┬─────────────────────────────────┘
                            │
                            ▼
    ┌─────────────────────────────────────────────────────────┐
    │  QUERY TIME                                             │
    │                                                         │
    │  User Goal ──► Load graph.json                          │
    │                    │                                    │
    │                    ├─ find relevant datasets             │
    │                    ├─ find join paths                    │
    │                    ├─ build DataPlan                     │
    │                    ▼                                    │
    │               Layer 0 (graph-aware)                      │
    │                    │                                    │
    │                    ├─ pull datasets                      │
    │                    ├─ temporal alignment (resample)      │
    │                    ├─ execute joins (disc + time)        │
    │                    ├─ auto-segment                       │
    │                    ▼                                    │
    │               Layers 1 & 2 (unchanged)                  │
    └─────────────────────────────────────────────────────────┘
"""

import json
import duckdb
import networkx as nx
from networkx.readwrite import json_graph
from pathlib import Path
from typing import Optional
from dataclasses import asdict

from tdv_profiler import (
    DataLakeScanner, DiscriminatorGraph, DatasetProfile,
    ColumnProfile, ColumnRole, create_demo_data
)


# =============================================================================
# 1. GRAPH SERIALIZATION
# =============================================================================

class GraphStore:
    VERSION = "1.0"

    @staticmethod
    def save(scanner: DataLakeScanner, output_path: str, metadata: dict = None):
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
        print(f"Graph saved: {output_path} ({Path(output_path).stat().st_size / 1024:.1f} KB)")

    @staticmethod
    def load(input_path: str) -> tuple[DiscriminatorGraph, dict]:
        with open(input_path, 'r') as f:
            data = json.load(f)

        graph = DiscriminatorGraph()
        graph.graph = json_graph.node_link_graph(data['graph'], directed=True)

        profiles = data.get('profiles', {})

        for ds_id, pd in profiles.items():
            cols = [ColumnProfile(name=c['name'], role=ColumnRole(c['role']), dtype=c['dtype'],
                                  cardinality=c['cardinality'], null_pct=c['null_pct'],
                                  sample_values=c['sample_values'], time_grain=c.get('time_grain'),
                                  time_range=c.get('time_range'), cardinality_ratio=c.get('cardinality_ratio'),
                                  distinct_values=c.get('distinct_values'), is_continuous=c.get('is_continuous'),
                                  value_stats=c.get('value_stats'))
                    for c in pd.get('columns', [])]
            dp = DatasetProfile(dataset_id=ds_id, source_path=pd['source_path'],
                                row_count=pd['row_count'], columns=cols,
                                is_temporal=pd['is_temporal'],
                                primary_time_col=pd.get('primary_time_col'),
                                discriminators=pd.get('discriminators', []),
                                values=pd.get('values', []))
            graph._dataset_profiles[ds_id] = dp

        return graph, profiles


# =============================================================================
# 2. DATA PLAN
# =============================================================================

class DataPlan:
    """Structured plan for dataset selection, joining, and filtering."""

    def __init__(self):
        self.primary_dataset: Optional[dict] = None
        self.supplementary_datasets: list[dict] = []
        self.joins: list[dict] = []
        self.filters: list[dict] = []
        self.target_grain: str = "daily"

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

        return '\n'.join(lines)


# =============================================================================
# 3. PLAN BUILDER
# =============================================================================

class PlanBuilder:
    """Uses the graph to build DataPlans from analytical goals."""

    def __init__(self, graph: DiscriminatorGraph, profiles: dict):
        self.graph = graph
        self.profiles = profiles

    def build_plan_for_value(self, target_value: str, target_disc: str = None) -> DataPlan:
        """Build a plan centered on a discriminator value (e.g., 'Bud Light')."""
        plan = DataPlan()
        matches = self.graph.find_datasets_for_value(target_value, target_disc)
        if not matches:
            return plan

        # Pick the primary dataset: the one with most discriminators (richest segmentation)
        direct = [m for m in matches if m['match_type'] == 'direct']
        if not direct:
            return plan

        # Score datasets by richness
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

        return plan

    def build_plan_for_datasets(self, dataset_ids: list[str]) -> DataPlan:
        """Build a plan for explicitly selected datasets."""
        plan = DataPlan()
        if not dataset_ids:
            return plan

        # First dataset is primary
        p = self.profiles[dataset_ids[0]]
        plan.set_primary(
            dataset_id=dataset_ids[0], source_path=p['source_path'],
            time_col=p.get('primary_time_col'),
            discriminators=p.get('discriminators', []),
            values=p.get('values', []),
            time_grain=self._get_time_grain(dataset_ids[0]),
        )

        # Remaining are supplementary — find join keys
        for ds_id in dataset_ids[1:]:
            join_info = self.graph.find_join_path(dataset_ids[0], ds_id)
            if not join_info:
                print(f"  ⚠ No join path from {dataset_ids[0]} to {ds_id}")
                continue
            rel_profile = self.profiles[ds_id]
            join_key = join_info['shared_discriminators'][0] if join_info['join_type'] == 'direct' else join_info.get('from_discriminator')

            plan.add_supplementary(
                dataset_id=ds_id, source_path=rel_profile['source_path'],
                time_col=rel_profile.get('primary_time_col'),
                join_key=join_key,
                time_grain=self._get_time_grain(ds_id),
                values=rel_profile.get('values', []),
            )

        return plan

    def _get_time_grain(self, ds_id):
        node = self.graph.graph.nodes.get(f"ds:{ds_id}", {})
        return node.get('time_grain', 'daily')


# =============================================================================
# 4. GRAPH-AWARE LAYER 0 EXECUTOR
# =============================================================================

class GraphAwareLayer0:
    """
    Executes a DataPlan to produce a unified DuckDB table.

    Key innovation: temporal-aware joins.
    When the primary dataset is daily and a supplementary is weekly,
    the executor resamples the supplementary to daily (forward-fill)
    before joining. This prevents cartesian explosions.
    """

    GRAIN_TO_INTERVAL = {
        'daily': 'DAY', 'weekly': 'WEEK', 'monthly': 'MONTH', 'hourly': 'HOUR'
    }

    def __init__(self, db=None):
        self.db = db or duckdb.connect()

    def execute_plan(self, plan: DataPlan, output_table: str = "unified") -> dict:
        if not plan.primary_dataset:
            return {'error': 'No primary dataset'}

        primary = plan.primary_dataset
        print(f"\n▶ Executing plan: primary={primary['dataset_id']}, "
              f"supplementary={[s['dataset_id'] for s in plan.supplementary_datasets]}")

        # Step 1: Load primary dataset
        self._load_view("_primary", primary['source_path'])

        # Step 2: Apply filters to primary
        filter_sql = ""
        if plan.filters:
            conditions = []
            for f in plan.filters:
                val = f"'{f['value']}'" if isinstance(f['value'], str) else str(f['value'])
                conditions.append(f'"{f["column"]}" {f["operator"]} {val}')
            filter_sql = "WHERE " + " AND ".join(conditions)

        self.db.execute(f"CREATE OR REPLACE VIEW _primary_filtered AS SELECT * FROM _primary {filter_sql}")
        count = self.db.execute("SELECT COUNT(*) FROM _primary_filtered").fetchone()[0]
        print(f"  ✓ Primary: {primary['dataset_id']} → {count:,} rows" +
              (f" (filtered: {filter_sql})" if filter_sql else ""))

        # Step 3: Join each supplementary dataset
        current_view = "_primary_filtered"

        for i, supp in enumerate(plan.supplementary_datasets):
            supp_view = f"_supp_{i}"
            self._load_view(supp_view, supp['source_path'])

            # Determine value columns to bring in (avoid column name conflicts)
            supp_value_cols = supp.get('values', [])
            if not supp_value_cols:
                # Grab all non-key, non-time columns
                cols = self.db.execute(f"DESCRIBE {supp_view}").fetchall()
                supp_value_cols = [c[0] for c in cols
                                   if c[0] != supp['join_key'] and c[0] != supp['time_col']]

            # Build the temporal-aware join
            join_key = supp['join_key']
            primary_time = primary['time_col']
            supp_time = supp['time_col']
            primary_grain = primary.get('time_grain', 'daily')
            supp_grain = supp.get('time_grain', 'daily')

            # Prefix supplementary columns to avoid conflicts
            prefix = supp['dataset_id'].replace('-', '_')
            select_cols = ", ".join([f's."{c}" AS "{prefix}_{c}"' for c in supp_value_cols])

            if not select_cols:
                print(f"  ⚠ No value columns from {supp['dataset_id']}, skipping")
                continue

            if supp_grain == primary_grain:
                # Same grain: straight join on key + time
                join_sql = f"""
                    CREATE OR REPLACE VIEW _joined_{i} AS
                    SELECT p.*, {select_cols}
                    FROM {current_view} p
                    LEFT JOIN {supp_view} s
                    ON p."{join_key}" = s."{join_key}"
                    AND CAST(p."{primary_time}" AS DATE) = CAST(s."{supp_time}" AS DATE)
                """
            else:
                # Different grain: use ASOF join (closest time match)
                # This avoids cartesian products by matching each primary row
                # to the most recent supplementary row <= primary's time
                join_sql = f"""
                    CREATE OR REPLACE VIEW _joined_{i} AS
                    SELECT p.*, {select_cols}
                    FROM {current_view} p
                    ASOF LEFT JOIN (
                        SELECT * FROM {supp_view} ORDER BY "{supp_time}"
                    ) s
                    ON p."{join_key}" = s."{join_key}"
                    AND CAST(p."{primary_time}" AS DATE) >= CAST(s."{supp_time}" AS DATE)
                """

            self.db.execute(join_sql)
            join_count = self.db.execute(f"SELECT COUNT(*) FROM _joined_{i}").fetchone()[0]
            print(f"  ✓ Joined ← {supp['dataset_id']} on [{join_key} + time] "
                  f"({supp_grain}→{primary_grain}) → {join_count:,} rows, "
                  f"added: {', '.join(supp_value_cols)}")

            current_view = f"_joined_{i}"

        # Step 4: Materialize final table
        self.db.execute(f"CREATE OR REPLACE TABLE {output_table} AS SELECT * FROM {current_view}")
        final_count = self.db.execute(f"SELECT COUNT(*) FROM {output_table}").fetchone()[0]
        final_cols = self.db.execute(f"DESCRIBE {output_table}").fetchall()

        print(f"\n  ✅ Unified table '{output_table}': {final_count:,} rows, {len(final_cols)} columns")
        print(f"     Columns: {', '.join(c[0] for c in final_cols)}")
        print(f"     → Ready for Layer 0 auto-segmentation")

        return {
            'table': output_table,
            'rows': final_count,
            'columns': [c[0] for c in final_cols],
        }

    def _load_view(self, name, path):
        ext = Path(path).suffix.lower()
        if ext == '.csv':
            self.db.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_csv_auto('{path}')")
        elif ext in ('.parquet', '.pq'):
            self.db.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{path}')")


# =============================================================================
# 5. FULL DEMO
# =============================================================================

def demo():
    print("=" * 60)
    print("FULL PIPELINE DEMO")
    print("=" * 60)

    # ── SETUP ────────────────────────────────────────────────
    print("\n📦 SETUP: Scan data lake → graph.json")
    lake_dir = create_demo_data()

    scanner = DataLakeScanner()
    scanner.scan_directory(lake_dir)

    graph_path = "/tmp/demo_lake/graph.json"
    GraphStore.save(scanner, graph_path)

    # Print what was discovered
    summary = scanner.graph.get_summary()
    print(f"\nDiscovered: {len(summary['datasets'])} datasets, "
          f"{len(summary['discriminators'])} discriminators, "
          f"{len(summary['hierarchies'])} hierarchies")
    for h in summary['hierarchies']:
        print(f"  Hierarchy: {h['child']} → {h['parent']}")
    shared = [d for d in summary['discriminators'] if len(d['datasets']) > 1]
    for s in shared:
        print(f"  Shared discriminator: '{s['column']}' in {s['datasets']}")

    # ── RUNTIME ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("🔄 RUNTIME: Load graph → build plan → execute")
    print("=" * 60)

    graph, profiles = GraphStore.load(graph_path)
    planner = PlanBuilder(graph, profiles)
    db = duckdb.connect()
    executor = GraphAwareLayer0(db)

    # ── SCENARIO 1: "Analyze Bud Light" ─────────────────────
    print("\n" + "-" * 50)
    print('SCENARIO 1: "Analyze Bud Light performance"')
    print("-" * 50)

    plan1 = planner.build_plan_for_value("Bud Light")
    print(plan1.describe())
    result1 = executor.execute_plan(plan1, "bud_light_analysis")

    print("\nSample rows:")
    sample = db.execute("SELECT * FROM bud_light_analysis LIMIT 3").fetchdf()
    print(sample.to_string(index=False))

    # ── SCENARIO 2: "Compare POS with weather" ──────────────
    print("\n" + "-" * 50)
    print('SCENARIO 2: "Compare POS transactions with weather"')
    print("-" * 50)

    plan2 = planner.build_plan_for_datasets(["pos_transactions", "weather_daily"])
    print(plan2.describe())
    result2 = executor.execute_plan(plan2, "pos_weather")

    print("\nSample rows:")
    sample2 = db.execute("SELECT * FROM pos_weather LIMIT 3").fetchdf()
    print(sample2.to_string(index=False))

    # ── SCENARIO 3: All three datasets ──────────────────────
    print("\n" + "-" * 50)
    print('SCENARIO 3: "POS + weather + marketing (3-way join)"')
    print("-" * 50)

    plan3 = planner.build_plan_for_datasets(["pos_transactions", "weather_daily", "marketing_spend"])
    print(plan3.describe())
    result3 = executor.execute_plan(plan3, "full_analysis")

    print("\nSample rows:")
    sample3 = db.execute("SELECT * FROM full_analysis LIMIT 3").fetchdf()
    print(sample3.to_string(index=False))

    # ── Summary ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    print(f"""
    graph.json contains the full data lake index.
    At query time, the agent:
      1. Loads graph.json (instant)
      2. Queries the graph to find datasets + join paths
      3. Builds a DataPlan
      4. Executor runs temporal-aware joins (ASOF for grain mismatches)
      5. Produces unified table → feeds into existing Layer 0 segmentation

    Key: The ASOF join prevents cartesian explosions when joining
    weekly marketing data to daily POS data. Each POS row gets
    the most recent marketing values as of that date.
    """)


if __name__ == "__main__":
    demo()
