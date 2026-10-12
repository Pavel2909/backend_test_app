import asyncio
import os
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from alembic import command
from redis.asyncio import Redis
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from analytics_worker.consumer import EventConsumer
from analytics_worker.repository import StockAggRepository
from inventory_api.app import create_app
from warehouse_common.broker import create_redis
from warehouse_common.db import create_engine
from warehouse_common.migrate import make_config
from warehouse_common.settings import Settings

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://inventory:inventory@localhost:5432/inventory_test",
)
TEST_REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")


async def _ensure_database(database_url: str) -> None:
    url = make_url(database_url)
    engine = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            )
            if not exists:
                await conn.execute(sa.text(f'CREATE DATABASE "{url.database}"'))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(database_url=TEST_DATABASE_URL, redis_url=TEST_REDIS_URL, db_pool_size=5)


@pytest.fixture(scope="session", autouse=True)
def migrated_database(settings: Settings) -> None:
    asyncio.run(_ensure_database(settings.database_url))
    config = make_config(settings.database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(settings)
    async with engine.begin() as conn:
        await conn.execute(sa.text("TRUNCATE stock_events, stock_agg, outbox RESTART IDENTITY"))
    yield engine
    await engine.dispose()


@pytest.fixture
async def redis(settings: Settings) -> AsyncIterator[Redis]:
    client = create_redis(settings, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
async def client(aiohttp_client, settings: Settings, engine: AsyncEngine):
    return await aiohttp_client(create_app(settings))


@pytest.fixture
def consumer(redis: Redis, engine: AsyncEngine) -> EventConsumer:
    return EventConsumer(redis, StockAggRepository(engine))
