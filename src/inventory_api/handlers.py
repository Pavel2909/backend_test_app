import json
from typing import Any

from aiohttp import web
from pydantic import BaseModel, ValidationError

from inventory_api.repository import InsufficientStockError
from inventory_api.schemas import (
    ErrorResponse,
    InsufficientStockResponse,
    OperationRequest,
    StockQuery,
    SummaryQuery,
    ValidationErrorResponse,
)
from inventory_api.service import InventoryService


class MalformedJSONError(Exception):
    pass


def _error_response(body: BaseModel, status: int) -> web.Response:
    return web.json_response(body.model_dump(mode="json"), status=status)


@web.middleware
async def error_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    try:
        return await handler(request)
    except MalformedJSONError:
        return _error_response(ErrorResponse(error="malformed_json"), 400)
    except ValidationError as exc:
        details = exc.errors(include_url=False, include_context=False, include_input=False)
        return _error_response(ValidationErrorResponse(details=details), 422)
    except InsufficientStockError as exc:
        return _error_response(
            InsufficientStockResponse(
                warehouse=exc.warehouse,
                sku=exc.sku,
                requested=exc.requested,
                available=exc.available,
            ),
            409,
        )


async def _read_json(request: web.Request) -> Any:
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MalformedJSONError from exc


class InventoryHandlers:
    def __init__(self, service: InventoryService) -> None:
        self._service = service

    def routes(self) -> list[web.RouteDef]:
        return [
            web.post("/receipts", self.create_receipt),
            web.post("/issues", self.create_issue),
            web.get("/stock", self.get_stock),
            web.get("/stock/summary", self.get_summary),
        ]

    async def create_receipt(self, request: web.Request) -> web.Response:
        payload = OperationRequest.model_validate(await _read_json(request))
        operation = await self._service.register_receipt(payload)
        return web.json_response(operation.model_dump(mode="json"), status=201)

    async def create_issue(self, request: web.Request) -> web.Response:
        payload = OperationRequest.model_validate(await _read_json(request))
        operation = await self._service.register_issue(payload)
        return web.json_response(operation.model_dump(mode="json"), status=201)

    async def get_stock(self, request: web.Request) -> web.Response:
        query = StockQuery.model_validate(dict(request.query))
        stock = await self._service.get_stock(query)
        return web.json_response(stock.model_dump(mode="json"))

    async def get_summary(self, request: web.Request) -> web.Response:
        query = SummaryQuery.model_validate(dict(request.query))
        summary = await self._service.get_summary(query.top_n)
        return web.json_response(summary.model_dump(mode="json"))
