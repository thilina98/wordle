"""Player statistics: every finished game of a signed-in player, and what it adds up to.

The rest of the app sees two seams:

- `PlayerStats`: `record` a result, read a `summary` under a filter.
  `PostgresPlayerStats` for real deployments, `InMemoryPlayerStats` for tests.
- `ScoringRulesSource`: the scoring constants. `PostgresScoringRules` reads the
  active scoring version; `FixedScoringRules` holds the WORDLE_SCORING_*
  settings when there is no database.

`ResultRecorder` moves results from the game store into `PlayerStats`.

Mode is the word length; difficulty is a label for the attempt allowance
(`wordle.game.Difficulty`). A combination is the two together.
"""

from .model import ComboStats, GameResult, NotRecordable, Outcome, StatsSummary
from .recorder import RETRY_SECONDS, ResultRecorder
from .service import (
    FixedScoringRules,
    InMemoryPlayerStats,
    PlayerStats,
    ScoringRulesSource,
    StatsUnavailable,
)

__all__ = [
    "RETRY_SECONDS",
    "ComboStats",
    "FixedScoringRules",
    "GameResult",
    "InMemoryPlayerStats",
    "NotRecordable",
    "Outcome",
    "PlayerStats",
    "ResultRecorder",
    "ScoringRulesSource",
    "StatsSummary",
    "StatsUnavailable",
]
