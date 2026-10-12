import asyncio
import logging

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from analytics_worker.repository import StockAggRepository
from warehouse_common.events import CHANNELS, InventoryEvent

logger = logging.getLogger(__name__)


class EventConsumer:
    def __init__(
        self,
        redis: Redis,
        repository: StockAggRepository,
        *,
        min_backoff: float = 0.5,
        max_backoff: float = 30.0,
    ) -> None:
        self._redis = redis
        self._repository = repository
        self._min_backoff = min_backoff
        self._max_backoff = max_backoff
        self._backoff = min_backoff
        self.ready = asyncio.Event()

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run()
            except (RedisError, SQLAlchemyError, OSError) as exc:
                self.ready.clear()
                logger.warning("Consumer failed: %r, restarting in %.1fs", exc, self._backoff)
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, self._max_backoff)

    async def run(self) -> None:
        async with self._redis.pubsub(ignore_subscribe_messages=True) as pubsub:
            await pubsub.subscribe(*CHANNELS)
            rebuilt = await self._repository.rebuild()
            logger.info("Subscribed to %s, rebuilt %s aggregates", ", ".join(CHANNELS), rebuilt)
            self._backoff = self._min_backoff
            self.ready.set()
            async for message in pubsub.listen():
                if message["type"] == "message":
                    await self.handle(message["channel"], message["data"])

    async def handle(self, channel: str | bytes, data: str | bytes) -> bool:
        if isinstance(channel, bytes):
            channel = channel.decode()
        try:
            event = InventoryEvent.model_validate_json(data)
        except ValidationError as exc:
            logger.warning("Rejected malformed message from %s: %s", channel, exc.errors())
            return False
        if event.event_type.value != channel:
            logger.warning(
                "Rejected event %s: type %s does not match channel %s",
                event.event_id,
                event.event_type.value,
                channel,
            )
            return False
        await self._repository.refresh(event.warehouse, event.sku)
        logger.debug("Applied event %s for %s/%s", event.event_id, event.warehouse, event.sku)
        return True
