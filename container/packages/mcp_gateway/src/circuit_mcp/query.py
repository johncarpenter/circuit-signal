"""Signal similarity search using pgvector."""

import logging
from enum import Enum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class SearchAxis(str, Enum):
    SHAPE = "shape"           # shape_embedding (seasonal shape similarity)
    DEVIATION = "deviation"   # deviation_embedding (anomaly pattern similarity)
    TEXT = "text"             # text_embedding (semantic text similarity)


async def find_similar_by_signal(
    db: AsyncSession,
    signal_id: str,
    axis: SearchAxis = SearchAxis.SHAPE,
    limit: int = 10,
    dataset_filter: str | None = None,
) -> list[dict]:
    """Find signals similar to a given signal using pgvector cosine distance."""
    embedding_col = f"{axis.value}_embedding"

    # Get the source signal's embedding
    source = await db.execute(
        text(f"""
            SELECT signal_id, {embedding_col}
            FROM signals
            WHERE signal_id = :signal_id AND {embedding_col} IS NOT NULL
        """),
        {"signal_id": signal_id},
    )
    source_row = source.fetchone()
    if not source_row:
        return []

    # Build similarity query
    where_clauses = [
        "s.status = 'active'",
        "s.signal_id != :signal_id",
        f"s.{embedding_col} IS NOT NULL",
    ]
    params = {"signal_id": signal_id, "limit": limit}

    if dataset_filter:
        where_clauses.append("s.dataset_name = :dataset_filter")
        params["dataset_filter"] = dataset_filter

    where_sql = " AND ".join(where_clauses)

    result = await db.execute(
        text(f"""
            SELECT
                s.signal_id,
                s.dataset_name,
                s.segment,
                s.segment_by,
                s.temporal_grain,
                s.text_description,
                s.trend_slope,
                s.seasonality_strength,
                s.deviation_count_90d,
                1 - (s.{embedding_col} <=> (
                    SELECT {embedding_col} FROM signals WHERE signal_id = :signal_id
                )) AS similarity
            FROM signals s
            WHERE {where_sql}
            ORDER BY s.{embedding_col} <=> (
                SELECT {embedding_col} FROM signals WHERE signal_id = :signal_id
            )
            LIMIT :limit
        """),
        params,
    )

    return [
        {
            "signal_id": row.signal_id,
            "dataset_name": row.dataset_name,
            "segment": row.segment,
            "segment_by": row.segment_by,
            "temporal_grain": row.temporal_grain,
            "text_description": row.text_description,
            "trend_slope": row.trend_slope,
            "seasonality_strength": row.seasonality_strength,
            "deviation_count_90d": row.deviation_count_90d,
            "similarity": round(float(row.similarity), 4) if row.similarity else None,
        }
        for row in result.fetchall()
    ]


async def find_similar_by_text(
    db: AsyncSession,
    query_embedding: list[float],
    limit: int = 10,
    dataset_filter: str | None = None,
) -> list[dict]:
    """Find signals similar to a text query using pgvector cosine distance.

    The query_embedding should be a 384-dim vector from sentence-transformers.
    """
    where_clauses = [
        "s.status = 'active'",
        "s.text_embedding IS NOT NULL",
    ]
    params = {"embedding": str(query_embedding), "limit": limit}

    if dataset_filter:
        where_clauses.append("s.dataset_name = :dataset_filter")
        params["dataset_filter"] = dataset_filter

    where_sql = " AND ".join(where_clauses)

    result = await db.execute(
        text(f"""
            SELECT
                s.signal_id,
                s.dataset_name,
                s.segment,
                s.segment_by,
                s.temporal_grain,
                s.text_description,
                s.trend_slope,
                s.seasonality_strength,
                s.deviation_count_90d,
                1 - (s.text_embedding <=> :embedding::vector) AS similarity
            FROM signals s
            WHERE {where_sql}
            ORDER BY s.text_embedding <=> :embedding::vector
            LIMIT :limit
        """),
        params,
    )

    return [
        {
            "signal_id": row.signal_id,
            "dataset_name": row.dataset_name,
            "segment": row.segment,
            "segment_by": row.segment_by,
            "temporal_grain": row.temporal_grain,
            "text_description": row.text_description,
            "trend_slope": row.trend_slope,
            "seasonality_strength": row.seasonality_strength,
            "deviation_count_90d": row.deviation_count_90d,
            "similarity": round(float(row.similarity), 4) if row.similarity else None,
        }
        for row in result.fetchall()
    ]


async def explain_similarity(
    db: AsyncSession,
    signal_id_a: str,
    signal_id_b: str,
) -> dict:
    """Compare two signals and explain their similarity across all axes."""
    result = await db.execute(
        text("""
            SELECT
                a.signal_id AS a_id,
                b.signal_id AS b_id,
                a.dataset_name AS a_dataset,
                b.dataset_name AS b_dataset,
                a.segment AS a_segment,
                b.segment AS b_segment,
                a.text_description AS a_description,
                b.text_description AS b_description,
                a.trend_slope AS a_trend,
                b.trend_slope AS b_trend,
                a.seasonality_strength AS a_seasonality,
                b.seasonality_strength AS b_seasonality,
                a.deviation_count_90d AS a_deviations,
                b.deviation_count_90d AS b_deviations,
                CASE WHEN a.shape_embedding IS NOT NULL AND b.shape_embedding IS NOT NULL
                    THEN 1 - (a.shape_embedding <=> b.shape_embedding) END AS shape_similarity,
                CASE WHEN a.deviation_embedding IS NOT NULL AND b.deviation_embedding IS NOT NULL
                    THEN 1 - (a.deviation_embedding <=> b.deviation_embedding) END AS deviation_similarity,
                CASE WHEN a.text_embedding IS NOT NULL AND b.text_embedding IS NOT NULL
                    THEN 1 - (a.text_embedding <=> b.text_embedding) END AS text_similarity
            FROM signals a, signals b
            WHERE a.signal_id = :a AND b.signal_id = :b
        """),
        {"a": signal_id_a, "b": signal_id_b},
    )

    row = result.fetchone()
    if not row:
        return {"error": "One or both signals not found"}

    similarities = {}
    if row.shape_similarity is not None:
        similarities["shape"] = round(float(row.shape_similarity), 4)
    if row.deviation_similarity is not None:
        similarities["deviation"] = round(float(row.deviation_similarity), 4)
    if row.text_similarity is not None:
        similarities["text"] = round(float(row.text_similarity), 4)

    # Compute ensemble (average of available axes)
    if similarities:
        similarities["ensemble"] = round(
            sum(similarities.values()) / len(similarities), 4
        )

    return {
        "signal_a": {
            "signal_id": row.a_id,
            "dataset_name": row.a_dataset,
            "segment": row.a_segment,
            "description": row.a_description,
            "trend_slope": row.a_trend,
            "seasonality_strength": row.a_seasonality,
            "deviation_count_90d": row.a_deviations,
        },
        "signal_b": {
            "signal_id": row.b_id,
            "dataset_name": row.b_dataset,
            "segment": row.b_segment,
            "description": row.b_description,
            "trend_slope": row.b_trend,
            "seasonality_strength": row.b_seasonality,
            "deviation_count_90d": row.b_deviations,
        },
        "similarities": similarities,
    }


async def cluster_signals(
    db: AsyncSession,
    axis: SearchAxis = SearchAxis.SHAPE,
    n_clusters: int = 5,
    dataset_filter: str | None = None,
) -> list[dict]:
    """Discover signal clusters (occasion archetypes) using k-means on embeddings.

    Uses PostgreSQL to fetch embeddings, then clusters in-process with scikit-learn.
    """
    embedding_col = f"{axis.value}_embedding"

    where_clauses = [
        "status = 'active'",
        f"{embedding_col} IS NOT NULL",
    ]
    params = {}

    if dataset_filter:
        where_clauses.append("dataset_name = :dataset_filter")
        params["dataset_filter"] = dataset_filter

    where_sql = " AND ".join(where_clauses)

    result = await db.execute(
        text(f"""
            SELECT signal_id, dataset_name, segment, segment_by,
                   text_description, {embedding_col}::text AS embedding
            FROM signals
            WHERE {where_sql}
        """),
        params,
    )
    rows = result.fetchall()

    if len(rows) < n_clusters:
        return [{"error": f"Not enough signals ({len(rows)}) for {n_clusters} clusters"}]

    import json
    import numpy as np
    from sklearn.cluster import KMeans

    # Parse embeddings
    signals_data = []
    embeddings = []
    for row in rows:
        # pgvector returns embedding as string like "[0.1,0.2,...]"
        emb = json.loads(row.embedding)
        embeddings.append(emb)
        signals_data.append({
            "signal_id": row.signal_id,
            "dataset_name": row.dataset_name,
            "segment": row.segment,
            "segment_by": row.segment_by,
            "text_description": row.text_description,
        })

    X = np.array(embeddings)
    kmeans = KMeans(n_clusters=min(n_clusters, len(X)), random_state=42, n_init=10)
    labels = kmeans.fit_predict(X)

    # Group signals by cluster
    clusters = {}
    for i, label in enumerate(labels):
        label = int(label)
        if label not in clusters:
            clusters[label] = {
                "cluster_id": label,
                "members": [],
            }
        clusters[label]["members"].append(signals_data[i])

    # Add cluster sizes and representative (closest to centroid)
    for label, cluster in clusters.items():
        cluster["size"] = len(cluster["members"])
        # Find representative (first member for simplicity)
        cluster["representative"] = cluster["members"][0]["signal_id"]

    return sorted(clusters.values(), key=lambda c: c["size"], reverse=True)


async def store_statistics(db: AsyncSession) -> dict:
    """Comprehensive signal store statistics."""
    result = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'active') AS total_active,
            COUNT(*) FILTER (WHERE status = 'superseded') AS total_superseded,
            COUNT(DISTINCT dataset_name) FILTER (WHERE status = 'active') AS datasets,
            COUNT(DISTINCT segment_by) FILTER (WHERE status = 'active') AS segment_types,
            COUNT(DISTINCT temporal_grain) FILTER (WHERE status = 'active') AS temporal_grains,
            AVG(deviation_count_90d) FILTER (WHERE status = 'active') AS avg_deviations,
            AVG(seasonality_strength) FILTER (WHERE status = 'active') AS avg_seasonality,
            COUNT(*) FILTER (WHERE status = 'active' AND shape_embedding IS NOT NULL) AS with_shape_embedding,
            COUNT(*) FILTER (WHERE status = 'active' AND text_embedding IS NOT NULL) AS with_text_embedding,
            MIN(registered_at) FILTER (WHERE status = 'active') AS earliest_signal,
            MAX(registered_at) FILTER (WHERE status = 'active') AS latest_signal
        FROM signals
    """))
    row = result.fetchone()

    # Per-dataset breakdown
    datasets_result = await db.execute(text("""
        SELECT dataset_name, COUNT(*) AS signal_count,
               AVG(deviation_count_90d) AS avg_deviations
        FROM signals
        WHERE status = 'active'
        GROUP BY dataset_name
        ORDER BY signal_count DESC
    """))

    datasets = [
        {
            "dataset_name": r.dataset_name,
            "signal_count": r.signal_count,
            "avg_deviations": round(float(r.avg_deviations), 2) if r.avg_deviations else None,
        }
        for r in datasets_result.fetchall()
    ]

    return {
        "total_active": row.total_active,
        "total_superseded": row.total_superseded,
        "datasets": row.datasets,
        "segment_types": row.segment_types,
        "temporal_grains": row.temporal_grains,
        "avg_deviations": round(float(row.avg_deviations), 2) if row.avg_deviations else None,
        "avg_seasonality": round(float(row.avg_seasonality), 2) if row.avg_seasonality else None,
        "with_shape_embedding": row.with_shape_embedding,
        "with_text_embedding": row.with_text_embedding,
        "earliest_signal": row.earliest_signal.isoformat() if row.earliest_signal else None,
        "latest_signal": row.latest_signal.isoformat() if row.latest_signal else None,
        "per_dataset": datasets,
    }
