"""Pydantic schema for the LLM-generated weekly plan.

These models define the strict structured-output contract for
``client.messages.parse``: the generator asks Claude to return exactly a
``PlannedWeek`` and the SDK validates the response against this schema before we
persist it. Keeping the shape flat (no free-form dicts) makes the JSON-schema
constraint reliable.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

DayName = Literal[
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]
SessionType = Literal["run", "strength", "functional", "sim", "rest", "cross"]
Intensity = Literal["easy", "moderate", "hard"]


class PlannedSession(BaseModel):
    """A single prescribed session within the week."""

    day: DayName
    session_type: SessionType
    title: str = Field(description="Short session title, e.g. 'Threshold 4x8min'.")
    zone: Optional[str] = Field(
        default=None,
        description="Target zone name (Recovery/Endurance/Tempo/Threshold/VO2max), "
        "'mixed' for sessions spanning zones, or null for rest/strength.",
    )
    intensity: Intensity
    duration_min: Optional[int] = Field(
        default=None, description="Planned total duration in minutes, if applicable."
    )
    distance_m: Optional[int] = Field(
        default=None, description="Planned running distance in metres, if applicable."
    )
    prescription: str = Field(
        description="Full human-readable detail: structure, intervals, paces/HR, "
        "stations, reps, loads, recoveries."
    )
    purpose: str = Field(description="One sentence on the training purpose.")
    hyrox_focus: Optional[str] = Field(
        default=None,
        description="Which Hyrox demand this targets (e.g. 'compromised running', "
        "'sled', 'wall balls'), or null.",
    )


class PlannedWeek(BaseModel):
    """A full week of prescribed sessions plus the generator's rationale."""

    rationale: str = Field(
        description="2-4 sentences explaining how this week reflects the phase, the "
        "athlete's recent load/recovery, and any auto-regulation applied."
    )
    sessions: list[PlannedSession]
