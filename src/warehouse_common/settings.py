import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = "postgresql+asyncpg://inventory:inventory@localhost:5432/inventory"
    redis_url: str = "redis://localhost:6379/0"
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    db_pool_size: int = 10
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            database_url=os.getenv("DATABASE_URL", defaults.database_url),
            redis_url=os.getenv("REDIS_URL", defaults.redis_url),
            api_host=os.getenv("API_HOST", defaults.api_host),
            api_port=int(os.getenv("API_PORT", defaults.api_port)),
            db_pool_size=int(os.getenv("DB_POOL_SIZE", defaults.db_pool_size)),
            log_level=os.getenv("LOG_LEVEL", defaults.log_level).upper(),
        )


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
