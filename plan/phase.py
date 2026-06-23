"""Deterministic periodization logic.

The phase a given week sits in is a pure function of how many weeks remain until
the race — no model involved, so it is fully reproducible and unit-testable. The
generator uses the phase to bias the week's structure and weekly-load target.

Phase map (by whole weeks remaining until the race):

* ``>= 9``  base       — aerobic volume, build the engine
* ``4..8``  build      — threshold + race-specific intensity
* ``3``     peak        — highest specificity, race simulation
* ``1..2``  taper       — cut volume, retain intensity, arrive fresh
* ``<= 0``  off         — race done / transition
"""

from __future__ import annotations

import math
from datetime import date

# Weekly-load multipliers applied to the chronic (CTL-derived) weekly load to set
# the target band for each phase. Taper deliberately drops volume.
_PHASE_LOAD_MULT: dict[str, float] = {
    "base": 1.00,
    "build": 1.10,
    "peak": 1.00,
    "taper": 0.55,
    "off": 0.30,
}


def weeks_to_race(week_start: date, race_date: date) -> int:
    """Whole weeks remaining from the start of a plan week to the race.

    Parameters
    ----------
    week_start : datetime.date
        Monday of the plan week.
    race_date : datetime.date
        Date of the target race.

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
        Output of :func:`weeks_to_race`.

    Returns
    -------
    str
        One of ``base``, ``build``, ``peak``, ``taper``, ``off``.
    """
    if weeks_remaining <= 0:
        return "off"
    if weeks_remaining <= 2:
        return "taper"
    if weeks_remaining == 3:
        return "peak"
    if weeks_remaining <= 8:
        return "build"
    return "base"


def phase_for_week(week_start: date, race_date: date) -> tuple[str, int]:
    """Return the phase and weeks-remaining for a plan week.

    Parameters
    ----------
    week_start : datetime.date
        Monday of the plan week.
    race_date : datetime.date
        Date of the target race.

    Returns
    -------
    tuple of (str, int)
        The phase label and the whole weeks remaining until the race.
    """
    remaining = weeks_to_race(week_start, race_date)
    return classify_phase(remaining), remaining


def load_target_band(weekly_chronic_load: float, phase: str) -> tuple[float, float]:
    """Compute an ACWR-bounded weekly training-load target for a phase.

    The midpoint is the chronic (CTL-derived) weekly load scaled by the phase
    multiplier; the band spans roughly an acute:chronic ratio of 0.9 to 1.1
    around that midpoint to keep week-to-week progression safe.

    Parameters
    ----------
    weekly_chronic_load : float
        Chronic training load expressed per week (CTL * 7).
    phase : str
        Phase label from :func:`classify_phase`.

    Returns
    -------
    tuple of (float, float)
        Lower and upper weekly-load targets.
    """
    mult = _PHASE_LOAD_MULT.get(phase, 1.0)
    midpoint = weekly_chronic_load * mult
    return round(midpoint * 0.9, 0), round(midpoint * 1.1, 0)


def upcoming_monday(today: date) -> date:
    """Return the Monday of the week to plan for.

    If ``today`` is already a Monday, that day is returned; otherwise the next
    Monday is returned. Run on the Sunday cron this yields the week about to
    start; run mid-week (manual) it yields next week.

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
