"""Tests for the descriptive running-volume helper."""
from __future__ import annotations

from datetime import date

import pandas as pd

from plan.volume import recent_weekly_km


def _acts(rows):
    return pd.DataFrame(rows, columns=["start_time_local", "activity_type", "distance_m"])


def test_none_when_empty():
    assert recent_weekly_km(_acts([]), today=date(2026, 7, 22)) is None


def test_averages_complete_weeks_only():
    # today = Wed 2026-07-22 -> current week Mon 07-20 is EXCLUDED.
    # 4-week window = 06-22 .. 07-19 inclusive.
    rows = [
        ("2026-07-21 06:00:00", "running", 10000),   # current week -> excluded
        ("2026-07-16 06:00:00", "running", 10000),    # wk of 07-13 -> in
        ("2026-07-14 06:00:00", "treadmill_running", 13000),  # in
        ("2026-07-06 06:00:00", "treadmill_running", 12000),  # wk of 07-06 -> in
        ("2026-06-29 06:00:00", "running", 12000),    # wk of 06-29 -> in
        ("2026-05-01 06:00:00", "running", 99000),    # older -> excluded
    ]
    # in-window running km = 10+13+12+12 = 47 over 4 weeks -> 11.75 -> 11.8
    assert recent_weekly_km(_acts(rows), weeks=4, today=date(2026, 7, 22)) == 11.8


def test_ignores_non_running():
    rows = [
        ("2026-07-16 06:00:00", "strength_training", 0),
        ("2026-07-15 06:00:00", "indoor_cycling", 0),
        ("2026-07-14 06:00:00", "indoor_cardio", 0),
    ]
    assert recent_weekly_km(_acts(rows), weeks=4, today=date(2026, 7, 22)) is None


def test_missing_columns_returns_none():
    df = pd.DataFrame([{"activity_type": "running"}])
    assert recent_weekly_km(df, today=date(2026, 7, 22)) is None
