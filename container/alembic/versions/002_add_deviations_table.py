"""Add deviations table for individual deviation records.

Revision ID: 002
Create Date: 2026-03-21
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE deviations (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            signal_id           TEXT NOT NULL,
            dataset_id          UUID,
            run_id              UUID,

            -- Denormalized context for fast queries
            dataset_name        TEXT NOT NULL,
            segment             TEXT NOT NULL,
            segment_by          TEXT NOT NULL,

            -- Deviation fields
            column_name         TEXT NOT NULL,
            deviation_type      TEXT NOT NULL,
            severity            TEXT NOT NULL,
            persistence         TEXT,
            timestamp_start     TIMESTAMPTZ NOT NULL,
            timestamp_end       TIMESTAMPTZ NOT NULL,

            -- Numeric details
            expected_value      DOUBLE PRECISION,
            observed_value      DOUBLE PRECISION,
            deviation_magnitude DOUBLE PRECISION,
            z_score             DOUBLE PRECISION,
            confidence          DOUBLE PRECISION,

            -- Human-readable
            narrative           TEXT,

            created_at          TIMESTAMPTZ DEFAULT now()
        );
    """)

    # Per-signal lookups
    op.execute("CREATE INDEX idx_deviations_signal_id ON deviations(signal_id);")

    # "What needs attention" — severity across all signals, newest first
    op.execute("CREATE INDEX idx_deviations_severity ON deviations(severity, timestamp_start DESC);")

    # Date range scans — "what happened this week"
    op.execute("CREATE INDEX idx_deviations_timestamp ON deviations(timestamp_start DESC);")

    # Dataset + date + severity — the retail power query
    op.execute(
        "CREATE INDEX idx_deviations_dataset_time "
        "ON deviations(dataset_name, timestamp_start DESC, severity);"
    )

    # FK index for cascade/cleanup
    op.execute("CREATE INDEX idx_deviations_run_id ON deviations(run_id);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS deviations;")
