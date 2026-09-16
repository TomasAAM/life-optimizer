"""Validation tests for generated training-plan models."""

import pytest
from pydantic import ValidationError

from plan.models import PlannedSession


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
