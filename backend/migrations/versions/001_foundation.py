"""Initial schema."""
from alembic import op
import sqlalchemy as sa
revision="001"
down_revision=None

def upgrade():
    op.create_table("records",sa.Column("key",sa.String(160),primary_key=True),sa.Column("value",sa.Text(),nullable=False))
    op.create_table("candles",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("instrument",sa.String(80),nullable=False),
        sa.Column("time",sa.Integer(),nullable=False),*[sa.Column(k,sa.Float(),nullable=False) for k in ("open","high","low","close")],
        sa.Column("volume",sa.Float(),nullable=True),sa.Column("source",sa.String(160),nullable=False),
        sa.Column("retrieved_at",sa.Integer(),nullable=False),sa.UniqueConstraint("instrument","time"))
    op.create_index("ix_candles_instrument","candles",["instrument"])
    op.create_index("ix_candles_time","candles",["time"])
    op.create_table("audit",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("time",sa.Integer(),nullable=False),
        sa.Column("actor",sa.String(80),nullable=False),sa.Column("action",sa.String(80),nullable=False),sa.Column("detail",sa.Text(),nullable=False))

def downgrade():
    op.drop_table("audit");op.drop_table("candles");op.drop_table("records")
