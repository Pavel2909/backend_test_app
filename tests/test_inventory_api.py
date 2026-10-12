import asyncio
import json

import pytest
from redis.asyncio import Redis

from warehouse_common.events import CHANNELS, EventType, InventoryEvent


async def post(client, path: str, sku: str, qty: int, warehouse: str = "WH-1"):
    return await client.post(path, json={"sku": sku, "qty": qty, "warehouse": warehouse})


async def test_receipts_and_issues_change_stock(client):
    response = await post(client, "/receipts", "A-100", 50)
    assert response.status == 201
    body = await response.json()
    assert body["operation"] == "receipt"
    assert body["qty"] == 50

    assert (await post(client, "/receipts", "B-200", 10)).status == 201
    assert (await post(client, "/receipts", "A-100", 5, warehouse="WH-2")).status == 201
    response = await post(client, "/issues", "A-100", 20)
    assert response.status == 201
    assert (await response.json())["operation"] == "issue"

    response = await client.get("/stock", params={"warehouse": "WH-1"})
    assert response.status == 200
    assert await response.json() == {
        "warehouse": "WH-1",
        "items": [{"sku": "A-100", "qty": 30}, {"sku": "B-200", "qty": 10}],
    }

    response = await client.get("/stock", params={"warehouse": "WH-1", "sku": "B-200"})
    assert (await response.json())["items"] == [{"sku": "B-200", "qty": 10}]


async def test_issue_rejected_when_stock_is_insufficient(client):
    await post(client, "/receipts", "A-100", 5)

    response = await post(client, "/issues", "A-100", 6)

    assert response.status == 409
    assert await response.json() == {
        "error": "insufficient_stock",
        "warehouse": "WH-1",
        "sku": "A-100",
        "requested": 6,
        "available": 5,
    }
    stock = await (await client.get("/stock", params={"warehouse": "WH-1"})).json()
    assert stock["items"] == [{"sku": "A-100", "qty": 5}]


async def test_concurrent_issues_never_oversell(client):
    await post(client, "/receipts", "A-100", 10)

    responses = await asyncio.gather(*(post(client, "/issues", "A-100", 3) for _ in range(6)))

    assert sorted(response.status for response in responses) == [201] * 3 + [409] * 3
    stock = await (await client.get("/stock", params={"warehouse": "WH-1"})).json()
    assert stock["items"] == [{"sku": "A-100", "qty": 1}]


@pytest.mark.parametrize(
    "payload",
    [
        {"sku": "A-100", "qty": 0, "warehouse": "WH-1"},
        {"sku": "A-100", "qty": -1, "warehouse": "WH-1"},
        {"sku": "A-100", "qty": "5", "warehouse": "WH-1"},
        {"sku": "A-100", "qty": 1.5, "warehouse": "WH-1"},
        {"sku": "", "qty": 5, "warehouse": "WH-1"},
        {"sku": "A-100", "qty": 5},
        {"sku": "A-100", "qty": 5, "warehouse": "WH-1", "extra": True},
        ["A-100", 5, "WH-1"],
    ],
)
async def test_invalid_operation_payload(client, payload):
    response = await client.post("/receipts", json=payload)

    assert response.status == 422
    assert (await response.json())["error"] == "validation_error"


async def test_malformed_json(client):
    response = await client.post(
        "/issues", data="{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status == 400


async def test_stock_requires_warehouse(client):
    response = await client.get("/stock")

    assert response.status == 422


async def test_summary(client):
    for sku, qty, warehouse in [
        ("A-100", 50, "WH-1"),
        ("B-200", 30, "WH-1"),
        ("C-300", 5, "WH-1"),
        ("A-100", 40, "WH-2"),
        ("D-400", 70, "WH-2"),
    ]:
        assert (await post(client, "/receipts", sku, qty, warehouse)).status == 201
    assert (await post(client, "/issues", "C-300", 5)).status == 201

    response = await client.get("/stock/summary", params={"top_n": 2})

    assert response.status == 200
    assert await response.json() == {
        "warehouses": [
            {"warehouse": "WH-1", "total_qty": 80, "sku_count": 2},
            {"warehouse": "WH-2", "total_qty": 110, "sku_count": 2},
        ],
        "top_skus": [
            {"sku": "A-100", "total_qty": 90},
            {"sku": "D-400", "total_qty": 70},
        ],
    }

    default = await (await client.get("/stock/summary")).json()
    assert [item["sku"] for item in default["top_skus"]] == ["A-100", "D-400", "B-200"]


@pytest.mark.parametrize("top_n", ["0", "101", "abc"])
async def test_summary_rejects_invalid_top_n(client, top_n):
    response = await client.get("/stock/summary", params={"top_n": top_n})

    assert response.status == 422


async def test_operations_are_published(client, redis: Redis):
    async with redis.pubsub(ignore_subscribe_messages=True) as pubsub:
        await pubsub.subscribe(*CHANNELS)

        receipt = await (await post(client, "/receipts", "A-100", 50)).json()
        issue = await (await post(client, "/issues", "A-100", 20)).json()

        messages = [await asyncio.wait_for(_next_message(pubsub), 5) for _ in range(2)]

    events = [InventoryEvent.model_validate_json(message["data"]) for message in messages]
    assert [message["channel"] for message in messages] == [
        EventType.RECEIPT.value,
        EventType.ISSUE.value,
    ]
    assert [event.event_id for event in events] == [receipt["id"], issue["id"]]
    assert json.loads(messages[1]["data"])["qty"] == 20


async def _next_message(pubsub) -> dict:
    while True:
        message = await pubsub.get_message(timeout=1)
        if message is not None:
            return message
