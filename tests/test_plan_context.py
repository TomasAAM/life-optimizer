"""Tests for the per-week periodization context fed to the generator."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pandas as pd

from plan import phase
from plan.config import DEFAULT_CONFIG, Race
from plan.context import (
    BlockContext,
    _format_easy_pace,
    _format_week_plan,
    _week_context,
    easy_pace_from_log,
    render_brief,
)
from plan.pace import EasyPaceReference

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


def _activities(n: int, activity_type: str = "running") -> pd.DataFrame:
    """n 9 km outdoor runs at 5:45/km and HR 135 in the week before 11-08."""
    return pd.DataFrame({
        "start_time_local": pd.to_datetime(["2026-11-03 07:00"] * n),
        "activity_name": ["Easy"] * n,
        "activity_type": [activity_type] * n,
        "distance_m": [9000.0] * n,
        "duration_s": [3105.0] * n,
        "moving_duration_s": [3105.0] * n,
        "avg_hr": [135.0] * n,
    })


_ZONES = pd.DataFrame({"zone_index": [1], "lt1_hr": [145]})


def test_easy_pace_from_log_reads_the_lt1_cap_from_the_zones() -> None:
    ref = easy_pace_from_log(_activities(6), _ZONES, DEFAULT_CONFIG, date(2026, 11, 8))

    assert (ref.pace_s_per_km, ref.n_runs, ref.from_data) == (345, 6, True)


def test_easy_pace_from_log_ignores_treadmill_runs() -> None:
    ref = easy_pace_from_log(
        _activities(6, "treadmill_running"), _ZONES, DEFAULT_CONFIG, date(2026, 11, 8)
    )

    assert ref.from_data is False


def test_easy_pace_section_states_its_source_and_the_conversion() -> None:
    text = _format_easy_pace(EasyPaceReference(345, 21, 42, True), 145)

    assert "Reference easy pace 5:45/km (median of 21 outdoor easy runs" in text
    assert "9 km = 55 min" in text
    assert "18 km = 105 min" in text
    assert "HR <=145 governs" in text


def test_easy_pace_section_flags_the_fallback() -> None:
    assert "configured fallback" in _format_easy_pace(EasyPaceReference(345, 0, 42, False), 145)


def test_brief_carries_the_time_based_easy_rules() -> None:
    weeks = [_week_context(date(2026, 11, 16), DEFAULT_CONFIG)]
    bundle = BlockContext(cfg=DEFAULT_CONFIG, weeks=weeks, zones=pd.DataFrame(),
                          easy_pace=EasyPaceReference(345, 21, 42, True))

    brief = render_brief(bundle)

    assert "EASY RUNS ARE PRESCRIBED BY TIME" in brief
    assert "EASY RUNS END ON TIME" in brief
    assert "Cut rule: HR 5+ bpm above usual at this speed" in brief


def test_treadmill_easy_target_fits_the_watch_step_limit() -> None:
    """The brief's longest easy step text must survive Garmin's 250-character cut."""
    from plan.garmin_workout import _STEP_DESCRIPTION_MAX_CHARS

    hr_line = "HR <=145 governs; ~9 km is a guide, not a goal."
    treadmill_line = (
        "Treadmill: start ~5:50/km, slow the belt if HR >140 at 10 min. Cut rule: HR 5+ bpm "
        "above usual at this speed = fatigue day: slow down, keep the minutes."
    )
    weeks = [_week_context(date(2026, 11, 16), DEFAULT_CONFIG)]
    brief = " ".join(
        render_brief(BlockContext(cfg=DEFAULT_CONFIG, weeks=weeks, zones=pd.DataFrame())).split()
    )

    assert hr_line in brief
    assert treadmill_line in brief
    step_text = f"20 min easy (PM): {hr_line} {treadmill_line}"
    assert len(step_text) <= _STEP_DESCRIPTION_MAX_CHARS


def test_brief_carries_the_warm_up_ramp_rules() -> None:
    weeks = [_week_context(date(2026, 11, 16), DEFAULT_CONFIG)]
    brief = render_brief(BlockContext(cfg=DEFAULT_CONFIG, weeks=weeks, zones=pd.DataFrame()))

    assert "WARM-UP RAMPS" in brief
    assert "lb PER HAND" in brief
    assert "25, 20, 15, 10, 5, 2.5, 1.25 kg per side" in brief
    assert "do NOT write warm-up sets as steps" in brief
