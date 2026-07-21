"""Tests for the deterministic periodization logic."""

from __future__ import annotations

from datetime import date

from plan import phase
from plan.config import Race


def test_weeks_to_race_six_weeks_out() -> None:
    assert phase.weeks_to_race(date(2026, 6, 22), date(2026, 8, 2)) == 6


def test_weeks_to_race_race_week() -> None:
    assert phase.weeks_to_race(date(2026, 7, 27), date(2026, 8, 2)) == 1


def test_weeks_to_race_past_is_zero() -> None:
    assert phase.weeks_to_race(date(2026, 8, 3), date(2026, 8, 2)) == 0


def test_phase_for_week_hyrox_build() -> None:
    phase_name, remaining = phase.phase_for_week(date(2026, 6, 22), date(2026, 8, 2))
    assert (phase_name, remaining) == ("build", 6)


def test_phase_boundaries() -> None:
    # Collapsed to base/build/peak (+off). No standalone taper phase — the
    # pre-race freshen is a within-week refinement, not a phase.
    assert phase.classify_phase(10) == "base"
    assert phase.classify_phase(9) == "base"
    assert phase.classify_phase(8) == "build"
    assert phase.classify_phase(4) == "build"
    assert phase.classify_phase(3) == "peak"
    assert phase.classify_phase(1) == "peak"
    assert phase.classify_phase(0) == "off"


def test_next_race_picks_earliest_upcoming() -> None:
    races = (Race("hyrox", date(2026, 8, 2)), Race("hyrox", date(2026, 11, 14)))
    # Before the first race -> first race.
    assert phase.next_race(date(2026, 7, 20), races).date == date(2026, 8, 2)
    # After the first race -> second race.
    assert phase.next_race(date(2026, 8, 3), races).date == date(2026, 11, 14)
    # After the last race -> None.
    assert phase.next_race(date(2026, 11, 16), races) is None


def test_next_race_within_week_still_upcoming() -> None:
    races = (Race("hyrox", date(2026, 8, 2)),)
    # Monday of race week (race is that Sunday) -> the race is still upcoming.
    assert phase.next_race(date(2026, 7, 27), races).date == date(2026, 8, 2)


def test_is_race_week() -> None:
    race = Race("hyrox", date(2026, 8, 2))  # a Sunday
    assert phase.is_race_week(date(2026, 7, 27), race) is True  # Mon-Sun contains it
    assert phase.is_race_week(date(2026, 7, 20), race) is False  # week before
    assert phase.is_race_week(date(2026, 8, 3), race) is False  # week after
    assert phase.is_race_week(date(2026, 7, 27), None) is False


def test_is_post_race_recovery_week() -> None:
    races = (Race("hyrox", date(2026, 8, 2)),)  # Sunday
    # Week starting the day after the race -> post-race recovery.
    assert phase.is_post_race_recovery_week(date(2026, 8, 3), races) is True
    # The race week itself is not a post-race week.
    assert phase.is_post_race_recovery_week(date(2026, 7, 27), races) is False
    # Two weeks later -> no.
    assert phase.is_post_race_recovery_week(date(2026, 8, 10), races) is False


def test_weekly_km_target_holds_base_but_off_cuts() -> None:
    base_low, base_high = phase.weekly_km_target(50.0, "base")
    peak_low, peak_high = phase.weekly_km_target(50.0, "peak")
    off_low, off_high = phase.weekly_km_target(50.0, "off")
    assert (base_low, base_high) == (45.0, 55.0)
    assert peak_high < base_high  # peak trims volume slightly
    assert peak_low > 40.0  # ...but gently — the 21k base is protected
    assert off_high < peak_low  # maintenance/off cuts harder


def test_upcoming_monday() -> None:
    # 2026-06-22 is a Monday -> returns itself.
    assert phase.upcoming_monday(date(2026, 6, 22)) == date(2026, 6, 22)
    # 2026-06-24 (Wed) -> next Monday.
    assert phase.upcoming_monday(date(2026, 6, 24)) == date(2026, 6, 29)
    # 2026-06-28 (Sun) -> next day Monday.
    assert phase.upcoming_monday(date(2026, 6, 28)) == date(2026, 6, 29)


def test_current_monday() -> None:
    # Mid-week maps back to the Monday that already started.
    assert phase.current_monday(date(2026, 6, 24)) == date(2026, 6, 22)
    assert phase.current_monday(date(2026, 6, 22)) == date(2026, 6, 22)
    assert phase.current_monday(date(2026, 6, 28)) == date(2026, 6, 22)  # Sunday
