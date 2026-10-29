"""A throwaway PostgreSQL database for the adapter tests.

Only used when WORDLE_TEST_DATABASE_URL is set, and that database is wiped:
every table the migrations create is dropped first. Never point it at a real
database.
"""

from __future__ import annotations

import psycopg

from wordle.db import Database

#: Every table the migrations create, dependents first.
TABLES = (
    "player_stats",
    "game_scores",
    "game_results",
    "scoring_versions",
    "data_script_runs",
    "deleted_identities",
    "player_identities",
    "players",
    "schema_migrations",
)


def fresh_database(url: str) -> Database:
    """Drop everything, then open (and so migrate) from scratch."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {', '.join(TABLES)}")
    return Database(url)
