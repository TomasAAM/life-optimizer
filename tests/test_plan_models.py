"""Validation tests for generated training-plan models."""

import pytest
from pydantic import ValidationError

from plan.models import PlannedSession, Step


def _session_payload() -> dict:
    """Return the smallest valid non-rest session payload.

    Returns
    -------
    dict
        A valid planned-session payload with one structured step.
    """
    return {
        "day": "Monday",
        "session_type": "run",
        "title": "Easy Aerobic",
        "zone": "Endurance",
        "intensity": "easy",
        "duration_min": 45,
        "distance_m": 7500,
        "prescription": "7.5 km easy.",
        "steps": [
            {
                "phase": None,
                "kind": "run",
                "metric": "7.5 km easy",
                "target": "Conversational",
                "load": None,
            }
        ],
        "purpose": "Build aerobic volume.",
        "why": "Easy volume supports recovery without adding intensity.",
        "hyrox_focus": None,
    }


def test_non_rest_session_requires_structured_steps() -> None:
    """A workout may not silently degrade to the plain-text card fallback."""
    payload = _session_payload()
    payload["steps"] = []

    with pytest.raises(ValidationError, match="require at least one structured step"):
        PlannedSession.model_validate(payload)


def test_non_rest_session_accepts_structured_steps() -> None:
    """A workout with visual steps satisfies the generation contract."""
    session = PlannedSession.model_validate(_session_payload())

    assert session.steps[0].metric == "7.5 km easy"


def test_rest_day_may_use_legacy_text_fallback() -> None:
    """A non-workout rest day may remain a concise text-only card."""
    payload = _session_payload()
    payload.update(
        session_type="rest",
        title="Rest",
        zone=None,
        duration_min=None,
        distance_m=None,
        prescription="Full rest.",
        steps=[],
    )

    session = PlannedSession.model_validate(payload)

    assert session.steps == []


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"duration_s": 480, "distance_m": 2000}, "not both"),
        ({"pace_fast_s_per_km": 248}, "or neither"),
        ({"pace_fast_s_per_km": 252, "pace_slow_s_per_km": 248}, "not be slower"),
        ({"hr_min": 130}, "requires hr_max"),
        ({"hr_min": 150, "hr_max": 145}, "must not exceed"),
        ({"repeats": 6}, "requires duration_s or distance_m"),
        ({"duration_s": 480, "watch_target": "pace"}, "requires a pace range"),
        ({"duration_s": 480, "watch_target": "hr"}, "requires hr_max"),
    ],
)
def test_step_rejects_contradictory_watch_fields(fields: dict, message: str) -> None:
    """Watch fields must describe one unambiguous dose and target."""
    with pytest.raises(ValidationError, match=message):
        Step.model_validate({"kind": "run", "metric": "8 min threshold", **fields})


def test_step_accepts_a_complete_threshold_rep() -> None:
    """A fully specified rep validates, and legacy text-only steps still do."""
    rep = Step.model_validate({
        "kind": "run", "metric": "8 min threshold", "duration_s": 480,
        "pace_fast_s_per_km": 248, "pace_slow_s_per_km": 252, "hr_max": 176,
    })
    legacy = Step.model_validate({"kind": "run", "metric": "6 km easy"})

    assert rep.pace_fast_s_per_km == 248
    assert legacy.duration_s is None and legacy.distance_m is None


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"working_weight": 115}, "both working_weight and implement"),
        ({"implement": "barbell"}, "both working_weight and implement"),
        ({"ramp": "full"}, "ramp requires working_weight"),
        ({"working_weight": 139, "implement": "barbell"}, "cannot be loaded"),
        ({"working_weight": 36, "implement": "dumbbell"}, "cannot be loaded"),
    ],
)
def test_step_rejects_bad_working_weights(fields: dict, message: str) -> None:
    """A working weight must be complete and buildable from the gym's plates."""
    with pytest.raises(ValidationError, match=message):
        Step.model_validate({"kind": "strength", "metric": "Back squat 5x3", **fields})


def test_ramp_is_only_for_strength_steps() -> None:
    with pytest.raises(ValidationError, match="only for strength steps"):
        Step.model_validate({
            "kind": "station", "metric": "Sled push", "working_weight": 115,
            "implement": "barbell", "ramp": "full",
        })


def test_step_accepts_a_ramped_lift_and_old_steps_still_validate() -> None:
    squat = Step.model_validate({
        "kind": "strength", "metric": "Back squat 5x3", "load": "115 kg",
        "working_weight": 115, "implement": "barbell", "ramp": "full",
    })
    bench = Step.model_validate({
        "kind": "strength", "metric": "DB bench 3x8", "load": "2x80 lb",
        "working_weight": 80, "implement": "dumbbell", "ramp": "short",
    })
    legacy = Step.model_validate({"kind": "strength", "metric": "Hip thrust 3x8", "load": "139 kg"})

    assert squat.ramp == "full" and bench.implement == "dumbbell"
    assert legacy.working_weight is None and legacy.ramp is None
