"""Pydantic schema for the generated training plan.

These models define the strict structured contract the Claude Code agent writes
to ``data/plan_block.json``: a :class:`PlannedBlock` of one or more
:class:`PlannedWeek` entries. ``plan.persist`` validates the file against this
schema before upserting it, so a malformed week is rejected rather than stored.
Keeping the shape flat (no free-form dicts) makes validation reliable.
"""

from __future__ import annotations

from typing import Literal, Optional, Self

from pydantic import BaseModel, Field, model_validator

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
        description="Sub-line: target HR/pace/effort or a short note, e.g. the Z4 HR and "
        "pace bounds from the brief's zone table, or 'then 90s walk'.",
    )
    load: Optional[str] = Field(
        default=None,
        description="Weight for strength/station moves, e.g. '9 kg', '~150 kg'. Null for runs/rest.",
    )
    # Machine-readable dose and targets, read by plan.garmin_workout to build the
    # watch workout. The text fields above stay the human-facing rendering.
    duration_s: Optional[int] = Field(
        default=None, gt=0,
        description="Step length in seconds when it ends on time. Null when it ends on "
        "distance or on the lap button.",
    )
    distance_m: Optional[int] = Field(
        default=None, gt=0,
        description="Step length in metres when it ends on distance.",
    )
    pace_fast_s_per_km: Optional[int] = Field(
        default=None, gt=0,
        description="Fast end of the pace target in seconds per km (4:08/km -> 248).",
    )
    pace_slow_s_per_km: Optional[int] = Field(
        default=None, gt=0,
        description="Slow end of the pace target in seconds per km (4:12/km -> 252).",
    )
    hr_min: Optional[int] = Field(
        default=None, gt=0, description="Heart-rate floor in bpm. Requires hr_max."
    )
    hr_max: Optional[int] = Field(
        default=None, gt=0, description="Heart-rate ceiling in bpm, e.g. 145 for easy."
    )
    repeats: Optional[int] = Field(
        default=None, ge=2,
        description="Repeat this effort N times with an untimed walk-back recovery "
        "between, e.g. 6 for '6x20 s strides'. Requires duration_s or distance_m.",
    )
    watch_target: Optional[Literal["pace", "hr", "none"]] = Field(
        default=None,
        description="Which target the watch alerts on. Null means pace when a pace "
        "range is given, else HR when hr_max is given, else none. Set 'hr' for "
        "treadmill threshold reps, where watch pace is unreliable.",
    )

    @model_validator(mode="after")
    def check_watch_fields(self) -> Self:
        """Reject contradictory or half-specified watch fields.

        Returns
        -------
        Step
            The validated step.

        Raises
        ------
        ValueError
            If the step ends on both time and distance, a range is half given or
            inverted, ``repeats`` has no dose, or ``watch_target`` names a target
            the step does not carry.
        """
        if self.duration_s is not None and self.distance_m is not None:
            raise ValueError("A step ends on duration_s or distance_m, not both.")
        if (self.pace_fast_s_per_km is None) != (self.pace_slow_s_per_km is None):
            raise ValueError("Give both pace_fast_s_per_km and pace_slow_s_per_km, or neither.")
        if self.pace_fast_s_per_km is not None and self.pace_fast_s_per_km > self.pace_slow_s_per_km:
            raise ValueError("pace_fast_s_per_km must not be slower than pace_slow_s_per_km.")
        if self.hr_min is not None and self.hr_max is None:
            raise ValueError("hr_min requires hr_max.")
        if self.hr_min is not None and self.hr_min > self.hr_max:
            raise ValueError("hr_min must not exceed hr_max.")
        if self.repeats is not None and self.duration_s is None and self.distance_m is None:
            raise ValueError("repeats requires duration_s or distance_m.")
        if self.watch_target == "pace" and self.pace_fast_s_per_km is None:
            raise ValueError("watch_target 'pace' requires a pace range.")
        if self.watch_target == "hr" and self.hr_max is None:
            raise ValueError("watch_target 'hr' requires hr_max.")
        return self


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
        "stations, reps, loads, recoveries. Retained as a legacy-rendering fallback."
    )
    steps: list[Step] = Field(
        default_factory=list,
        description="The session broken into labelled blocks (warm-up / main set / "
        "cool-down, or rounds). Drives the structured card; only rest days may "
        "leave this empty.",
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

    @model_validator(mode="after")
    def require_visual_steps_for_workouts(self) -> Self:
        """Reject workouts that would degrade to the plain-text fallback.

        Returns
        -------
        PlannedSession
            The validated session.

        Raises
        ------
        ValueError
            If a non-rest session does not provide structured visual steps.
        """
        if self.session_type != "rest" and not self.steps:
            raise ValueError("Non-rest sessions require at least one structured step.")
        return self


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
        "strength sequenced to protect key running, gradual load progression, freshen "
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
