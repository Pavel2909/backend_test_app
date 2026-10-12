import asyncio
import contextlib
import logging

import sqlalchemy as sa
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from warehouse_common.db import outbox
from warehouse_common.events import InventoryEvent

logger = logging.getLogger(__name__)


async def enqueue(conn: AsyncConnection, event: InventoryEvent) -> None:
    await conn.execute(
        sa.insert(outbox).values(event_type=event.event_type.value, payload=event.model_dump_json())
    )


class OutboxRelay:
    """Publishes events from the outbox table to Redis with at-least-once semantics.

    A row is deleted only after Redis accepted it, in the same transaction that locked it,
    so a crash or Redis outage leaves undelivered rows in place for the next attempt.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        redis: Redis,
        *,
        batch_size: int = 100,
        poll_interval: float = 1.0,
        min_backoff: float = 0.5,
        max_backoff: float = 30.0,
    ) -> None:
        self._engine = engine
        self._redis = redis
        self._batch_size = batch_size
        self._poll_interval = poll_interval
        self._min_backoff = min_backoff
        self._max_backoff = max_backoff
        self._wakeup = asyncio.Event()

    def notify(self) -> None:
        self._wakeup.set()

    async def run_forever(self) -> None:
        backoff = self._min_backoff
        while True:
            self._wakeup.clear()
            try:
                await self.publish_pending()
            except (RedisError, SQLAlchemyError, OSError) as exc:
                logger.warning("Outbox relay failed: %r, retrying in %.1fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._max_backoff)
                continue
            backoff = self._min_backoff
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wakeup.wait(), self._poll_interval)

    async def publish_pending(self) -> int:
        total = 0
        while True:
            published = await self._publish_batch()
            total += published
            if published < self._batch_size:
                return total

    async def _publish_batch(self) -> int:
        stmt = (
            sa.select(outbox.c.id, outbox.c.event_type, outbox.c.payload)
            .order_by(outbox.c.id)
            .limit(self._batch_size)
            .with_for_update(skip_locked=True)
        )
        published: list[int] = []
        error: RedisError | None = None
        async with self._engine.begin() as conn:
            for row in await conn.execute(stmt):
                try:
                    await self._redis.publish(row.event_type, row.payload)
                except RedisError as exc:
                    error = exc
                    break
                published.append(row.id)
            if published:
                await conn.execute(sa.delete(outbox).where(outbox.c.id.in_(published)))
        if error is not None:
            raise error
        if published:
            logger.debug("Published %s outbox events", len(published))
        return len(published)
