"""Aggregations over the strength log: what was lifted, how heavy, how sure.

Pure pandas over ``garmin_activity_exercises`` and ``garmin_exercise_sets`` --
no Supabase, no I/O -- matching :mod:`dashboard.activity_metrics` and
:mod:`dashboard.body_metrics`.

Four rules govern every number here, because each one is a way this data lies if
taken at face value:

* **Identification is a probability, not a fact.** Garmin infers the movement
  from wrist motion. Only where it reports 100 is the answer settled -- either
  the watch was certain or the athlete named the lift in Garmin Connect. The
  guesses are visibly wrong where they are heavy: the log holds a 120 kg
  "shrug" at 45% confidence and a 110 kg "bench dip" at 46%, which are compound
  lifts wearing a label the watch picked from three candidates. So **no lift is
  ever named on the strength of a guess** -- progression is drawn from settled
  sets only. Note what this flag does and does not cover: it is Garmin's
  confidence in the *movement*, not in the *load*. A settled label can still
  carry a weight that was entered against the wrong exercise, which is why the
  load checks below name the specific lift and date behind every number rather
  than reporting a bare maximum.
* **Load history starts on 2026-07-01.** Nothing before it carries a weight, so
  a chart spanning the whole log would draw four months of zero tonnage and read
  as detraining. Every load panel starts where the loads do, and says so.
* **Unattributed work is still work.** ``UNKNOWN`` is Garmin's own category for
  reps it could not attribute, and those sets reach 130 kg. They count toward
  tonnage and set totals -- dropping them would understate the training -- and
  are never named or charted as a lift.
* **Bodyweight sessions are not zero-tonnage sessions.** The HIIT sessions
  record sets and reps but never a load. They contribute sets, never kilograms,
  and a mean load computed across them would be meaningless rather than low.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from dashboard import body_metrics as bm
from plan import config

# Garmin's identification is settled at this probability and a guess below it.
# There is no middle ground worth modelling: the payload either carries a single
# certain candidate or three competing ones, and the runner-ups were never
# stored because no reading of this data uses them.
CONFIRMED_PROBABILITY_PCT = 100.0

# Garmin's own category for reps it recorded but could not attribute to a
# movement. Counted in totals, never named.
UNIDENTIFIED_CATEGORY = "UNKNOWN"

_ACTIVE = "ACTIVE"

# Trailing window for "what are you currently lifting". Ninety days rather than
# all-time, so a check reports the working load rather than a personal best set
# in a block that has since ended.
CURRENT_LOAD_WINDOW_DAYS = 90

_HEADLINE_WINDOW_DAYS = 28
_TONNAGE_WINDOW_DAYS = 7

# A lift needs settled top sets on this many separate days before it earns a
# progression line. Two points are a line through anything; three is the least
# that can show a direction.
MIN_SESSIONS_FOR_TREND = 3

# Garmin's movement taxonomy grouped into the patterns a programme is actually
# balanced across. Every category observed in the log is placed; anything Garmin
# adds later falls to "Other" rather than being silently dropped.
MOVEMENT_PATTERNS: dict[str, str] = {
    "SQUAT": "Squat",
    "LUNGE": "Squat",
    "DEADLIFT": "Hinge",
    "HIP_RAISE": "Hinge",
    "BENCH_PRESS": "Push",
    "SHOULDER_PRESS": "Push",
    "PUSH_UP": "Push",
    "TRICEPS_EXTENSION": "Push",
    "FLYE": "Push",
    "LATERAL_RAISE": "Push",
    "PULL_UP": "Pull",
    "ROW": "Pull",
    "SHRUG": "Pull",
    "CARRY": "Carry",
    "SIT_UP": "Core",
}
OTHER_PATTERN = "Other"

# Display order, heaviest patterns first so the stack reads consistently.
PATTERN_ORDER = ("Squat", "Hinge", "Push", "Pull", "Carry", "Core", OTHER_PATTERN)

# The lifts whose prescription in ``plan.config.ATHLETE_LOADS`` is an
# unambiguous total in kilograms, mapped onto the Garmin category that records
# them. Deliberately the same four :data:`dashboard.body_metrics.RELATIVE_STRENGTH_LIFTS`
# uses, and for the same reason: the others are recorded per hand or as
# "bodyweight plus", so the figure in the prescription is not the load on the
# bar and comparing it to a measured weight would be wrong in a way that looks
# right.
CONFIG_LIFT_CATEGORIES: dict[str, str] = {
    "back_squat": "SQUAT",
    "trap_bar_deadlift": "DEADLIFT",
    "hip_thrust": "HIP_RAISE",
    "overhead_press": "SHOULDER_PRESS",
}

# Below this the config constant and the measured load agree closely enough
# that flagging the gap would be noise. Matches the tolerance
# :mod:`dashboard.body_tab` applies to bodyweight.
CONFIG_GAP_TOLERANCE_KG = 2.5


@dataclass(frozen=True)
class StrengthHeadline:
    """Current-state summary of the strength log.

    Parameters
    ----------
    sessions_28d : int
        Set-bearing sessions in the last 28 days.
    tonnage_7d : float
        Kilograms lifted in the last 7 days, summed over weight x reps.
    total_tonnage_kg : float
        Kilograms lifted since loads started being recorded.
    heaviest_lift : str or None
        Display name of the heaviest settled lift in the current window.
    heaviest_kg : float or None
        Its load.
    heaviest_on : datetime.date or None
        When it was lifted.
    active_sets : int
        Working sets on record, rests excluded.
    settled_sets : int
        How many of those carry a certain identification.
    """

    sessions_28d: int
    tonnage_7d: float
    total_tonnage_kg: float
    heaviest_lift: str | None
    heaviest_kg: float | None
    heaviest_on: date | None
    active_sets: int
    settled_sets: int


@dataclass(frozen=True)
class LoadCheck:
    """One config working load against the heaviest load actually recorded.

    Parameters
    ----------
    lift : str
        Key in :data:`plan.config.ATHLETE_LOADS`.
    label : str
        Display name.
    config_kg : float
        The load prescribed in ``plan/config.py``.
    measured_kg : float or None
        Heaviest settled set in the mapped category within
        :data:`CURRENT_LOAD_WINDOW_DAYS`, or ``None`` if nothing settled.
    measured_lift : str or None
        The specific movement that produced it, so the comparison is auditable
        rather than a bare number.
    measured_on : datetime.date or None
        When.
    """

    lift: str
    label: str
    config_kg: float
    measured_kg: float | None
    measured_lift: str | None
    measured_on: date | None

    @property
    def gap_kg(self) -> float | None:
        """Measured minus prescribed; positive means the config is stale-low."""
        if self.measured_kg is None:
            return None
        return self.measured_kg - self.config_kg

    @property
    def is_stale(self) -> bool:
        """Whether the gap is wide enough to be worth acting on."""
        gap = self.gap_kg
        return gap is not None and abs(gap) >= CONFIG_GAP_TOLERANCE_KG


def exercise_label(category: str | None, sub_category: str | None) -> str:
    """Render a Garmin movement code as a readable name.

    The specific lift wins when Garmin got that far; otherwise the category
    stands alone, which is honest about how much was actually identified.

    Parameters
    ----------
    category : str or None
        Garmin category, e.g. ``"SQUAT"``.
    sub_category : str or None
        Specific movement, e.g. ``"BARBELL_SIFF_SQUAT"``. Empty or ``None``
        when Garmin named only the category.

    Returns
    -------
    str
        A display name.

    Examples
    --------
    >>> exercise_label("SQUAT", "BARBELL_SIFF_SQUAT")
    'Barbell siff squat'
    >>> exercise_label("SHOULDER_PRESS", "")
    'Shoulder press'
    >>> exercise_label("UNKNOWN", None)
    'Unidentified'
    """
    code = sub_category or category
    if not code or code == UNIDENTIFIED_CATEGORY:
        return "Unidentified"
    return code.replace("_", " ").capitalize()


def movement_pattern(category: str | None) -> str:
    """Map a Garmin category onto the movement pattern it trains.

    Parameters
    ----------
    category : str or None
        Garmin category.

    Returns
    -------
    str
        One of :data:`PATTERN_ORDER`.

    Examples
    --------
    >>> movement_pattern("DEADLIFT")
    'Hinge'
    >>> movement_pattern("OLYMPIC_LIFT")
    'Other'
    """
    return MOVEMENT_PATTERNS.get(category or "", OTHER_PATTERN)


def _session_days(activities: pd.DataFrame) -> pd.DataFrame:
    """Reduce the activity table to the session date and type of each id."""
    columns = ["activity_id", "day", "activity_type", "activity_name"]
    if activities.empty or "activity_id" not in activities:
        return pd.DataFrame(columns=columns)

    out = activities.copy()
    # ``start_time_local`` is the wall clock the session happened on, the same
    # column ``activity_metrics`` uses -- a UTC date would push an early-morning
    # Santiago session onto the same day but a late-evening one onto the next.
    stamps = pd.to_datetime(out["start_time_local"], errors="coerce")
    out["day"] = stamps.dt.date
    for column in ("activity_type", "activity_name"):
        if column not in out:
            out[column] = None
    return out.dropna(subset=["day"])[columns]


def prepare_exercises(
    exercises: pd.DataFrame, activities: pd.DataFrame
) -> pd.DataFrame:
    """Attach session dates and movement patterns to the per-exercise rows.

    Parameters
    ----------
    exercises : pandas.DataFrame
        Rows from :func:`dashboard.query.fetch_activity_exercises`.
    activities : pandas.DataFrame
        Rows from :func:`dashboard.query.fetch_activities`, which carry the
        date; the exercise table stores only the activity id.

    Returns
    -------
    pandas.DataFrame
        Columns: activity_id, day, activity_type, category, sub_category,
        label, pattern, sets, reps, volume_kg, max_weight_kg. Sorted by day.
        Empty in, empty out.
    """
    columns = [
        "activity_id", "day", "activity_type", "category", "sub_category",
        "label", "pattern", "sets", "reps", "volume_kg", "max_weight_kg",
    ]
    if exercises.empty or "activity_id" not in exercises:
        return pd.DataFrame(columns=columns)

    sessions = _session_days(activities)
    if sessions.empty:
        return pd.DataFrame(columns=columns)

    out = exercises.merge(sessions, on="activity_id", how="inner")
    if out.empty:
        return pd.DataFrame(columns=columns)

    if "sub_category" not in out:
        out["sub_category"] = ""
    out["sub_category"] = out["sub_category"].fillna("")
    out["label"] = [
        exercise_label(c, s) for c, s in zip(out["category"], out["sub_category"])
    ]
    out["pattern"] = [movement_pattern(c) for c in out["category"]]
    for column in ("sets", "reps", "volume_kg", "max_weight_kg"):
        out[column] = pd.to_numeric(out.get(column), errors="coerce")

    return out.sort_values(["day", "category"]).reset_index(drop=True)[columns]


def prepare_sets(sets: pd.DataFrame, activities: pd.DataFrame) -> pd.DataFrame:
    """Attach session dates and the settled flag to the per-set rows.

    Rest sets are dropped here: every panel built on this frame asks about work
    done, and rest is stored for the analyses that will want it rather than for
    these.

    Parameters
    ----------
    sets : pandas.DataFrame
        Rows from :func:`dashboard.query.fetch_exercise_sets`.
    activities : pandas.DataFrame
        Rows from :func:`dashboard.query.fetch_activities`.

    Returns
    -------
    pandas.DataFrame
        Columns: activity_id, set_index, day, activity_type, category,
        exercise_name, label, pattern, reps, weight_kg, duration_s, settled.
        Working sets only, sorted by day then position.
    """
    columns = [
        "activity_id", "set_index", "day", "activity_type", "category",
        "exercise_name", "label", "pattern", "reps", "weight_kg",
        "duration_s", "settled",
    ]
    if sets.empty or "activity_id" not in sets:
        return pd.DataFrame(columns=columns)

    sessions = _session_days(activities)
    if sessions.empty:
        return pd.DataFrame(columns=columns)

    out = sets.merge(sessions, on="activity_id", how="inner")
    out = out[out["set_type"] == _ACTIVE]
    if out.empty:
        return pd.DataFrame(columns=columns)

    out["label"] = [
        exercise_label(c, n)
        for c, n in zip(out["category"], out.get("exercise_name", pd.Series(dtype=object)))
    ]
    out["pattern"] = [movement_pattern(c) for c in out["category"]]
    for column in ("reps", "weight_kg", "duration_s", "probability_pct"):
        out[column] = pd.to_numeric(out.get(column), errors="coerce")
    # Not >= : Garmin reports 99.6 on a set it flatly failed to identify, so a
    # threshold below 100 would promote the clearest non-answers in the log.
    out["settled"] = out["probability_pct"] == CONFIRMED_PROBABILITY_PCT

    return out.sort_values(["day", "set_index"]).reset_index(drop=True)[columns]


def first_weighted_day(sets: pd.DataFrame) -> date | None:
    """Find the day loads started being recorded.

    Derived rather than hard-coded: the answer is a fact about the athlete's
    logging habit, and pinning it as a constant would quietly mislabel the
    charts if earlier sessions were ever edited to carry weights.

    Parameters
    ----------
    sets : pandas.DataFrame
        Output of :func:`prepare_sets`.

    Returns
    -------
    datetime.date or None
        The first day carrying any load, or ``None`` if none does.
    """
    if sets.empty:
        return None
    weighted = sets.dropna(subset=["weight_kg"])
    return None if weighted.empty else min(weighted["day"])


def top_sets(sets: pd.DataFrame) -> pd.DataFrame:
    """Reduce the settled working sets to one top set per lift per day.

    Progressive overload is read off the heaviest set of the session, not off
    its mean or its total: a heavy triple followed by two back-off sets is a
    heavier session than three sets at the back-off weight, and averaging says
    the opposite.

    Only settled sets are considered. A guessed label attaches a real weight to
    the wrong movement, which is exactly the error a progression chart would
    render as a breakthrough.

    Parameters
    ----------
    sets : pandas.DataFrame
        Output of :func:`prepare_sets`.

    Returns
    -------
    pandas.DataFrame
        Columns: day, label, category, weight_kg, reps, sets. One row per lift
        per day, ``reps`` being the reps of the heaviest set and ``sets`` how
        many settled working sets of that lift the session held.
    """
    columns = ["day", "label", "category", "weight_kg", "reps", "sets"]
    if sets.empty:
        return pd.DataFrame(columns=columns)

    pool = sets[sets["settled"]].dropna(subset=["weight_kg"])
    pool = pool[pool["category"] != UNIDENTIFIED_CATEGORY]
    if pool.empty:
        return pd.DataFrame(columns=columns)

    ordered = pool.sort_values("weight_kg", ascending=False)
    heaviest = ordered.groupby(["day", "label"], as_index=False).first()
    counts = (
        pool.groupby(["day", "label"], as_index=False)
        .size()
        .rename(columns={"size": "sets"})
    )
    out = heaviest.merge(counts, on=["day", "label"], how="left")
    return out.sort_values(["day", "label"]).reset_index(drop=True)[columns]


def trending_lifts(progression: pd.DataFrame) -> list[str]:
    """Pick the lifts with enough settled history to draw a line through.

    Parameters
    ----------
    progression : pandas.DataFrame
        Output of :func:`top_sets`.

    Returns
    -------
    list of str
        Lift labels with top sets on at least :data:`MIN_SESSIONS_FOR_TREND`
        separate days, heaviest first so the busiest lifts lead the legend.
    """
    if progression.empty:
        return []
    grouped = progression.groupby("label").agg(
        days=("day", "nunique"), heaviest=("weight_kg", "max")
    )
    qualified = grouped[grouped["days"] >= MIN_SESSIONS_FOR_TREND]
    return list(qualified.sort_values("heaviest", ascending=False).index)


def weekly_volume(exercises: pd.DataFrame, since: date | None = None) -> pd.DataFrame:
    """Aggregate tonnage and set count by week and movement pattern.

    Tonnage comes from Garmin's own ``volume_kg`` -- the sum of weight x reps
    across an exercise's sets -- rather than being recomputed from the set
    table, because it reconciles exactly and covers sessions whichever way they
    were logged.

    Parameters
    ----------
    exercises : pandas.DataFrame
        Output of :func:`prepare_exercises`.
    since : datetime.date, optional
        Drop everything before this day. Normally the first weighted day, so
        the panel does not draw months of zero tonnage from before loads were
        recorded and invite them to be read as detraining.

    Returns
    -------
    pandas.DataFrame
        Columns: week_start, pattern, volume_kg, sets. One row per pattern per
        week that had work in it.
    """
    columns = ["week_start", "pattern", "volume_kg", "sets"]
    if exercises.empty:
        return pd.DataFrame(columns=columns)

    out = exercises.copy()
    if since is not None:
        out = out[out["day"] >= since]
    if out.empty:
        return pd.DataFrame(columns=columns)

    days = pd.to_datetime(out["day"])
    out["week_start"] = (days - pd.to_timedelta(days.dt.weekday, unit="D")).dt.date
    grouped = (
        out.groupby(["week_start", "pattern"], as_index=False)
        .agg(volume_kg=("volume_kg", "sum"), sets=("sets", "sum"))
    )
    return grouped.sort_values(["week_start", "pattern"]).reset_index(drop=True)[columns]


def headline(
    exercises: pd.DataFrame, sets: pd.DataFrame, today: date
) -> StrengthHeadline:
    """Summarise the current state of the strength log.

    Parameters
    ----------
    exercises : pandas.DataFrame
        Output of :func:`prepare_exercises`.
    sets : pandas.DataFrame
        Output of :func:`prepare_sets`.
    today : datetime.date
        The day the dashboard is being built for.

    Returns
    -------
    StrengthHeadline
        Header-card view model.
    """
    if exercises.empty:
        return StrengthHeadline(
            sessions_28d=0, tonnage_7d=0.0, total_tonnage_kg=0.0,
            heaviest_lift=None, heaviest_kg=None, heaviest_on=None,
            active_sets=0, settled_sets=0,
        )

    recent = exercises[exercises["day"] >= today - timedelta(days=_HEADLINE_WINDOW_DAYS)]
    week = exercises[exercises["day"] >= today - timedelta(days=_TONNAGE_WINDOW_DAYS)]

    heaviest_lift = heaviest_kg = heaviest_on = None
    if not sets.empty:
        window = sets[
            (sets["day"] >= today - timedelta(days=CURRENT_LOAD_WINDOW_DAYS))
            & sets["settled"]
        ].dropna(subset=["weight_kg"])
        window = window[window["category"] != UNIDENTIFIED_CATEGORY]
        if not window.empty:
            best = window.loc[window["weight_kg"].idxmax()]
            heaviest_lift = str(best["label"])
            heaviest_kg = float(best["weight_kg"])
            heaviest_on = best["day"]

    active = 0 if sets.empty else len(sets)
    settled = 0 if sets.empty else int(sets["settled"].sum())

    return StrengthHeadline(
        sessions_28d=int(recent["activity_id"].nunique()),
        tonnage_7d=float(week["volume_kg"].sum()),
        total_tonnage_kg=float(exercises["volume_kg"].sum()),
        heaviest_lift=heaviest_lift,
        heaviest_kg=heaviest_kg,
        heaviest_on=heaviest_on,
        active_sets=active,
        settled_sets=settled,
    )


def load_checks(sets: pd.DataFrame, today: date) -> list[LoadCheck]:
    """Compare each prescribed working load against the heaviest load recorded.

    ``plan/config.py``'s ``ATHLETE_LOADS`` is hand-maintained, and every
    strength prescription in a generated block is written against it. A load
    that has moved on the gym floor but not in the config quietly under-writes
    the next block -- the recurring failure the 2026-09-06 zone re-anchor found
    on the running side. This is the same check for the lifting side.

    Only the four lifts recorded as an unambiguous total in kilograms are
    checked, and only settled sets count, so the comparison is never between a
    prescription and a movement Garmin guessed at.

    Parameters
    ----------
    sets : pandas.DataFrame
        Output of :func:`prepare_sets`.
    today : datetime.date
        The day the dashboard is being built for.

    Returns
    -------
    list of LoadCheck
        One entry per checkable lift, in ``CONFIG_LIFT_CATEGORIES`` order.
    """
    if sets.empty:
        return []

    window = sets[
        (sets["day"] >= today - timedelta(days=CURRENT_LOAD_WINDOW_DAYS))
        & sets["settled"]
    ].dropna(subset=["weight_kg"])

    checks: list[LoadCheck] = []
    for lift, category in CONFIG_LIFT_CATEGORIES.items():
        prescription = config.ATHLETE_LOADS.get(lift)
        if prescription is None:
            continue
        config_kg = bm.parse_load_kg(prescription)
        if config_kg is None:
            continue

        matches = window[window["category"] == category]
        measured_kg = measured_lift = measured_on = None
        if not matches.empty:
            best = matches.loc[matches["weight_kg"].idxmax()]
            measured_kg = float(best["weight_kg"])
            measured_lift = str(best["label"])
            measured_on = best["day"]

        checks.append(
            LoadCheck(
                lift=lift,
                label=lift.replace("_", " ").capitalize(),
                config_kg=config_kg,
                measured_kg=measured_kg,
                measured_lift=measured_lift,
                measured_on=measured_on,
            )
        )
    return checks


def session_detail(
    exercises: pd.DataFrame, sets: pd.DataFrame, activity_id: int
) -> pd.DataFrame:
    """Lay out one session as exercises with the sets that made them up.

    Parameters
    ----------
    exercises : pandas.DataFrame
        Output of :func:`prepare_exercises`.
    sets : pandas.DataFrame
        Output of :func:`prepare_sets`.
    activity_id : int
        The session to lay out.

    Returns
    -------
    pandas.DataFrame
        Columns: label, pattern, sets, reps, max_weight_kg, volume_kg,
        set_detail, settled. ``set_detail`` reads like ``"3 x 3 @ 100 kg"`` or
        ``"3 @ 100, 3 @ 100, 4 @ 110 kg"`` when the sets differ; ``settled``
        says whether every set behind the row was certainly identified.
    """
    columns = [
        "label", "pattern", "sets", "reps", "max_weight_kg", "volume_kg",
        "set_detail", "settled",
    ]
    if exercises.empty:
        return pd.DataFrame(columns=columns)

    rows = exercises[exercises["activity_id"] == activity_id].copy()
    if rows.empty:
        return pd.DataFrame(columns=columns)

    session_sets = (
        sets[sets["activity_id"] == activity_id]
        if not sets.empty
        else pd.DataFrame(columns=sets.columns)
    )
    details, settled_flags = [], []
    for _, row in rows.iterrows():
        matching = (
            session_sets[session_sets["label"] == row["label"]]
            if not session_sets.empty
            else session_sets
        )
        details.append(_format_sets(matching))
        settled_flags.append(
            bool(len(matching)) and bool(matching["settled"].all())
        )
    rows["set_detail"] = details
    rows["settled"] = settled_flags
    return rows.sort_values("pattern").reset_index(drop=True)[columns]


def _format_sets(matching: pd.DataFrame) -> str:
    """Render a lift's sets as reps and load, collapsing identical ones.

    Examples
    --------
    >>> import pandas as pd
    >>> frame = pd.DataFrame({"reps": [3, 3, 3], "weight_kg": [100.0] * 3})
    >>> _format_sets(frame)
    '3 x 3 @ 100 kg'
    >>> _format_sets(pd.DataFrame({"reps": [5, 3], "weight_kg": [70.0, 100.0]}))
    '5 @ 70 kg, 3 @ 100 kg'
    >>> _format_sets(pd.DataFrame({"reps": [12, 12], "weight_kg": [None, None]}))
    '2 x 12'
    """
    if matching.empty:
        return "—"

    def _one(reps: object, weight: object) -> str:
        rep_text = "?" if pd.isna(reps) else f"{int(reps)}"
        if weight is None or pd.isna(weight):
            return rep_text
        return f"{rep_text} @ {float(weight):g} kg"

    rendered = [_one(r, w) for r, w in zip(matching["reps"], matching["weight_kg"])]
    if len(set(rendered)) == 1 and len(rendered) > 1:
        return f"{len(rendered)} x {rendered[0]}"
    return ", ".join(rendered)
