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


def test_recovery_scaler_fresh_no_cut() -> None:
    # Fresh athlete (high readiness trend, balanced HRV, positive form) -> no cut.
    s = phase.recovery_scaler([70, 80, 90, 85, 95], "BALANCED", 55.0, 45.0, 20.0)
    assert s == 1.0


def test_recovery_scaler_gentle_trim() -> None:
    # Mildly suppressed readiness only -> a small 5% trim, nothing dramatic.
    s = phase.recovery_scaler([59, 59, 59], "BALANCED", 55.0, 45.0, 0.0)
    assert s == 0.95


def test_recovery_scaler_redflag_floor() -> None:
    # Readiness tanked + HRV LOW + deep-negative TSB -> raw penalty below the
    # red-flag floor, so it clamps at 0.75 (a real deload, but still bounded).
    s = phase.recovery_scaler([30, 30, 30], "LOW", 40.0, 45.0, -30.0)
    assert s == 0.75


def test_recovery_scaler_unbalanced_is_direction_aware() -> None:
    # UNBALANCED with night HRV ABOVE baseline low -> not a suppression, no cut.
    assert phase.recovery_scaler([80, 80, 80], "UNBALANCED", 70.0, 45.0, 10.0) == 1.0
    # UNBALANCED with night HRV at/below baseline low -> genuine dip, small cut.
    assert phase.recovery_scaler([80, 80, 80], "UNBALANCED", 40.0, 45.0, 10.0) == 0.95


def test_weekly_km_target_holds_base_but_off_cuts_hard() -> None:
    base_low, base_high = phase.weekly_km_target(50.0, "base")
    taper_low, taper_high = phase.weekly_km_target(50.0, "taper")
    off_low, off_high = phase.weekly_km_target(50.0, "off")
    assert (base_low, base_high) == (45.0, 55.0)
    assert taper_high < base_high  # taper trims volume
    assert taper_low > 40.0  # ...but gently — the 21k base is protected
    assert off_high < taper_low  # only the post-race off week cuts hard


def test_load_target_band_scaler_and_acwr_ceiling() -> None:
    full_high = phase.load_target_band(700.0, "peak", scaler=1.0)[1]
    scaled_high = phase.load_target_band(700.0, "peak", scaler=0.85)[1]
    assert scaled_high < full_high  # recovery scaler lowers the band
    # Upper bound never exceeds the acute:chronic ceiling (1.25 * chronic).
    for ph in ("base", "build", "peak"):
        assert phase.load_target_band(700.0, ph)[1] <= round(700.0 * 1.25, 0)


def test_upcoming_monday() -> None:
    # 2026-06-22 is a Monday -> returns itself.
    assert phase.upcoming_monday(date(2026, 6, 22)) == date(2026, 6, 22)
    # 2026-06-24 (Wed) -> next Monday.
    assert phase.upcoming_monday(date(2026, 6, 24)) == date(2026, 6, 29)
    # 2026-06-28 (Sun) -> next day Monday.
    assert phase.upcoming_monday(date(2026, 6, 28)) == date(2026, 6, 29)
