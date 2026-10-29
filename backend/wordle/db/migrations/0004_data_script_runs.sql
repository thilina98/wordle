-- Which data scripts have been run against this database, and when.
--
-- Data scripts change data, not schema, so they live apart from migrations
-- (wordle/db/data_scripts/) and are run by hand: python -m wordle.db run-data-script NAME.

CREATE TABLE data_script_runs (
    name   TEXT        PRIMARY KEY CHECK (length(name) BETWEEN 1 AND 200),
    ran_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
