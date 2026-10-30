"""Operator commands for the database. Connects with the server's own settings.

    python -m wordle.db migrate                  apply pending migrations
    python -m wordle.db data-scripts             list data scripts and whether each has run
    python -m wordle.db run-data-script NAME     run one data script

Opening the database migrates first, so a data script always runs against the
schema it was written for.
"""

from __future__ import annotations

import argparse
import sys

from ..config import get_settings
from . import Database, DataScriptError, data_scripts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m wordle.db")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply pending migrations")
    commands.add_parser("data-scripts", help="list data scripts and whether each has run")
    run = commands.add_parser("run-data-script", help="run one data script")
    run.add_argument("name", help="script name without .sql, e.g. 0001_seed_scoring_version_1")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.database_url:
        print("WORDLE_DATABASE_URL is not set", file=sys.stderr)
        return 2
    database = Database(settings.database_url, password=settings.database_password)
    try:
        if args.command == "migrate":
            print("Schema is up to date")
        elif args.command == "data-scripts":
            done = database.data_scripts_run()
            for name in sorted(data_scripts()):
                print(f"{'ran ' if name in done else 'todo'}  {name}")
        else:
            try:
                database.run_data_script(args.name)
            except DataScriptError as exc:
                print(exc, file=sys.stderr)
                return 1
            print(f"Ran {args.name}")
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
