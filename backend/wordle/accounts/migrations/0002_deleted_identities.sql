-- Sign-in identities of deleted players.
--
-- A sign-in token stays valid until it expires, even after its player is
-- deleted. Remembering when each identity was deleted lets the API refuse a
-- token issued before that moment, instead of quietly creating a new player.
--
-- Only a SHA-256 fingerprint of (issuer, subject) is kept, never the
-- provider's id or an email, so nothing here identifies a person.

CREATE TABLE deleted_identities (
    identity_fingerprint TEXT        PRIMARY KEY CHECK (length(identity_fingerprint) = 64),
    deleted_at           TIMESTAMPTZ NOT NULL
);
