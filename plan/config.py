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
    secondary_goal : str
        The parallel goal trained alongside the target race (e.g. "21k").
    goal_weighting : str
        How to balance the target race and the secondary goal — "equal" or
        "race_priority". "equal" splits running quality and race-specific work
        roughly 50/50; "race_priority" biases toward the target race.
    gym_access : str
        Equipment availability — "full" enables heavy barbell and plyometric
        prescriptions, not just bodyweight/station circuits.
    base_weekly_km : float
        The athlete's normal base weekly running volume (km). Phase-scaled into a
        weekly-km target so runs are prescribed by volume, not arbitrary minutes.
        Held near base year-round for the undated 21k (standing readiness); only
        the race-week taper cuts it hard.
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
    secondary_goal: str
    goal_weighting: str
    gym_access: str
    base_weekly_km: float


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

# Heavy and explosive gym movements (full-gym access) that drive running economy
# and station power. Kept off hard-run days to avoid the one real interference
# risk — explosive-strength loss in same-session concurrent training.
STRENGTH_LIBRARY: tuple[str, ...] = (
    "back_squat",
    "trap_bar_deadlift",
    "hip_thrust",
    "walking_lunge",
    "box_jump",
    "hurdle_hop",
    "weighted_step_up",
    "pull_up",
    "overhead_press",
)

# The athlete's target Hyrox division and its official station standards. Station
# work is prescribed AT these competition loads (specificity); see hycrew.com/hyrox/weights.
HYROX_DIVISION = "Men's Pro"
HYROX_STANDARDS: dict[str, str] = {
    "sled_push": "202 kg / 50 m",
    "sled_pull": "153 kg / 50 m",
    "farmers_carry": "2x32 kg / 200 m",
    "sandbag_lunges": "30 kg / 100 m",
    "wall_balls": "9 kg to 3.0 m, 100 reps",
    "ski_erg": "1000 m",
    "rowing": "1000 m",
    "burpee_broad_jump": "bodyweight, 80 m",
}
# Known athlete capacities (update as they report feeling too light/heavy). Barbell
# lifts are prescribed by RPE until working weights are provided.
ATHLETE_LOADS: dict[str, str] = {
    "back_squat": "100 kg last used for triples; likely light — progress to RPE 8 (~110+ kg)",
    "trap_bar_deadlift": "130 kg for top triples @ RPE 8",
    "hip_thrust": "110 kg for 6-8 reps",
    "weighted_step_up": "20 kg per hand",
    "wall_balls": "9 kg, ~20 unbroken (build to 25+)",
    "sandbag_lunges": "30 kg comfortable",
}

# Evidence-based heavy-strength template for running economy (Blagrove 2018;
# Llanos-Lagos 2024): heavy, low-rep, full rest, explosive intent, ~1-2 reps in
# reserve — never to failure. HR and Garmin training-load UNDER-READ lifting, so
# judge effort by load + RIR, not heart rate. Progress the weight whenever a top
# set leaves more than ~2 reps in reserve (that is the fix for "it felt easy").
STRENGTH_TEMPLATE = (
    "Heavy compound lifts 3-5 sets x 3-5 reps @ RPE 8 (~1-2 RIR, never to failure), "
    "2-3 min full rest, concentric as fast as possible. Judge by load + RIR, NOT HR. "
    "Progress load when a top set leaves >2 reps in reserve. Plyometrics (jumps/hops) "
    "3-5 x 3-5 with full recovery, ONLY on easy-run days."
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
    secondary_goal="21k",
    goal_weighting="equal",
    gym_access="full",
    base_weekly_km=53.0,
)
