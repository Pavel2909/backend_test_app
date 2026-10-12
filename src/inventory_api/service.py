import logging

from redis.exceptions import RedisError

from inventory_api.publisher import EventPublisher
from inventory_api.repository import InventoryRepository
from inventory_api.schemas import (
    OperationRequest,
    StockOperation,
    StockQuery,
    StockResponse,
    StockSummary,
)

logger = logging.getLogger(__name__)


class InventoryService:
    def __init__(self, repository: InventoryRepository, publisher: EventPublisher) -> None:
        self._repository = repository
        self._publisher = publisher

    async def register_receipt(self, request: OperationRequest) -> StockOperation:
        operation = await self._repository.add_receipt(request)
        await self._publish(operation)
        return operation

    async def register_issue(self, request: OperationRequest) -> StockOperation:
        operation = await self._repository.add_issue(request)
        await self._publish(operation)
        return operation

    async def get_stock(self, query: StockQuery) -> StockResponse:
        items = await self._repository.get_stock(query.warehouse, query.sku)
        return StockResponse(warehouse=query.warehouse, items=items)

    async def get_summary(self, top_n: int) -> StockSummary:
        return await self._repository.get_summary(top_n)

    async def _publish(self, operation: StockOperation) -> None:
        event = operation.to_event()
        try:
            await self._publisher.publish(event)
        except RedisError:
            logger.exception(
                "Failed to publish %s event %s", event.event_type.value, event.event_id
            )
