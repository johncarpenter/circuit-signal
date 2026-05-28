"""Query engine — all logic for graph loading, querying, plan building, and execution."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb
import networkx as nx

logger = logging.getLogger("query-planner")


class QueryEngine:
    """Stateful engine that loads a TDV graph and executes data plans."""

    def __init__(self) -> None:
        self.graph: nx.DiGraph | None = None
        self.summary: dict | None = None
        self.graph_base_dir: Path | None = None
        self.current_plan: dict | None = None
        self.db = duckdb.connect(":memory:")

    # ------------------------------------------------------------------
    # Graph loading
    # ------------------------------------------------------------------

    def load_graph(self, graph_path: str) -> dict:
        """Load graph.json into memory. Returns summary."""
        path = Path(graph_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Graph file not found: {path}")

        with open(path) as f:
            data = json.load(f)

        self.graph_base_dir = path.parent
        self.summary = data.get("summary", {})

        # Reconstruct networkx DiGraph from serialized nodes/edges
        g = nx.DiGraph()
        graph_data = data.get("graph", {})

        for node in graph_data.get("nodes", []):
            node_id = node.pop("id")
            g.add_node(node_id, **node)

        for edge in graph_data.get("edges", []):
            src = edge.pop("source")
            tgt = edge.pop("target")
            g.add_edge(src, tgt, **edge)

        self.graph = g

        return {
            "status": "loaded",
            "path": str(path),
            "datasets": len(self.summary.get("datasets", [])),
            "discriminators": len(self.summary.get("discriminators", [])),
            "hierarchies": len(self.summary.get("hierarchies", [])),
            "nodes": g.number_of_nodes(),
            "edges": g.number_of_edges(),
        }

    # ------------------------------------------------------------------
    # Graph summary
    # ------------------------------------------------------------------

    def get_summary(self) -> dict:
        """Return cached summary from graph.json."""
        self._require_graph()
        return self.summary

    # ------------------------------------------------------------------
    # Graph queries
    # ------------------------------------------------------------------

    def find_datasets(self, value: str, discriminator_col: str | None = None) -> list[dict]:
        """Find datasets containing a value, traversing CHILD_OF edges."""
        self._require_graph()
        results = []
        for nid, data in self.graph.nodes(data=True):
            if data.get("node_type") != "VALUE" or data.get("value") != value:
                continue
            if discriminator_col and data.get("discriminator") != discriminator_col:
                continue

            disc_node = self._get_parent_disc(nid)
            if disc_node:
                for ds_id in self.graph.nodes[disc_node].get("datasets", []):
                    results.append({
                        "dataset_id": ds_id,
                        "match_type": "direct",
                        "matched_column": self.graph.nodes[disc_node]["column_name"],
                        "matched_value": value,
                    })

            for parent in self._traverse_up(nid):
                pd_node = self._get_parent_disc(parent)
                if pd_node:
                    for ds_id in self.graph.nodes[pd_node].get("datasets", []):
                        if not any(r["dataset_id"] == ds_id for r in results):
                            results.append({
                                "dataset_id": ds_id,
                                "match_type": "hierarchical_up",
                                "matched_column": self.graph.nodes[pd_node]["column_name"],
                                "matched_value": self.graph.nodes[parent].get("value"),
                            })
        return results

    def find_join_path(self, dataset_a: str, dataset_b: str) -> dict | None:
        """Find shared discriminators or hierarchy bridge between two datasets."""
        self._require_graph()
        a_discs, b_discs = set(), set()
        for _, t, d in self.graph.edges(f"ds:{dataset_a}", data=True):
            if d.get("edge_type") == "DATASET_HAS_DISCRIMINATOR":
                a_discs.add(t)
        for _, t, d in self.graph.edges(f"ds:{dataset_b}", data=True):
            if d.get("edge_type") == "DATASET_HAS_DISCRIMINATOR":
                b_discs.add(t)

        shared = a_discs & b_discs
        if shared:
            return {
                "join_type": "direct",
                "shared_discriminators": [
                    self.graph.nodes[d]["column_name"] for d in shared
                ],
                "datasets": [dataset_a, dataset_b],
            }

        for da in a_discs:
            for db_ in b_discs:
                path = self._find_bridge(da, db_)
                if path:
                    return {
                        "join_type": "hierarchical",
                        "from_discriminator": self.graph.nodes[da]["column_name"],
                        "to_discriminator": self.graph.nodes[db_]["column_name"],
                        "bridge_path": path,
                        "datasets": [dataset_a, dataset_b],
                    }
        return None

    # ------------------------------------------------------------------
    # Plan building
    # ------------------------------------------------------------------

    def build_plan(
        self,
        target_value: str | None = None,
        dataset_ids: list[str] | None = None,
        target_discriminator: str | None = None,
    ) -> dict:
        """Build a DataPlan. Value mode or dataset mode."""
        self._require_graph()

        if target_value:
            plan = self._build_value_plan(target_value, target_discriminator)
        elif dataset_ids:
            plan = self._build_dataset_plan(dataset_ids)
        else:
            raise ValueError("Provide target_value or dataset_ids")

        self.current_plan = plan
        return plan

    def _build_value_plan(self, value: str, discriminator: str | None) -> dict:
        """Value mode: find datasets for value, pick richest as primary."""
        matches = self.find_datasets(value, discriminator)
        if not matches:
            return {"error": f"No datasets found for value '{value}'"}

        # Pick richest dataset as primary (most rows)
        best = None
        best_rows = -1
        for m in matches:
            ds_info = self._get_dataset_info(m["dataset_id"])
            if ds_info and ds_info.get("rows", 0) > best_rows:
                best = m
                best_rows = ds_info.get("rows", 0)

        primary_ds = best["dataset_id"]
        primary_info = self._get_dataset_info(primary_ds)

        plan = {
            "mode": "value",
            "target_value": value,
            "primary": {
                "dataset_id": primary_ds,
                "source_path": str(self._resolve_source(primary_ds)),
                "time_col": primary_info.get("time_col"),
                "time_grain": primary_info.get("time_grain"),
                "filter": {
                    "column": best["matched_column"],
                    "value": best["matched_value"],
                },
            },
            "supplementary": [],
        }

        # Add supplementary datasets
        for m in matches:
            if m["dataset_id"] == primary_ds:
                continue
            supp_info = self._get_dataset_info(m["dataset_id"])
            join_path = self.find_join_path(primary_ds, m["dataset_id"])
            join_key = None
            join_type = "unknown"
            if join_path:
                join_type = join_path["join_type"]
                if join_type == "direct":
                    join_key = join_path["shared_discriminators"][0]

            plan["supplementary"].append({
                "dataset_id": m["dataset_id"],
                "source_path": str(self._resolve_source(m["dataset_id"])),
                "time_col": supp_info.get("time_col") if supp_info else None,
                "time_grain": supp_info.get("time_grain") if supp_info else None,
                "join_key": join_key,
                "join_type": join_type,
                "filter": {
                    "column": m["matched_column"],
                    "value": m["matched_value"],
                } if m["match_type"] != "direct" or m["dataset_id"] != primary_ds else None,
            })

        return plan

    def _build_dataset_plan(self, dataset_ids: list[str]) -> dict:
        """Dataset mode: first = primary, rest = supplementary with auto join keys."""
        primary_id = dataset_ids[0]
        primary_info = self._get_dataset_info(primary_id)
        if not primary_info:
            return {"error": f"Dataset '{primary_id}' not found in graph"}

        plan = {
            "mode": "dataset",
            "primary": {
                "dataset_id": primary_id,
                "source_path": str(self._resolve_source(primary_id)),
                "time_col": primary_info.get("time_col"),
                "time_grain": primary_info.get("time_grain"),
                "filter": None,
            },
            "supplementary": [],
        }

        for ds_id in dataset_ids[1:]:
            supp_info = self._get_dataset_info(ds_id)
            if not supp_info:
                logger.warning("Dataset '%s' not found in graph, skipping", ds_id)
                continue

            join_path = self.find_join_path(primary_id, ds_id)
            join_key = None
            join_type = "unknown"
            if join_path:
                join_type = join_path["join_type"]
                if join_type == "direct":
                    join_key = join_path["shared_discriminators"][0]

            plan["supplementary"].append({
                "dataset_id": ds_id,
                "source_path": str(self._resolve_source(ds_id)),
                "time_col": supp_info.get("time_col"),
                "time_grain": supp_info.get("time_grain"),
                "join_key": join_key,
                "join_type": join_type,
                "filter": None,
            })

        return plan

    # ------------------------------------------------------------------
    # Plan execution
    # ------------------------------------------------------------------

    def execute_plan(self, output_path: str, export_format: str = "csv") -> dict:
        """Execute current plan with ASOF joins, export to file."""
        if not self.current_plan:
            raise ValueError("No plan to execute. Call build_plan first.")

        plan = self.current_plan
        if "error" in plan:
            return plan

        primary = plan["primary"]
        primary_src = primary["source_path"]
        time_col = primary["time_col"]

        # Load primary dataset
        self.db.execute("DROP TABLE IF EXISTS __primary")
        self.db.execute(
            f"CREATE TABLE __primary AS SELECT * FROM read_csv_auto('{primary_src}')"
        )

        # Apply primary filter
        if primary.get("filter"):
            col = primary["filter"]["column"]
            val = primary["filter"]["value"]
            self.db.execute(
                f"DELETE FROM __primary WHERE \"{col}\" != '{val}'"
            )

        # Add date column for joining
        if time_col:
            self.db.execute(
                f'ALTER TABLE __primary ADD COLUMN IF NOT EXISTS __date DATE'
            )
            self.db.execute(
                f'UPDATE __primary SET __date = CAST("{time_col}" AS DATE)'
            )

        result_table = "__primary"
        joined_count = 0

        for i, supp in enumerate(plan.get("supplementary", [])):
            supp_table = f"__supp_{i}"
            supp_src = supp["source_path"]
            supp_time = supp.get("time_col")
            join_key = supp.get("join_key")
            ds_id = supp["dataset_id"]
            prefix = ds_id.replace("-", "_")

            self.db.execute(f"DROP TABLE IF EXISTS {supp_table}")
            self.db.execute(
                f"CREATE TABLE {supp_table} AS SELECT * FROM read_csv_auto('{supp_src}')"
            )

            # Apply supplementary filter
            if supp.get("filter"):
                col = supp["filter"]["column"]
                val = supp["filter"]["value"]
                self.db.execute(
                    f"DELETE FROM {supp_table} WHERE \"{col}\" != '{val}'"
                )

            # Add date column to supplementary
            if supp_time:
                self.db.execute(
                    f'ALTER TABLE {supp_table} ADD COLUMN IF NOT EXISTS __date DATE'
                )
                self.db.execute(
                    f'UPDATE {supp_table} SET __date = CAST("{supp_time}" AS DATE)'
                )

            if not join_key:
                logger.warning("No join key for %s, skipping", ds_id)
                continue

            # Get supplementary columns (exclude join key, time col, __date)
            cols_info = self.db.execute(f"DESCRIBE {supp_table}").fetchall()
            supp_cols = []
            for col_info in cols_info:
                cname = col_info[0]
                if cname in (join_key, supp_time, "__date"):
                    continue
                supp_cols.append(cname)

            if not supp_cols:
                continue

            # Build prefixed column list
            prefixed = ", ".join(
                f's."{c}" AS "{prefix}_{c}"' for c in supp_cols
            )

            # Determine join strategy: same grain = equi-join, different = ASOF
            primary_grain = primary.get("time_grain")
            supp_grain = supp.get("time_grain")
            same_grain = primary_grain and supp_grain and primary_grain == supp_grain

            new_result = f"__result_{i}"
            self.db.execute(f"DROP TABLE IF EXISTS {new_result}")

            if same_grain and time_col and supp_time:
                # Equi-join on key + date
                self.db.execute(f"""
                    CREATE TABLE {new_result} AS
                    SELECT p.*, {prefixed}
                    FROM {result_table} p
                    LEFT JOIN {supp_table} s
                      ON p."{join_key}" = s."{join_key}"
                      AND p.__date = s.__date
                """)
            elif time_col and supp_time:
                # ASOF join for grain mismatch
                self.db.execute(f"""
                    CREATE TABLE {new_result} AS
                    SELECT p.*, {prefixed}
                    FROM {result_table} p
                    ASOF LEFT JOIN {supp_table} s
                      ON p."{join_key}" = s."{join_key}"
                      AND p.__date >= s.__date
                """)
            else:
                # No time columns — simple equi-join on key only
                self.db.execute(f"""
                    CREATE TABLE {new_result} AS
                    SELECT p.*, {prefixed}
                    FROM {result_table} p
                    LEFT JOIN {supp_table} s
                      ON p."{join_key}" = s."{join_key}"
                """)

            # Clean up previous result table
            if result_table != "__primary":
                self.db.execute(f"DROP TABLE IF EXISTS {result_table}")
            result_table = new_result
            joined_count += 1

        # Drop the __date helper column before export
        try:
            self.db.execute(f'ALTER TABLE {result_table} DROP COLUMN __date')
        except Exception:
            pass

        # Export
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        fmt = export_format.lower()
        if fmt == "parquet":
            self.db.execute(
                f"COPY {result_table} TO '{out}' (FORMAT PARQUET)"
            )
        else:
            self.db.execute(
                f"COPY {result_table} TO '{out}' (FORMAT CSV, HEADER)"
            )

        row_count = self.db.execute(f"SELECT COUNT(*) FROM {result_table}").fetchone()[0]
        col_count = len(self.db.execute(f"DESCRIBE {result_table}").fetchall())

        # Cleanup temp tables
        for tbl in self.db.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall():
            if tbl[0].startswith("__"):
                self.db.execute(f"DROP TABLE IF EXISTS {tbl[0]}")

        return {
            "status": "exported",
            "output_path": str(out),
            "format": fmt,
            "rows": row_count,
            "columns": col_count,
            "datasets_joined": joined_count,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_graph(self) -> None:
        if self.graph is None:
            raise ValueError("No graph loaded. Call load_graph first.")

    def _get_parent_disc(self, val_node: str) -> str | None:
        """Find DISCRIMINATOR owning a VALUE node."""
        for s, _, d in self.graph.in_edges(val_node, data=True):
            if d.get("edge_type") == "DISCRIMINATOR_HAS_VALUE":
                return s
        return None

    def _traverse_up(self, node: str, visited: set | None = None) -> list[str]:
        """Follow CHILD_OF edges upward."""
        if visited is None:
            visited = set()
        visited.add(node)
        parents = []
        for _, t, d in self.graph.edges(node, data=True):
            if d.get("edge_type") == "CHILD_OF" and t not in visited:
                parents.append(t)
                parents.extend(self._traverse_up(t, visited))
        return parents

    def _find_bridge(self, disc_a: str, disc_b: str) -> list[str] | None:
        """Find shortest path between value nodes of two discriminators."""
        a_vals = [t for _, t, d in self.graph.edges(disc_a, data=True)
                  if d.get("edge_type") == "DISCRIMINATOR_HAS_VALUE"][:5]
        b_vals = [t for _, t, d in self.graph.edges(disc_b, data=True)
                  if d.get("edge_type") == "DISCRIMINATOR_HAS_VALUE"][:5]
        for av in a_vals:
            for bv in b_vals:
                try:
                    return nx.shortest_path(self.graph, av, bv)
                except nx.NetworkXNoPath:
                    continue
        return None

    def _get_dataset_info(self, dataset_id: str) -> dict | None:
        """Look up dataset info from cached summary."""
        if not self.summary:
            return None
        for ds in self.summary.get("datasets", []):
            if ds["id"] == dataset_id:
                return ds
        return None

    def _resolve_source(self, dataset_id: str) -> Path:
        """Resolve a dataset's source path relative to graph_base_dir."""
        ds_node = f"ds:{dataset_id}"
        if self.graph.has_node(ds_node):
            rel_path = self.graph.nodes[ds_node].get("source_path", "")
            if rel_path and self.graph_base_dir:
                resolved = (self.graph_base_dir / rel_path).resolve()
                if resolved.exists():
                    return resolved
        # Fallback: check summary
        info = self._get_dataset_info(dataset_id)
        if info and info.get("source") and self.graph_base_dir:
            return (self.graph_base_dir / info["source"]).resolve()
        raise FileNotFoundError(f"Cannot resolve source for dataset '{dataset_id}'")
