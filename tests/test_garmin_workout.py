"""Tests for mapping planned sessions to Garmin workout payloads."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from plan.garmin_workout import (
    UnstructuredSessionError,
    build_workout,
    content_hash_of,
    has_run_steps,
    is_synced_workout,
    read_content_hash,
)
from plan.models import PlannedSession

_FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "garmin_reference_workouts.json").read_text(encoding="utf-8")
)
_DATE = date(2026, 10, 20)


def _session(steps: list[dict[str, Any]], **overrides: Any) -> PlannedSession:
    """Build a planned session around the given steps.

    Parameters
    ----------
    steps : list of dict
        Step payloads.
    **overrides
        Session fields to replace.

    Returns
    -------
    PlannedSession
        The validated session.
    """
    payload = {
        "day": "Tuesday",
        "session_type": "run",
        "title": "Threshold 5x8 min",
        "zone": "Threshold",
        "intensity": "hard",
        "duration_min": 75,
        "distance_m": 15000,
        "prescription": "Threshold reps at fixed pace.",
        "steps": steps,
        "purpose": "Raise LT2.",
        "why": "Fixed-pace reps confirm the anchor.",
        "hyrox_focus": None,
    }
    payload.update(overrides)
    return PlannedSession.model_validate(payload)


def _threshold_steps(final_target: str = "4:12-4:08/km") -> list[dict[str, Any]]:
    """Return the W4 Tuesday threshold session as structured steps."""
    rep = {"phase": "main", "kind": "run", "metric": "8 min threshold", "target": "4:12-4:08/km",
           "duration_s": 480, "pace_fast_s_per_km": 248, "pace_slow_s_per_km": 252, "hr_max": 176}
    jog = {"phase": "main", "kind": "rest", "metric": "2:00 jog recovery", "target": "Easy jog",
           "duration_s": 120}
    steps = [{"phase": "warmup", "kind": "run", "metric": "15 min easy", "target": "HR <=145 bpm",
              "duration_s": 900, "hr_max": 145}]
    for _ in range(4):
        steps += [rep, jog]
    steps.append({**rep, "target": final_target})
    steps.append({"phase": "cooldown", "kind": "run", "metric": "12 min easy", "target": "Easy jog",
                  "duration_s": 720, "hr_max": 145})
    return steps


def _steps_of(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the top-level steps of a payload's only segment."""
    return payload["workoutSegments"][0]["workoutSteps"]


def _reference_steps(name: str) -> list[dict[str, Any]]:
    """Return the top-level steps of a reference workout from the fixture."""
    return _FIXTURES[name]["workoutSegments"][0]["workoutSteps"]


def test_payload_uses_the_ids_garmin_stores() -> None:
    """Step types, end conditions and targets must match real Garmin workouts."""
    runna = _reference_steps("runna_intervals")
    coach = _reference_steps("garmin_coach_strides")
    ours = _steps_of(build_workout(_session(_threshold_steps()), _DATE))
    group = ours[1]
    rep = group["workoutSteps"][0]

    assert ours[0]["stepType"] == runna[0]["stepType"]
    assert ours[-1]["stepType"] == runna[-1]["stepType"]
    assert ours[0]["endCondition"] == coach[0]["endCondition"]
    assert group["stepType"] == runna[2]["stepType"]
    assert group["endCondition"] == runna[2]["endCondition"]
    assert rep["stepType"] == runna[2]["workoutSteps"][0]["stepType"]
    assert rep["targetType"] == runna[2]["workoutSteps"][0]["targetType"]
    assert group["workoutSteps"][1]["stepType"] == coach[2]["workoutSteps"][1]["stepType"]


def test_lap_button_and_station_ids_match_garmin_coach() -> None:
    """A station step ends on the lap button with Garmin's 'other' step type."""
    coach_lap = _reference_steps("garmin_coach_strides")[1]
    session = _session([
        {"kind": "run", "metric": "1 km run", "distance_m": 1000},
        {"kind": "station", "metric": "Row 1000 m", "target": "Race effort", "load": None},
        {"kind": "run", "metric": "1 km run", "distance_m": 1000},
    ])

    station = _steps_of(build_workout(session, _DATE))[1]

    assert station["stepType"] == coach_lap["stepType"]
    assert station["endCondition"] == coach_lap["endCondition"]
    assert station["endConditionValue"] is None


def test_distance_end_condition_matches_runna() -> None:
    """A distance step uses Garmin's distance condition, value in metres."""
    runna_warmup = _reference_steps("runna_intervals")[0]
    session = _session([{"kind": "run", "metric": "15 km easy", "distance_m": 15000, "hr_max": 145}])

    step = _steps_of(build_workout(session, _DATE))[0]

    assert step["endCondition"] == runna_warmup["endCondition"]
    assert step["endConditionValue"] == 15000.0


def test_threshold_reps_fold_into_a_repeat_group_plus_final_rep() -> None:
    """Five reps with four recoveries become 4 x [rep, jog] then the last rep."""
    steps = _steps_of(build_workout(_session(_threshold_steps("may reach 180 bpm")), _DATE))

    assert [s["stepType"]["stepTypeKey"] for s in steps] == ["warmup", "repeat", "interval", "cooldown"]
    assert steps[1]["numberOfIterations"] == 4
    assert steps[1]["endConditionValue"] == 4.0
    assert steps[2]["description"] == "8 min threshold: may reach 180 bpm"


def test_threshold_pace_is_metres_per_second_fast_end_first() -> None:
    """4:08-4:12/km becomes m/s with the faster speed first, like Runna's ranges."""
    rep = _steps_of(build_workout(_session(_threshold_steps()), _DATE))[1]["workoutSteps"][0]

    assert rep["targetValueOne"] == pytest.approx(1000 / 248)
    assert rep["targetValueTwo"] == pytest.approx(1000 / 252)
    assert rep["targetValueOne"] > rep["targetValueTwo"]
    assert rep["endConditionValue"] == 480.0


def test_easy_step_targets_the_hr_ceiling_with_a_low_floor() -> None:
    """An easy run alerts on the 145 bpm ceiling only."""
    session = _session([{"kind": "run", "metric": "6 km easy", "distance_m": 6000, "hr_max": 145}])

    step = _steps_of(build_workout(session, _DATE))[0]

    assert step["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert (step["targetValueOne"], step["targetValueTwo"]) == (100.0, 145.0)
    assert "zoneNumber" not in step


def test_treadmill_threshold_can_target_hr_instead_of_pace() -> None:
    """watch_target 'hr' overrides the default pace target."""
    session = _session([{"kind": "run", "metric": "8 min threshold", "duration_s": 480,
                         "pace_fast_s_per_km": 248, "pace_slow_s_per_km": 252,
                         "hr_min": 172, "hr_max": 178, "watch_target": "hr"}])

    step = _steps_of(build_workout(session, _DATE))[0]

    assert step["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert (step["targetValueOne"], step["targetValueTwo"]) == (172.0, 178.0)


def test_strides_become_a_repeat_with_lap_button_walk_back() -> None:
    """'6x20 s strides' runs six times with an untimed recovery between."""
    session = _session([
        {"kind": "run", "metric": "6 km easy", "distance_m": 6000, "hr_max": 145},
        {"phase": "main", "kind": "run", "metric": "6x20 s strides", "duration_s": 20, "repeats": 6},
    ])

    strides = _steps_of(build_workout(session, _DATE))[1]

    assert strides["type"] == "RepeatGroupDTO"
    assert strides["numberOfIterations"] == 6
    work, walk = strides["workoutSteps"]
    assert work["endConditionValue"] == 20.0
    assert work["targetType"]["workoutTargetTypeKey"] == "no.target"
    assert walk["stepType"]["stepTypeKey"] == "recovery"
    assert walk["endCondition"]["conditionTypeKey"] == "lap.button"


def test_double_day_keeps_only_the_run() -> None:
    """Strength and an AM station finisher before the PM run stay off the watch."""
    session = _session([
        {"phase": "main", "kind": "strength", "metric": "Weighted pull-up 4x4", "load": "+12.5 kg"},
        {"phase": "main", "kind": "station", "metric": "Wall balls 5x20", "load": "9 kg"},
        {"kind": "run", "metric": "8 km easy", "distance_m": 8000, "hr_max": 145},
    ], session_type="strength", title="Upper Strength (AM) + Easy Run (PM)",
       prescription="AM: weighted pull-up 4x4 @ +12.5 kg; wall balls 5x20. PM: 8 km easy.")

    payload = build_workout(session, _DATE)
    steps = _steps_of(payload)

    assert len(steps) == 1
    assert steps[0]["description"] == "8 km easy"
    assert payload["workoutName"] == "LOD 10-20 Run: 8 km easy"
    assert payload["description"].startswith("8 km easy\n\n[lod:")
    for gym_text in ("Strength", "pull-up", "Wall balls", "wall balls"):
        assert gym_text not in payload["workoutName"] + payload["description"]


def test_sim_keeps_its_title_and_prescription() -> None:
    """Stations between runs are part of the watch workout, so nothing is hidden."""
    session = _session([
        {"kind": "run", "metric": "1 km run", "distance_m": 1000},
        {"kind": "station", "metric": "Row 1000 m"},
        {"kind": "run", "metric": "1 km run", "distance_m": 1000},
    ], session_type="sim", title="Compromised Sim", prescription="Run, row, run.")

    payload = build_workout(session, _DATE)

    assert payload["workoutName"] == "LOD 10-20 Compromised Sim"
    assert payload["description"].startswith("Run, row, run.")


def test_sim_keeps_distinct_stations_between_runs() -> None:
    """Different stations never fold together, so each keeps its name on the watch."""
    rounds = []
    for station in ["Row 1000 m", "Farmers carry 200 m", "Sandbag lunges 100 m", "Wall balls 100"]:
        rounds += [
            {"phase": "main", "kind": "run", "metric": "1 km compromised run", "distance_m": 1000,
             "pace_fast_s_per_km": 262, "pace_slow_s_per_km": 268},
            {"phase": "main", "kind": "station", "metric": station, "target": "Race effort"},
        ]
    session = _session(rounds + [
        {"phase": "cooldown", "kind": "run", "metric": "Easy jog", "distance_m": 2000, "hr_max": 145},
    ], session_type="sim")

    steps = _steps_of(build_workout(session, _DATE))

    assert len(steps) == 9
    assert [s["description"].split(":")[0] for s in steps if s["stepType"]["stepTypeKey"] == "other"] == [
        "Row 1000 m", "Farmers carry 200 m", "Sandbag lunges 100 m", "Wall balls 100",
    ]


def test_step_order_is_depth_first_with_group_ids() -> None:
    """Garmin numbers a repeat group, then its children, then what follows."""
    steps = _steps_of(build_workout(_session(_threshold_steps()), _DATE))

    assert [s["stepOrder"] for s in steps] == [1, 2, 5, 6]
    assert [c["stepOrder"] for c in steps[1]["workoutSteps"]] == [3, 4]
    assert {c["childStepId"] for c in steps[1]["workoutSteps"]} == {1}


def test_run_step_without_a_dose_is_refused() -> None:
    """A run step with only prose cannot be turned into a faithful workout."""
    session = _session([{"kind": "run", "metric": "Easy jog to 9 km total"}])

    with pytest.raises(UnstructuredSessionError, match="Easy jog to 9 km total"):
        build_workout(session, _DATE)


def test_session_without_running_is_not_a_watch_workout() -> None:
    """A pure strength session has nothing to sync."""
    session = _session([{"kind": "strength", "metric": "Back squat 4x3", "load": "110 kg"}],
                       session_type="strength")

    assert not has_run_steps(session)
    with pytest.raises(UnstructuredSessionError):
        build_workout(session, _DATE)


def test_hash_tracks_steps_not_prose() -> None:
    """Rewording the prescription keeps the hash; changing a dose changes it."""
    base = build_workout(_session(_threshold_steps()), _DATE)
    reworded = build_workout(_session(_threshold_steps(), prescription="Different words."), _DATE)
    longer = _threshold_steps()
    longer[0] = {**longer[0], "duration_s": 1200}
    changed = build_workout(_session(longer), _DATE)

    assert content_hash_of(base) == content_hash_of(reworded)
    assert content_hash_of(base) != content_hash_of(changed)
    assert read_content_hash(base["description"]) == content_hash_of(base)


def test_name_carries_the_sync_prefix_and_date() -> None:
    """Synced workouts are recognisable, so the sync never touches others."""
    payload = build_workout(_session(_threshold_steps()), _DATE)

    assert payload["workoutName"] == "LOD 10-20 Threshold 5x8 min"
    assert is_synced_workout(payload["workoutName"])
    assert not is_synced_workout("W11 Wed Intervals - 800m into 400m Intervals (10km)")
    assert not is_synced_workout(None)


def test_no_session_time_estimate_is_sent() -> None:
    """A double day's 116 min covers the gym too, so no estimate is sent for the run."""
    session = _session([
        {"kind": "strength", "metric": "OHP 3x5", "load": "62.5 kg"},
        {"kind": "run", "metric": "8 km easy (PM)", "distance_m": 8000, "hr_max": 145},
    ], session_type="strength", duration_min=116)

    payload = build_workout(session, _DATE)

    assert "estimatedDurationInSecs" not in payload
    assert _steps_of(payload)[0]["endCondition"]["conditionTypeKey"] == "distance"
