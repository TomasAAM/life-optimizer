"""Immutable training-plan configuration.

Holds the race target, the athlete's weekly availability, and the model used for
generation. Edit ``DEFAULT_CONFIG`` when the target race, schedule, or weekly
availability changes — everything downstream reads from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Race:
    """A target race on the calendar.

    Parameters
    ----------
    name : str
        Race label (e.g. ``"hyrox"``); stored per planned week as ``target_race``.
    date : datetime.date
        Race day. The periodization phase for any week is computed from the next
        race on or after that week.
    """

    name: str
    date: date


@dataclass(frozen=True)
class PlanConfig:
    """Static configuration for the training-plan generator.

    Parameters
    ----------
    races : tuple of Race
        The athlete's calendar of target races, in date order. For any planned
        week the phase is computed against the next race on or after that week, so
        one multi-week block can flow across a race into the next build with no
        manual re-pointing.
    block_weeks : int
        How many weeks a generated block spans by default.
    pre_race_freshen_days : int
        In the week containing a race, ease off (reduce volume, keep intensity,
        short openers) over this many final days before race day. This is the
        athlete's chosen "half-week" freshen — deliberately shorter than the
        classic ~2-week taper, which the shorter Hyrox effort and his err-high
        bias justify.
    post_race_recovery_days : int
        Number of easy/recovery days at the very start of the week following a
        race, before normal training resumes. The athlete prefers a single
        recovery day and then to train through, not a full recovery week.
    sessions_per_week : int
        Total training sessions per week (the remainder are rest days).
    runs_per_week : int
        How many of the weekly sessions should be runs.
    strength_per_week : int
        How many of the weekly sessions should be strength/functional work.
    rest_days : tuple of str
        Weekday names that default to rest.
    long_run_day : str
        Preferred weekday for the week's long/endurance run.
    recent_window_days : int
        Retained for compatibility; recent Garmin data no longer feeds generation
        (the athlete self-regulates recovery on the day).
    secondary_goal : str
        The parallel goal trained alongside the races (e.g. "21k").
    goal_weighting : str
        How to balance the race and the secondary goal — "equal" or
        "race_priority". "equal" splits running quality and race-specific work
        roughly 50/50; "race_priority" biases toward the race.
    gym_access : str
        Equipment availability — "full" enables heavy barbell and plyometric
        prescriptions, not just bodyweight/station circuits.
    base_weekly_km : float
        The athlete's normal base weekly running volume (km). Phase-scaled into a
        weekly-km target so runs are prescribed by volume, not arbitrary minutes.
        This is the single knob that sets the ceiling for the entire macrocycle —
        the phase multipliers only redistribute around it, they never grow it, so
        a volume ramp has to be driven by raising this value block over block.
    """

    races: tuple[Race, ...]
    block_weeks: int
    pre_race_freshen_days: int
    post_race_recovery_days: int
    sessions_per_week: int
    runs_per_week: int
    strength_per_week: int
    rest_days: tuple[str, ...]
    long_run_day: str
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
    "dumbbell_bench_press",
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
# Athlete bodyweight (kg): mean of 15 fasted-morning smart-scale weigh-ins,
# 2026-09-07..09-22 (range 83.8-85.4). Replaces the self-reported 75.0 from
# 2026-08-08, which understated weight by ~9 kg and inflated every relative-strength
# ratio by ~13%. Power-to-weight is what the running half of Hyrox rewards, so
# loads are read against this. The Body tab flags drift from the measured trend.
ATHLETE_BODYWEIGHT_KG = 84.4

# Known athlete capacities, from settled Garmin sets as of 2026-09-22 (the Strength
# tab's load check compares these with what was lifted). Each value leads with the
# heaviest load the evidence supports, so the load check stays meaningful. Prescribe
# from these and progress whenever a top set leaves >2 reps in reserve; where the
# log already shows that headroom (squat, hip thrust), the next block progresses.
ATHLETE_LOADS: dict[str, str] = {
    "back_squat": "100 kg for sets of 5 (2026-08-18) — triples at 100 leave >2 RIR, so progress",
    "trap_bar_deadlift": "140 kg for a top triple (2026-08-11), back-off triples at 130 kg",
    "hip_thrust": "110 kg for 3x8 (2026-09-08), up 5 kg per session since August",
    "weighted_step_up": "20 kg per hand",
    "wall_balls": "9 kg, ~20 unbroken (build to 25+)",
    "sandbag_lunges": "30 kg comfortable",
    "pull_up": "bodyweight +10 kg for sets of 4-5 @ RPE 8 (since 2026-08-31)",
    "overhead_press": "62.5 kg for 4-5 reps @ RPE 8 (2026-09-21)",
    "dumbbell_bench_press": "2x34 kg per hand for 8 reps (2026-09-21), 2x32 kg for 8-10",
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


# Race calendar: two Hyrox races (2026-08-02, then 2026-12-13) plus a standing
# 21k. Seven movement days/week (4 runs + 2 strength + active recovery), long run
# Saturday. Sunday is deliberately active recovery rather than a full rest day.
# Blocks span 4 weeks; a race week freshens over its final 3 days; the week after
# a race opens with a single recovery day, then trains through. Add/edit races to
# re-point the whole engine — no other change needed.
DEFAULT_CONFIG = PlanConfig(
    races=(
        Race(name="hyrox", date=date(2026, 8, 2)),
        Race(name="hyrox", date=date(2026, 12, 13)),
    ),
    block_weeks=4,
    pre_race_freshen_days=3,
    post_race_recovery_days=1,
    sessions_per_week=7,
    runs_per_week=4,
    strength_per_week=2,
    rest_days=(),
    long_run_day="Saturday",
    recent_window_days=28,
    secondary_goal="21k",
    goal_weighting="race_priority",
    gym_access="full, mornings only",
    # Raised 53 -> 62 on 2026-08-08 for the Dec 13 macrocycle. Running is the gap
    # to the Pro field and the old value capped the whole cycle near 61 km, below
    # the ~65 km the goal needs. Athlete chose the aggressive step over a phased
    # ramp; he self-regulates on the day, which is the only check on overshoot.
    base_weekly_km=62.0,
)
