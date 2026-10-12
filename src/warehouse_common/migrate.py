import argparse

from alembic import command
from alembic.config import Config

from warehouse_common.settings import Settings, setup_logging


def make_config(database_url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", "warehouse_common:migrations")
    config.attributes["database_url"] = database_url or Settings.from_env().database_url
    return config


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="warehouse-migrate")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("upgrade").add_argument("revision", nargs="?", default="head")
    commands.add_parser("downgrade").add_argument("revision")
    commands.add_parser("current")
    args = parser.parse_args(argv)

    setup_logging(Settings.from_env().log_level)
    config = make_config()
    if args.command == "current":
        command.current(config)
    else:
        getattr(command, args.command)(config, args.revision)


if __name__ == "__main__":
    main()
