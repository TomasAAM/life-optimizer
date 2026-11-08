"""Tests for the reference easy pace and the km-to-minutes conversion."""

from __future__ import annotations

from datetime import date

import pandas as pd

from plan.pace import EasyPaceReference, easy_minutes, reference_easy_pace

_TODAY = date(2026, 11, 8)


def _runs(rows: list[dict]) -> pd.DataFrame:
    """Build a prepared-runs frame, defaulting every row to a qualifying easy run."""
    base = {"date": "2026-11-01", "km": 8.0, "pace_s_km": 345.0, "avg_hr": 135.0,
            "is_treadmill": False, "implausible": False}
    frame = pd.DataFrame([{**base, **row} for row in rows])
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


def _reference(runs: pd.DataFrame, hr_cap: float | None = 145) -> EasyPaceReference:
    return reference_easy_pace(runs, _TODAY, window_days=42, hr_cap=hr_cap, min_runs=6,
                               min_km=5.0, fallback_s_per_km=345)


def test_median_of_qualifying_runs() -> None:
    runs = _runs([{"pace_s_km": p} for p in (330, 340, 350, 360, 370, 380)])

    ref = _reference(runs)

    assert ref == EasyPaceReference(pace_s_per_km=355, n_runs=6, window_days=42, from_data=True)


def test_treadmill_hard_short_old_and_implausible_runs_are_left_out() -> None:
    easy = [{"pace_s_km": 360} for _ in range(6)]
    excluded = [
        {"pace_s_km": 300, "is_treadmill": True},
        {"pace_s_km": 240, "avg_hr": 182},
        {"pace_s_km": 300, "km": 1.7},
        {"pace_s_km": 300, "date": "2026-09-27"},
        {"pace_s_km": 100, "implausible": True},
    ]

    ref = _reference(_runs(easy + excluded))

    assert (ref.pace_s_per_km, ref.n_runs) == (360, 6)


def test_window_includes_its_first_and_last_day() -> None:
    edges = [{"date": "2026-09-28"}, {"date": "2026-11-08"}] + [{} for _ in range(4)]

    assert _reference(_runs(edges)).n_runs == 6


def test_too_few_runs_fall_back_to_the_configured_pace() -> None:
    ref = _reference(_runs([{"pace_s_km": 400} for _ in range(5)]))

    assert ref == EasyPaceReference(pace_s_per_km=345, n_runs=0, window_days=42, from_data=False)


def test_unknown_lt1_falls_back() -> None:
    assert _reference(_runs([{} for _ in range(8)]), hr_cap=None).from_data is False


def test_empty_log_falls_back() -> None:
    assert _reference(pd.DataFrame()).from_data is False


def test_minutes_round_up_to_five() -> None:
    assert easy_minutes(9, 345) == 55
    assert easy_minutes(7, 345) == 45
    assert easy_minutes(6, 345) == 35
    assert easy_minutes(16, 345) == 95


def test_exact_multiple_is_not_pushed_up_a_step() -> None:
    assert easy_minutes(10, 360) == 60
