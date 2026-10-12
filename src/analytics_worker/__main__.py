import asyncio
import contextlib
import signal

from analytics_worker.consumer import EventConsumer
from analytics_worker.repository import StockAggRepository
from warehouse_common.broker import create_redis
from warehouse_common.db import create_engine
from warehouse_common.settings import Settings, setup_logging


async def run(settings: Settings) -> None:
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, task.cancel)

    engine = create_engine(settings)
    redis = create_redis(settings, decode_responses=True)
    try:
        await EventConsumer(redis, StockAggRepository(engine)).run_forever()
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    settings = Settings.from_env()
    setup_logging(settings.log_level)
    with contextlib.suppress(asyncio.CancelledError, KeyboardInterrupt):
        asyncio.run(run(settings))


if __name__ == "__main__":
    main()
