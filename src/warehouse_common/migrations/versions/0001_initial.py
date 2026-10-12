"""initial

Revision ID: 0001
Revises:
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

operation_type = sa.Enum("receipt", "issue", name="operation_type")


def upgrade() -> None:
    op.create_table(
        "stock_events",
        sa.Column("id", sa.BigInteger, sa.Identity(), nullable=False),
        sa.Column("operation", operation_type, nullable=False),
        sa.Column("warehouse", sa.String(64), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("qty", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("qty > 0", name="ck_stock_events_qty_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_stock_events"),
    )
    op.create_index("ix_stock_events_warehouse_sku", "stock_events", ["warehouse", "sku"])
    op.create_table(
        "stock_agg",
        sa.Column("warehouse", sa.String(64), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("qty", sa.BigInteger, nullable=False),
        sa.Column("received_qty", sa.BigInteger, nullable=False),
        sa.Column("issued_qty", sa.BigInteger, nullable=False),
        sa.Column("events_count", sa.Integer, nullable=False),
        sa.Column("last_event_id", sa.BigInteger, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("warehouse", "sku", name="pk_stock_agg"),
    )


def downgrade() -> None:
    op.drop_table("stock_agg")
    op.drop_index("ix_stock_events_warehouse_sku", table_name="stock_events")
    op.drop_table("stock_events")
    operation_type.drop(op.get_bind(), checkfirst=True)
