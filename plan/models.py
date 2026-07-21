"""Pydantic schema for the generated training plan.

These models define the strict structured contract the Claude Code agent writes
to ``data/plan_block.json``: a :class:`PlannedBlock` of one or more
:class:`PlannedWeek` entries. ``plan.persist`` validates the file against this
schema before upserting it, so a malformed week is rejected rather than stored.
Keeping the shape flat (no free-form dicts) makes validation reliable.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

DayName = Literal[
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]
SessionType = Literal["run", "strength", "functional", "sim", "rest", "cross"]
Intensity = Literal["easy", "moderate", "hard"]


StepKind = Literal["run", "rest", "station", "strength", "note"]
StepPhase = Literal["warmup", "main", "cooldown"]


class Step(BaseModel):
    """One typed segment of a session, rendered as a Runna-style row.

    Consecutive segments that share a ``phase`` are grouped under one colored band
    (Warm-up / Main set / Cool-down). A repeated block (e.g. 3x threshold) is
    listed as its individual work + rest segments, all with phase "main".
    """

    phase: Optional[StepPhase] = Field(
        default=None,
        description="Band grouping: warmup, main, or cooldown. Null for a single-effort "
        "session (e.g. an easy run) that needs no bands.",
    )
    kind: StepKind = Field(default="note", description="Segment type — drives icon and tag.")
    metric: str = Field(
        description="The bold primary line: the dose, e.g. '10 min at threshold', '1 km run', "
        "'40 wall balls', '2:30 jog recovery'.",
    )
    target: Optional[str] = Field(
        default=None,
        description="Sub-line: target HR/pace/effort or a short note, e.g. '155-163 bpm, "
        "4:48-4:34/km' or 'then 90s walk'.",
    )
    load: Optional[str] = Field(
        default=None,
        description="Weight for strength/station moves, e.g. '9 kg', '~150 kg'. Null for runs/rest.",
    )


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
        "stations, reps, loads, recoveries. Used as a fallback when steps is empty."
    )
    steps: list[Step] = Field(
        default_factory=list,
        description="The session broken into labelled blocks (warm-up / main set / "
        "cool-down, or rounds). Drives the structured card; leave empty for a "
        "single-block session like an easy run or rest.",
    )
    purpose: str = Field(description="One sentence on the training purpose.")
    why: str = Field(
        description="The justification AND the trade-off: why this session, at this "
        "dose, today — and why not more (more volume / intensity / strength). Tie to "
        "the training principle it serves (e.g. polarized easy volume, threshold to "
        "raise LT2, strength for economy, gradual load).",
    )
    hyrox_focus: Optional[str] = Field(
        default=None,
        description="Which Hyrox demand this targets (e.g. 'compromised running', "
        "'sled', 'wall balls'), or null.",
    )


class PlannedWeek(BaseModel):
    """A full week of prescribed sessions plus the generator's rationale."""

    rationale: str = Field(
        description="2-4 sentences explaining how this week reflects its phase and any "
        "race-week freshen or post-race recovery applied. The athlete self-regulates "
        "recovery on the day, so do not reference Garmin readiness/HRV/CTL here."
    )
    methodology: str = Field(
        description="3-5 sentences naming the training PRINCIPLES this week applies "
        "(polarized mostly-easy volume, threshold work to raise LT2, heavy/explosive "
        "strength for economy kept off hard-run days, gradual load progression, freshen "
        "before a race) and why those principles fit a hybrid endurance athlete. "
        "Reference principles only — do NOT invent citations; the sources are curated "
        "separately.",
    )
    sessions: list[PlannedSession]


class PlannedBlock(BaseModel):
    """A multi-week training block: an ordered list of planned weeks.

    Week starts are not carried in the JSON — they are assigned deterministically
    on persist from the block's first Monday (week ``i`` starts ``block_start +
    7*i``), so the generator only has to order the weeks correctly, never compute
    dates. ``weeks`` runs from the first week of the block to the last, in order.
    """

    weeks: list[PlannedWeek] = Field(
        description="The block's weeks in chronological order (first week first). "
        "Each is a full PlannedWeek; the number of weeks matches the block length "
        "given in the brief."
    )
