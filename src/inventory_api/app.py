from aiohttp import web

from inventory_api.handlers import InventoryHandlers, error_middleware
from inventory_api.publisher import EventPublisher
from inventory_api.repository import InventoryRepository
from inventory_api.service import InventoryService
from warehouse_common.broker import create_redis
from warehouse_common.db import create_engine
from warehouse_common.settings import Settings


def create_app(settings: Settings) -> web.Application:
    engine = create_engine(settings)
    redis = create_redis(settings)
    service = InventoryService(InventoryRepository(engine), EventPublisher(redis))

    async def close_resources(_: web.Application) -> None:
        await redis.aclose()
        await engine.dispose()

    app = web.Application(middlewares=[error_middleware])
    app.add_routes(InventoryHandlers(service).routes())
    app.on_cleanup.append(close_resources)
    return app
