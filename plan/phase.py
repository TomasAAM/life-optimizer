"""Deterministic periodization logic.

The phase a given week sits in is a pure function of how many weeks remain until
the next race — no model involved, so it is fully reproducible and
unit-testable. The generator uses the phase to bias the week's structure and the
weekly running-volume target.

Phase map (by whole weeks remaining until the next race):

* ``>= 9``  base   — aerobic volume, build the engine
* ``4..8``  build  — threshold + race-specific intensity
* ``1..3``  peak   — highest specificity, race simulation
* ``<= 0``  off    — no upcoming race (post-race transition / maintenance)

Two sub-week refinements are layered on top and handled in session design, not as
phases of their own:

* the **race week** (a race falls inside it) freshens over its final few days —
  volume down, intensity kept (see :func:`is_race_week`);
* the **week after a race** opens with a short recovery block before normal
  training resumes (see :func:`is_post_race_recovery_week`).
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from plan.config import Race

# Weekly running-volume (km) multipliers by phase. Deliberately gentle: the
# undated 21k is a standing-readiness goal, so an aerobic-volume floor is held
# year-round. Easy runs carry this volume (polarized). The race-week freshen and
# post-race recovery are handled in session design, not here.
_PHASE_KM_MULT: dict[str, float] = {
    "base": 1.00,
    "build": 1.05,
    "peak": 0.90,
    "off": 0.70,
}


def weeks_to_race(week_start: date, race_date: date) -> int:
    """Whole weeks remaining from the start of a plan week to a race.

    Parameters
    ----------
    week_start : datetime.date
        Monday of the plan week.
    race_date : datetime.date
        Date of the race.

    Returns
    -------
    int
        Number of whole weeks until the race (0 once the race week has passed).

    Examples
    --------
    >>> weeks_to_race(date(2026, 6, 22), date(2026, 8, 2))
    6
    >>> weeks_to_race(date(2026, 7, 27), date(2026, 8, 2))
    1
    """
    days = (race_date - week_start).days
    if days <= 0:
        return 0
    return math.ceil(days / 7)


def classify_phase(weeks_remaining: int) -> str:
    """Map whole weeks remaining to a periodization phase.

    Parameters
    ----------
    weeks_remaining : int
        Output of :func:`weeks_to_race`, or 0 when no race is upcoming.

    Returns
    -------
    str
        One of ``base``, ``build``, ``peak``, ``off``.
    """
    if weeks_remaining <= 0:
        return "off"
    if weeks_remaining <= 3:
        return "peak"
    if weeks_remaining <= 8:
        return "build"
    return "base"


def next_race(week_start: date, races: tuple[Race, ...]) -> Race | None:
    """Return the next race on or after a plan week.

    A race whose day falls inside the plan week counts as upcoming for that week
    (it is that week's race). Weeks after the final race return ``None``.

    Parameters
    ----------
    week_start : datetime.date
        Monday of the plan week.
    races : tuple of Race
        The race calendar, any order.

    Returns
    -------
    Race or None
        The earliest race with ``date >= week_start``, or ``None`` if none remain.
    """
    upcoming = sorted((r for r in races if r.date >= week_start), key=lambda r: r.date)
    return upcoming[0] if upcoming else None


def phase_for_week(week_start: date, race_date: date) -> tuple[str, int]:
    """Return the phase and weeks-remaining for a plan week against one race.

    Parameters
    ----------
    week_start : datetime.date
        Monday of the plan week.
    race_date : datetime.date
        Date of the reference race.

    Returns
    -------
    tuple of (str, int)
        The phase label and the whole weeks remaining until the race.
    """
    remaining = weeks_to_race(week_start, race_date)
    return classify_phase(remaining), remaining


def is_race_week(week_start: date, race: Race | None) -> bool:
    """True when a race falls within the seven days of this plan week.

    Parameters
    ----------
    week_start : datetime.date
        Monday of the plan week.
    race : Race or None
        The week's next race (from :func:`next_race`).

    Returns
    -------
    bool
        Whether race day is Monday..Sunday of this week.
    """
    if race is None:
        return False
    return week_start <= race.date <= week_start + timedelta(days=6)


def is_post_race_recovery_week(week_start: date, races: tuple[Race, ...]) -> bool:
    """True when a race occurred in the seven days before this plan week.

    Such a week opens with a short recovery block (see
    :attr:`plan.config.PlanConfig.post_race_recovery_days`) before normal training
    resumes.

    Parameters
    ----------
    week_start : datetime.date
        Monday of the plan week.
    races : tuple of Race
        The race calendar.

    Returns
    -------
    bool
        Whether any race day fell in the seven days immediately before this week.
    """
    prior_week_start = week_start - timedelta(days=7)
    return any(prior_week_start <= r.date < week_start for r in races)


def weekly_km_target(base_weekly_km: float, phase: str) -> tuple[float, float]:
    """Phase-scaled weekly running-volume target (km), as a +/-10% band.

    Parameters
    ----------
    base_weekly_km : float
        The athlete's normal base weekly running volume.
    phase : str
        Phase label from :func:`classify_phase`.

    Returns
    -------
    tuple of (float, float)
        Lower and upper weekly-km targets.
    """
    midpoint = base_weekly_km * _PHASE_KM_MULT.get(phase, 1.0)
    return round(midpoint * 0.9, 1), round(midpoint * 1.1, 1)


def upcoming_monday(today: date) -> date:
    """Return the Monday of the week to plan for.

    If ``today`` is already a Monday, that day is returned; otherwise the next
    Monday is returned.

    Parameters
    ----------
    today : datetime.date
        Reference date.

    Returns
    -------
    datetime.date
        Monday of the week to generate.
    """
    days_ahead = (0 - today.weekday()) % 7
    return today if days_ahead == 0 else date.fromordinal(today.toordinal() + days_ahead)


def current_monday(today: date) -> date:
    """Return the Monday of the week that contains ``today``.

    Unlike :func:`upcoming_monday`, a mid-week date maps back to the Monday that
    already started — used by the dashboard to show the week in progress.

    Parameters
    ----------
    today : datetime.date
        Reference date.

    Returns
    -------
    datetime.date
        Monday of the current week.
    """
    return today - timedelta(days=today.weekday())
