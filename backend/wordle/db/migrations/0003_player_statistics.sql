-- Player statistics: every finished game of a signed-in player, its score, and
-- a per-combination summary for fast reading.
--
-- Schema only. Scoring version 1 is seeded by data script
-- 0001_seed_scoring_version_1, not here.

-- Every scoring rule set ever released, with its constants. Scores are read
-- under the active one. The formula lives in code; these are its numbers.
CREATE TABLE scoring_versions (
    scoring_version    SMALLINT         PRIMARY KEY CHECK (scoring_version >= 1),
    released_at        TIMESTAMPTZ      NOT NULL DEFAULT now(),
    is_active          BOOLEAN          NOT NULL DEFAULT false,
    max_base           DOUBLE PRECISION NOT NULL CHECK (max_base > 0),
    last_attempt_ratio DOUBLE PRECISION NOT NULL CHECK (last_attempt_ratio > 0 AND last_attempt_ratio <= 1),
    time_bonus_cap     DOUBLE PRECISION NOT NULL CHECK (time_bonus_cap >= 0),
    seconds_per_letter DOUBLE PRECISION NOT NULL CHECK (seconds_per_letter > 0),
    difficulty_step    DOUBLE PRECISION NOT NULL CHECK (difficulty_step > 0),
    normal_max_score   DOUBLE PRECISION NOT NULL CHECK (normal_max_score > 0),
    score_precision    SMALLINT         NOT NULL CHECK (score_precision >= 0)
);

-- At most one active version.
CREATE UNIQUE INDEX scoring_versions_one_active_idx ON scoring_versions (is_active) WHERE is_active;

-- One row per finished game: the facts only. Never updated.
--
-- difficulty is the label the game was played under, frozen at recording, so
-- a later change to the mapping never relabels a game already played.
-- max_attempts is kept beside it because it is a fact the label cannot give
-- back: last-attempt wins and re-scoring both need it.
CREATE TABLE game_results (
    -- The in-progress store's game id. As the primary key it makes recording
    -- idempotent: a game retried or submitted twice is stored once.
    game_id                      TEXT        PRIMARY KEY CHECK (length(game_id) BETWEEN 1 AND 64),
    player_id                    UUID        NOT NULL REFERENCES players (player_id) ON DELETE CASCADE,
    answer                       TEXT        NOT NULL,
    word_length                  SMALLINT    NOT NULL CHECK (word_length BETWEEN 2 AND 32),
    max_attempts                 SMALLINT    NOT NULL CHECK (max_attempts >= 2),
    difficulty                   TEXT        NOT NULL CHECK (difficulty IN ('easy', 'normal', 'hard')),
    -- Colours are not stored: evaluate_guess rebuilds them from answer and guess.
    guesses                      TEXT[]      NOT NULL,
    outcome                      TEXT        NOT NULL CHECK (outcome IN ('won', 'lost', 'abandoned')),
    attempt_won_on               SMALLINT,
    started_at                   TIMESTAMPTZ NOT NULL,
    ended_at                     TIMESTAMPTZ NOT NULL,
    scoring_version_played_under SMALLINT    NOT NULL REFERENCES scoring_versions (scoring_version),
    CHECK (length(answer) = word_length),
    CHECK (ended_at >= started_at),
    CHECK ((outcome = 'won') = (attempt_won_on IS NOT NULL)),
    CHECK (outcome <> 'won'       OR cardinality(guesses) = attempt_won_on),
    CHECK (outcome <> 'lost'      OR cardinality(guesses) = max_attempts),
    -- A game left after a single guess is never recorded.
    CHECK (outcome <> 'abandoned' OR cardinality(guesses) BETWEEN 2 AND max_attempts - 1)
);

-- A player's games in one combination, in the order they ended: the guess
-- distribution and any rebuild of player_stats read through this.
CREATE INDEX game_results_player_combo_idx ON game_results (player_id, word_length, difficulty, ended_at);

-- Each game's score under the active scoring version, so reads never
-- recompute it. Rewritten when the active version changes.
CREATE TABLE game_scores (
    game_id TEXT         PRIMARY KEY REFERENCES game_results (game_id) ON DELETE CASCADE,
    score   NUMERIC(8,2) NOT NULL CHECK (score >= 0)
);

-- For leaderboards.
CREATE INDEX game_scores_score_idx ON game_scores (score);

-- The summary: one row per player, scoring version and combination. Every
-- figure in it is a count, sum, minimum or maximum, so any filter (a word
-- length, a difficulty, or neither) adds rows together. Streaks are the
-- exception and are only read for a single combination.
--
-- Derived data: rebuildable from game_results and game_scores at any time.
CREATE TABLE player_stats (
    player_id          UUID          NOT NULL REFERENCES players (player_id) ON DELETE CASCADE,
    scoring_version    SMALLINT      NOT NULL REFERENCES scoring_versions (scoring_version),
    word_length        SMALLINT      NOT NULL CHECK (word_length BETWEEN 2 AND 32),
    difficulty         TEXT          NOT NULL CHECK (difficulty IN ('easy', 'normal', 'hard')),
    -- Includes abandoned games.
    games              INTEGER       NOT NULL CHECK (games >= 1),
    wins               INTEGER       NOT NULL CHECK (wins >= 0),
    first_attempt_wins INTEGER       NOT NULL CHECK (first_attempt_wins >= 0),
    last_attempt_wins  INTEGER       NOT NULL CHECK (last_attempt_wins >= 0),
    -- Losses and attempt-1 wins score 0, so they add nothing here. The average
    -- divides by scored games: wins - first_attempt_wins.
    total_score        NUMERIC(14,2) NOT NULL CHECK (total_score >= 0),
    highest_score      NUMERIC(8,2)  NOT NULL CHECK (highest_score >= 0),
    -- Wins on attempt 2 or later only: attempt-1 wins are luck, not pace.
    total_win_ms       BIGINT        NOT NULL CHECK (total_win_ms >= 0),
    fastest_win_ms     BIGINT                 CHECK (fastest_win_ms >= 0),
    current_streak     INTEGER       NOT NULL CHECK (current_streak >= 0),
    best_streak        INTEGER       NOT NULL,
    updated_at         TIMESTAMPTZ   NOT NULL,
    PRIMARY KEY (player_id, scoring_version, word_length, difficulty),
    CHECK (first_attempt_wins <= wins AND wins <= games),
    CHECK (last_attempt_wins <= wins),
    CHECK (current_streak <= best_streak AND best_streak <= wins)
);
