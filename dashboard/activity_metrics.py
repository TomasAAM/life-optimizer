"""Volume, consistency and performance aggregations over the activity log.

Pure pandas over the Garmin activity table -- no Supabase, no I/O -- so every
rule below is unit-testable in isolation. The dashboard is a static file, so
these aggregations run once at build time and are baked into the page.

Three conventions are worth stating up front, because they change the numbers:

* **What counts as a run.** Only ``running`` and ``treadmill_running``.
  ``multi_sport`` (Hyrox) sessions carry running legs, but their recorded
  distance mixes running with station work, so counting them as running
  distance would overstate it.
* **Which clock.** Pace and time use Garmin's *moving* duration where it is
  present, falling back to elapsed duration when it is zero or missing (some
  treadmill sessions record no moving time). Moving time excludes the traffic
  lights that pad street-running pace.
* **Implausible sessions.** A recorded pace outside
  ``MIN_PLAUSIBLE_PACE_S_KM``..``MAX_PLAUSIBLE_PACE_S_KM`` is a corrupt
  distance, not a performance. Those rows are flagged rather than dropped, so
  callers can exclude them *and* report how many were excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

RUN_TYPES = ("running", "treadmill_running")
TREADMILL_TYPE = "treadmill_running"

# 2:30/km is faster than a world-class 10 km; 10:00/km is slower than a brisk
# walk. Anything outside that on a recorded "run" is a bad distance reading.
MIN_PLAUSIBLE_PACE_S_KM = 150.0
MAX_PLAUSIBLE_PACE_S_KM = 600.0

# Zones treated as easy for the pace-trend and efficiency series.
EASY_ZONES = ("Recovery", "Endurance")

_CONSISTENCY_WINDOW_DAYS = 28

# ``to_period`` codes. Weeks are anchored on Sunday so ``start_time`` is the
# Monday, matching the plan weeks and ``dashboard.metrics.weekly_summary``.
_PERIOD_FREQ = {"week": "W-SUN", "month": "M", "year": "Y"}
GRANULARITIES = tuple(_PERIOD_FREQ)


@dataclass(frozen=True)
class VolumeHeadline:
    """Running distance for the current periods, against like-for-like priors.

    The prior figures cover the *same elapsed span* of the previous period --
    this week through Wednesday against last week through Wednesday -- so a
    period in progress is never compared against a completed one.

    Parameters
    ----------
    km_week, km_month, km_year : float
        Distance run in the current week, calendar month, and year to date.
    km_week_prior, km_month_prior : float
        Distance over the same elapsed span of the previous week and month.
    km_total : float
        Distance run across the whole log.
    runs_total : int
        Number of runs counted.
    excluded_runs : int
        Runs omitted for an implausible recorded pace.
    """

    km_week: float
    km_week_prior: float
    km_month: float
    km_month_prior: float
    km_year: float
    km_total: float
    runs_total: int
    excluded_runs: int

    @property
    def week_delta(self) -> float:
        """Change in weekly distance against the same span last week, in km."""
        return self.km_week - self.km_week_prior

    @property
    def month_delta(self) -> float:
        """Change in monthly distance against the same span last month, in km."""
        return self.km_month - self.km_month_prior


@dataclass(frozen=True)
class ConsistencySummary:
    """Training frequency over the recent window and across the whole log.

    Streaks count *any* activity, not just runs -- a gym day is a training day.
    The current streak is measured back from today, or from yesterday when
    today has no activity yet, so it does not read as broken at nine in the
    morning.

    Parameters
    ----------
    training_days_28, rest_days_28 : int
        Days with and without an activity over the last 28 days.
    current_streak, longest_streak : int
        Consecutive training days now, and the longest ever recorded.
    days_since_last_run : int or None
        Days since the most recent run, or ``None`` when none is on record.
    """

    training_days_28: int
    rest_days_28: int
    current_streak: int
    longest_streak: int
    days_since_last_run: int | None


def _effective_seconds(moving: pd.Series, elapsed: pd.Series) -> pd.Series:
    """Pick the moving clock per activity, falling back to elapsed.

    Parameters
    ----------
    moving, elapsed : pandas.Series
        Numeric moving and elapsed durations in seconds.

    Returns
    -------
    pandas.Series
        Moving seconds where positive, else elapsed seconds.
    """
    usable = moving.notna() & (moving > 0)
    return moving.where(usable, elapsed)


def prepare_runs(activities: pd.DataFrame) -> pd.DataFrame:
    """Reduce the activity log to runs with derived distance, time and pace.

    Every run is returned, including implausible ones -- the ``implausible``
    flag lets a caller both exclude them and count what it excluded.

    Parameters
    ----------
    activities : pandas.DataFrame
        Output of :func:`dashboard.query.fetch_activities`.

    Returns
    -------
    pandas.DataFrame
        Columns: date, activity_name, km, seconds, pace_s_km, avg_hr,
        is_treadmill, implausible. Empty (with those columns) when no runs
        are present.
    """
    columns = [
        "date", "activity_name", "km", "seconds", "pace_s_km",
        "avg_hr", "is_treadmill", "implausible",
    ]
    if activities.empty or "activity_type" not in activities:
        return pd.DataFrame(columns=columns)

    runs = activities[activities["activity_type"].isin(RUN_TYPES)].copy()
    if runs.empty:
        return pd.DataFrame(columns=columns)

    distance_m = pd.to_numeric(runs["distance_m"], errors="coerce")
    seconds = _effective_seconds(
        pd.to_numeric(runs["moving_duration_s"], errors="coerce"),
        pd.to_numeric(runs["duration_s"], errors="coerce"),
    )
    km = distance_m / 1000.0
    # Guard the division: a zero-distance row would otherwise yield an
    # infinity that no plausibility band can catch. A NaN pace fails the
    # ``between`` test and is therefore flagged implausible, which is right.
    pace = (seconds / km).where(km > 0)

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(runs["start_time_local"]).dt.normalize(),
            "activity_name": runs["activity_name"],
            "km": km.fillna(0.0),
            "seconds": seconds.fillna(0.0),
            "pace_s_km": pace,
            "avg_hr": pd.to_numeric(runs["avg_hr"], errors="coerce"),
            "is_treadmill": runs["activity_type"].eq(TREADMILL_TYPE),
            "implausible": ~pace.between(
                MIN_PLAUSIBLE_PACE_S_KM, MAX_PLAUSIBLE_PACE_S_KM
            ),
        }
    )
    return out.sort_values("date").reset_index(drop=True)


def valid_runs(runs: pd.DataFrame) -> pd.DataFrame:
    """Drop the runs whose recorded pace is implausible.

    Parameters
    ----------
    runs : pandas.DataFrame
        Output of :func:`prepare_runs`.

    Returns
    -------
    pandas.DataFrame
        ``runs`` without the flagged rows.
    """
    if runs.empty:
        return runs
    return runs[~runs["implausible"]]


def volume_by_period(
    runs: pd.DataFrame, granularity: str, through: date | None = None
) -> pd.DataFrame:
    """Aggregate running volume into weeks, months or years.

    Periods with no running are emitted as zeros rather than skipped, so a week
    off reads as a gap in the bar chart instead of silently closing up.

    Parameters
    ----------
    runs : pandas.DataFrame
        Output of :func:`prepare_runs`.
    granularity : {"week", "month", "year"}
        Period size.
    through : datetime.date, optional
        Extend the zero-fill to the period containing this date, so the current
        period appears even before its first run.

    Returns
    -------
    pandas.DataFrame
        Columns: period_start, label, km, hours, runs -- chronological.
    """
    freq = _PERIOD_FREQ[granularity]
    columns = ["period_start", "label", "km", "hours", "runs"]
    usable = valid_runs(runs)
    if usable.empty:
        return pd.DataFrame(columns=columns)

    periods = usable["date"].dt.to_period(freq)
    grouped = usable.groupby(periods).agg(
        km=("km", "sum"), seconds=("seconds", "sum"), runs=("km", "size")
    )

    last = periods.max()
    if through is not None:
        last = max(last, pd.Period(through, freq=freq))
    grouped = grouped.reindex(
        pd.period_range(periods.min(), last, freq=freq), fill_value=0.0
    )

    return pd.DataFrame(
        {
            "period_start": grouped.index.start_time,
            "label": _period_labels(grouped.index, granularity),
            "km": grouped["km"].round(2).to_numpy(),
            "hours": (grouped["seconds"] / 3600.0).round(2).to_numpy(),
            "runs": grouped["runs"].astype(int).to_numpy(),
        }
    ).reset_index(drop=True)


def _period_labels(index: pd.PeriodIndex, granularity: str) -> list[str]:
    """Format period labels for the x-axis of the volume chart."""
    if granularity == "week":
        return [f"{p.start_time:%d %b}" for p in index]
    if granularity == "month":
        return [f"{p.start_time:%b %Y}" for p in index]
    return [f"{p.start_time:%Y}" for p in index]


def _sum_between(runs: pd.DataFrame, start: date, end: date) -> float:
    """Total valid running distance over an inclusive date window."""
    if runs.empty:
        return 0.0
    dates = runs["date"].dt.date
    window = runs[(dates >= start) & (dates <= end)]
    return float(window["km"].sum())


def _clamped(year: int, month: int, day: int) -> date:
    """Build a date, clamping the day to the last day of that month.

    Comparing 31 March against February needs a defined end -- the prior window
    stops at the month's last day rather than overflowing into March.
    """
    next_month_start = (
        date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    )
    last_day = (next_month_start - timedelta(days=1)).day
    return date(year, month, min(day, last_day))


def volume_headline(runs: pd.DataFrame, today: date) -> VolumeHeadline:
    """Summarise current-period distance against like-for-like priors.

    Parameters
    ----------
    runs : pandas.DataFrame
        Output of :func:`prepare_runs`.
    today : datetime.date
        The day the dashboard is being built for.

    Returns
    -------
    VolumeHeadline
        Week, month and year-to-date distance with prior-period comparisons.
    """
    usable = valid_runs(runs)
    excluded = int(runs["implausible"].sum()) if not runs.empty else 0

    week_start = today - timedelta(days=today.weekday())
    days_in = (today - week_start).days
    prior_week_start = week_start - timedelta(days=7)

    month_start = today.replace(day=1)
    prior_month_start = (month_start - timedelta(days=1)).replace(day=1)

    return VolumeHeadline(
        km_week=_sum_between(usable, week_start, today),
        km_week_prior=_sum_between(
            usable, prior_week_start, prior_week_start + timedelta(days=days_in)
        ),
        km_month=_sum_between(usable, month_start, today),
        km_month_prior=_sum_between(
            usable,
            prior_month_start,
            _clamped(prior_month_start.year, prior_month_start.month, today.day),
        ),
        km_year=_sum_between(usable, date(today.year, 1, 1), today),
        km_total=float(usable["km"].sum()) if not usable.empty else 0.0,
        runs_total=int(len(usable)),
        excluded_runs=excluded,
    )


def _longest_run_of_days(days: list[date]) -> int:
    """Length of the longest consecutive-day span in a sorted date list."""
    longest = 0
    current = 0
    previous: date | None = None
    for day in days:
        consecutive = previous is not None and day - previous == timedelta(days=1)
        current = current + 1 if consecutive else 1
        longest = max(longest, current)
        previous = day
    return longest


def consistency(
    activities: pd.DataFrame, runs: pd.DataFrame, today: date
) -> ConsistencySummary:
    """Summarise training frequency and streaks.

    Parameters
    ----------
    activities : pandas.DataFrame
        Output of :func:`dashboard.query.fetch_activities` -- every discipline.
    runs : pandas.DataFrame
        Output of :func:`prepare_runs`, used only for days-since-last-run.
    today : datetime.date
        The day the dashboard is being built for.

    Returns
    -------
    ConsistencySummary
        Training days, rest days, current and longest streak.
    """
    if activities.empty:
        return ConsistencySummary(0, _CONSISTENCY_WINDOW_DAYS, 0, 0, None)

    days = sorted(set(pd.to_datetime(activities["start_time_local"]).dt.date.dropna()))
    day_set = set(days)

    window_start = today - timedelta(days=_CONSISTENCY_WINDOW_DAYS - 1)
    trained = sum(1 for d in day_set if window_start <= d <= today)

    # A streak should not read as broken simply because today's session has
    # not happened yet, so it may end on yesterday.
    cursor = today if today in day_set else today - timedelta(days=1)
    current = 0
    while cursor in day_set:
        current += 1
        cursor -= timedelta(days=1)

    last_run = None
    usable_runs = valid_runs(runs)
    if not usable_runs.empty:
        last_run = (today - usable_runs["date"].dt.date.max()).days

    return ConsistencySummary(
        training_days_28=trained,
        rest_days_28=_CONSISTENCY_WINDOW_DAYS - trained,
        current_streak=current,
        longest_streak=_longest_run_of_days(days),
        days_since_last_run=last_run,
    )


def daily_distance(runs: pd.DataFrame, today: date) -> pd.DataFrame:
    """Build a gap-free daily distance series for the calendar heatmap.

    Parameters
    ----------
    runs : pandas.DataFrame
        Output of :func:`prepare_runs`.
    today : datetime.date
        Last day of the calendar.

    Returns
    -------
    pandas.DataFrame
        Columns: date, km, week_start, weekday (0=Monday) -- one row per day
        from the first run to ``today``, rest days included as zero.
    """
    columns = ["date", "km", "week_start", "weekday"]
    usable = valid_runs(runs)
    if usable.empty:
        return pd.DataFrame(columns=columns)

    daily = usable.groupby("date")["km"].sum()
    span = pd.date_range(daily.index.min(), pd.Timestamp(today), freq="D")
    daily = daily.reindex(span, fill_value=0.0)

    return pd.DataFrame(
        {
            "date": daily.index,
            "km": daily.to_numpy().round(2),
            "week_start": daily.index.to_period("W-SUN").start_time,
            "weekday": daily.index.weekday,
        }
    )


def assign_zones(runs: pd.DataFrame, zones: pd.DataFrame) -> pd.Series:
    """Bucket each run into a lactate zone by its average heart rate.

    Bounds are lower-inclusive and upper-exclusive, and the open ends of the
    first and last zone (stored as NULL) become infinities -- so a heart rate
    below the Recovery ceiling is Recovery, and one at or above LT2 is VO2max.

    This is a coarse proxy: a session average flattens an interval workout's
    real distribution into one bucket. True time-in-zone needs the per-reading
    heart-rate series, not the activity summary.

    Parameters
    ----------
    runs : pandas.DataFrame
        Output of :func:`prepare_runs`.
    zones : pandas.DataFrame
        Output of :func:`dashboard.query.fetch_training_zones`.

    Returns
    -------
    pandas.Series
        Zone name per run, aligned to ``runs.index``; NA where the heart rate
        or the zone table is missing.
    """
    if runs.empty or zones.empty or "hr_low" not in zones:
        return pd.Series(pd.NA, index=runs.index, dtype="object")

    ordered = zones.sort_values("zone_index")
    lows = pd.to_numeric(ordered["hr_low"], errors="coerce").to_numpy()
    edges = [-np.inf, *lows[1:], np.inf]
    labels = ordered["zone_name"].tolist()

    binned = pd.cut(runs["avg_hr"], bins=edges, labels=labels, right=False)
    return pd.Series(binned, index=runs.index).astype("object")


def pace_trend(runs: pd.DataFrame, zones: pd.DataFrame) -> pd.DataFrame:
    """Per-run pace over time, tagged with its zone and surface.

    Parameters
    ----------
    runs : pandas.DataFrame
        Output of :func:`prepare_runs`.
    zones : pandas.DataFrame
        Output of :func:`dashboard.query.fetch_training_zones`.

    Returns
    -------
    pandas.DataFrame
        Columns: date, activity_name, km, pace_s_km, avg_hr, is_treadmill,
        zone -- implausible runs excluded.
    """
    usable = valid_runs(runs)
    if usable.empty:
        return pd.DataFrame(
            columns=["date", "activity_name", "km", "pace_s_km",
                     "avg_hr", "is_treadmill", "zone"]
        )
    out = usable.assign(zone=assign_zones(usable, zones))
    return out.drop(columns=["implausible", "seconds"]).reset_index(drop=True)


def _easy_outdoor(trend: pd.DataFrame) -> pd.DataFrame:
    """Easy-zone outdoor runs -- the only comparable basis for a pace trend.

    Treadmill pace is set by the belt rather than earned, so mixing it in
    would track the machine's settings, not fitness.
    """
    if trend.empty:
        return trend
    return trend[trend["zone"].isin(EASY_ZONES) & ~trend["is_treadmill"]]


def monthly_easy_pace(trend: pd.DataFrame) -> pd.DataFrame:
    """Median pace of easy outdoor runs per month.

    Parameters
    ----------
    trend : pandas.DataFrame
        Output of :func:`pace_trend`.

    Returns
    -------
    pandas.DataFrame
        Columns: month_start, pace_s_km, runs.
    """
    easy = _easy_outdoor(trend)
    if easy.empty:
        return pd.DataFrame(columns=["month_start", "pace_s_km", "runs"])

    grouped = easy.groupby(easy["date"].dt.to_period("M")).agg(
        pace_s_km=("pace_s_km", "median"), runs=("pace_s_km", "size")
    )
    return pd.DataFrame(
        {
            "month_start": grouped.index.start_time,
            "pace_s_km": grouped["pace_s_km"].round(1).to_numpy(),
            "runs": grouped["runs"].astype(int).to_numpy(),
        }
    )


def aerobic_efficiency(trend: pd.DataFrame) -> pd.DataFrame:
    """Monthly efficiency factor for easy outdoor runs.

    Efficiency factor is speed per heartbeat -- metres per minute divided by
    average heart rate. Holding intensity easy, a rising value means the same
    heart rate is buying more speed, which is aerobic fitness improving.

    Parameters
    ----------
    trend : pandas.DataFrame
        Output of :func:`pace_trend`.

    Returns
    -------
    pandas.DataFrame
        Columns: month_start, efficiency, runs.
    """
    easy = _easy_outdoor(trend)
    if not easy.empty:
        easy = easy[easy["avg_hr"] > 0]
    if easy.empty:
        return pd.DataFrame(columns=["month_start", "efficiency", "runs"])

    metres_per_minute = 60_000.0 / easy["pace_s_km"]
    frame = pd.DataFrame(
        {
            "month": easy["date"].dt.to_period("M"),
            "efficiency": metres_per_minute / easy["avg_hr"],
        }
    )
    grouped = frame.groupby("month").agg(
        efficiency=("efficiency", "median"), runs=("efficiency", "size")
    )
    return pd.DataFrame(
        {
            "month_start": grouped.index.start_time,
            "efficiency": grouped["efficiency"].round(3).to_numpy(),
            "runs": grouped["runs"].astype(int).to_numpy(),
        }
    )
