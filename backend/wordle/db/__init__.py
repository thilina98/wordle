"""The PostgreSQL database every module shares: one pool, one schema history.

Schema and data are kept apart on purpose:

- **Migrations** (`migrations/`) change the schema only: tables, columns,
  constraints, indexes. They run on their own when the server starts.
- **Data scripts** (`data_scripts/`) change what is in the tables: seed rows,
  backfills, re-scoring. They never run on their own; an operator runs each
  one by name (see `__main__.py`), and the run is recorded in
  `data_script_runs`.

Only adapters import this package, so anonymous-only play never loads the
database driver.
"""

from __future__ import annotations

from importlib import resources

import psycopg
from psycopg_pool import ConnectionPool

#: Any constant works; it only has to be the same in every process, so two
#: servers starting at once do not both run a migration.
_MIGRATION_LOCK = 0x776F72646C65  # "wordle"

_CONNECT_TIMEOUT = 5
_POOL_TIMEOUT = 5.0


class DataScriptError(Exception):
    """A data script is unknown, or has already been run."""


def _sql_files(folder: str) -> list[tuple[str, str]]:
    """(file name, sql) for every .sql file in a folder of this package, in name order."""
    files = resources.files(__package__).joinpath(folder)
    found = [
        (entry.name, entry.read_text(encoding="utf-8"))
        for entry in files.iterdir()
        if entry.name.endswith(".sql")
    ]
    return sorted(found)


def _migrations() -> list[tuple[int, str]]:
    """(version, sql) for every migration shipped, oldest first."""
    return [(int(name.split("_", 1)[0]), sql) for name, sql in _sql_files("migrations")]


def data_scripts() -> dict[str, str]:
    """Every data script shipped, by name without the .sql suffix."""
    return {name.removesuffix(".sql"): sql for name, sql in _sql_files("data_scripts")}


class Database:
    """A connection pool, with the schema brought up to date on opening.

    Opening one migrates, so the server refuses to start against a database it
    cannot use rather than failing one request at a time.
    """

    def __init__(self, url: str, *, password: str | None = None, max_connections: int = 5) -> None:
        kwargs: dict[str, object] = {"connect_timeout": _CONNECT_TIMEOUT, "autocommit": True}
        if password:
            kwargs["password"] = password
        self.pool = ConnectionPool(
            url,
            kwargs=kwargs,
            min_size=1,
            max_size=max_connections,
            timeout=_POOL_TIMEOUT,
            open=False,
        )
        self.pool.open(wait=True, timeout=_CONNECT_TIMEOUT * 2)
        self.migrate()

    def close(self) -> None:
        self.pool.close()

    def migrate(self) -> None:
        """Apply every migration not yet applied, each in its own transaction."""
        with self.pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK,))
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version    INTEGER     PRIMARY KEY,"
                " applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            for version, sql in _migrations():
                if version in applied:
                    continue
                with conn.transaction():
                    conn.execute(sql)
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))

    def run_data_script(self, name: str) -> None:
        """Run one data script and record it. Raises DataScriptError if unknown or already run.

        Script and record commit together, so a failed script leaves no record
        and can simply be run again.
        """
        scripts = data_scripts()
        if name not in scripts:
            known = ", ".join(sorted(scripts)) or "none"
            raise DataScriptError(f"No data script named {name!r}. Known: {known}")
        with self.pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK,))
            try:
                conn.execute("INSERT INTO data_script_runs (name) VALUES (%s)", (name,))
            except psycopg.errors.UniqueViolation:
                raise DataScriptError(f"Data script {name!r} has already been run") from None
            conn.execute(scripts[name])

    def data_scripts_run(self) -> set[str]:
        """Names of the data scripts already run against this database."""
        with self.pool.connection() as conn:
            return {row[0] for row in conn.execute("SELECT name FROM data_script_runs")}
