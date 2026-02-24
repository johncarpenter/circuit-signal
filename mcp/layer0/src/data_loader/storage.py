"""Storage backend abstraction — DuckDB (primary) with pandas fallback."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger("data-loader")

# Frequency mappings used by both backends
FREQ_MAP = {
    "hourly": "h",
    "daily": "D",
    "weekly": "W-MON",
    "monthly": "MS",
}

DUCKDB_TRUNC_MAP = {
    "hourly": "hour",
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
}


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class StorageBackend(ABC):
    """Base interface for storage backends."""

    @abstractmethod
    def load(self, data_path: str, dataset_name: str) -> dict:
        """Load file into store. Return schema dict."""

    @abstractmethod
    def schema(self, dataset_name: str) -> dict:
        """Return column names, types, row count."""

    @abstractmethod
    def unique_values(self, dataset_name: str, column: str) -> list[dict]:
        """Return [{value, count}] sorted by count desc."""

    @abstractmethod
    def get_dataframe(self, dataset_name: str, columns: list[str] | None = None, limit: int | None = None) -> pd.DataFrame:
        """Return the dataset (or subset) as a pandas DataFrame."""

    @abstractmethod
    def query_sql(self, sql: str) -> pd.DataFrame:
        """Execute raw SQL and return results as DataFrame. DuckDB only; pandas raises."""

    @abstractmethod
    def table_exists(self, table_name: str) -> bool:
        """Check if a table/dataset exists in the store."""

    @abstractmethod
    def create_table_from_query(self, table_name: str, sql: str) -> int:
        """Create a table from a SQL query. Return row count."""

    @abstractmethod
    def export_table(self, table_name: str, output_path: str, fmt: str = "csv") -> int:
        """Export a table to file. Return row count."""

    @abstractmethod
    def aggregate(
        self,
        dataset_name: str,
        timestamp_col: str,
        freq: str,
        metrics: list[dict],
        segment_col: str | None = None,
        segment_value: str | None = None,
    ) -> pd.DataFrame:
        """Filter + aggregate + gap-fill. Return DataFrame."""


# ---------------------------------------------------------------------------
# DuckDB backend
# ---------------------------------------------------------------------------

class DuckDBBackend(StorageBackend):
    """DuckDB-backed storage. Persists on disk."""

    def __init__(self, db_path: str):
        import duckdb
        self._db_path = db_path
        self._conn = duckdb.connect(db_path)
        logger.info("DuckDB backend initialized at %s", db_path)

    def load(self, data_path: str, dataset_name: str) -> dict:
        p = Path(data_path)
        ext = p.suffix.lower()
        if ext == ".csv":
            reader = f"read_csv_auto('{data_path}')"
        elif ext in (".parquet", ".pq"):
            reader = f"read_parquet('{data_path}')"
        elif ext == ".json":
            reader = f"read_json_auto('{data_path}')"
        else:
            raise ValueError(f"Unsupported format: {ext}")

        self._conn.execute(
            f"CREATE OR REPLACE TABLE \"{dataset_name}\" AS SELECT * FROM {reader}"
        )
        return self.schema(dataset_name)

    def schema(self, dataset_name: str) -> dict:
        cols = self._conn.execute(
            f"DESCRIBE \"{dataset_name}\""
        ).fetchall()
        row_count = self._conn.execute(
            f"SELECT COUNT(*) FROM \"{dataset_name}\""
        ).fetchone()[0]
        return {
            "columns": [
                {"name": c[0], "type": c[1]} for c in cols
            ],
            "row_count": row_count,
        }

    def unique_values(self, dataset_name: str, column: str) -> list[dict]:
        rows = self._conn.execute(
            f'SELECT "{column}", COUNT(*) as cnt '
            f'FROM "{dataset_name}" '
            f'GROUP BY "{column}" '
            f'ORDER BY cnt DESC'
        ).fetchall()
        return [{"value": str(r[0]), "count": r[1]} for r in rows]

    def get_dataframe(self, dataset_name: str, columns: list[str] | None = None, limit: int | None = None) -> pd.DataFrame:
        cols = ", ".join(f'"{c}"' for c in columns) if columns else "*"
        sql = f'SELECT {cols} FROM "{dataset_name}"'
        if limit:
            sql += f" LIMIT {limit}"
        return self._conn.execute(sql).fetchdf()

    def query_sql(self, sql: str) -> pd.DataFrame:
        return self._conn.execute(sql).fetchdf()

    def table_exists(self, table_name: str) -> bool:
        result = self._conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [table_name],
        ).fetchone()
        return result[0] > 0

    def create_table_from_query(self, table_name: str, sql: str) -> int:
        self._conn.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS {sql}')
        count = self._conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        return count

    def export_table(self, table_name: str, output_path: str, fmt: str = "csv") -> int:
        if fmt == "parquet":
            self._conn.execute(f"COPY \"{table_name}\" TO '{output_path}' (FORMAT PARQUET)")
        else:
            self._conn.execute(f"COPY \"{table_name}\" TO '{output_path}' (HEADER, DELIMITER ',')")
        count = self._conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        return count

    def aggregate(
        self,
        dataset_name: str,
        timestamp_col: str,
        freq: str,
        metrics: list[dict],
        segment_col: str | None = None,
        segment_value: str | None = None,
    ) -> pd.DataFrame:
        trunc = DUCKDB_TRUNC_MAP.get(freq)
        if not trunc:
            raise ValueError(f"Unsupported freq: {freq}. Use: {list(DUCKDB_TRUNC_MAP)}")

        # Build SELECT expressions
        select_exprs = [f'DATE_TRUNC(\'{trunc}\', CAST("{timestamp_col}" AS TIMESTAMP)) AS period']
        for m in metrics:
            col = m["col"]
            agg = m["agg"].upper()
            if col == "*":
                alias = f"count_all"
                select_exprs.append(f"COUNT(*) AS {alias}")
            else:
                alias = f"{agg.lower()}_{col}"
                select_exprs.append(f'{agg}("{col}") AS "{alias}"')

        # Build WHERE
        where = ""
        if segment_col and segment_value is not None:
            where = f'WHERE "{segment_col}" = \'{segment_value}\''

        sql = (
            f"SELECT {', '.join(select_exprs)} "
            f'FROM "{dataset_name}" '
            f"{where} "
            f"GROUP BY period "
            f"ORDER BY period"
        )
        agg_df = self._conn.execute(sql).fetchdf()

        if agg_df.empty:
            return agg_df

        # Gap-fill using GENERATE_SERIES
        min_ts = agg_df["period"].min()
        max_ts = agg_df["period"].max()

        interval_map = {
            "hourly": "INTERVAL 1 HOUR",
            "daily": "INTERVAL 1 DAY",
            "weekly": "INTERVAL 7 DAY",
            "monthly": "INTERVAL 1 MONTH",
        }
        interval = interval_map[freq]

        # Generate complete time spine
        spine_sql = (
            f"SELECT UNNEST(generate_series("
            f"CAST('{min_ts}' AS TIMESTAMP), "
            f"CAST('{max_ts}' AS TIMESTAMP), "
            f"{interval})) AS period"
        )

        # Register agg_df as a temporary table for joining
        self._conn.register("_agg_temp", agg_df)
        metric_cols = [c for c in agg_df.columns if c != "period"]
        coalesce_exprs = ", ".join(
            f'COALESCE(a."{c}", 0) AS "{c}"' for c in metric_cols
        )

        fill_sql = (
            f"SELECT s.period, {coalesce_exprs} "
            f"FROM ({spine_sql}) s "
            f"LEFT JOIN _agg_temp a ON s.period = a.period "
            f"ORDER BY s.period"
        )
        result = self._conn.execute(fill_sql).fetchdf()
        self._conn.unregister("_agg_temp")

        return result


# ---------------------------------------------------------------------------
# Pandas backend (fallback)
# ---------------------------------------------------------------------------

class PandasBackend(StorageBackend):
    """In-memory pandas backend. Used when DuckDB is not installed."""

    def __init__(self):
        self._tables: dict[str, pd.DataFrame] = {}
        logger.info("Pandas fallback backend initialized (in-memory)")

    def load(self, data_path: str, dataset_name: str) -> dict:
        p = Path(data_path)
        ext = p.suffix.lower()
        if ext == ".csv":
            df = pd.read_csv(data_path)
        elif ext in (".parquet", ".pq"):
            df = pd.read_parquet(data_path)
        elif ext == ".json":
            df = pd.read_json(data_path)
        else:
            raise ValueError(f"Unsupported format: {ext}")

        self._tables[dataset_name] = df
        return self.schema(dataset_name)

    def schema(self, dataset_name: str) -> dict:
        df = self._tables[dataset_name]
        return {
            "columns": [
                {"name": col, "type": str(df[col].dtype)} for col in df.columns
            ],
            "row_count": len(df),
        }

    def unique_values(self, dataset_name: str, column: str) -> list[dict]:
        df = self._tables[dataset_name]
        counts = df[column].value_counts().reset_index()
        counts.columns = ["value", "count"]
        return [
            {"value": str(row["value"]), "count": int(row["count"])}
            for _, row in counts.iterrows()
        ]

    def get_dataframe(self, dataset_name: str, columns: list[str] | None = None, limit: int | None = None) -> pd.DataFrame:
        df = self._tables[dataset_name]
        if columns:
            df = df[columns]
        if limit:
            df = df.head(limit)
        return df.copy()

    def query_sql(self, sql: str) -> pd.DataFrame:
        raise NotImplementedError("SQL queries require DuckDB backend. Install duckdb>=0.9.")

    def table_exists(self, table_name: str) -> bool:
        return table_name in self._tables

    def create_table_from_query(self, table_name: str, sql: str) -> int:
        raise NotImplementedError("create_table_from_query requires DuckDB backend.")

    def export_table(self, table_name: str, output_path: str, fmt: str = "csv") -> int:
        df = self._tables[table_name]
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "parquet":
            df.to_parquet(output_path, index=False)
        else:
            df.to_csv(output_path, index=False)
        return len(df)

    def aggregate(
        self,
        dataset_name: str,
        timestamp_col: str,
        freq: str,
        metrics: list[dict],
        segment_col: str | None = None,
        segment_value: str | None = None,
    ) -> pd.DataFrame:
        pd_freq = FREQ_MAP.get(freq)
        if not pd_freq:
            raise ValueError(f"Unsupported freq: {freq}. Use: {list(FREQ_MAP)}")

        df = self._tables[dataset_name].copy()

        # Parse timestamps
        df[timestamp_col] = pd.to_datetime(df[timestamp_col], utc=True)

        # Filter by segment
        if segment_col and segment_value is not None:
            df = df[df[segment_col].astype(str) == str(segment_value)]

        if df.empty:
            return df

        # Set period column
        df = df.set_index(timestamp_col)

        # Build aggregation dict
        agg_dict = {}
        result_cols = []
        for m in metrics:
            col = m["col"]
            agg = m["agg"]
            if col == "*":
                # Count all rows — use the first column as a proxy
                proxy = df.columns[0]
                agg_dict[proxy] = "count"
                result_cols.append(("count_all", proxy))
            else:
                agg_dict[col] = agg
                result_cols.append((f"{agg}_{col}", col))

        # Resample and aggregate
        resampled = df.resample(pd_freq).agg(agg_dict)

        # Rename columns
        rename_map = {}
        for alias, orig_col in result_cols:
            rename_map[orig_col] = alias
        resampled = resampled.rename(columns=rename_map)

        # Gap-fill: reindex with complete range, fill with 0
        full_range = pd.date_range(
            start=resampled.index.min(),
            end=resampled.index.max(),
            freq=pd_freq,
        )
        resampled = resampled.reindex(full_range, fill_value=0)
        resampled.index.name = "period"
        resampled = resampled.reset_index()

        return resampled


# ---------------------------------------------------------------------------
# Singleton backend selection
# ---------------------------------------------------------------------------

_backend: StorageBackend | None = None


def get_backend(data_dir: str | None = None) -> StorageBackend:
    """Get or create the storage backend. DuckDB preferred, pandas fallback."""
    global _backend
    if _backend is not None:
        return _backend

    try:
        import duckdb  # noqa: F401
        db_dir = Path(data_dir) if data_dir else Path.cwd()
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(db_dir / "signal.duckdb")
        _backend = DuckDBBackend(db_path)
    except ImportError:
        logger.warning("duckdb not installed — using pandas fallback (in-memory only)")
        _backend = PandasBackend()

    return _backend
