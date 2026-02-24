"""
Signal Store — DuckDB-backed persistence for sources, signals, correlations, and insights.

Handles schema creation, CRUD operations, and analytical queries.
The store is a single DuckDB file that persists across sessions.
"""

import json
import logging
from pathlib import Path

import duckdb

logger = logging.getLogger("signal-correlation.store")

DEFAULT_DB_PATH = ".signal-store/signals.duckdb"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sources (
    source_id       VARCHAR PRIMARY KEY,
    name            VARCHAR NOT NULL,
    description     VARCHAR,
    domain          VARCHAR,
    region          VARCHAR,
    latitude        DOUBLE,
    longitude       DOUBLE,
    radius_km       DOUBLE,
    entity_keys     JSON,
    baseline_path   VARCHAR,
    tags            JSON,
    registered_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signals (
    signal_id       VARCHAR PRIMARY KEY,
    source_id       VARCHAR,
    column_name     VARCHAR NOT NULL,
    signal_type     VARCHAR NOT NULL,
    severity        VARCHAR,
    ts_start        TIMESTAMP NOT NULL,
    ts_end          TIMESTAMP,
    magnitude       DOUBLE,
    direction       VARCHAR,
    confidence      DOUBLE,
    latitude        DOUBLE,
    longitude       DOUBLE,
    entity_values   JSON,
    metadata        JSON,
    narrative       VARCHAR,
    ingested_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS correlations (
    correlation_id   VARCHAR PRIMARY KEY,
    signal_a_id      VARCHAR,
    signal_b_id      VARCHAR,
    source_a_id      VARCHAR,
    source_b_id      VARCHAR,
    correlation_type VARCHAR NOT NULL,
    strength         DOUBLE,
    lag_description  VARCHAR,
    lag_periods      INTEGER,
    spatial_distance_km DOUBLE,
    confidence       DOUBLE,
    evidence         VARCHAR,
    narrative        VARCHAR,
    discovered_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS insights (
    insight_id        VARCHAR PRIMARY KEY,
    title             VARCHAR,
    signal_ids        JSON,
    correlation_ids   JSON,
    correlation_types JSON,
    strength          DOUBLE,
    actionability     DOUBLE,
    lag_structure     VARCHAR,
    suggested_actions JSON,
    narrative         VARCHAR,
    discovered_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class SignalStore:
    """DuckDB-backed signal store."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(self.db_path)
        self._init_schema()

    def _init_schema(self):
        """Create tables if they don't exist."""
        for statement in SCHEMA_SQL.strip().split(";"):
            statement = statement.strip()
            if statement:
                self.conn.execute(statement)
        logger.info(f"Signal store initialized at {self.db_path}")

    def close(self):
        self.conn.close()

    # --- Sources ---

    def upsert_source(self, source: dict) -> str:
        """Insert or update a source. Returns 'registered' or 'updated'."""
        existing = self.conn.execute(
            "SELECT source_id FROM sources WHERE source_id = ?",
            [source["source_id"]],
        ).fetchone()

        if existing:
            self.conn.execute(
                """UPDATE sources SET name=?, description=?, domain=?, region=?,
                   latitude=?, longitude=?, radius_km=?, entity_keys=?,
                   baseline_path=?, tags=?
                   WHERE source_id=?""",
                [
                    source.get("name"),
                    source.get("description"),
                    source.get("domain"),
                    source.get("geography", {}).get("region"),
                    source.get("geography", {}).get("latitude"),
                    source.get("geography", {}).get("longitude"),
                    source.get("geography", {}).get("radius_km"),
                    json.dumps(source.get("entity_keys")),
                    source.get("baseline_path"),
                    json.dumps(source.get("tags")),
                    source["source_id"],
                ],
            )
            return "updated"
        else:
            self.conn.execute(
                """INSERT INTO sources (source_id, name, description, domain, region,
                   latitude, longitude, radius_km, entity_keys, baseline_path, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    source["source_id"],
                    source.get("name", source["source_id"]),
                    source.get("description"),
                    source.get("domain"),
                    source.get("geography", {}).get("region"),
                    source.get("geography", {}).get("latitude"),
                    source.get("geography", {}).get("longitude"),
                    source.get("geography", {}).get("radius_km"),
                    json.dumps(source.get("entity_keys")),
                    source.get("baseline_path"),
                    json.dumps(source.get("tags")),
                ],
            )
            return "registered"

    def get_source(self, source_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM sources WHERE source_id = ?", [source_id]
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        return dict(zip(cols, row))

    def list_sources(self) -> list[dict]:
        rows = self.conn.execute("""
            SELECT s.source_id, s.name, s.domain, s.region, s.tags,
                   COUNT(sig.signal_id) as signal_count,
                   MAX(sig.ts_start) as latest_signal
            FROM sources s
            LEFT JOIN signals sig ON s.source_id = sig.source_id
            GROUP BY s.source_id, s.name, s.domain, s.region, s.tags, s.registered_at
            ORDER BY s.registered_at
        """).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, row)) for row in rows]

    def count_sources(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]

    # --- Signals ---

    def insert_signals(self, signals: list[dict]) -> int:
        """Bulk insert signals. Returns count inserted."""
        count = 0
        for sig in signals:
            try:
                self.conn.execute(
                    """INSERT OR REPLACE INTO signals
                       (signal_id, source_id, column_name, signal_type, severity,
                        ts_start, ts_end, magnitude, direction, confidence,
                        latitude, longitude, entity_values, metadata, narrative)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        sig["signal_id"],
                        sig["source_id"],
                        sig["column_name"],
                        sig["signal_type"],
                        sig.get("severity"),
                        sig["ts_start"],
                        sig.get("ts_end"),
                        sig.get("magnitude"),
                        sig.get("direction"),
                        sig.get("confidence"),
                        sig.get("latitude"),
                        sig.get("longitude"),
                        json.dumps(sig.get("entity_values")),
                        json.dumps(sig.get("metadata")),
                        sig.get("narrative"),
                    ],
                )
                count += 1
            except Exception as e:
                logger.warning(f"Failed to insert signal {sig.get('signal_id')}: {e}")
        return count

    def get_signals(
        self,
        source_ids: list[str] | None = None,
        signal_types: list[str] | None = None,
        ts_start: str | None = None,
        ts_end: str | None = None,
    ) -> list[dict]:
        """Query signals with optional filters."""
        query = "SELECT * FROM signals WHERE 1=1"
        params = []

        if source_ids:
            placeholders = ",".join(["?"] * len(source_ids))
            query += f" AND source_id IN ({placeholders})"
            params.extend(source_ids)

        if signal_types:
            placeholders = ",".join(["?"] * len(signal_types))
            query += f" AND signal_type IN ({placeholders})"
            params.extend(signal_types)

        if ts_start:
            query += " AND ts_start >= ?"
            params.append(ts_start)

        if ts_end:
            query += " AND (ts_end <= ? OR ts_end IS NULL)"
            params.append(ts_end)

        query += " ORDER BY ts_start"
        rows = self.conn.execute(query, params).fetchall()
        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, row)) for row in rows]

    def count_signals(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]

    # --- Correlations ---

    def insert_correlations(self, correlations: list[dict]) -> int:
        count = 0
        for corr in correlations:
            try:
                self.conn.execute(
                    """INSERT OR REPLACE INTO correlations
                       (correlation_id, signal_a_id, signal_b_id, source_a_id, source_b_id,
                        correlation_type, strength, lag_description, lag_periods,
                        spatial_distance_km, confidence, evidence, narrative)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        corr["correlation_id"],
                        corr["signal_a_id"],
                        corr["signal_b_id"],
                        corr.get("source_a_id"),
                        corr.get("source_b_id"),
                        corr["correlation_type"],
                        corr.get("strength"),
                        corr.get("lag_description"),
                        corr.get("lag_periods"),
                        corr.get("spatial_distance_km"),
                        corr.get("confidence"),
                        corr.get("evidence"),
                        corr.get("narrative"),
                    ],
                )
                count += 1
            except Exception as e:
                logger.warning(f"Failed to insert correlation: {e}")
        return count

    def get_correlations(self, insight_id: str | None = None) -> list[dict]:
        if insight_id:
            # Get correlation IDs from insight, then fetch them
            row = self.conn.execute(
                "SELECT correlation_ids FROM insights WHERE insight_id = ?",
                [insight_id],
            ).fetchone()
            if not row or not row[0]:
                return []
            corr_ids = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            placeholders = ",".join(["?"] * len(corr_ids))
            rows = self.conn.execute(
                f"SELECT * FROM correlations WHERE correlation_id IN ({placeholders})",
                corr_ids,
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM correlations ORDER BY strength DESC").fetchall()

        cols = [d[0] for d in self.conn.description]
        return [dict(zip(cols, row)) for row in rows]

    # --- Insights ---

    def insert_insights(self, insights: list[dict]) -> int:
        count = 0
        for ins in insights:
            try:
                self.conn.execute(
                    """INSERT OR REPLACE INTO insights
                       (insight_id, title, signal_ids, correlation_ids,
                        correlation_types, strength, actionability,
                        lag_structure, suggested_actions, narrative)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        ins["insight_id"],
                        ins.get("title"),
                        json.dumps(ins.get("signal_ids", [])),
                        json.dumps(ins.get("correlation_ids", [])),
                        json.dumps(ins.get("correlation_types", [])),
                        ins.get("strength"),
                        ins.get("actionability"),
                        ins.get("lag_structure"),
                        json.dumps(ins.get("suggested_actions", [])),
                        ins.get("narrative"),
                    ],
                )
                count += 1
            except Exception as e:
                logger.warning(f"Failed to insert insight: {e}")
        return count

    def query_insights(
        self,
        source_ids: list[str] | None = None,
        min_actionability: float = 0.0,
        min_strength: float = 0.0,
        limit: int = 20,
        sort_by: str = "actionability",
    ) -> list[dict]:
        query = "SELECT * FROM insights WHERE actionability >= ? AND strength >= ?"
        params: list = [min_actionability, min_strength]

        sort_col = {
            "actionability": "actionability DESC",
            "strength": "strength DESC",
            "recency": "discovered_at DESC",
        }.get(sort_by, "actionability DESC")

        query += f" ORDER BY {sort_col} LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        cols = [d[0] for d in self.conn.description]
        results = []
        for row in rows:
            d = dict(zip(cols, row))
            # Parse JSON fields
            for json_field in ["signal_ids", "correlation_ids", "correlation_types", "suggested_actions"]:
                if isinstance(d.get(json_field), str):
                    try:
                        d[json_field] = json.loads(d[json_field])
                    except (json.JSONDecodeError, TypeError):
                        pass
            results.append(d)

        # Filter by source_ids if provided (check if any signal in insight is from requested sources)
        if source_ids:
            filtered = []
            for ins in results:
                sig_ids = ins.get("signal_ids", [])
                if sig_ids:
                    sigs = self.get_signals()
                    insight_sources = {s["source_id"] for s in sigs if s["signal_id"] in sig_ids}
                    if insight_sources & set(source_ids):
                        filtered.append(ins)
            results = filtered

        return results

    def get_insight(self, insight_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM insights WHERE insight_id = ?", [insight_id]
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in self.conn.description]
        d = dict(zip(cols, row))
        for json_field in ["signal_ids", "correlation_ids", "correlation_types", "suggested_actions"]:
            if isinstance(d.get(json_field), str):
                try:
                    d[json_field] = json.loads(d[json_field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d

    def clear_correlations_and_insights(self):
        """Clear derived data (correlations + insights) while keeping sources and signals."""
        self.conn.execute("DELETE FROM insights")
        self.conn.execute("DELETE FROM correlations")
