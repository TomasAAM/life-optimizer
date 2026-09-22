"""Match planned sessions to what Garmin actually recorded.

The previous rule marked a planned session "done" whenever *any* activity landed
on its date, so a hike on an easy-run day, or a gym session on a gym-plus-run
day with the run skipped, both read as complete. Here each planned session is
broken into the parts it asks for, and each part is checked against that day's
activities:

* **run km** -- the prescription's ``distance_m``. Met by outdoor and treadmill
  runs plus multisport sessions, because the plan counts the running inside a
  Hyrox simulation toward the week's km and so must the comparison.
* **gym** -- any ``strength`` step. Met by a strength-training activity.
* **stations** -- any ``station`` step, or a ``sim`` session. Met by a strength,
  indoor-cardio (Hyrox class) or multisport activity, since station work is
  recorded under all three.

A planned day is one row even when it holds a gym-AM plus run-PM double, so the
day's activities are pooled and compared with the row as a whole.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from dashboard.activity_metrics import RUN_TYPES

SIM_TYPES = ("multi_sport",)
GYM_TYPES = ("strength_training",)
STATION_TYPES = ("strength_training", "indoor_cardio", "multi_sport")

# Share of the planned km that counts as the run being done. Below it the run
# was cut short enough to matter; above it the gap is GPS noise and rounding.
DONE_KM_FRACTION = 0.85

# A run of at least this distance is the week's long run, which is a key session
# alongside anything prescribed as hard (threshold, simulations).
LONG_RUN_MIN_KM = 14.0

# Statuses that describe a session that was due and has an outcome.
DUE_STATUSES = ("done", "partial", "swapped", "missed")

# Title words that mark the gym half of a legacy session with no structured steps.
_GYM_TITLE_PATTERN = re.compile(r"\b(strength|gym|upper|lower)\b")

_ACTIVITY_LABELS = {
    "hiking": "hike",
    "cycling": "ride",
    "walking": "walk",
    "indoor_cardio": "Hyrox class",
    "multi_sport": "multisport session",
    "strength_training": "gym session",
}


@dataclass(frozen=True)
class SessionNeeds:
    """The parts a planned session asks for.

    Parameters
    ----------
    run_km : float
        Planned running distance, 0 when the session has no run.
    gym : bool
        Whether the session includes gym strength work.
    station : bool
        Whether the session includes Hyrox station work.
    """

    run_km: float
    gym: bool
    station: bool

    def describe(self) -> str:
        """Short human description listing every part, e.g. ``"8.0 km + gym + stations"``."""
        parts = []
        if self.run_km > 0:
            parts.append(f"{self.run_km:.1f} km")
        if self.gym:
            parts.append("gym")
        if self.station:
            parts.append("stations")
        return " + ".join(parts) or "session"


@dataclass(frozen=True)
class DayActuals:
    """What Garmin recorded on one local calendar day.

    Parameters
    ----------
    run_km : float
        Running distance, including multisport (simulation) distance.
    gym : bool
        Whether a strength-training activity was recorded.
    station : bool
        Whether an activity that can carry station work was recorded.
    other : tuple of str
        Descriptions of activities that satisfy no planned part, e.g.
        ``"hike 5.8 km"``.
    """

    run_km: float = 0.0
    gym: bool = False
    station: bool = False
    other: tuple[str, ...] = ()

    @property
    def any_activity(self) -> bool:
        """Whether anything at all was recorded that day."""
        return self.run_km > 0 or self.gym or self.station or bool(self.other)

    def describe(self) -> str:
        """Short human description, e.g. ``"8.2 km + gym"`` or ``"nothing"``."""
        parts = []
        if self.run_km > 0:
            parts.append(f"{self.run_km:.1f} km")
        if self.gym:
            parts.append("gym")
        elif self.station:
            parts.append("stations")
        parts.extend(self.other)
        return " + ".join(parts) or "nothing"


def session_needs(
    session_type: str, prescription: dict | None, title: str | None = None
) -> SessionNeeds:
    """Derive what a planned session asks for from its structured steps.

    Parameters
    ----------
    session_type : str
        The planned ``session_type`` (run, strength, functional, sim, rest, cross).
    prescription : dict or None
        The stored ``prescription`` JSON, carrying ``distance_m`` and ``steps``.
    title : str, optional
        The session title. Only read for sessions persisted without structured
        steps, where a gym-plus-run double such as "Upper Maintenance (AM) + Easy
        Aerobic (PM)" is stored as a plain ``run`` and the title is the only
        record of its gym half.

    Returns
    -------
    SessionNeeds
        The run km, gym and station parts the session requires.

    Examples
    --------
    >>> session_needs("run", {"distance_m": 9000, "steps": [{"kind": "strength"}, {"kind": "run"}]})
    SessionNeeds(run_km=9.0, gym=True, station=False)
    """
    presc = prescription if isinstance(prescription, dict) else {}
    run_km = float(presc.get("distance_m") or 0) / 1000.0
    kinds = {step.get("kind") for step in presc.get("steps") or [] if isinstance(step, dict)}
    if kinds:
        gym = "strength" in kinds
        station = "station" in kinds or session_type == "sim"
    else:
        lowered = (title or "").lower()
        gym = session_type == "strength" or bool(_GYM_TITLE_PATTERN.search(lowered))
        station = session_type in ("functional", "sim") or "station" in lowered
    return SessionNeeds(run_km=run_km, gym=gym, station=station)


def _activity_days(activities: pd.DataFrame) -> pd.Series:
    """Local calendar date of each activity."""
    return pd.to_datetime(activities["start_time_local"], errors="coerce").dt.date


def day_actuals(activities: pd.DataFrame) -> dict[date, DayActuals]:
    """Summarise every recorded day into the parts a plan can ask for.

    Parameters
    ----------
    activities : pandas.DataFrame
        Output of :func:`dashboard.query.fetch_activities`.

    Returns
    -------
    dict of datetime.date to DayActuals
        One entry per day with at least one activity.
    """
    if activities.empty:
        return {}

    frame = pd.DataFrame(
        {
            "day": _activity_days(activities),
            "type": activities["activity_type"].fillna("").astype(str),
            "km": pd.to_numeric(activities["distance_m"], errors="coerce").fillna(0.0) / 1000.0,
        }
    ).dropna(subset=["day"])

    out: dict[date, DayActuals] = {}
    for day, group in frame.groupby("day"):
        counts_as_run = group["type"].isin(RUN_TYPES + SIM_TYPES)
        other = tuple(
            _ACTIVITY_LABELS.get(t, t.replace("_", " "))
            + (f" {km:.1f} km" if km > 0 else "")
            for t, km in zip(group["type"], group["km"])
            if t not in RUN_TYPES + SIM_TYPES + STATION_TYPES
        )
        out[day] = DayActuals(
            run_km=round(float(group.loc[counts_as_run, "km"].sum()), 2),
            gym=bool(group["type"].isin(GYM_TYPES).any()),
            station=bool(group["type"].isin(STATION_TYPES).any()),
            other=other,
        )
    return out


def is_key_session(session_type: str, intensity: str | None, needs: SessionNeeds) -> bool:
    """Whether a session is one of the week's key sessions.

    Key sessions are anything prescribed as hard (threshold, simulations) plus
    the long run, identified by distance so a long run with a pace finish and
    an easy one both count.

    Parameters
    ----------
    session_type : str
        The planned session type.
    intensity : str or None
        The planned intensity.
    needs : SessionNeeds
        Output of :func:`session_needs`.

    Returns
    -------
    bool
        ``True`` for key sessions.
    """
    if session_type in ("rest", "cross"):
        return False
    return intensity == "hard" or needs.run_km >= LONG_RUN_MIN_KM


def score_session(
    session_type: str,
    session_day: date,
    needs: SessionNeeds,
    actual: DayActuals,
    today: date,
) -> str:
    """Classify one planned session against the day's activities.

    Parameters
    ----------
    session_type : str
        The planned session type.
    session_day : datetime.date
        The planned date.
    needs : SessionNeeds
        What the session asks for.
    actual : DayActuals
        What was recorded that day.
    today : datetime.date
        The build date. Future sessions, and today's before anything is
        recorded, are ``upcoming`` rather than missed.

    Returns
    -------
    str
        One of ``rest``, ``upcoming``, ``done``, ``partial``, ``swapped``,
        ``missed``. Active recovery is ``done`` when anything was recorded and
        ``rest`` otherwise, so an optional session is never counted as missed.
    """
    if session_type == "rest":
        return "rest"
    if session_day > today:
        return "upcoming"
    if session_type == "cross":
        return "done" if actual.any_activity else "rest"

    run_ok = needs.run_km == 0 or actual.run_km >= DONE_KM_FRACTION * needs.run_km
    gym_ok = not needs.gym or actual.gym
    station_ok = not needs.station or actual.station
    if run_ok and gym_ok and station_ok:
        return "done"

    progress = (
        (needs.run_km > 0 and actual.run_km > 0)
        or (needs.gym and actual.gym)
        or (needs.station and actual.station)
    )
    if progress:
        return "partial"
    if actual.any_activity:
        return "swapped"
    return "upcoming" if session_day == today else "missed"


def score_sessions(
    planned: pd.DataFrame, activities: pd.DataFrame, today: date
) -> pd.DataFrame:
    """Score every planned session against the recorded activities.

    Parameters
    ----------
    planned : pandas.DataFrame
        Planned sessions as returned by :mod:`dashboard.query`.
    activities : pandas.DataFrame
        Output of :func:`dashboard.query.fetch_activities`.
    today : datetime.date
        The build date.

    Returns
    -------
    pandas.DataFrame
        ``planned`` plus ``status``, ``planned_km``, ``done_km``, ``is_key``,
        ``gym_planned``, ``gym_done`` and ``status_detail`` (a one-line
        "planned ... · did ..." description for the tooltip and miss list).
    """
    if planned.empty:
        return planned

    actuals = day_actuals(activities)
    rows = []
    for row in planned.itertuples(index=False):
        session_day = pd.to_datetime(row.session_date).date()
        needs = session_needs(row.session_type, row.prescription, row.title)
        actual = actuals.get(session_day, DayActuals())
        status = score_session(row.session_type, session_day, needs, actual, today)
        detail = (
            f"planned {needs.describe()} · did {actual.describe()}"
            if status in DUE_STATUSES else ""
        )
        rows.append(
            {
                "status": status,
                "planned_km": needs.run_km,
                "done_km": actual.run_km if status in DUE_STATUSES else 0.0,
                "is_key": is_key_session(row.session_type, row.intensity, needs),
                "gym_planned": needs.gym and row.session_type not in ("rest", "cross"),
                "gym_done": needs.gym and actual.gym,
                "status_detail": detail,
            }
        )
    scored = pd.DataFrame(rows, index=planned.index)
    return pd.concat([planned, scored], axis=1)


@dataclass(frozen=True)
class WeekAdherence:
    """Planned versus done for one plan week, counted up to the build date.

    Parameters
    ----------
    week_start : datetime.date
        Monday of the plan week.
    is_current : bool
        Whether the week contains the build date (its figures are to date).
    planned_km : float
        Planned run km of the sessions that are due.
    done_km : float
        Run km recorded on the week's days up to the build date, including runs
        the plan did not ask for.
    key_planned, key_done : int
        Due key sessions and how many of them were done.
    gym_planned, gym_done : int
        Due gym sessions and how many had a gym activity that day.
    misses : tuple of str
        One line per partial, swapped or missed session.
    """

    week_start: date
    is_current: bool
    planned_km: float
    done_km: float
    key_planned: int
    key_done: int
    gym_planned: int
    gym_done: int
    misses: tuple[str, ...]

    @property
    def km_pct(self) -> float | None:
        """Done km as a percentage of planned km, ``None`` with nothing due."""
        if self.planned_km <= 0:
            return None
        return 100.0 * self.done_km / self.planned_km


def weekly_adherence(
    scored: pd.DataFrame, activities: pd.DataFrame, today: date
) -> list[WeekAdherence]:
    """Aggregate scored sessions into one planned-versus-done row per week.

    Only sessions that are due count, so the week in progress is compared with
    what was planned *so far* and does not read as a failure on a Tuesday.

    Parameters
    ----------
    scored : pandas.DataFrame
        Output of :func:`score_sessions`, possibly spanning several weeks.
    activities : pandas.DataFrame
        Every activity, so unplanned runs still count toward done km.
    today : datetime.date
        The build date.

    Returns
    -------
    list of WeekAdherence
        Chronological, one entry per plan week present in ``scored``.
    """
    if scored.empty:
        return []

    actuals = day_actuals(activities)
    weeks: list[WeekAdherence] = []
    for week_key, group in scored.groupby("week_start"):
        week_start = pd.to_datetime(week_key).date()
        last_day = min(week_start + timedelta(days=6), today)
        due = group[group["status"].isin(DUE_STATUSES)]
        done_km = sum(
            actuals[d].run_km
            for d in (week_start + timedelta(days=i) for i in range(7))
            if d <= last_day and d in actuals
        )
        misses = tuple(
            f"{pd.to_datetime(r.session_date).strftime('%a %d %b')} · {r.title} — "
            f"{r.status_detail} ({r.status})"
            for r in due.sort_values("session_date").itertuples()
            if r.status != "done"
        )
        weeks.append(
            WeekAdherence(
                week_start=week_start,
                is_current=week_start <= today <= week_start + timedelta(days=6),
                planned_km=round(float(due["planned_km"].sum()), 1),
                done_km=round(float(done_km), 1),
                key_planned=int(due["is_key"].sum()),
                key_done=int((due["is_key"] & (due["status"] == "done")).sum()),
                gym_planned=int(due["gym_planned"].sum()),
                gym_done=int(due["gym_done"].sum()),
                misses=misses,
            )
        )
    return sorted(weeks, key=lambda w: w.week_start)
