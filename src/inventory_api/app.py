import asyncio
from collections.abc import AsyncIterator

from aiohttp import web

from inventory_api.handlers import InventoryHandlers, error_middleware
from inventory_api.outbox import OutboxRelay
from inventory_api.repository import InventoryRepository
from inventory_api.service import InventoryService
from warehouse_common.broker import create_redis
from warehouse_common.db import create_engine
from warehouse_common.settings import Settings


def create_app(settings: Settings) -> web.Application:
    engine = create_engine(settings)
    redis = create_redis(settings)
    relay = OutboxRelay(
        engine,
        redis,
        batch_size=settings.outbox_batch_size,
        poll_interval=settings.outbox_poll_interval,
    )
    service = InventoryService(InventoryRepository(engine), relay)

    async def lifespan(_: web.Application) -> AsyncIterator[None]:
        relay_task = asyncio.create_task(relay.run_forever())
        yield
        relay_task.cancel()
        await asyncio.gather(relay_task, return_exceptions=True)
        await redis.aclose()
        await engine.dispose()

    app = web.Application(middlewares=[error_middleware])
    app.add_routes(InventoryHandlers(service).routes())
    app.cleanup_ctx.append(lifespan)
    return app
