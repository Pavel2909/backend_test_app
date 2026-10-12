from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from warehouse_common.db import Operation
from warehouse_common.events import Code, EventType, InventoryEvent, Quantity


class OperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: Code
    qty: Quantity
    warehouse: Code


class StockQuery(BaseModel):
    warehouse: Annotated[str, Field(min_length=1, max_length=64)]
    sku: Annotated[str | None, Field(min_length=1, max_length=64)] = None


class SummaryQuery(BaseModel):
    top_n: Annotated[int, Field(ge=1, le=100)] = 5


class StockOperation(BaseModel):
    id: int
    operation: Operation
    warehouse: str
    sku: str
    qty: int
    created_at: datetime

    def to_event(self) -> InventoryEvent:
        return InventoryEvent(
            event_id=self.id,
            event_type=EventType.for_operation(self.operation),
            warehouse=self.warehouse,
            sku=self.sku,
            qty=self.qty,
            occurred_at=self.created_at,
        )


class StockItem(BaseModel):
    sku: str
    qty: int


class StockResponse(BaseModel):
    warehouse: str
    items: list[StockItem]


class WarehouseSummary(BaseModel):
    warehouse: str
    total_qty: int
    sku_count: int


class SkuTotal(BaseModel):
    sku: str
    total_qty: int


class StockSummary(BaseModel):
    warehouses: list[WarehouseSummary]
    top_skus: list[SkuTotal]
