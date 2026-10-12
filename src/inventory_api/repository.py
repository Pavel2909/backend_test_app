import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from inventory_api.schemas import (
    OperationRequest,
    SkuTotal,
    StockItem,
    StockOperation,
    StockSummary,
    WarehouseSummary,
)
from warehouse_common.db import Operation, signed_qty, stock_events


class InsufficientStockError(Exception):
    def __init__(self, warehouse: str, sku: str, requested: int, available: int) -> None:
        super().__init__(f"Insufficient stock of {sku} in {warehouse}")
        self.warehouse = warehouse
        self.sku = sku
        self.requested = requested
        self.available = available


def _sum_bigint(expression: sa.ColumnElement[int]) -> sa.ColumnElement[int]:
    return sa.cast(sa.func.coalesce(sa.func.sum(expression), 0), sa.BigInteger)


class InventoryRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def add_receipt(self, request: OperationRequest) -> StockOperation:
        async with self._engine.begin() as conn:
            return await self._insert(conn, Operation.RECEIPT, request)

    async def add_issue(self, request: OperationRequest) -> StockOperation:
        async with self._engine.begin() as conn:
            await self._lock_position(conn, request.warehouse, request.sku)
            available = await conn.scalar(
                sa.select(_sum_bigint(signed_qty())).where(
                    stock_events.c.warehouse == request.warehouse,
                    stock_events.c.sku == request.sku,
                )
            )
            if available < request.qty:
                raise InsufficientStockError(request.warehouse, request.sku, request.qty, available)
            return await self._insert(conn, Operation.ISSUE, request)

    async def get_stock(self, warehouse: str, sku: str | None = None) -> list[StockItem]:
        qty = _sum_bigint(signed_qty()).label("qty")
        stmt = (
            sa.select(stock_events.c.sku, qty)
            .where(stock_events.c.warehouse == warehouse)
            .group_by(stock_events.c.sku)
            .order_by(stock_events.c.sku)
        )
        if sku is not None:
            stmt = stmt.where(stock_events.c.sku == sku)
        async with self._engine.connect() as conn:
            rows = await conn.execute(stmt)
        return [StockItem(sku=row.sku, qty=row.qty) for row in rows]

    async def get_summary(self, top_n: int) -> StockSummary:
        balances = (
            sa.select(
                stock_events.c.warehouse,
                stock_events.c.sku,
                _sum_bigint(signed_qty()).label("qty"),
            )
            .group_by(stock_events.c.warehouse, stock_events.c.sku)
            .subquery("balances")
        )
        warehouses_stmt = (
            sa.select(
                balances.c.warehouse,
                _sum_bigint(balances.c.qty).label("total_qty"),
                sa.func.count().filter(balances.c.qty > 0).label("sku_count"),
            )
            .group_by(balances.c.warehouse)
            .order_by(balances.c.warehouse)
        )
        sku_total = _sum_bigint(balances.c.qty).label("total_qty")
        top_skus_stmt = (
            sa.select(balances.c.sku, sku_total)
            .group_by(balances.c.sku)
            .having(sku_total > 0)
            .order_by(sku_total.desc(), balances.c.sku)
            .limit(top_n)
        )
        async with self._engine.connect() as conn:
            conn = await conn.execution_options(isolation_level="REPEATABLE READ")
            async with conn.begin():
                warehouses = await conn.execute(warehouses_stmt)
                top_skus = await conn.execute(top_skus_stmt)
        return StockSummary(
            warehouses=[
                WarehouseSummary(
                    warehouse=row.warehouse, total_qty=row.total_qty, sku_count=row.sku_count
                )
                for row in warehouses
            ],
            top_skus=[SkuTotal(sku=row.sku, total_qty=row.total_qty) for row in top_skus],
        )

    @staticmethod
    async def _lock_position(conn: AsyncConnection, warehouse: str, sku: str) -> None:
        key = sa.func.hashtextextended(f"{warehouse}\x1f{sku}", 0)
        await conn.execute(sa.select(sa.func.pg_advisory_xact_lock(key)))

    @staticmethod
    async def _insert(
        conn: AsyncConnection, operation: Operation, request: OperationRequest
    ) -> StockOperation:
        stmt = (
            sa.insert(stock_events)
            .values(
                operation=operation,
                warehouse=request.warehouse,
                sku=request.sku,
                qty=request.qty,
            )
            .returning(*stock_events.c)
        )
        row = (await conn.execute(stmt)).one()
        return StockOperation.model_validate(row._asdict())
