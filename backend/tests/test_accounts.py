"""The accounts module, tested through its interface: header in, player out.

The repository contract runs against every adapter. PostgreSQL joins in when
WORDLE_TEST_DATABASE_URL points at a database the tests may write to (and
empty: they drop and recreate the tables).
"""

from __future__ import annotations

import os
import threading

import pytest

from tests.fakes import ISSUER, FakeIdentityProvider
from wordle.accounts import (
    Accounts,
    AccountsUnavailable,
    AuthenticationError,
    Identity,
    InMemoryPlayerRepository,
    Profile,
    SignInDisabled,
)

TEST_DATABASE_URL = os.environ.get("WORDLE_TEST_DATABASE_URL")


@pytest.fixture(params=["memory", "postgres"])
def repository(request):
    if request.param == "memory":
        yield InMemoryPlayerRepository()
        return
    if not TEST_DATABASE_URL:
        pytest.skip("WORDLE_TEST_DATABASE_URL not set")
    import psycopg

    from wordle.accounts.postgres import PostgresPlayerRepository

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS player_identities, players, schema_migrations")
    repo = PostgresPlayerRepository(TEST_DATABASE_URL)
    yield repo
    repo.close()


@pytest.fixture
def provider() -> FakeIdentityProvider:
    return FakeIdentityProvider()


@pytest.fixture
def accounts(provider, repository) -> Accounts:
    return Accounts(provider, repository)


def bearer(token: str) -> str:
    return f"Bearer {token}"


class TestIdentify:
    def test_no_header_is_an_anonymous_player(self, accounts):
        assert accounts.identify(None) is None

    def test_first_sign_in_registers_a_player(self, accounts, provider):
        token = provider.person("auth0|1", email="ada@example.com", verified=True, name="Ada")
        player = accounts.identify(bearer(token))
        assert player.display_name == "Ada"
        assert player.player_id

    def test_the_same_identity_is_the_same_player(self, accounts, provider):
        token = provider.person("auth0|1")
        assert accounts.identify(bearer(token)) == accounts.identify(bearer(token))

    def test_different_people_are_different_players(self, accounts, provider):
        one = accounts.identify(bearer(provider.person("auth0|1")))
        two = accounts.identify(bearer(provider.person("auth0|2")))
        assert one.player_id != two.player_id

    def test_a_verified_email_joins_a_new_method_to_the_existing_player(self, accounts, provider):
        password = provider.person("auth0|1", email="ada@example.com", verified=True)
        github = provider.person("github|9", email="Ada@Example.com", verified=True)
        assert accounts.identify(bearer(password)) == accounts.identify(bearer(github))

    def test_an_unverified_email_never_joins(self, accounts, provider):
        # Otherwise anyone could claim an account by typing its email.
        owner = provider.person("auth0|1", email="ada@example.com", verified=True)
        claimant = provider.person("auth0|2", email="ada@example.com", verified=False)
        assert accounts.identify(bearer(owner)) != accounts.identify(bearer(claimant))

    def test_an_unverified_email_is_never_joined_to(self, accounts, provider):
        first = provider.person("auth0|1", email="ada@example.com", verified=False)
        second = provider.person("github|2", email="ada@example.com", verified=True)
        assert accounts.identify(bearer(first)) != accounts.identify(bearer(second))

    def test_linking_can_be_turned_off(self, provider, repository):
        accounts = Accounts(provider, repository, link_verified_emails=False)
        one = provider.person("auth0|1", email="ada@example.com", verified=True)
        two = provider.person("github|2", email="ada@example.com", verified=True)
        assert accounts.identify(bearer(one)) != accounts.identify(bearer(two))

    def test_the_same_subject_at_another_issuer_is_someone_else(self, repository):
        first, second = FakeIdentityProvider(ISSUER), FakeIdentityProvider("https://other.test/")
        one = Accounts(first, repository).identify(bearer(first.person("1")))
        two = Accounts(second, repository).identify(bearer(second.person("1")))
        assert one != two

    def test_switching_provider_keeps_players_with_a_verified_email(self, repository):
        old, new = FakeIdentityProvider(ISSUER), FakeIdentityProvider("https://new-idp.test/")
        before = Accounts(old, repository).identify(
            bearer(old.person("auth0|1", email="ada@example.com", verified=True))
        )
        after = Accounts(new, repository).identify(
            bearer(new.person("uuid-77", email="ada@example.com", verified=True))
        )
        assert before == after

    def test_a_display_name_falls_back_to_the_email_then_a_default(self, accounts, provider):
        from_email = accounts.identify(bearer(provider.person("a", email="ada@example.com")))
        nothing = accounts.identify(bearer(provider.person("b")))
        assert from_email.display_name == "ada"
        assert nothing.display_name == "Player"

    def test_a_long_display_name_is_cut_to_fit(self, accounts, provider):
        player = accounts.identify(bearer(provider.person("a", name="x" * 500)))
        assert len(player.display_name) == 64

    @pytest.mark.parametrize("header", ["", "token", "Basic abc", "Bearer", "Bearer   "])
    def test_a_malformed_header_is_an_authentication_error(self, accounts, header):
        with pytest.raises(AuthenticationError):
            accounts.identify(header)

    def test_an_unknown_token_is_an_authentication_error(self, accounts):
        with pytest.raises(AuthenticationError):
            accounts.identify(bearer("forged"))

    def test_a_provider_outage_is_unavailable_not_unauthenticated(self, accounts, provider):
        token = provider.person("auth0|1")
        provider.down = True
        with pytest.raises(AccountsUnavailable):
            accounts.identify(bearer(token))


class TestRepositoryContract:
    """Behaviour every PlayerRepository adapter must share."""

    ME = Identity(ISSUER, "auth0|1")

    def test_an_unknown_identity_is_not_found(self, repository):
        assert repository.find(self.ME) is None

    def test_register_then_find(self, repository):
        player = repository.register(self.ME, Profile(name="Ada"), None)
        assert repository.find(self.ME) == player

    def test_register_is_idempotent(self, repository):
        first = repository.register(self.ME, Profile(name="Ada"), None)
        assert repository.register(self.ME, Profile(name="Other"), None) == first

    def test_a_link_email_with_no_match_creates_a_player(self, repository):
        player = repository.register(self.ME, Profile(), "nobody@example.com")
        assert repository.find(self.ME) == player

    def test_delete_forgets_the_player_and_their_identities(self, repository):
        repository.register(self.ME, Profile(name="Ada"), None)
        player = repository.find(self.ME)
        repository.delete(player.player_id)
        assert repository.find(self.ME) is None

    def test_delete_is_idempotent(self, repository):
        player = repository.register(self.ME, Profile(), None)
        repository.delete(player.player_id)
        repository.delete(player.player_id)

    def test_delete_leaves_other_players_alone(self, repository):
        other = Identity(ISSUER, "auth0|2")
        repository.register(self.ME, Profile(), None)
        kept = repository.register(other, Profile(), None)
        repository.delete(repository.find(self.ME).player_id)
        assert repository.find(other) == kept

    def test_signing_in_after_delete_is_a_new_player(self, repository):
        before = repository.register(self.ME, Profile(), None)
        repository.delete(before.player_id)
        after = repository.register(self.ME, Profile(), None)
        assert after.player_id != before.player_id

    def test_a_deleted_players_email_no_longer_links(self, repository):
        email = Profile(email="ada@example.com", email_verified=True)
        old = repository.register(self.ME, email, None)
        repository.delete(old.player_id)
        other = Identity(ISSUER, "github|9")
        assert repository.register(other, email, "ada@example.com").player_id != old.player_id

    def test_racing_registrations_of_one_identity_make_one_player(self, repository):
        results, barrier = [], threading.Barrier(8)

        def register():
            barrier.wait()
            results.append(repository.register(self.ME, Profile(name="Ada"), None))

        threads = [threading.Thread(target=register) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len({p.player_id for p in results}) == 1


def test_sign_in_disabled_lets_anonymous_players_through():
    assert SignInDisabled().identify(None) is None


def test_sign_in_disabled_refuses_credentials():
    with pytest.raises(AuthenticationError, match="not enabled"):
        SignInDisabled().identify("Bearer anything")
