import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from warehouse_common.db import Operation, stock_agg, stock_events

AGGREGATE_COLUMNS = (
    "warehouse",
    "sku",
    "qty",
    "received_qty",
    "issued_qty",
    "events_count",
    "last_event_id",
)


def _total(operation: Operation) -> sa.ColumnElement[int]:
    return sa.func.coalesce(
        sa.func.sum(stock_events.c.qty).filter(stock_events.c.operation == operation), 0
    )


def _aggregates(*criteria: sa.ColumnElement[bool]) -> sa.Select:
    received = _total(Operation.RECEIPT)
    issued = _total(Operation.ISSUE)
    return (
        sa.select(
            stock_events.c.warehouse,
            stock_events.c.sku,
            (received - issued).label("qty"),
            received.label("received_qty"),
            issued.label("issued_qty"),
            sa.func.count().label("events_count"),
            sa.func.max(stock_events.c.id).label("last_event_id"),
        )
        .where(*criteria)
        .group_by(stock_events.c.warehouse, stock_events.c.sku)
    )


def _upsert(source: sa.Select) -> sa.Insert:
    stmt = insert(stock_agg).from_select(AGGREGATE_COLUMNS, source)
    return stmt.on_conflict_do_update(
        index_elements=[stock_agg.c.warehouse, stock_agg.c.sku],
        set_={
            **{name: stmt.excluded[name] for name in AGGREGATE_COLUMNS[2:]},
            "updated_at": sa.func.now(),
        },
        where=stock_agg.c.last_event_id <= stmt.excluded.last_event_id,
    )


class StockAggRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def refresh(self, warehouse: str, sku: str) -> None:
        stmt = _upsert(
            _aggregates(stock_events.c.warehouse == warehouse, stock_events.c.sku == sku)
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def rebuild(self) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(_upsert(_aggregates()))
        return result.rowcount
