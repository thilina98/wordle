-- Scoring version 1: the constants scoring has used since it shipped, made
-- the active version. Run once, before the server first starts with sign-in
-- on: a server with sign-in and no active scoring version refuses to start.
--
-- Safe to rerun: an existing version 1 is left alone, and version 1 is only
-- made active if no version is active yet.

INSERT INTO scoring_versions (
    scoring_version, is_active,
    max_base, last_attempt_ratio, time_bonus_cap, seconds_per_letter,
    difficulty_step, normal_max_score, score_precision
)
SELECT 1, NOT EXISTS (SELECT 1 FROM scoring_versions WHERE is_active),
       100, 0.2, 0.20, 60, 1.25, 10, 2
ON CONFLICT (scoring_version) DO NOTHING;
