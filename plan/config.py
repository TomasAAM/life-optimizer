"""Immutable training-plan configuration.

Holds the race target, the athlete's weekly availability, and the model used for
generation. Edit ``DEFAULT_CONFIG`` when the target race, schedule, or weekly
availability changes — everything downstream reads from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PlanConfig:
    """Static configuration for the training-plan generator.

    Parameters
    ----------
    target_race : str
        Race being trained for (e.g. ``"hyrox"``).
    race_date : datetime.date
        Date of the target race; the periodization phase is computed from it.
    sessions_per_week : int
        Total training sessions per week (the remainder are rest days).
    runs_per_week : int
        How many of the weekly sessions should be runs.
    strength_per_week : int
        How many of the weekly sessions should be strength/functional work.
    rest_days : tuple of str
        Weekday names that default to rest (the generator may shift them to
        auto-regulate, but should keep the same count).
    long_run_day : str
        Preferred weekday for the week's long/endurance run.
    model : str
        Anthropic model id used to generate each week.
    recent_window_days : int
        How many days of recent training to summarize into the prompt.
    """

    target_race: str
    race_date: date
    sessions_per_week: int
    runs_per_week: int
    strength_per_week: int
    rest_days: tuple[str, ...]
    long_run_day: str
    model: str
    recent_window_days: int


# The eight Hyrox stations, in race order, the generator draws functional work from.
HYROX_STATIONS: tuple[str, ...] = (
    "ski_erg",
    "sled_push",
    "sled_pull",
    "burpee_broad_jump",
    "rowing",
    "farmers_carry",
    "sandbag_lunges",
    "wall_balls",
)


# Current target: Hyrox on 2026-08-02. 6 training days/week (4 runs + 2 strength),
# Friday rest, long run on Sunday. Swap RACE_DATE/target_race to re-point at a 21k.
DEFAULT_CONFIG = PlanConfig(
    target_race="hyrox",
    race_date=date(2026, 8, 2),
    sessions_per_week=6,
    runs_per_week=4,
    strength_per_week=2,
    rest_days=("Friday",),
    long_run_day="Sunday",
    model="claude-sonnet-4-6",
    recent_window_days=28,
)
