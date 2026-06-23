"""Tests for the deterministic periodization logic."""

from __future__ import annotations

from datetime import date

from plan import phase


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
    assert phase.classify_phase(10) == "base"
    assert phase.classify_phase(6) == "build"
    assert phase.classify_phase(3) == "peak"
    assert phase.classify_phase(2) == "taper"
    assert phase.classify_phase(1) == "taper"
    assert phase.classify_phase(0) == "off"


def test_load_target_band_taper_cuts_volume() -> None:
    build_low, build_high = phase.load_target_band(700.0, "build")
    taper_low, taper_high = phase.load_target_band(700.0, "taper")
    assert taper_high < build_low  # taper band sits clearly below build


def test_upcoming_monday() -> None:
    # 2026-06-22 is a Monday -> returns itself.
    assert phase.upcoming_monday(date(2026, 6, 22)) == date(2026, 6, 22)
    # 2026-06-24 (Wed) -> next Monday.
    assert phase.upcoming_monday(date(2026, 6, 24)) == date(2026, 6, 29)
    # 2026-06-28 (Sun) -> next day Monday.
    assert phase.upcoming_monday(date(2026, 6, 28)) == date(2026, 6, 29)
