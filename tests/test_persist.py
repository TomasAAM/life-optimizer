"""Tests for lossless conversion of plan models into database rows."""

from datetime import date

from dashboard.render import _session_steps_html
from plan.models import PlannedWeek
from plan.persist import _to_rows


def test_mixed_run_and_strength_steps_survive_persistence_and_rendering() -> None:
    """A combined workout must not lose strength steps after the run cooldown."""
    week = PlannedWeek.model_validate(
        {
            "rationale": "Protect running quality while developing complete lower strength.",
            "methodology": "Threshold and strength are separated by approximately 24 hours.",
            "sessions": [
                {
                    "day": "Wednesday",
                    "session_type": "strength",
                    "title": "Lower Strength (AM) + Easy Aerobic (PM)",
                    "zone": "Endurance",
                    "intensity": "moderate",
                    "duration_min": 105,
                    "distance_m": 10000,
                    "prescription": "Full lower session, then 10 km easy later.",
                    "steps": [
                        {
                            "phase": "main",
                            "kind": "strength",
                            "metric": "Back squat 3x4",
                            "target": "RPE 8, 2 RIR",
                            "load": "100 kg",
                        },
                        {
                            "phase": "cooldown",
                            "kind": "run",
                            "metric": "10 km easy",
                            "target": "HR <=145 bpm",
                            "load": None,
                        },
                    ],
                    "purpose": "Develop lower strength without compromising threshold.",
                    "why": "Morning gym access makes next-day separation the executable option.",
                    "hyrox_focus": "sled power",
                }
            ],
        }
    )

    prescription = _to_rows(week, date(2026, 9, 21))[0]["prescription"]
    rendered = _session_steps_html(prescription)

    assert [step["kind"] for step in prescription["steps"]] == ["strength", "run"]
    assert "Back squat 3x4" in rendered
    assert "10 km easy" in rendered
