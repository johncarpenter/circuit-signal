"""Initial schema: datasets, analysis_runs, signals with pgvector.

Revision ID: 001
Create Date: 2026-03-20
"""

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    op.execute("""
        CREATE TABLE datasets (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            TEXT NOT NULL,
            created_by      TEXT,
            status          TEXT NOT NULL DEFAULT 'uploaded',
            file_refs       JSONB NOT NULL,
            profile         JSONB,
            config          JSONB,
            tags            JSONB DEFAULT '{}',
            created_at      TIMESTAMPTZ DEFAULT now(),
            updated_at      TIMESTAMPTZ DEFAULT now(),
            deleted_at      TIMESTAMPTZ
        );
    """)

    op.execute("""
        CREATE TABLE analysis_runs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            dataset_id      UUID REFERENCES datasets(id),
            status          TEXT NOT NULL DEFAULT 'queued',
            manifest        JSONB NOT NULL,
            progress        JSONB DEFAULT '{}',
            result_refs     JSONB,
            error           TEXT,
            started_at      TIMESTAMPTZ,
            completed_at    TIMESTAMPTZ,
            created_at      TIMESTAMPTZ DEFAULT now()
        );
    """)

    op.execute("""
        CREATE TABLE signals (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            signal_id       TEXT UNIQUE NOT NULL,
            dataset_id      UUID REFERENCES datasets(id),
            run_id          UUID REFERENCES analysis_runs(id),

            dataset_name    TEXT NOT NULL,
            segment         TEXT NOT NULL,
            segment_by      TEXT NOT NULL,
            time_range      TSTZRANGE,
            temporal_grain  TEXT NOT NULL,
            row_count       INTEGER,
            tags            JSONB DEFAULT '{}',

            trend_slope     DOUBLE PRECISION,
            trend_intercept DOUBLE PRECISION,
            seasonal_weekly DOUBLE PRECISION[7],
            seasonal_hourly DOUBLE PRECISION[24],
            seasonal_monthly DOUBLE PRECISION[12],
            seasonality_strength DOUBLE PRECISION,
            residual_std    DOUBLE PRECISION,

            deviation_count_90d INTEGER,
            deviation_density DOUBLE PRECISION,
            critical_pct    DOUBLE PRECISION,
            change_points   JSONB,

            shape_embedding     vector(54),
            deviation_embedding vector(47),
            foundation_embedding vector(512),
            text_description    TEXT,
            text_embedding      vector(384),

            status          TEXT NOT NULL DEFAULT 'active',
            superseded_by   TEXT,
            registered_at   TIMESTAMPTZ DEFAULT now(),
            updated_at      TIMESTAMPTZ DEFAULT now()
        );
    """)

    # Vector indices (HNSW)
    op.execute("""
        CREATE INDEX idx_signals_shape ON signals
            USING hnsw (shape_embedding vector_cosine_ops)
            WHERE status = 'active';
    """)
    op.execute("""
        CREATE INDEX idx_signals_deviation ON signals
            USING hnsw (deviation_embedding vector_cosine_ops)
            WHERE status = 'active';
    """)
    op.execute("""
        CREATE INDEX idx_signals_text ON signals
            USING hnsw (text_embedding vector_cosine_ops)
            WHERE status = 'active';
    """)
    op.execute("""
        CREATE INDEX idx_signals_foundation ON signals
            USING hnsw (foundation_embedding vector_cosine_ops)
            WHERE status = 'active' AND foundation_embedding IS NOT NULL;
    """)

    # Metadata indices
    op.execute("CREATE INDEX idx_signals_dataset ON signals(dataset_name);")
    op.execute("CREATE INDEX idx_signals_segment_by ON signals(segment_by);")
    op.execute("CREATE INDEX idx_signals_status ON signals(status);")
    op.execute("CREATE INDEX idx_signals_tags ON signals USING gin(tags);")
    op.execute("""
        CREATE INDEX idx_signals_description ON signals
            USING gin(text_description gin_trgm_ops);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS signals CASCADE;")
    op.execute("DROP TABLE IF EXISTS analysis_runs CASCADE;")
    op.execute("DROP TABLE IF EXISTS datasets CASCADE;")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm;")
    op.execute("DROP EXTENSION IF EXISTS vector;")
