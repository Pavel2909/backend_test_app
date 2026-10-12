from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from warehouse_common.settings import Settings


def create_redis(settings: Settings, *, decode_responses: bool = False) -> Redis:
    return Redis.from_url(
        settings.redis_url,
        decode_responses=decode_responses,
        retry=Retry(ExponentialBackoff(cap=1.0, base=0.05), retries=3),
        retry_on_error=[RedisConnectionError, RedisTimeoutError],
        health_check_interval=30,
    )
