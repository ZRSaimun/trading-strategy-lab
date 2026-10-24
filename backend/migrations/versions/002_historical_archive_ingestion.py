"""Add isolated, provider-aware historical import tables.

Revision ID: 002
Revises: 001
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "historical_datasets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("instrument", sa.String(80), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("utc_offset_minutes", sa.Integer(), nullable=False),
        sa.Column("archive_sha256", sa.String(64), nullable=False),
        sa.Column("archive_filename", sa.String(255), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("seen", sa.BigInteger(), nullable=False),
        sa.Column("accepted", sa.BigInteger(), nullable=False),
        sa.Column("rejected", sa.BigInteger(), nullable=False),
        sa.Column("zero_volume", sa.BigInteger(), nullable=False),
        sa.Column("checkpoint_member", sa.Integer(), nullable=False),
        sa.Column("checkpoint_line", sa.BigInteger(), nullable=False),
        sa.Column("last_timestamp", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_table(
        "historical_candles",
        sa.Column("dataset_id", sa.String(64), sa.ForeignKey("historical_datasets.id"), primary_key=True),
        sa.Column("time", sa.BigInteger(), primary_key=True),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("source_member", sa.String(255), nullable=False),
        sa.Column("source_line", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "historical_quarantine",
        sa.Column("dataset_id", sa.String(64), sa.ForeignKey("historical_datasets.id"), primary_key=True),
        sa.Column("member_index", sa.Integer(), primary_key=True),
        sa.Column("line", sa.BigInteger(), primary_key=True),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("sample", sa.String(300), nullable=False),
    )
    op.create_index("ix_historical_dataset_instrument", "historical_datasets", ["provider", "instrument", "state"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # The app's existing DB engine sets a private search_path for each
        # transaction. Disable access from Supabase browser Data API roles.
        for table in ("historical_datasets", "historical_candles", "historical_quarantine"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")
            for role in ("anon", "authenticated"):
                present = bind.execute(sa.text(
                    "SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": role}).scalar()
                if present:
                    op.execute(f"REVOKE ALL ON TABLE {table} FROM {role}")


def downgrade():
    # Fail closed: never drop a historical research database with candles.
    existing = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM historical_datasets")).scalar()
    if existing:
        raise RuntimeError("Historical data exists; archive/export and review before downgrading")
    op.drop_index("ix_historical_dataset_instrument", table_name="historical_datasets")
    op.drop_table("historical_quarantine")
    op.drop_table("historical_candles")
    op.drop_table("historical_datasets")
