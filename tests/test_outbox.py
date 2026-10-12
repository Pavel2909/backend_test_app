import asyncio
from collections.abc import Awaitable, Callable

import pytest
import sqlalchemy as sa
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncEngine

from inventory_api.outbox import OutboxRelay
from inventory_api.repository import InsufficientStockError, InventoryRepository
from inventory_api.schemas import OperationRequest
from warehouse_common.db import outbox
from warehouse_common.events import CHANNELS, InventoryEvent


class FlakyRedis:
    def __init__(self, redis: Redis, fail_after: int) -> None:
        self._redis = redis
        self._fail_after = fail_after
        self.calls = 0
        self.retried = asyncio.Event()

    async def recover(self) -> None:
        self._fail_after = float("inf")

    async def publish(self, channel: str, payload: str) -> int:
        self.calls += 1
        if self.calls > 1:
            self.retried.set()
        if self.calls > self._fail_after:
            raise RedisConnectionError("redis is down")
        return await self._redis.publish(channel, payload)


async def fetch_outbox(engine: AsyncEngine) -> list[InventoryEvent]:
    async with engine.connect() as conn:
        rows = await conn.execute(sa.select(outbox.c.payload).order_by(outbox.c.id))
        return [InventoryEvent.model_validate_json(row.payload) for row in rows]


async def wait_until_drained(engine: AsyncEngine, timeout: float = 5) -> None:
    for _ in range(int(timeout / 0.05)):
        if not await fetch_outbox(engine):
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("outbox was not drained")


async def record(engine: AsyncEngine, *quantities: int) -> list[int]:
    repository = InventoryRepository(engine)
    request = [OperationRequest(sku="A-100", qty=qty, warehouse="WH-1") for qty in quantities]
    return [(await repository.add_receipt(item)).id for item in request]


async def receive(
    redis: Redis, count: int, action: Callable[[], Awaitable[object]]
) -> list[InventoryEvent]:
    async with redis.pubsub(ignore_subscribe_messages=True) as pubsub:
        await pubsub.subscribe(*CHANNELS)
        await action()
        messages = []
        while len(messages) < count:
            message = await asyncio.wait_for(pubsub.get_message(timeout=1), 5)
            if message is not None:
                messages.append(message)
    return [InventoryEvent.model_validate_json(message["data"]) for message in messages]


async def test_operation_and_outbox_event_are_written_atomically(engine: AsyncEngine):
    repository = InventoryRepository(engine)
    receipt = await repository.add_receipt(OperationRequest(sku="A-100", qty=5, warehouse="WH-1"))

    with pytest.raises(InsufficientStockError):
        await repository.add_issue(OperationRequest(sku="A-100", qty=6, warehouse="WH-1"))

    assert await fetch_outbox(engine) == [receipt.to_event()]


async def test_relay_publishes_and_removes_pending_events(engine: AsyncEngine, redis: Redis):
    ids = await record(engine, 1, 2, 3)
    relay = OutboxRelay(engine, redis, batch_size=2)

    published = 0

    async def publish() -> None:
        nonlocal published
        published = await relay.publish_pending()

    events = await receive(redis, 3, publish)

    assert published == 3
    assert [event.event_id for event in events] == ids
    assert await fetch_outbox(engine) == []


async def test_undelivered_events_stay_in_outbox_until_redis_recovers(
    engine: AsyncEngine, redis: Redis
):
    ids = await record(engine, 1, 2, 3)

    with pytest.raises(RedisConnectionError):
        await OutboxRelay(engine, FlakyRedis(redis, fail_after=1)).publish_pending()
    assert [event.event_id for event in await fetch_outbox(engine)] == ids[1:]

    with pytest.raises(RedisConnectionError):
        await OutboxRelay(engine, FlakyRedis(redis, fail_after=0)).publish_pending()
    assert [event.event_id for event in await fetch_outbox(engine)] == ids[1:]

    relay = OutboxRelay(engine, redis)
    events = await receive(redis, 2, relay.publish_pending)

    assert [event.event_id for event in events] == ids[1:]
    assert await fetch_outbox(engine) == []


async def test_relay_retries_in_background_until_redis_recovers(engine: AsyncEngine, redis: Redis):
    [event_id] = await record(engine, 1)
    flaky = FlakyRedis(redis, fail_after=0)
    relay = OutboxRelay(engine, flaky, poll_interval=0.05, min_backoff=0.05)

    task = asyncio.create_task(relay.run_forever())
    try:
        await asyncio.wait_for(flaky.retried.wait(), 5)
        events = await receive(redis, 1, flaky.recover)
        await wait_until_drained(engine)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert [event.event_id for event in events] == [event_id]
