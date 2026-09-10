"""Bodyweight and body-composition aggregations.

Pure pandas over the ``body_composition`` table -- no Supabase, no I/O -- so
every rule below is unit-testable in isolation, matching
:mod:`dashboard.activity_metrics`.

Four conventions govern how these numbers are read, because each one changes
what the panels are allowed to claim:

* **Only weight is measured.** The scale reports weight from a load cell and
  everything else from a single bioimpedance reading pushed through the
  vendor's undisclosed regression. Body fat, lean mass, bone mass and body
  water are therefore not four signals but one, and are never presented as
  independent trends.
* **A single weigh-in is not a bodyweight.** Day-to-day readings carry roughly
  a kilogram of hydration, glycogen and gut-content noise, so the trend line is
  the signal and the raw points are shown to make the scatter visible rather
  than to be read individually.
* **Rate of change is fitted, not differenced.** The change between two
  readings is dominated by the noise in those two readings; a least-squares fit
  over a trailing window is not. Below ``_MIN_RATE_SPAN_DAYS`` of span the fit
  is refused outright rather than extrapolated.
* **Time of day is a data-quality dimension.** ``BENCHMARKS.md`` prescribes
  weighing weekly and fasted, in the morning. An evening weigh-in reads 1-1.5 kg
  heavier for reasons that have nothing to do with training, so off-protocol
  readings are flagged and counted rather than silently averaged in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from plan import config

# Readings at or after this hour are off the fasted-AM protocol in
# ``BENCHMARKS.md``. Ten o'clock rather than midday: by then a normal morning
# has included breakfast and fluids, which is exactly what the protocol excludes.
PROTOCOL_LATEST_HOUR = 10

# Trailing window for the trend line. Fourteen days rather than seven because
# the prescribed cadence is weekly: a 7-day window over weekly readings contains
# exactly one reading and therefore does no smoothing at all, while 14 days
# averages the two most recent and damps a single bad reading.
TREND_WINDOW_DAYS = 14

# Trailing window the rate of change is fitted over, and the minimum span of
# readings that fit is allowed to use.
RATE_WINDOW_DAYS = 28
_MIN_RATE_SPAN_DAYS = 7
_MIN_RATE_READINGS = 3

# Loss faster than this costs lean mass and session quality rather than just
# fat, which for a concurrent Hyrox/21k build is a training problem and not a
# dietary success. Signed, so it reads as a floor on the rate.
AGGRESSIVE_LOSS_KG_WEEK = -0.7

_DELTA_WINDOW_DAYS = 28

# Lifts whose recorded load in ``plan.config.ATHLETE_LOADS`` is an unambiguous
# total in kilograms, and so can be divided by bodyweight to mean something.
# The others are deliberately excluded: `pull_up` is recorded as
# "bodyweight +5 kg", which makes a bodyweight ratio circular; `weighted_step_up`
# and `dumbbell_bench_press` are recorded per hand, so the number in the string
# is half the load lifted; `wall_balls` and `sandbag_lunges` are Hyrox station
# standards rather than strength tests.
RELATIVE_STRENGTH_LIFTS = (
    "back_squat", "trap_bar_deadlift", "hip_thrust", "overhead_press",
)
_LIFT_LABELS = {
    "back_squat": "Back squat",
    "trap_bar_deadlift": "Trap-bar deadlift",
    "hip_thrust": "Hip thrust",
    "overhead_press": "Overhead press",
}
_LEADING_KG = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*kg", re.IGNORECASE)


@dataclass(frozen=True)
class BodyHeadline:
    """Current-state summary of the weigh-in series.

    Parameters
    ----------
    trend_weight_kg : float or None
        Latest value of the trend line -- the number to quote as "your weight".
        ``None`` when there are no readings.
    latest_weight_kg : float or None
        The most recent raw reading, noise included.
    latest_at : pandas.Timestamp or None
        When that reading was taken.
    delta_kg : float or None
        Change in the trend over the last 28 days. ``None`` when the series does
        not reach back that far.
    rate_kg_week : float or None
        Fitted rate of change in kg/week, or ``None`` when the readings span too
        little time to fit one.
    body_fat_pct : float or None
        Most recent body-fat estimate.
    fat_mass_kg : float or None
        Derived as ``weight * body_fat_pct / 100``.
    lean_mass_kg : float or None
        Derived as ``weight - fat_mass_kg``, so the two sum to the weight.
    readings : int
        Number of weigh-ins on record.
    off_protocol : int
        How many of those were taken at or after :data:`PROTOCOL_LATEST_HOUR`.
    """

    trend_weight_kg: float | None
    latest_weight_kg: float | None
    latest_at: pd.Timestamp | None
    delta_kg: float | None
    rate_kg_week: float | None
    body_fat_pct: float | None
    fat_mass_kg: float | None
    lean_mass_kg: float | None
    readings: int
    off_protocol: int


@dataclass(frozen=True)
class RelativeStrength:
    """One lift's working load expressed against bodyweight.

    Parameters
    ----------
    lift : str
        Key in :data:`plan.config.ATHLETE_LOADS`.
    label : str
        Display name.
    load_kg : float
        The working load parsed from the recorded prescription.
    ratio : float
        ``load_kg / bodyweight``.
    """

    lift: str
    label: str
    load_kg: float
    ratio: float


def prepare_weigh_ins(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalise raw ``body_composition`` rows into a weigh-in series.

    Adds the derived composition split and the protocol flag, and sorts
    chronologically. Fat and lean mass are both derived from weight and body
    fat rather than read from the reported ``lean_mass_kg``, so that the two
    always sum to the weight on the same row -- a reported lean mass comes from
    a separate Health Connect record and need not reconcile.

    Parameters
    ----------
    frame : pandas.DataFrame
        Rows as returned by :func:`dashboard.query.fetch_body_composition`.

    Returns
    -------
    pandas.DataFrame
        Columns: measured_at_local, day, weight_kg, body_fat_pct, fat_mass_kg,
        lean_mass_kg, hour, off_protocol. Empty in, empty out.
    """
    columns = [
        "measured_at_local", "day", "weight_kg", "body_fat_pct",
        "fat_mass_kg", "lean_mass_kg", "hour", "off_protocol",
    ]
    if frame.empty or "measured_at_local" not in frame:
        return pd.DataFrame(columns=columns)

    out = frame.copy()
    # Parsed without ``utc=True`` on purpose. The column is a wall clock, and
    # forcing UTC would move a Santiago 07:12 weigh-in to 10:12 and flag an
    # on-protocol reading as an evening one.
    out["measured_at_local"] = pd.to_datetime(
        out["measured_at_local"], errors="coerce"
    )
    if isinstance(out["measured_at_local"].dtype, pd.DatetimeTZDtype):
        out["measured_at_local"] = out["measured_at_local"].dt.tz_localize(None)
    out["weight_kg"] = pd.to_numeric(out.get("weight_kg"), errors="coerce")
    out["body_fat_pct"] = pd.to_numeric(
        out.get("body_fat_pct", pd.Series(dtype="float64")), errors="coerce"
    )
    out = out.dropna(subset=["measured_at_local", "weight_kg"])
    if out.empty:
        return pd.DataFrame(columns=columns)

    out["day"] = out["measured_at_local"].dt.date
    out["hour"] = out["measured_at_local"].dt.hour
    out["off_protocol"] = out["hour"] >= PROTOCOL_LATEST_HOUR
    out["fat_mass_kg"] = out["weight_kg"] * out["body_fat_pct"] / 100.0
    out["lean_mass_kg"] = out["weight_kg"] - out["fat_mass_kg"]

    out = out.sort_values("measured_at_local").reset_index(drop=True)
    return out[columns]


def trend_series(
    weigh_ins: pd.DataFrame, window_days: int = TREND_WINDOW_DAYS
) -> pd.DataFrame:
    """Compute the trailing-mean trend through the weigh-ins.

    Uses a time-based window rather than a fixed number of readings, so an
    irregular weigh-in cadence does not silently change how much smoothing is
    applied.

    Parameters
    ----------
    weigh_ins : pandas.DataFrame
        Output of :func:`prepare_weigh_ins`.
    window_days : int, optional
        Width of the trailing window in days.

    Returns
    -------
    pandas.DataFrame
        Columns: measured_at_local, trend_kg. One row per weigh-in.
    """
    if weigh_ins.empty:
        return pd.DataFrame(columns=["measured_at_local", "trend_kg"])

    indexed = weigh_ins.set_index("measured_at_local")["weight_kg"].sort_index()
    trend = indexed.rolling(f"{window_days}D", min_periods=1).mean()
    return trend.rename("trend_kg").reset_index()


def rate_kg_per_week(
    weigh_ins: pd.DataFrame,
    today: date,
    window_days: int = RATE_WINDOW_DAYS,
) -> float | None:
    """Fit the rate of weight change over a trailing window.

    A least-squares fit rather than a difference between endpoints: differencing
    two readings propagates the full hydration noise of both, which on a weekly
    cadence can swamp a real trend.

    Parameters
    ----------
    weigh_ins : pandas.DataFrame
        Output of :func:`prepare_weigh_ins`.
    today : datetime.date
        The day the dashboard is being built for.
    window_days : int, optional
        How far back to fit.

    Returns
    -------
    float or None
        Rate in kg/week, negative for loss. ``None`` when the window holds
        fewer than three readings or spans under a week -- a slope from less
        than that is noise scaled up to a weekly figure.
    """
    if weigh_ins.empty:
        return None

    cutoff = pd.Timestamp(today) - timedelta(days=window_days)
    window = weigh_ins[weigh_ins["measured_at_local"] >= cutoff]
    if len(window) < _MIN_RATE_READINGS:
        return None

    days = (
        window["measured_at_local"] - window["measured_at_local"].min()
    ).dt.total_seconds()
    days = days / 86_400.0
    if days.max() < _MIN_RATE_SPAN_DAYS:
        return None

    slope_per_day = float(np.polyfit(days.to_numpy(), window["weight_kg"].to_numpy(), 1)[0])
    return slope_per_day * 7.0


def _trend_at_or_before(trend: pd.DataFrame, when: pd.Timestamp) -> float | None:
    """Return the trend value at the last weigh-in on or before ``when``."""
    prior = trend[trend["measured_at_local"] <= when]
    if prior.empty:
        return None
    return float(prior["trend_kg"].iloc[-1])


def headline(weigh_ins: pd.DataFrame, today: date) -> BodyHeadline:
    """Summarise the current state of the weigh-in series.

    Parameters
    ----------
    weigh_ins : pandas.DataFrame
        Output of :func:`prepare_weigh_ins`.
    today : datetime.date
        The day the dashboard is being built for.

    Returns
    -------
    BodyHeadline
        Header-card view model; every field is ``None`` when there is no data.
    """
    if weigh_ins.empty:
        return BodyHeadline(
            trend_weight_kg=None, latest_weight_kg=None, latest_at=None,
            delta_kg=None, rate_kg_week=None, body_fat_pct=None,
            fat_mass_kg=None, lean_mass_kg=None, readings=0, off_protocol=0,
        )

    trend = trend_series(weigh_ins)
    trend_now = float(trend["trend_kg"].iloc[-1])
    then = _trend_at_or_before(
        trend, pd.Timestamp(today) - timedelta(days=_DELTA_WINDOW_DAYS)
    )
    latest = weigh_ins.iloc[-1]

    def _maybe(value: object) -> float | None:
        return None if value is None or pd.isna(value) else float(value)

    return BodyHeadline(
        trend_weight_kg=trend_now,
        latest_weight_kg=float(latest["weight_kg"]),
        latest_at=latest["measured_at_local"],
        delta_kg=None if then is None else trend_now - then,
        rate_kg_week=rate_kg_per_week(weigh_ins, today),
        body_fat_pct=_maybe(latest["body_fat_pct"]),
        fat_mass_kg=_maybe(latest["fat_mass_kg"]),
        lean_mass_kg=_maybe(latest["lean_mass_kg"]),
        readings=len(weigh_ins),
        off_protocol=int(weigh_ins["off_protocol"].sum()),
    )


def composition_series(weigh_ins: pd.DataFrame) -> pd.DataFrame:
    """Return the weigh-ins that carry a body-fat estimate.

    Parameters
    ----------
    weigh_ins : pandas.DataFrame
        Output of :func:`prepare_weigh_ins`.

    Returns
    -------
    pandas.DataFrame
        The subset with a non-null ``body_fat_pct``, and so a usable fat/lean
        split. Readings where the scale failed to get an impedance measurement
        still carry a valid weight and are kept by :func:`prepare_weigh_ins`;
        they simply cannot appear here.
    """
    if weigh_ins.empty:
        return weigh_ins
    return weigh_ins.dropna(subset=["body_fat_pct"]).reset_index(drop=True)


def parse_load_kg(prescription: str) -> float | None:
    """Extract the leading kilogram figure from a recorded prescription.

    Parameters
    ----------
    prescription : str
        A value from :data:`plan.config.ATHLETE_LOADS`, e.g.
        ``"100 kg for triples @ RPE ~8"``.

    Returns
    -------
    float or None
        The load in kilograms, or ``None`` when the string does not start with
        one.

    Examples
    --------
    >>> parse_load_kg("130 kg for top triples @ RPE 8")
    130.0
    >>> parse_load_kg("bodyweight +5 kg for sets of 4 @ RPE 8") is None
    True
    """
    match = _LEADING_KG.match(prescription)
    return float(match.group(1)) if match else None


def relative_strength(weight_kg: float | None) -> list[RelativeStrength]:
    """Express each unambiguous working load as a multiple of bodyweight.

    Power-to-weight is what the running half of Hyrox rewards, so absolute
    kilograms alone mislead -- the same rationale that put
    :data:`plan.config.ATHLETE_BODYWEIGHT_KG` in the plan config. This computes
    the same ratios against the *measured* trend weight instead of that
    hard-coded constant.

    Parameters
    ----------
    weight_kg : float or None
        Bodyweight to divide by, normally the trend weight.

    Returns
    -------
    list of RelativeStrength
        One entry per lift in :data:`RELATIVE_STRENGTH_LIFTS` whose recorded
        load parses. Empty when there is no weight to divide by.
    """
    if weight_kg is None or weight_kg <= 0:
        return []

    out: list[RelativeStrength] = []
    for lift in RELATIVE_STRENGTH_LIFTS:
        prescription = config.ATHLETE_LOADS.get(lift)
        if prescription is None:
            continue
        load = parse_load_kg(prescription)
        if load is None:
            continue
        out.append(
            RelativeStrength(
                lift=lift,
                label=_LIFT_LABELS.get(lift, lift.replace("_", " ").capitalize()),
                load_kg=load,
                ratio=load / weight_kg,
            )
        )
    return out


def config_weight_disagreement(weight_kg: float | None) -> float | None:
    """Gap between the measured trend weight and the plan config's constant.

    :data:`plan.config.ATHLETE_BODYWEIGHT_KG` is a self-reported figure that
    every relative-strength number in ``BENCHMARKS.md`` is computed against.
    Once the scale is feeding real weights the two can drift, and a stale
    constant quietly rescales those benchmarks, so the gap is surfaced rather
    than left to be noticed.

    Parameters
    ----------
    weight_kg : float or None
        Measured trend weight.

    Returns
    -------
    float or None
        ``weight_kg - ATHLETE_BODYWEIGHT_KG``, or ``None`` with no measurement.
    """
    if weight_kg is None:
        return None
    return weight_kg - config.ATHLETE_BODYWEIGHT_KG
