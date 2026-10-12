from importlib.metadata import version
from typing import Any

from aiohttp import web
from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaMode, models_json_schema

from inventory_api.schemas import (
    ErrorResponse,
    InsufficientStockResponse,
    OperationRequest,
    StockOperation,
    StockQuery,
    StockResponse,
    StockSummary,
    SummaryQuery,
    ValidationErrorResponse,
)

SWAGGER_UI_URL = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14"

SWAGGER_UI_HTML = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Inventory API</title>
  <link rel="stylesheet" href="{SWAGGER_UI_URL}/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="{SWAGGER_UI_URL}/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({{url: "openapi.json", dom_id: "#swagger-ui"}});
  </script>
</body>
</html>
"""

MODELS: list[tuple[type[BaseModel], JsonSchemaMode]] = [
    (OperationRequest, "validation"),
    (StockOperation, "serialization"),
    (StockResponse, "serialization"),
    (StockSummary, "serialization"),
    (ErrorResponse, "serialization"),
    (ValidationErrorResponse, "serialization"),
    (InsufficientStockResponse, "serialization"),
]


def _query_parameters(model: type[BaseModel]) -> list[dict[str, Any]]:
    schema = model.model_json_schema()
    required = set(schema.get("required", ()))
    return [
        {"name": name, "in": "query", "required": name in required, "schema": field}
        for name, field in schema["properties"].items()
    ]


def build_spec() -> dict[str, Any]:
    refs, definitions = models_json_schema(MODELS, ref_template="#/components/schemas/{model}")

    def content(model: type[BaseModel], mode: JsonSchemaMode = "serialization") -> dict:
        return {"application/json": {"schema": refs[(model, mode)]}}

    def response(description: str, model: type[BaseModel]) -> dict:
        return {"description": description, "content": content(model)}

    invalid = response("Validation error", ValidationErrorResponse)
    operation_responses = {
        "201": response("Operation recorded", StockOperation),
        "400": response("Malformed JSON", ErrorResponse),
        "422": invalid,
    }
    request_body = {"required": True, "content": content(OperationRequest, "validation")}

    return {
        "openapi": "3.1.0",
        "info": {"title": "Inventory API", "version": version("warehouse-services")},
        "paths": {
            "/receipts": {
                "post": {
                    "summary": "Register a stock receipt",
                    "requestBody": request_body,
                    "responses": operation_responses,
                }
            },
            "/issues": {
                "post": {
                    "summary": "Register a stock issue",
                    "requestBody": request_body,
                    "responses": {
                        **operation_responses,
                        "409": response("Insufficient stock", InsufficientStockResponse),
                    },
                }
            },
            "/stock": {
                "get": {
                    "summary": "Stock balances of a warehouse",
                    "parameters": _query_parameters(StockQuery),
                    "responses": {"200": response("Stock balances", StockResponse), "422": invalid},
                }
            },
            "/stock/summary": {
                "get": {
                    "summary": "Totals per warehouse and top SKUs",
                    "parameters": _query_parameters(SummaryQuery),
                    "responses": {"200": response("Stock summary", StockSummary), "422": invalid},
                }
            },
        },
        "components": {"schemas": definitions.get("$defs", {})},
    }


def routes() -> list[web.RouteDef]:
    spec = build_spec()

    async def openapi_json(_: web.Request) -> web.Response:
        return web.json_response(spec)

    async def swagger_ui(_: web.Request) -> web.Response:
        return web.Response(text=SWAGGER_UI_HTML, content_type="text/html")

    return [web.get("/openapi.json", openapi_json), web.get("/docs", swagger_ui)]
