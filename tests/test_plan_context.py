"""Tests for the per-week periodization context fed to the generator."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from plan import phase
from plan.config import DEFAULT_CONFIG, Race
from plan.context import _format_week_plan, _week_context

_RACE = Race("hyrox", date(2026, 11, 14), note="mixed doubles")


def test_week_after_the_last_race_holds_base_volume() -> None:
    cfg = replace(DEFAULT_CONFIG, races=(_RACE,), phase_without_race="base")

    week = _week_context(date(2026, 11, 16), cfg)

    assert week.phase_name == "base"
    assert week.race_name is None
    assert week.is_post_race_recovery is True
    assert week.weekly_km_band == phase.weekly_km_target(cfg.base_weekly_km, "base")


def test_phase_without_race_can_still_be_off() -> None:
    cfg = replace(DEFAULT_CONFIG, races=(_RACE,), phase_without_race="off")

    assert _week_context(date(2026, 11, 16), cfg).phase_name == "off"


def test_peak_weeks_from_config_reach_the_week() -> None:
    cfg = replace(DEFAULT_CONFIG, races=(_RACE,), peak_weeks=1)

    assert _week_context(date(2026, 10, 26), cfg).phase_name == "build"
    assert _week_context(date(2026, 11, 9), cfg).phase_name == "peak"
    assert _week_context(date(2026, 11, 9), cfg).is_race_week is True


def test_b_race_keeps_the_phase_and_reaches_the_brief() -> None:
    five_k = Race("5k", date(2026, 11, 8), note="road 5k", priority="B")
    cfg = replace(DEFAULT_CONFIG, races=(five_k, _RACE), peak_weeks=1)

    week = _week_context(date(2026, 11, 2), cfg)

    assert week.phase_name == "build"
    assert week.race_name == "hyrox"
    assert week.is_race_week is False
    assert week.b_races == (five_k,)
    assert ">> B RACE: 5k on Sunday 08 Nov (road 5k)" in _format_week_plan(week, cfg)


def test_a_race_after_an_a_race_is_a_race_week_with_recovery() -> None:
    ten_k = Race("10k", date(2026, 11, 22))
    cfg = replace(DEFAULT_CONFIG, races=(_RACE, ten_k), peak_weeks=1)

    week = _week_context(date(2026, 11, 16), cfg)

    assert (week.race_name, week.phase_name) == ("10k", "peak")
    assert week.is_race_week is True
    assert week.is_post_race_recovery is True
