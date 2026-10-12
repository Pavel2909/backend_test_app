from redis.asyncio import Redis

from warehouse_common.events import InventoryEvent


class EventPublisher:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, event: InventoryEvent) -> int:
        return await self._redis.publish(event.event_type.value, event.model_dump_json())
