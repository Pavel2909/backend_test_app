import enum
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from warehouse_common.db import Operation

Code = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=64),
]
Quantity = Annotated[int, Field(strict=True, gt=0, le=2**31 - 1)]


class EventType(str, enum.Enum):
    RECEIPT = "inventory.receipt"
    ISSUE = "inventory.issue"

    @classmethod
    def for_operation(cls, operation: Operation) -> "EventType":
        return cls.RECEIPT if operation is Operation.RECEIPT else cls.ISSUE


CHANNELS = tuple(event_type.value for event_type in EventType)


class InventoryEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: Annotated[int, Field(strict=True, gt=0)]
    event_type: EventType
    warehouse: Code
    sku: Code
    qty: Quantity
    occurred_at: datetime
