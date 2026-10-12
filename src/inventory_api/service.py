from inventory_api.outbox import OutboxRelay
from inventory_api.repository import InventoryRepository
from inventory_api.schemas import (
    OperationRequest,
    StockOperation,
    StockQuery,
    StockResponse,
    StockSummary,
)


class InventoryService:
    def __init__(self, repository: InventoryRepository, outbox: OutboxRelay) -> None:
        self._repository = repository
        self._outbox = outbox

    async def register_receipt(self, request: OperationRequest) -> StockOperation:
        operation = await self._repository.add_receipt(request)
        self._outbox.notify()
        return operation

    async def register_issue(self, request: OperationRequest) -> StockOperation:
        operation = await self._repository.add_issue(request)
        self._outbox.notify()
        return operation

    async def get_stock(self, query: StockQuery) -> StockResponse:
        items = await self._repository.get_stock(query.warehouse, query.sku)
        return StockResponse(warehouse=query.warehouse, items=items)

    async def get_summary(self, top_n: int) -> StockSummary:
        return await self._repository.get_summary(top_n)
