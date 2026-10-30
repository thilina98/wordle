-- Players and the identities that sign them in.
--
-- A player is ours; an identity is the identity provider's. Keeping them in
-- separate tables is what lets the provider change: a new provider brings new
-- identities, which join existing players by verified email, and every player
-- id (and everything keyed on it) stays put.

CREATE TABLE players (
    -- UUID rather than an identity column: this id leaves the server (in API
    -- responses, later in leaderboards) and must not reveal how many players
    -- there are or let anyone walk the sequence.
    player_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name TEXT        NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 64),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE player_identities (
    identity_id    BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Deleting a player removes their sign-in methods with them.
    player_id      UUID        NOT NULL REFERENCES players (player_id) ON DELETE CASCADE,
    -- The provider's issuer URL and its id for this person. The subject is
    -- unique only within its issuer, so the pair is the natural key.
    issuer         TEXT        NOT NULL CHECK (length(issuer) BETWEEN 1 AND 512),
    subject        TEXT        NOT NULL CHECK (length(subject) BETWEEN 1 AND 255),
    -- Kept only to join a new sign-in method to an existing player.
    email          TEXT                 CHECK (length(email) <= 320),
    email_verified BOOLEAN     NOT NULL DEFAULT false,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT player_identities_issuer_subject_key UNIQUE (issuer, subject),
    -- Only an email the provider vouches for can link accounts.
    CONSTRAINT player_identities_verified_needs_email CHECK (NOT email_verified OR email IS NOT NULL)
);

-- PostgreSQL does not index foreign keys on its own. Needed for "every
-- identity of this player" and for cascading deletes.
CREATE INDEX player_identities_player_id_idx ON player_identities (player_id);

-- Linking looks up verified emails case-insensitively. Partial, because an
-- unverified email is never looked up.
CREATE INDEX player_identities_verified_email_idx
    ON player_identities (lower(email))
    WHERE email_verified;
