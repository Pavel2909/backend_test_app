from aiohttp import web

from inventory_api.app import create_app
from warehouse_common.settings import Settings, setup_logging


def main() -> None:
    settings = Settings.from_env()
    setup_logging(settings.log_level)
    web.run_app(create_app(settings), host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
