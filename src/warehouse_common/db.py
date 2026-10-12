import enum

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from warehouse_common.settings import Settings


class Operation(str, enum.Enum):
    RECEIPT = "receipt"
    ISSUE = "issue"


metadata = sa.MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

operation_type = sa.Enum(
    Operation,
    name="operation_type",
    values_callable=lambda members: [member.value for member in members],
)

stock_events = sa.Table(
    "stock_events",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("operation", operation_type, nullable=False),
    sa.Column("warehouse", sa.String(64), nullable=False),
    sa.Column("sku", sa.String(64), nullable=False),
    sa.Column("qty", sa.Integer, nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.CheckConstraint("qty > 0", name="qty_positive"),
    sa.Index(None, "warehouse", "sku"),
)

stock_agg = sa.Table(
    "stock_agg",
    metadata,
    sa.Column("warehouse", sa.String(64), primary_key=True),
    sa.Column("sku", sa.String(64), primary_key=True),
    sa.Column("qty", sa.BigInteger, nullable=False),
    sa.Column("received_qty", sa.BigInteger, nullable=False),
    sa.Column("issued_qty", sa.BigInteger, nullable=False),
    sa.Column("events_count", sa.Integer, nullable=False),
    sa.Column("last_event_id", sa.BigInteger, nullable=False),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)

outbox = sa.Table(
    "outbox",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("event_type", sa.String(64), nullable=False),
    sa.Column("payload", sa.Text, nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)


def signed_qty() -> sa.ColumnElement[int]:
    return sa.case(
        (stock_events.c.operation == Operation.ISSUE, -stock_events.c.qty),
        else_=stock_events.c.qty,
    )


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        pool_pre_ping=True,
    )
