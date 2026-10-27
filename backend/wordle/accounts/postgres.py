"""PostgreSQL adapter for PlayerRepository.

The only module in the codebase that knows PostgreSQL exists. Another database
means another adapter beside this one; nothing outside `accounts` changes.
"""

from __future__ import annotations

import uuid
from importlib import resources

import psycopg
from psycopg_pool import ConnectionPool

from .model import Identity, Player, Profile
from .service import AccountsUnavailable

#: Any constant works; it only has to be the same in every process, so two
#: servers starting at once do not both run a migration.
_MIGRATION_LOCK = 0x776F72646C65  # "wordle"

_CONNECT_TIMEOUT = 5
_POOL_TIMEOUT = 5.0


def _is_uuid(value: str) -> bool:
    """Player ids are UUIDs here; anything else would be a query error, not a miss."""
    try:
        uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        return False
    return True


class _AlreadyRegistered(Exception):
    """A racing request registered the same identity first. Roll back and reread."""


def _migrations() -> list[tuple[int, str]]:
    """(version, sql) for every migration shipped, oldest first."""
    files = resources.files(__package__).joinpath("migrations")
    found = []
    for entry in files.iterdir():
        name = entry.name
        if name.endswith(".sql"):
            found.append((int(name.split("_", 1)[0]), entry.read_text(encoding="utf-8")))
    return sorted(found)


class PostgresPlayerRepository:
    """Players in PostgreSQL, through a small connection pool.

    Creating one brings the schema up to date, so the server refuses to start
    against a database it cannot use rather than failing one sign-in at a time.
    """

    def __init__(self, url: str, *, password: str | None = None, max_connections: int = 5) -> None:
        kwargs: dict[str, object] = {"connect_timeout": _CONNECT_TIMEOUT, "autocommit": True}
        if password:
            kwargs["password"] = password
        self._pool = ConnectionPool(
            url,
            kwargs=kwargs,
            min_size=1,
            max_size=max_connections,
            timeout=_POOL_TIMEOUT,
            open=False,
        )
        self._pool.open(wait=True, timeout=_CONNECT_TIMEOUT * 2)
        self.migrate()

    def close(self) -> None:
        self._pool.close()

    def migrate(self) -> None:
        """Apply every migration not yet applied, each in its own transaction."""
        with self._pool.connection() as conn, conn.transaction():
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

    # --- PlayerRepository ---------------------------------------------------

    def find(self, identity: Identity) -> Player | None:
        try:
            with self._pool.connection() as conn:
                return self._find(conn, identity)
        except psycopg.Error as exc:
            raise AccountsUnavailable("Player store unavailable") from exc

    def register(self, identity: Identity, profile: Profile, link_email: str | None) -> Player:
        try:
            with self._pool.connection() as conn:
                try:
                    with conn.transaction():
                        existing = self._find(conn, identity)
                        if existing is not None:
                            return existing
                        return self._insert(conn, identity, profile, link_email)
                except _AlreadyRegistered:
                    player = self._find(conn, identity)
                    if player is None:  # pragma: no cover - would need a delete mid-race
                        raise AccountsUnavailable("Registration raced and lost") from None
                    return player
        except psycopg.Error as exc:
            # PoolTimeout is an OperationalError, so a full pool lands here too.
            raise AccountsUnavailable("Player store unavailable") from exc

    def identities(self, player_id: str) -> list[Identity]:
        if not _is_uuid(player_id):
            return []  # not an id this store could ever have issued
        try:
            with self._pool.connection() as conn:
                return self._identities(conn, player_id)
        except psycopg.Error as exc:
            raise AccountsUnavailable("Player store unavailable") from exc

    def delete(self, player_id: str, deleted_at: float) -> None:
        if not _is_uuid(player_id):
            return
        try:
            with self._pool.connection() as conn, conn.transaction():
                for identity in self._identities(conn, player_id):
                    conn.execute(
                        "INSERT INTO deleted_identities (identity_fingerprint, deleted_at)"
                        " VALUES (%s, to_timestamp(%s))"
                        " ON CONFLICT (identity_fingerprint) DO UPDATE"
                        " SET deleted_at = GREATEST(deleted_identities.deleted_at,"
                        " EXCLUDED.deleted_at)",
                        (identity.fingerprint(), deleted_at),
                    )
                # Identities go with the player: ON DELETE CASCADE.
                conn.execute("DELETE FROM players WHERE player_id = %s", (player_id,))
        except psycopg.Error as exc:
            raise AccountsUnavailable("Player store unavailable") from exc

    def deleted_at(self, identity: Identity) -> float | None:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    "SELECT extract(epoch FROM deleted_at) FROM deleted_identities"
                    " WHERE identity_fingerprint = %s",
                    (identity.fingerprint(),),
                ).fetchone()
        except psycopg.Error as exc:
            raise AccountsUnavailable("Player store unavailable") from exc
        return float(row[0]) if row else None

    # --- Internals ----------------------------------------------------------

    @staticmethod
    def _identities(conn: psycopg.Connection, player_id: str) -> list[Identity]:
        rows = conn.execute(
            "SELECT issuer, subject FROM player_identities"
            " WHERE player_id = %s ORDER BY identity_id",
            (player_id,),
        ).fetchall()
        return [Identity(issuer, subject) for issuer, subject in rows]

    @staticmethod
    def _find(conn: psycopg.Connection, identity: Identity) -> Player | None:
        row = conn.execute(
            "SELECT p.player_id, p.display_name"
            " FROM player_identities AS i JOIN players AS p USING (player_id)"
            " WHERE i.issuer = %s AND i.subject = %s",
            (identity.issuer, identity.subject),
        ).fetchone()
        return Player(str(row[0]), row[1]) if row else None

    @staticmethod
    def _insert(
        conn: psycopg.Connection, identity: Identity, profile: Profile, link_email: str | None
    ) -> Player:
        """Caller holds a transaction."""
        row = None
        if link_email:
            # Same expression as the partial index, so the index serves it.
            row = conn.execute(
                "SELECT p.player_id, p.display_name"
                " FROM player_identities AS i JOIN players AS p USING (player_id)"
                " WHERE lower(i.email) = lower(%s) AND i.email_verified"
                " ORDER BY i.identity_id LIMIT 1",
                (link_email,),
            ).fetchone()
        if row is None:
            row = conn.execute(
                "INSERT INTO players (display_name) VALUES (%s) RETURNING player_id, display_name",
                (profile.display_name(),),
            ).fetchone()
        player = Player(str(row[0]), row[1])

        inserted = conn.execute(
            "INSERT INTO player_identities (player_id, issuer, subject, email, email_verified)"
            " VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (issuer, subject) DO NOTHING RETURNING identity_id",
            (
                player.player_id,
                identity.issuer,
                identity.subject,
                profile.email,
                bool(profile.verified_email),
            ),
        ).fetchone()
        if inserted is None:
            # Undo the player we may have just created; it would be an orphan.
            raise _AlreadyRegistered
        return player
