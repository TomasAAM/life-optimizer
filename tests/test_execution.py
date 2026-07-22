"""Tests for the pure execution-review scorer."""
from __future__ import annotations

import json
from datetime import date

import pandas as pd

from analysis.execution import review_week

ZONES = pd.DataFrame(
    [
        {"zone_index": 1, "zone_name": "Recovery", "hr_low": None, "hr_high": 139},
        {"zone_index": 2, "zone_name": "Endurance", "hr_low": 139, "hr_high": 147},
        {"zone_index": 3, "zone_name": "Tempo", "hr_low": 147, "hr_high": 155},
        {"zone_index": 4, "zone_name": "Threshold", "hr_low": 155, "hr_high": 163},
        {"zone_index": 5, "zone_name": "VO2max", "hr_low": 163, "hr_high": None},
    ]
)


def _planned():
    def sess(dt, stype, title, zone, inten, dist=None):
        return {
            "session_date": dt, "session_type": stype, "title": title,
            "zone": zone, "intensity": inten,
            "prescription": json.dumps({"distance_m": dist}) if dist else json.dumps({}),
        }
    return pd.DataFrame([
        sess("2026-07-13", "run", "Easy Run", "Endurance", "easy", 8400),
        sess("2026-07-14", "run", "Threshold 4x8", "Threshold", "hard", 12500),
        sess("2026-07-15", "strength", "Heavy Lower", None, "hard"),
        sess("2026-07-16", "run", "Easy Aerobic", "Endurance", "easy", 9000),
        sess("2026-07-17", "rest", "Rest", None, "easy"),
        sess("2026-07-18", "sim", "Hyrox Sim", "mixed", "hard", 7700),
        sess("2026-07-19", "run", "Long Run", "Endurance", "easy", 18000),
    ])


def _activities():
    def act(dt, atype, dist, avg, mx):
        return {"start_time_local": dt + " 06:00:00", "activity_type": atype,
                "distance_m": dist, "avg_hr": avg, "max_hr": mx}
    return pd.DataFrame([
        act("2026-07-13", "running", 8400, 152, 165),        # grey-zone: 152 > 147+3
        act("2026-07-14", "treadmill_running", 12500, 150, 171),  # threshold touched (max 171)
        act("2026-07-15", "strength_training", 0, 92, 140),
        # Thu 07-16 missed
        act("2026-07-18", "indoor_cardio", 0, 160, 183),     # sim done
        act("2026-07-19", "running", 18000, 144, 173),       # easy long, in-zone
    ])


def test_week_review_counts_and_flags():
    r = review_week(_planned(), _activities(), ZONES, date(2026, 7, 13))
    assert r.planned_sessions == 6      # Mon,Tue,Wed,Thu,Sat,Sun (Fri rest)
    assert r.completed_sessions == 5    # Thu missed
    assert r.adherence_pct == 83
    assert r.grey_zone_breaches == 1
    # actual running km = 8.4 + 12.5 + 18.0
    assert r.actual_km == 38.9
    # planned km = 8.4 + 12.5 + 9.0 + 7.7 + 18.0
    assert r.planned_km == 55.6
    thu = next(d for d in r.days if d.day == "Thursday")
    assert thu.status == "missed"
    mon = next(d for d in r.days if d.day == "Monday")
    assert any("grey-zone" in f for f in mon.flags)


def test_markdown_renders():
    r = review_week(_planned(), _activities(), ZONES, date(2026, 7, 13))
    md = r.to_markdown()
    assert "Execution review" in md and "Monday" in md


def test_empty_plan_is_safe():
    r = review_week(pd.DataFrame(), pd.DataFrame(), ZONES, date(2026, 7, 13))
    assert r.planned_sessions == 0 and r.adherence_pct is None
