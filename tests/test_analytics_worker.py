import asyncio
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from analytics_worker.consumer import EventConsumer
from inventory_api.repository import InventoryRepository
from inventory_api.schemas import OperationRequest
from warehouse_common.db import stock_agg
from warehouse_common.events import EventType, InventoryEvent


async def fetch_aggregates(engine: AsyncEngine) -> list[dict]:
    stmt = sa.select(
        stock_agg.c.warehouse,
        stock_agg.c.sku,
        stock_agg.c.qty,
        stock_agg.c.received_qty,
        stock_agg.c.issued_qty,
        stock_agg.c.events_count,
    ).order_by(stock_agg.c.warehouse, stock_agg.c.sku)
    async with engine.connect() as conn:
        return [row._asdict() for row in await conn.execute(stmt)]


async def record(engine: AsyncEngine, issue: bool, sku: str, qty: int, warehouse: str = "WH-1"):
    repository = InventoryRepository(engine)
    request = OperationRequest(sku=sku, qty=qty, warehouse=warehouse)
    operation = await (repository.add_issue if issue else repository.add_receipt)(request)
    return operation.to_event()


async def test_events_update_single_aggregate_row(engine, consumer: EventConsumer):
    first = await record(engine, False, "A-100", 50)
    assert await consumer.handle(first.event_type.value, first.model_dump_json())

    second = await record(engine, True, "A-100", 20)
    assert await consumer.handle(second.event_type.value, second.model_dump_json())
    assert await consumer.handle(second.event_type.value, second.model_dump_json())

    assert await fetch_aggregates(engine) == [
        {
            "warehouse": "WH-1",
            "sku": "A-100",
            "qty": 30,
            "received_qty": 50,
            "issued_qty": 20,
            "events_count": 2,
        }
    ]


@pytest.mark.parametrize(
    ("channel", "data"),
    [
        (EventType.RECEIPT.value, "not json"),
        (EventType.RECEIPT.value, '{"event_type": "inventory.receipt"}'),
        (
            EventType.RECEIPT.value,
            '{"event_id": 1, "event_type": "inventory.unknown", "warehouse": "WH-1",'
            ' "sku": "A-100", "qty": 1, "occurred_at": "2026-01-01T00:00:00Z"}',
        ),
        (
            EventType.ISSUE.value,
            InventoryEvent(
                event_id=1,
                event_type=EventType.RECEIPT,
                warehouse="WH-1",
                sku="A-100",
                qty=1,
                occurred_at=datetime.now(timezone.utc),
            ).model_dump_json(),
        ),
    ],
)
async def test_invalid_messages_are_rejected(engine, consumer: EventConsumer, channel, data):
    await record(engine, False, "A-100", 1)

    assert not await consumer.handle(channel, data)
    assert await fetch_aggregates(engine) == []


async def test_startup_rebuilds_aggregates_for_missed_events(engine, consumer: EventConsumer):
    await record(engine, False, "A-100", 10)
    await record(engine, False, "B-200", 7, warehouse="WH-2")
    await record(engine, True, "A-100", 4)

    task = asyncio.create_task(consumer.run())
    try:
        await asyncio.wait_for(consumer.ready.wait(), 5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    rows = await fetch_aggregates(engine)
    assert [(row["warehouse"], row["sku"], row["qty"]) for row in rows] == [
        ("WH-1", "A-100", 6),
        ("WH-2", "B-200", 7),
    ]


async def test_end_to_end_through_pubsub(client, engine, consumer: EventConsumer):
    task = asyncio.create_task(consumer.run_forever())
    try:
        await asyncio.wait_for(consumer.ready.wait(), 5)

        for path, qty in [("/receipts", 50), ("/receipts", 15), ("/issues", 20)]:
            response = await client.post(
                path, json={"sku": "A-100", "qty": qty, "warehouse": "WH-1"}
            )
            assert response.status == 201

        expected = {"warehouse": "WH-1", "sku": "A-100", "qty": 45, "events_count": 3}
        rows = await asyncio.wait_for(wait_for_aggregates(engine, expected), 5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert len(rows) == 1


async def wait_for_aggregates(engine: AsyncEngine, expected: dict) -> list[dict]:
    while True:
        rows = await fetch_aggregates(engine)
        if rows and {key: rows[0][key] for key in expected} == expected:
            return rows
        await asyncio.sleep(0.05)
