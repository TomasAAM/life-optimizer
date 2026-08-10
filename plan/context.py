"""Assemble the data brief for training-block generation.

No LLM API is called here. This script assembles everything a Claude Code agent
(driven on demand) needs to write the upcoming multi-week block: the
deterministic per-week periodization, the lactate-anchored zones, the athlete's
known loads, and the guardrails. The agent reads this brief, writes a
``PlannedBlock`` JSON file, then runs ``plan.persist`` to validate and save it.

Recent Garmin training/recovery data is deliberately NOT part of the brief — the
athlete self-regulates recovery on the day. Generation depends only on the race
calendar, the measured zones, and the configured availability.

Run with ``python -m plan.context`` to print the brief.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from dashboard import query
from plan import phase
from plan.config import (
    ATHLETE_BODYWEIGHT_KG,
    ATHLETE_LOADS,
    DEFAULT_CONFIG,
    HYROX_DIVISION,
    HYROX_STANDARDS,
    HYROX_STATIONS,
    STRENGTH_LIBRARY,
    STRENGTH_TEMPLATE,
    PlanConfig,
)
from plan.pace import seconds_to_pace

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

PLAN_FILE = _PROJECT_ROOT / "data" / "plan_block.json"


@dataclass(frozen=True)
class WeekContext:
    """Deterministic periodization metadata for one week of a block.

    Parameters
    ----------
    week_start : datetime.date
        Monday of the week.
    phase_name : str
        Periodization phase (base/build/peak/off) against the next race.
    weeks_remaining : int
        Whole weeks from this week to the next race (0 if none upcoming).
    race_name : str or None
        Name of the next race, or ``None`` when no race is upcoming.
    race_date : datetime.date or None
        Date of the next race, or ``None``.
    is_race_week : bool
        Whether the next race falls within this week.
    is_post_race_recovery : bool
        Whether a race fell in the seven days before this week.
    weekly_km_band : tuple of float
        Phase-scaled weekly running-volume target (km).
    """

    week_start: date
    phase_name: str
    weeks_remaining: int
    race_name: str | None
    race_date: date | None
    is_race_week: bool
    is_post_race_recovery: bool
    weekly_km_band: tuple[float, float]


@dataclass(frozen=True)
class BlockContext:
    """Everything needed to generate and later persist a training block.

    Parameters
    ----------
    cfg : PlanConfig
        The active plan configuration.
    weeks : list of WeekContext
        Per-week deterministic periodization, first week first.
    zones : pandas.DataFrame
        Lactate-anchored training zones.
    """

    cfg: PlanConfig
    weeks: list[WeekContext]
    zones: pd.DataFrame

    @property
    def block_start(self) -> date:
        """Monday of the block's first week."""
        return self.weeks[0].week_start


def _week_context(week_start: date, cfg: PlanConfig) -> WeekContext:
    """Compute the deterministic periodization metadata for a single week."""
    race = phase.next_race(week_start, cfg.races)
    if race is not None:
        phase_name, remaining = phase.phase_for_week(week_start, race.date)
    else:
        phase_name, remaining = "off", 0
    return WeekContext(
        week_start=week_start,
        phase_name=phase_name,
        weeks_remaining=remaining,
        race_name=race.name if race else None,
        race_date=race.date if race else None,
        is_race_week=phase.is_race_week(week_start, race),
        is_post_race_recovery=phase.is_post_race_recovery_week(week_start, cfg.races),
        weekly_km_band=phase.weekly_km_target(cfg.base_weekly_km, phase_name),
    )


def compute_block(cfg: PlanConfig = DEFAULT_CONFIG) -> list[WeekContext]:
    """Compute the per-week periodization for the upcoming block (no I/O).

    The block starts on the upcoming Monday and runs ``cfg.block_weeks`` weeks,
    flowing across any race in between (the next-race lookup shifts week by week).

    Parameters
    ----------
    cfg : PlanConfig
        Plan configuration (race calendar, block length, availability).

    Returns
    -------
    list of WeekContext
        One entry per week of the block, in chronological order.
    """
    block_start = phase.upcoming_monday(date.today())
    return [
        _week_context(block_start + timedelta(days=7 * i), cfg)
        for i in range(cfg.block_weeks)
    ]


def gather(cfg: PlanConfig = DEFAULT_CONFIG) -> BlockContext:
    """Compute the block context and pull the measured zones.

    Parameters
    ----------
    cfg : PlanConfig
        Plan configuration.

    Returns
    -------
    BlockContext
        Per-week periodization plus the lactate-anchored zones.
    """
    supabase = query.get_supabase_client()
    zones = query.fetch_training_zones(supabase)
    return BlockContext(cfg=cfg, weeks=compute_block(cfg), zones=zones)


def _format_zones(zones: pd.DataFrame) -> str:
    """Render the zone table as a compact text block."""
    if zones.empty:
        return "  (no zones — run plan.zones first)"
    lines = []
    for z in zones.sort_values("zone_index").itertuples():
        lo = "" if pd.isna(z.hr_low) else int(z.hr_low)
        hi = "" if pd.isna(z.hr_high) else int(z.hr_high)
        hr = f"{lo or '<'}–{hi or '>'} bpm"
        pace = f"{seconds_to_pace(z.pace_low_s_per_km)}–{seconds_to_pace(z.pace_high_s_per_km)} /km"
        lines.append(f"  Z{z.zone_index} {z.zone_name}: HR {hr}, pace {pace}")
    return "\n".join(lines)


def _format_week_plan(w: WeekContext, cfg: PlanConfig) -> str:
    """Render one week's periodization line, with any race-week / recovery note."""
    end = w.week_start + timedelta(days=6)
    header = (
        f"  WEEK of {w.week_start.isoformat()}..{end.isoformat()} — "
        f"phase {w.phase_name.upper()}"
    )
    if w.race_name and w.race_date:
        header += f", next race {w.race_name} {w.race_date.isoformat()} ({w.weeks_remaining} wk)"
    else:
        header += ", no upcoming race (maintenance)"
    header += f"\n    weekly running volume target: {w.weekly_km_band[0]}–{w.weekly_km_band[1]} km"

    if w.is_race_week and w.race_date:
        header += (
            f"\n    >> RACE WEEK: race on {w.race_date.strftime('%A %d %b')}. Train normally "
            f"early, then FRESHEN the final {cfg.pre_race_freshen_days} days — cut volume, keep "
            f"a short race-pace opener, no heavy/exhausting work. Do NOT taper the whole week."
        )
    if w.is_post_race_recovery:
        header += (
            f"\n    >> POST-RACE: open with {cfg.post_race_recovery_days} easy recovery day(s) "
            f"only, then train through in-band for the rest of the week (the athlete prefers "
            f"this to a full recovery week)."
        )
    return header


def render_brief(bundle: BlockContext) -> str:
    """Render the human/agent-readable block-generation brief.

    Parameters
    ----------
    bundle : BlockContext
        Output of :func:`gather`.

    Returns
    -------
    str
        The full brief: role, per-week periodization, zones, loads, guardrails,
        and the exact JSON shape to write to ``data/plan_block.json``.
    """
    cfg = bundle.cfg
    lt1_note = ""
    if not bundle.zones.empty and pd.isna(bundle.zones.iloc[0].get("lt1_hr")):
        lt1_note = (
            "\nNOTE: LT1 was not captured in the lab test — keep easy runs genuinely "
            "easy (well below the Z2 ceiling)."
        )

    race_line = "; ".join(f"{r.name} {r.date.isoformat()}" for r in cfg.races)
    week_blocks = "\n".join(_format_week_plan(w, cfg) for w in bundle.weeks)
    n_weeks = len(bundle.weeks)

    week_example = {
        "rationale": "2-4 sentences: how this week reflects its phase and any race-week "
        "freshen or post-race recovery. The athlete self-regulates recovery — do not cite "
        "Garmin readiness/HRV/CTL.",
        "methodology": "3-5 sentences naming the principles applied (polarized easy volume, "
        "threshold to raise LT2, heavy/explosive strength for economy kept off hard-run days, "
        "gradual load, freshen before a race). Principles only — no invented citations.",
        "sessions": [
            {
                "day": "Monday",
                "session_type": "run | strength | functional | sim | rest | cross",
                "title": "e.g. Threshold 4x8min",
                "zone": "Recovery|Endurance|Tempo|Threshold|VO2max|mixed|null",
                "intensity": "easy | moderate | hard",
                "duration_min": 60,
                "distance_m": 10000,
                "prescription": "Full detail (one-line fallback): intervals, target zone "
                "HR/pace, recoveries, station reps/loads.",
                "steps": [
                    {"phase": "warmup", "kind": "run", "metric": "15 min easy",
                     "target": "Z1, no faster than 5:22/km", "load": None},
                    {"phase": "main", "kind": "run", "metric": "10 min at threshold",
                     "target": "155-163 bpm, 4:48-4:34/km", "load": None},
                    {"phase": "main", "kind": "rest", "metric": "2:30 jog recovery",
                     "target": "easy", "load": None},
                    {"phase": "main", "kind": "station", "metric": "sled push 4x12.5 m",
                     "target": "then 90s walk", "load": "202 kg"},
                    {"phase": "cooldown", "kind": "run", "metric": "10 min easy",
                     "target": "or slower", "load": None},
                ],
                "purpose": "One sentence on the training purpose.",
                "why": "Why this session at this dose today, and why not more — tied to a "
                "principle (e.g. 'threshold raises LT2; only one hard run today to stay polarized').",
                "hyrox_focus": "compromised running | sled | wall balls | ... | null",
            }
        ],
    }
    schema_example = {"weeks": [f"<PlannedWeek for each of the {n_weeks} weeks, first week first>", "..."]}

    return f"""You are an expert coach for a HYBRID endurance athlete. Write a threshold-centric, \
lactate-anchored {n_weeks}-WEEK TRAINING BLOCK grounded in hybrid/concurrent-training science (the deep \
evidence base; Hyrox-specific research is still thin). Optimize EQUALLY for HYROX (compromised running + \
strength-endurance across 8 stations) and {cfg.secondary_goal} running; the shared lever is raising LT2 \
and aerobic base. Apply the principles: mostly-easy polarized volume, sparing high-quality threshold \
work, heavy/explosive strength for running economy, and gradual load progression. Anchor every run to \
the measured zones below — never generic %HRmax. Protect the hard, protect the easy, kill the grey zone.

The athlete SELF-REGULATES recovery on the day (err high — rather over- than under-train, take on-the-day
outs rather than pre-cutting). Do NOT auto-regulate off Garmin readiness/HRV/CTL — none is provided.

RACE CALENDAR: {race_line} | parallel goal: {cfg.secondary_goal} | weighting: {cfg.goal_weighting}
BLOCK TO PLAN: {n_weeks} weeks, {bundle.block_start.isoformat()} onward.

PERIODIZATION (deterministic — do not override), week by week:
{week_blocks}

LACTATE-ANCHORED ZONES (shared across the block):
{_format_zones(bundle.zones)}{lt1_note}

AVAILABILITY & STRUCTURE (every week):
  {cfg.sessions_per_week} sessions/week: ~{cfg.runs_per_week} runs + ~{cfg.strength_per_week} \
strength/functional; the rest are rest days.
  Default rest day(s): {", ".join(cfg.rest_days)}. Long/endurance run on {cfg.long_run_day}.
  Gym access: {cfg.gym_access} — program heavy barbell and explosive/plyometric work, not only \
bodyweight circuits.
  EQUIPMENT: FREE WEIGHTS ONLY — barbell, dumbbell, kettlebell, bodyweight, bands. Do NOT prescribe \
cable or selectorized machines (lat pulldown, pec deck, leg press, cable rows). The Hyrox stations \
(ski erg, rower, sleds) are the only permitted exception, since they are the event itself.
  Gym frequency: ONE gym visit available EVERY day, so a gym session can be placed on any day.
  A gym trip must be WORTH THE TRIP: if a day includes a gym session, give it a full session \
(~45-60 min, roughly 5-7 movements), not a 20-minute accessory add-on.
  Home treadmill: running is always available at home independent of the gym visit. The natural
  double is therefore GYM in the morning + RUN at home in the afternoon. Prefer splitting a high-km
  day into two shorter runs (AM/PM) over one oversized run — same km, lower per-session tissue load.
  Hyrox stations: {", ".join(HYROX_STATIONS)}.
  Strength/explosive movements: {", ".join(STRENGTH_LIBRARY)}.

LOADS ({HYROX_DIVISION}) — prescribe station work AT these competition standards (the athlete handles them):
{chr(10).join(f"  {k}: {v}" for k, v in HYROX_STANDARDS.items())}
  Athlete bodyweight: {ATHLETE_BODYWEIGHT_KG:.0f} kg — read the loads below as relative strength.
  Known athlete capacity: {"; ".join(f"{k} {v}" for k, v in ATHLETE_LOADS.items())}.
  STRENGTH STRUCTURE (evidence-based): {STRENGTH_TEMPLATE}

GUARDRAILS (apply to EVERY week of the block):
  - Each week has exactly 7 entries, one per weekday Monday..Sunday (use session_type "rest" for rest days).
  - Keep "hard" days separated by >= 1 easy or rest day.
  - Weight the two goals EQUALLY: balance pure running quality (threshold, long run, economy) with
    Hyrox-specific work (compromised running, stations) roughly 50/50 across each week.
  - Use the full gym: at least one strength session per week includes heavy compound or explosive
    lifts (squat, trap-bar deadlift, hip thrust, jumps) for running economy and sled power.
  - Keep explosive/plyometric strength OFF hard-run days (same-session concurrent training blunts
    power) — schedule it on an easy-run or standalone strength day.
  - Hit the weekly-km target; easy runs carry the km (strength/stations don't count toward km). Judge
    strength by load + RIR, not HR, and prescribe concrete kg from the loads above.
  - Double sessions are welcome, but a double day = exactly one GYM session + one NO-GYM session (run or
    bodyweight); never schedule two gym sessions in a day.
  - Never place two low-intensity-FEEL days back to back (e.g. a heavy low-rep lift immediately before an
    easy run) — pair heavy strength with a hard run to make a clean hard day, keep the easy days cleanly easy.
  - In build/peak weeks include >= 1 compromised-running session and >= 1 station/strength-endurance session.
  - Respect the per-week RACE WEEK and POST-RACE notes above where present (freshen the final days before a
    race; open a post-race week with the stated recovery day(s), then train through).
  - STEPS = typed segments rendered as Runna-style rows. Each segment has: phase (warmup/main/
    cooldown, or null), kind (run/rest/station/strength/note), metric (the bold dose), target
    (sub-line: HR/pace/effort or a note), load (kg for station/strength, else null). List a repeated
    block (e.g. 3x threshold) as its individual work + rest segments, all phase "main". For a
    compromised-running sim, alternate run segments and station segments (with load), each round.
    Leave `steps` empty ([]) only for a trivial single-effort session; always also fill the one-line
    `prescription` as a fallback.
  - DETAIL & CONSISTENCY: be explicit and unambiguous. State the exact number of rounds/sets/reps.
    `distance_m` and `duration_min` MUST equal the sum across the steps.
  - LOADS: give a concrete weight for every strength/station movement — station work at the Hyrox
    division standard above, barbell lifts by RPE. State reps and rest. Never write a loadless station.
  - Fill `why` for every session (the justification AND the trade-off — why not more), and the
    week-level `methodology` (principles only). Do NOT invent citations; sources are curated separately.

OUTPUT: write JSON matching this shape to {PLAN_FILE}, then run `python -m plan.persist`. The top level is
a PlannedBlock with a `weeks` list of {n_weeks} PlannedWeek objects (first week first). Each PlannedWeek is:
{json.dumps(week_example, indent=2)}

...wrapped as:
{json.dumps(schema_example, indent=2)}
"""


def main() -> None:
    """Print the block-generation brief to stdout."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print(render_brief(gather()))


if __name__ == "__main__":
    main()
