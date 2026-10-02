"""Monthly recap: one month of training reduced to the figures a story card shows.

Pure pandas over frames the build already holds -- no Supabase, no I/O -- so
the recap can never disagree with the tabs it summarises. Every rule is
inherited rather than restated:

* **Runs** come from :func:`dashboard.activity_metrics.prepare_runs`, so only
  outdoor and treadmill runs count as running distance and corrupt paces are
  excluded *and* counted.
* **Zones** come from :func:`dashboard.activity_metrics.assign_zones`, which
  buckets a run by its *average* heart rate. That is a proxy, and the card says
  so.
* **Planned versus done** comes from :func:`dashboard.adherence.score_sessions`,
  part by part, so a hike on a run day is a swap here exactly as it is on the
  Training plan tab.
* **Lifts** come from :func:`dashboard.strength_metrics.top_sets`, settled sets
  only, so no lift is named on Garmin's guess.

A month still in progress is compared with the same elapsed span of the month
before it, never with the whole of it, so on the 2nd the recap does not read as
a collapse.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

import pandas as pd

from dashboard import activity_metrics as am
from dashboard import adherence
from dashboard import body_metrics as bm
from dashboard import strength_metrics as sm
from plan.config import Race

# How each Garmin activity type is drawn on the calendar. Hyrox work is recorded
# as a multisport simulation or as an indoor-cardio class, so both map to it.
KIND_RUN = "run"
KIND_GYM = "gym"
KIND_HYROX = "hyrox"
KIND_OTHER = "other"
KIND_ORDER = (KIND_RUN, KIND_GYM, KIND_HYROX, KIND_OTHER)
_KIND_BY_TYPE = {
    "running": KIND_RUN,
    "treadmill_running": KIND_RUN,
    "strength_training": KIND_GYM,
    "multi_sport": KIND_HYROX,
    "indoor_cardio": KIND_HYROX,
}

# Short calendar labels for activities that are neither runs, gym nor Hyrox.
_OTHER_LABEL = {"hiking": "Hike", "cycling": "Ride", "walking": "Walk",
                "swimming": "Swim", "lap_swimming": "Swim"}

# The five lactate zones folded into the three bands a story card can show.
# Endurance runs up to LT1, so "easy" is everything at or below it.
INTENSITY_BANDS: dict[str, tuple[str, ...]] = {
    "Easy": ("Recovery", "Endurance"),
    "Tempo": ("Tempo",),
    "Threshold+": ("Threshold", "VO2max"),
}

# A lift card can hold this many rows before the type gets too small to read
# on a phone.
MAX_TOP_LIFTS = 4


def month_start(day: date) -> date:
    """First day of the month containing ``day``.

    Examples
    --------
    >>> month_start(date(2026, 9, 17))
    datetime.date(2026, 9, 1)
    """
    return day.replace(day=1)


def month_end(first: date) -> date:
    """Last day of the month starting on ``first``.

    Examples
    --------
    >>> month_end(date(2026, 2, 1))
    datetime.date(2026, 2, 28)
    """
    return first.replace(day=calendar.monthrange(first.year, first.month)[1])


def previous_month(first: date) -> date:
    """First day of the month before the one starting on ``first``.

    Examples
    --------
    >>> previous_month(date(2026, 1, 1))
    datetime.date(2025, 12, 1)
    """
    return month_start(first - timedelta(days=1))


def comparison_window(first: date, through: date) -> tuple[date, date]:
    """The span of the previous month that is comparable with ``first..through``.

    A completed month is compared with the whole previous month. A month in
    progress is compared with the same number of elapsed days, clamped to the
    previous month's length.

    Parameters
    ----------
    first : datetime.date
        First day of the month being recapped.
    through : datetime.date
        Last day counted in it.

    Returns
    -------
    tuple of datetime.date
        Inclusive start and end of the comparison span.

    Examples
    --------
    >>> comparison_window(date(2026, 3, 1), date(2026, 3, 31))
    (datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))
    >>> comparison_window(date(2026, 10, 1), date(2026, 10, 2))
    (datetime.date(2026, 9, 1), datetime.date(2026, 9, 2))
    """
    prev_first = previous_month(first)
    prev_last = month_end(prev_first)
    if through >= month_end(first):
        return prev_first, prev_last
    return prev_first, min(prev_first + timedelta(days=through.day - 1), prev_last)


@dataclass(frozen=True)
class DayMark:
    """What one calendar day held, for the cover's month grid.

    Parameters
    ----------
    day : datetime.date
        The calendar day.
    kinds : tuple of str
        Activity kinds recorded that day, in :data:`KIND_ORDER`.
    run_km : float
        Running distance that day (outdoor plus treadmill).
    others : tuple of str
        A short label per "other" activity, e.g. ``"Ride 21"`` with its km.
    """

    day: date
    kinds: tuple[str, ...] = ()
    run_km: float = 0.0
    others: tuple[str, ...] = ()


@dataclass(frozen=True)
class WeekBar:
    """Running km for the days of one plan week that fall inside the month.

    Parameters
    ----------
    week_start : datetime.date
        Monday of the week.
    first_day, last_day : datetime.date
        The week's days that fall inside the month and are counted.
    km : float
        Run km recorded on the week's days inside the month.
    planned_km : float or None
        Planned run km on those same days, ``None`` with no plan for the week.
    """

    week_start: date
    first_day: date
    last_day: date
    km: float
    planned_km: float | None


@dataclass(frozen=True)
class RunningRecap:
    """The running card.

    Parameters
    ----------
    km, prev_km : float
        Run km this month and in the comparison span.
    runs : int
        Number of runs.
    hours : float
        Moving hours (elapsed where no moving time was recorded).
    outdoor_km, treadmill_km : float
        The surface split of ``km``.
    longest_km : float
        Longest single run, 0 with no runs.
    longest_label : str
        Name and date of the longest run.
    weeks : tuple of WeekBar
        Week-by-week km inside the month.
    band_km : dict of str to float
        Km per intensity band (:data:`INTENSITY_BANDS`) by average HR.
    unzoned_km : float
        Km on runs with no heart rate, which no band can hold.
    easy_pace_s, prev_easy_pace_s : float or None
        Median pace of outdoor easy runs this month and last.
    excluded_runs : int
        Runs dropped for an implausible pace.
    """

    km: float
    prev_km: float
    runs: int
    hours: float
    outdoor_km: float
    treadmill_km: float
    longest_km: float
    longest_label: str
    weeks: tuple[WeekBar, ...]
    band_km: dict[str, float]
    unzoned_km: float
    easy_pace_s: float | None
    prev_easy_pace_s: float | None
    excluded_runs: int


@dataclass(frozen=True)
class PlanRecap:
    """Planned versus done over the month's due sessions.

    Not a card of its own: it feeds the closing lines (key sessions and the
    share of planned km).

    Parameters
    ----------
    planned_km, done_km : float
        Planned run km of the due sessions, and run km recorded on the planned
        days (unplanned runs included, as on the Training plan tab).
    sessions_due, sessions_done : int
        Due sessions (rest days excluded) and how many were fully done.
    status_counts : dict of str to int
        Due sessions per status: done, partial, swapped, missed.
    key_planned, key_done : int
        Key sessions due and done.
    gym_planned, gym_done : int
        Gym sessions due and done.
    """

    planned_km: float
    done_km: float
    sessions_due: int
    sessions_done: int
    status_counts: dict[str, int]
    key_planned: int
    key_done: int
    gym_planned: int
    gym_done: int

    @property
    def km_pct(self) -> float | None:
        """Done km as a percentage of planned km, ``None`` with nothing planned."""
        if self.planned_km <= 0:
            return None
        return 100.0 * self.done_km / self.planned_km


@dataclass(frozen=True)
class LiftLine:
    """One lift on the strength card.

    Parameters
    ----------
    label : str
        Exercise name.
    weight_kg : float
        Heaviest settled set this month.
    reps : float or None
        Reps of that set.
    day : datetime.date
        When it was lifted.
    is_pr : bool
        Heavier than any settled set of this lift in earlier months. A lift
        with no earlier history is never a PR, only a first entry.
    """

    label: str
    weight_kg: float
    reps: float | None
    day: date
    is_pr: bool


@dataclass(frozen=True)
class StrengthRecap:
    """The strength card.

    Parameters
    ----------
    sessions, prev_sessions : int
        Strength-training activities this month and in the comparison span.
    hours : float
        Elapsed hours. Moving time is never used: it drops inter-set rest and
        reads a 60-minute session as 13 minutes.
    working_sets, settled_sets : int
        Working sets recorded, and how many Garmin identified with certainty.
    tonnage_kg : float
        Load times reps over every working set, unidentified ones included.
    lifts : tuple of LiftLine
        Heaviest settled lifts, heaviest first.
    """

    sessions: int
    prev_sessions: int
    hours: float
    working_sets: int
    settled_sets: int
    tonnage_kg: float
    lifts: tuple[LiftLine, ...]


@dataclass(frozen=True)
class BodyRecap:
    """The body-and-recovery card.

    Parameters
    ----------
    weigh_ins : int
        Weigh-ins this month.
    trend_start_kg, trend_end_kg : float or None
        Trailing-mean weight entering and leaving the month. The trend rather
        than single readings, because a day's water swings exceed a month's
        real change.
    hrv_avg, prev_hrv_avg : float or None
        Mean nightly HRV this month and in the comparison span.
    hrv_nights : int
        Nights with an HRV reading.
    baseline_low, baseline_high : float or None
        Garmin's HRV baseline band on the last night of the month.
    load, prev_load : float
        Summed Garmin training load this month and in the comparison span.
    """

    weigh_ins: int
    trend_start_kg: float | None
    trend_end_kg: float | None
    hrv_avg: float | None
    prev_hrv_avg: float | None
    hrv_nights: int
    baseline_low: float | None
    baseline_high: float | None
    load: float
    prev_load: float


@dataclass(frozen=True)
class RaceRecap:
    """The race-calendar card.

    Parameters
    ----------
    raced : tuple of Race
        Races that fell inside the month.
    next_race : Race or None
        The first race after the month's last counted day.
    days_to_next : int or None
        Days from the month's last counted day to ``next_race``.
    """

    raced: tuple[Race, ...]
    next_race: Race | None
    days_to_next: int | None


@dataclass(frozen=True)
class MonthRecap:
    """Everything one month's story shows.

    Parameters
    ----------
    month : datetime.date
        First day of the month.
    through : datetime.date
        Last day counted: the month's end, or the build date mid-month.
    in_progress : bool
        Whether the month has not finished yet.
    active_days : int
        Days with at least one activity.
    sessions, prev_sessions : int
        Activities this month and in the comparison span.
    kind_counts : dict of str to int
        Activities this month per kind, in :data:`KIND_ORDER`.
    hours, prev_hours : float
        Elapsed hours across every activity.
    longest_streak : int
        Longest run of consecutive active days inside the month.
    calendar : tuple of DayMark
        One mark per day of the month, including days after ``through``.
    running : RunningRecap
        The running card.
    plan : PlanRecap or None
        Planned versus done, ``None`` when no plan covered the month.
    strength : StrengthRecap or None
        The strength card, ``None`` with no strength sessions.
    body : BodyRecap
        The body-and-recovery card.
    races : RaceRecap
        The race-calendar card.
    takeaways : tuple of str
        Short rule-based lines for the closing card.
    """

    month: date
    through: date
    in_progress: bool
    active_days: int
    sessions: int
    prev_sessions: int
    kind_counts: dict[str, int]
    hours: float
    prev_hours: float
    longest_streak: int
    calendar: tuple[DayMark, ...]
    running: RunningRecap
    plan: PlanRecap | None
    strength: StrengthRecap | None
    body: BodyRecap
    races: RaceRecap
    takeaways: tuple[str, ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        """``YYYY-MM`` identifier, used to namespace the month's elements."""
        return self.month.strftime("%Y-%m")

    @property
    def title(self) -> str:
        """Display name, e.g. ``"September 2026"``."""
        return self.month.strftime("%B %Y")


def _between(days: pd.Series, start: date, end: date) -> pd.Series:
    """Boolean mask of ``days`` falling in the inclusive span."""
    return (days >= start) & (days <= end)


def _activity_frame(activities: pd.DataFrame) -> pd.DataFrame:
    """Activities reduced to day, kind, km, elapsed hours and load."""
    if activities.empty:
        return pd.DataFrame(columns=["day", "type", "kind", "km", "hours", "load"])
    types = activities["activity_type"].fillna("").astype(str)
    frame = pd.DataFrame(
        {
            "day": pd.to_datetime(activities["start_time_local"], errors="coerce").dt.date,
            "type": types,
            "kind": types.map(_KIND_BY_TYPE).fillna(KIND_OTHER),
            "km": pd.to_numeric(activities["distance_m"], errors="coerce").fillna(0.0) / 1000.0,
            "hours": pd.to_numeric(activities["duration_s"], errors="coerce").fillna(0.0) / 3600.0,
            "load": pd.to_numeric(activities["training_load"], errors="coerce").fillna(0.0),
        }
    )
    return frame.dropna(subset=["day"])


def available_months(activities: pd.DataFrame, today: date) -> list[date]:
    """Every month from the first recorded activity to the build month.

    Parameters
    ----------
    activities : pandas.DataFrame
        Output of :func:`dashboard.query.fetch_activities`.
    today : datetime.date
        The build date.

    Returns
    -------
    list of datetime.date
        First days of the months, newest first. Empty with no activities.
    """
    frame = _activity_frame(activities)
    frame = frame[frame["day"] <= today]
    if frame.empty:
        return []
    months = []
    cursor = month_start(today)
    first = month_start(min(frame["day"]))
    while cursor >= first:
        months.append(cursor)
        cursor = previous_month(cursor)
    return months


def _longest_streak(days: set[date], start: date, end: date) -> int:
    """Longest run of consecutive days in ``days`` inside ``start..end``."""
    best = current = 0
    cursor = start
    while cursor <= end:
        current = current + 1 if cursor in days else 0
        best = max(best, current)
        cursor += timedelta(days=1)
    return best


def _calendar(frame: pd.DataFrame, first: date, last: date) -> tuple[DayMark, ...]:
    """One :class:`DayMark` per day of the month."""
    marks = []
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        today_rows = frame[frame["day"] == day]
        present = set(today_rows["kind"])
        run_km = float(today_rows.loc[today_rows["kind"] == KIND_RUN, "km"].sum())
        other_rows = today_rows[today_rows["kind"] == KIND_OTHER]
        others = tuple(
            _OTHER_LABEL.get(t, t.replace("_", " ").title()) + (f" {km:.0f}" if km >= 1 else "")
            for t, km in zip(other_rows["type"], other_rows["km"])
        )
        marks.append(
            DayMark(
                day=day,
                kinds=tuple(k for k in KIND_ORDER if k in present),
                run_km=round(run_km, 2),
                others=others,
            )
        )
    return tuple(marks)


def _median_easy_pace(trend: pd.DataFrame, start: date, end: date) -> float | None:
    """Median pace of outdoor easy runs in the span, ``None`` with none."""
    if trend.empty:
        return None
    days = trend["date"].dt.date
    easy = trend[
        _between(days, start, end)
        & trend["zone"].isin(am.EASY_ZONES)
        & ~trend["is_treadmill"]
    ]
    if easy.empty:
        return None
    return float(easy["pace_s_km"].median())


def _running(
    runs: pd.DataFrame,
    trend: pd.DataFrame,
    scored: pd.DataFrame,
    first: date,
    through: date,
    prev: tuple[date, date],
) -> RunningRecap:
    """Build the running card for ``first..through``."""
    days = runs["date"].dt.date if not runs.empty else pd.Series(dtype=object)
    in_month = runs[_between(days, first, through)] if not runs.empty else runs
    excluded = int(in_month["implausible"].sum()) if not in_month.empty else 0
    valid = am.valid_runs(in_month)

    prev_runs = runs[_between(days, *prev)] if not runs.empty else runs
    prev_km = float(am.valid_runs(prev_runs)["km"].sum()) if not prev_runs.empty else 0.0

    if valid.empty:
        longest_km, longest_label = 0.0, ""
    else:
        top = valid.loc[valid["km"].idxmax()]
        longest_km = float(top["km"])
        longest_label = f"{top['activity_name']} · {top['date']:%d %b}"

    weeks = _week_bars(valid, scored, first, through)

    band_km = {band: 0.0 for band in INTENSITY_BANDS}
    unzoned = 0.0
    if not trend.empty:
        month_trend = trend[_between(trend["date"].dt.date, first, through)]
        for band, zone_names in INTENSITY_BANDS.items():
            band_km[band] = round(
                float(month_trend.loc[month_trend["zone"].isin(zone_names), "km"].sum()), 1
            )
        unzoned = round(float(month_trend.loc[month_trend["zone"].isna(), "km"].sum()), 1)

    return RunningRecap(
        km=round(float(valid["km"].sum()), 1) if not valid.empty else 0.0,
        prev_km=round(prev_km, 1),
        runs=len(valid),
        hours=round(float(valid["seconds"].sum()) / 3600.0, 1) if not valid.empty else 0.0,
        outdoor_km=round(float(valid.loc[~valid["is_treadmill"], "km"].sum()), 1)
        if not valid.empty else 0.0,
        treadmill_km=round(float(valid.loc[valid["is_treadmill"], "km"].sum()), 1)
        if not valid.empty else 0.0,
        longest_km=round(longest_km, 1),
        longest_label=longest_label,
        weeks=weeks,
        band_km=band_km,
        unzoned_km=unzoned,
        easy_pace_s=_median_easy_pace(trend, first, through),
        prev_easy_pace_s=_median_easy_pace(trend, *prev),
        excluded_runs=excluded,
    )


def _week_bars(
    valid: pd.DataFrame, scored: pd.DataFrame, first: date, through: date
) -> tuple[WeekBar, ...]:
    """Run km per Monday-anchored week, clipped to the month's counted days."""
    bars = []
    monday = first - timedelta(days=first.weekday())
    run_days = valid["date"].dt.date if not valid.empty else pd.Series(dtype=object)
    plan_days = (
        pd.to_datetime(scored["session_date"]).dt.date
        if not scored.empty else pd.Series(dtype=object)
    )
    while monday <= through:
        lo, hi = max(monday, first), min(monday + timedelta(days=6), through)
        km = float(valid.loc[_between(run_days, lo, hi), "km"].sum()) if not valid.empty else 0.0
        planned = None
        if not scored.empty:
            week_plan = scored[_between(plan_days, lo, hi)]
            if not week_plan.empty:
                planned = round(float(week_plan["planned_km"].sum()), 1)
        bars.append(WeekBar(week_start=monday, first_day=lo, last_day=hi,
                            km=round(km, 1), planned_km=planned))
        monday += timedelta(days=7)
    return tuple(bars)


def _plan(
    scored: pd.DataFrame, activities: pd.DataFrame, first: date, through: date
) -> PlanRecap | None:
    """Score the sessions due inside the month against the plan."""
    if scored.empty:
        return None
    session_days = pd.to_datetime(scored["session_date"]).dt.date
    in_month = scored[_between(session_days, first, through)]
    if in_month.empty:
        return None

    due = in_month[in_month["status"].isin(adherence.DUE_STATUSES)]
    actuals = adherence.day_actuals(activities)
    planned_days = set(pd.to_datetime(in_month["session_date"]).dt.date)
    done_km = sum(actuals[d].run_km for d in planned_days if d in actuals and d <= through)

    counts = {s: int((due["status"] == s).sum()) for s in adherence.DUE_STATUSES}
    return PlanRecap(
        planned_km=round(float(due["planned_km"].sum()), 1),
        done_km=round(float(done_km), 1),
        sessions_due=len(due),
        sessions_done=counts["done"],
        status_counts=counts,
        key_planned=int(due["is_key"].sum()),
        key_done=int((due["is_key"] & (due["status"] == "done")).sum()),
        gym_planned=int(due["gym_planned"].sum()),
        gym_done=int(due["gym_done"].sum()),
    )


def _strength(
    frame: pd.DataFrame,
    sets: pd.DataFrame,
    first: date,
    through: date,
    prev: tuple[date, date],
) -> StrengthRecap | None:
    """Build the strength card, ``None`` when no strength session happened."""
    gym = frame[frame["kind"] == KIND_GYM]
    month_gym = gym[_between(gym["day"], first, through)]
    if month_gym.empty:
        return None
    prev_sessions = int(_between(gym["day"], *prev).sum())

    if sets.empty:
        month_sets = sets
    else:
        month_sets = sets[_between(sets["day"], first, through)]
    working = len(month_sets)
    settled = int(month_sets["settled"].sum()) if working else 0
    tonnage = (
        float((month_sets["weight_kg"].fillna(0) * month_sets["reps"].fillna(0)).sum())
        if working else 0.0
    )

    lifts: list[LiftLine] = []
    tops = sm.top_sets(sets)
    if not tops.empty:
        month_tops = tops[_between(tops["day"], first, through)]
        earlier = tops[tops["day"] < first]
        prior_best = earlier.groupby("label")["weight_kg"].max().to_dict()
        best = (
            month_tops.sort_values(["weight_kg", "day"], ascending=[False, True])
            .groupby("label", as_index=False)
            .first()
            .sort_values("weight_kg", ascending=False)
            .head(MAX_TOP_LIFTS)
        )
        for row in best.itertuples():
            previous = prior_best.get(row.label)
            lifts.append(
                LiftLine(
                    label=row.label,
                    weight_kg=float(row.weight_kg),
                    reps=None if pd.isna(row.reps) else float(row.reps),
                    day=row.day,
                    is_pr=previous is not None and float(row.weight_kg) > float(previous),
                )
            )

    return StrengthRecap(
        sessions=len(month_gym),
        prev_sessions=prev_sessions,
        hours=round(float(month_gym["hours"].sum()), 1),
        working_sets=working,
        settled_sets=settled,
        tonnage_kg=round(tonnage),
        lifts=tuple(lifts),
    )


def _mean_or_none(values: pd.Series) -> float | None:
    """Mean of the non-null values, ``None`` when there are none."""
    clean = values.dropna()
    return None if clean.empty else round(float(clean.mean()), 1)


def _body(
    frame: pd.DataFrame,
    weigh_ins: pd.DataFrame,
    hrv_series: pd.DataFrame,
    first: date,
    through: date,
    prev: tuple[date, date],
) -> BodyRecap:
    """Build the body-and-recovery card."""
    trend_start = trend_end = None
    count = 0
    if not weigh_ins.empty:
        trend = bm.trend_series(weigh_ins)
        trend_days = trend["measured_at_local"].dt.date
        in_month = trend[_between(trend_days, first, through)]
        count = len(in_month)
        if count:
            before = trend[trend_days < first]
            start_row = before.iloc[-1] if not before.empty else in_month.iloc[0]
            trend_start = round(float(start_row["trend_kg"]), 1)
            trend_end = round(float(in_month.iloc[-1]["trend_kg"]), 1)

    hrv_avg = prev_hrv = low = high = None
    nights = 0
    if not hrv_series.empty:
        hrv_days = pd.Series(hrv_series.index.date, index=hrv_series.index)
        month_hrv = hrv_series[_between(hrv_days, first, through).to_numpy()]
        prev_hrv_rows = hrv_series[_between(hrv_days, *prev).to_numpy()]
        hrv_avg = _mean_or_none(month_hrv["hrv_night"])
        prev_hrv = _mean_or_none(prev_hrv_rows["hrv_night"])
        nights = int(month_hrv["hrv_night"].notna().sum())
        banded = month_hrv.dropna(subset=["baseline_low", "baseline_high"])
        if not banded.empty:
            low = float(banded["baseline_low"].iloc[-1])
            high = float(banded["baseline_high"].iloc[-1])

    return BodyRecap(
        weigh_ins=count,
        trend_start_kg=trend_start,
        trend_end_kg=trend_end,
        hrv_avg=hrv_avg,
        prev_hrv_avg=prev_hrv,
        hrv_nights=nights,
        baseline_low=low,
        baseline_high=high,
        load=round(float(frame.loc[_between(frame["day"], first, through), "load"].sum())),
        prev_load=round(float(frame.loc[_between(frame["day"], *prev), "load"].sum())),
    )


def _races(races: tuple[Race, ...], first: date, through: date) -> RaceRecap:
    """Races inside the month and the countdown to the next one."""
    raced = tuple(r for r in races if first <= r.date <= through)
    upcoming = [r for r in races if r.date > through]
    next_race = min(upcoming, key=lambda r: r.date) if upcoming else None
    return RaceRecap(
        raced=raced,
        next_race=next_race,
        days_to_next=(next_race.date - through).days if next_race else None,
    )


def _pct_change(now: float, before: float) -> float | None:
    """Percentage change, ``None`` when there is no baseline to compare with."""
    if before <= 0:
        return None
    return 100.0 * (now - before) / before


def takeaways(recap: MonthRecap) -> tuple[str, ...]:
    """Derive the closing card's lines from fixed rules.

    Each line is a comparison the reader could check against the other cards;
    none is generated free-form, so none can claim what the data does not show.

    Parameters
    ----------
    recap : MonthRecap
        The month, with every card already built.

    Returns
    -------
    tuple of str
        Up to four lines, most important first.
    """
    lines: list[str] = []
    prev_name = previous_month(recap.month).strftime("%B")
    running = recap.running

    change = _pct_change(running.km, running.prev_km)
    if change is not None and running.km > 0:
        direction = "up" if change >= 0 else "down"
        lines.append(
            f"Running km {direction} {abs(change):.0f}% on {prev_name} "
            f"({running.prev_km:.0f} → {running.km:.0f} km)."
        )
    elif running.km > 0:
        lines.append(f"{running.km:.0f} km run across {running.runs} runs.")

    plan = recap.plan
    if plan is not None and plan.key_planned:
        lines.append(
            f"{plan.key_done} of {plan.key_planned} key sessions done"
            + (f", {plan.km_pct:.0f}% of planned km." if plan.km_pct is not None else ".")
        )

    if running.easy_pace_s is not None and running.prev_easy_pace_s is not None:
        delta = running.easy_pace_s - running.prev_easy_pace_s
        if abs(delta) >= 3:
            word = "faster" if delta < 0 else "slower"
            lines.append(
                f"Easy outdoor pace {abs(delta):.0f} s/km {word} than {prev_name}."
            )

    easy_km = running.band_km.get("Easy", 0.0)
    zoned = sum(running.band_km.values())
    if zoned > 0:
        lines.append(f"{100 * easy_km / zoned:.0f}% of run km at easy heart rate.")

    if recap.strength is not None:
        prs = [lift.label for lift in recap.strength.lifts if lift.is_pr]
        if prs:
            lines.append("New top set: " + ", ".join(prs) + ".")

    if recap.longest_streak >= 5:
        lines.append(f"Longest streak: {recap.longest_streak} active days in a row.")

    return tuple(lines[:4])


def build_month_recap(
    month: date,
    today: date,
    activities: pd.DataFrame,
    runs: pd.DataFrame,
    zones: pd.DataFrame,
    scored_sessions: pd.DataFrame,
    strength_sets: pd.DataFrame,
    weigh_ins: pd.DataFrame,
    hrv_series: pd.DataFrame,
    races: tuple[Race, ...],
) -> MonthRecap:
    """Reduce one month of every data source to a :class:`MonthRecap`.

    Parameters
    ----------
    month : datetime.date
        Any day of the month to recap.
    today : datetime.date
        The build date; a month containing it is counted up to it.
    activities : pandas.DataFrame
        Output of :func:`dashboard.query.fetch_activities`.
    runs : pandas.DataFrame
        Output of :func:`dashboard.activity_metrics.prepare_runs`.
    zones : pandas.DataFrame
        Output of :func:`dashboard.query.fetch_training_zones`.
    scored_sessions : pandas.DataFrame
        Planned sessions scored by :func:`dashboard.adherence.score_sessions`;
        may be empty.
    strength_sets : pandas.DataFrame
        Output of :func:`dashboard.strength_metrics.prepare_sets`.
    weigh_ins : pandas.DataFrame
        Output of :func:`dashboard.body_metrics.prepare_weigh_ins`.
    hrv_series : pandas.DataFrame
        Output of :func:`dashboard.metrics.build_hrv_series`.
    races : tuple of Race
        The race calendar.

    Returns
    -------
    MonthRecap
        The month's figures, ready to render.
    """
    first = month_start(month)
    last = month_end(first)
    through = min(last, today)
    prev = comparison_window(first, through)

    frame = _activity_frame(activities)
    month_rows = frame[_between(frame["day"], first, through)]
    prev_rows = frame[_between(frame["day"], *prev)]
    active = set(month_rows["day"])

    trend = am.pace_trend(runs, zones)

    recap = MonthRecap(
        month=first,
        through=through,
        in_progress=through < last,
        active_days=len(active),
        sessions=len(month_rows),
        prev_sessions=len(prev_rows),
        kind_counts={k: int((month_rows["kind"] == k).sum()) for k in KIND_ORDER},
        hours=round(float(month_rows["hours"].sum()), 1),
        prev_hours=round(float(prev_rows["hours"].sum()), 1),
        longest_streak=_longest_streak(active, first, through),
        calendar=_calendar(frame, first, last),
        running=_running(runs, trend, scored_sessions, first, through, prev),
        plan=_plan(scored_sessions, activities, first, through),
        strength=_strength(frame, strength_sets, first, through, prev),
        body=_body(frame, weigh_ins, hrv_series, first, through, prev),
        races=_races(races, first, through),
    )
    return replace(recap, takeaways=takeaways(recap))
