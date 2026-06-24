"""Gather the data brief for the weekly plan generation.

No LLM API is called here. This script assembles everything a Claude Code agent
(driven by ``/loop`` or ``/schedule``) needs to write the upcoming week: the
deterministic periodization phase, the lactate-anchored zones, a summary of
recent training and recovery, and the guardrails. The agent reads this brief,
writes a ``PlannedWeek`` JSON file, then runs ``plan.persist`` to save it.

Run with ``python -m plan.context`` to print the brief.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from dashboard import metrics, query
from plan import phase
from plan.config import DEFAULT_CONFIG, HYROX_STATIONS, PlanConfig
from plan.pace import seconds_to_pace

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

PLAN_FILE = _PROJECT_ROOT / "data" / "plan_week.json"


@dataclass(frozen=True)
class ContextBundle:
    """Everything needed to generate and later persist a plan week.

    Parameters
    ----------
    cfg : PlanConfig
        The active plan configuration.
    week_start : datetime.date
        Monday of the week being planned.
    phase_name : str
        Deterministic periodization phase.
    weeks_remaining : int
        Whole weeks until the race.
    load_band : tuple of float
        ACWR-bounded weekly training-load target.
    summary : dict
        Recent training and recovery snapshot (the audit input).
    zones : pandas.DataFrame
        Lactate-anchored training zones.
    """

    cfg: PlanConfig
    week_start: date
    phase_name: str
    weeks_remaining: int
    load_band: tuple[float, float]
    summary: dict[str, Any]
    zones: pd.DataFrame


def _recent_summary(
    activities: pd.DataFrame,
    load_series: pd.DataFrame,
    snapshot: metrics.ReadinessSnapshot,
    readiness: pd.DataFrame,
    window_days: int,
) -> dict[str, Any]:
    """Summarize recent training and recovery into a compact, auditable dict."""
    acwr = round(snapshot.atl / snapshot.ctl, 2) if snapshot.ctl > 0 else None
    cutoff = pd.Timestamp(snapshot.date) - pd.Timedelta(days=window_days)
    recent = load_series[load_series.index >= cutoff]
    last7 = load_series[load_series.index >= pd.Timestamp(snapshot.date) - pd.Timedelta(days=7)]

    sessions: list[dict[str, Any]] = []
    if not activities.empty:
        act = activities.copy()
        act["d"] = pd.to_datetime(act["start_time_local"]).dt.normalize()
        act = act[act["d"] >= cutoff].sort_values("d")
        for r in act.itertuples():
            sessions.append(
                {
                    "date": r.d.date().isoformat(),
                    "type": r.activity_type,
                    "name": r.activity_name,
                    "load": None if pd.isna(r.training_load) else round(float(r.training_load)),
                }
            )

    latest_readiness: dict[str, Any] = {}
    if not readiness.empty:
        rd = readiness.sort_values("date").iloc[-1]
        latest_readiness = {
            "date": str(rd.get("date")),
            "score": None if pd.isna(rd.get("score")) else int(rd["score"]),
            "level": rd.get("level"),
            "recovery_time_h": None
            if pd.isna(rd.get("recovery_time_h"))
            else int(rd["recovery_time_h"]),
        }

    return {
        "as_of": snapshot.date.date().isoformat(),
        "ctl_fitness": snapshot.ctl,
        "atl_fatigue": snapshot.atl,
        "tsb_form": snapshot.tsb,
        "tsb_label": snapshot.tsb_label,
        "acwr": acwr,
        "load_last_7d": round(float(last7["load"].sum())),
        f"load_last_{window_days}d": round(float(recent["load"].sum())),
        f"training_days_last_{window_days}d": int((recent["load"] > 0).sum()),
        "hrv_last_night": snapshot.hrv_night,
        "hrv_status": snapshot.hrv_status,
        "readiness": latest_readiness,
        "recent_sessions": sessions,
    }


def gather(cfg: PlanConfig = DEFAULT_CONFIG) -> ContextBundle:
    """Pull recent data and compute the deterministic plan context.

    Parameters
    ----------
    cfg : PlanConfig
        Plan configuration (race date, availability, etc.).

    Returns
    -------
    ContextBundle
        The computed phase/load context plus recent-data summary and zones.
    """
    supabase = query.get_supabase_client()
    activities = query.fetch_activities(supabase)
    if activities.empty:
        raise RuntimeError("No activities available; cannot build plan context")

    readiness = query.fetch_readiness(supabase)
    zones = query.fetch_training_zones(supabase)
    hrv_series = metrics.build_hrv_series(query.fetch_hrv(supabase))
    load_series = metrics.build_load_series(activities)
    snapshot = metrics.latest_snapshot(load_series, hrv_series)

    week_start = phase.upcoming_monday(date.today())
    phase_name, weeks_remaining = phase.phase_for_week(week_start, cfg.race_date)
    load_band = phase.load_target_band(snapshot.ctl * 7.0, phase_name)
    summary = _recent_summary(activities, load_series, snapshot, readiness, cfg.recent_window_days)

    return ContextBundle(
        cfg=cfg,
        week_start=week_start,
        phase_name=phase_name,
        weeks_remaining=weeks_remaining,
        load_band=load_band,
        summary=summary,
        zones=zones,
    )


def _format_zones(zones: pd.DataFrame) -> str:
    """Render the zone table as a compact text block."""
    if zones.empty:
        return "  (no zones — run plan.zones first)"
    lines = []
    for z in zones.sort_values("zone_index").itertuples():
        hr = f"{z.hr_low or '<'}–{z.hr_high or '>'} bpm"
        pace = f"{seconds_to_pace(z.pace_low_s_per_km)}–{seconds_to_pace(z.pace_high_s_per_km)} /km"
        lines.append(f"  Z{z.zone_index} {z.zone_name}: HR {hr}, pace {pace}")
    return "\n".join(lines)


def render_brief(bundle: ContextBundle) -> str:
    """Render the human/agent-readable generation brief.

    Parameters
    ----------
    bundle : ContextBundle
        Output of :func:`gather`.

    Returns
    -------
    str
        The full brief: role, periodization, zones, recent data, guardrails, and
        the exact JSON shape to write to ``data/plan_week.json``.
    """
    cfg = bundle.cfg
    lt1_note = ""
    if not bundle.zones.empty and pd.isna(bundle.zones.iloc[0].get("lt1_hr")):
        lt1_note = (
            "\nNOTE: LT1 was not captured in the lab test — keep easy runs genuinely "
            "easy (well below the Z2 ceiling)."
        )

    schema_example = {
        "rationale": "2-4 sentences: how this week reflects the phase, recent load/recovery, "
        "and any auto-regulation applied.",
        "methodology": "3-5 sentences naming the principles applied (polarized easy volume, "
        "threshold to raise LT2, heavy/explosive strength for economy kept off hard-run days, "
        "gradual load, taper near race). Principles only — no invented citations.",
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
                    {"label": "Warm-up", "detail": "15 min easy, Z1"},
                    {"label": "Main set", "detail": "3x10 min @ threshold, 155-163 bpm, 2:30 jog"},
                    {"label": "Cool-down", "detail": "10 min easy"},
                ],
                "purpose": "One sentence on the training purpose.",
                "why": "Why this session at this dose today, and why not more — tied to a "
                "principle (e.g. 'threshold raises LT2; only one hard run today to stay polarized "
                "and protect recovery').",
                "hyrox_focus": "compromised running | sled | wall balls | ... | null",
            }
        ],
    }

    return f"""You are an expert coach for a HYBRID endurance athlete. Write a threshold-centric, \
lactate-anchored training week grounded in hybrid/concurrent-training science (the deep evidence \
base; Hyrox-specific research is still thin). Optimize EQUALLY for {cfg.target_race.upper()} \
(compromised running + strength-endurance across 8 stations) and {cfg.secondary_goal} running; \
the shared lever is raising LT2 and aerobic base. Apply the principles: mostly-easy polarized \
volume, sparing high-quality threshold work, heavy/explosive strength for running economy, and \
gradual load progression. Auto-regulate: when recovery is poor (low readiness, strongly negative \
TSB/form, rising load), cut intensity and volume rather than pushing on. Anchor every run to the \
measured zones below — never generic %HRmax.

TARGET: {cfg.target_race.upper()} on {cfg.race_date.isoformat()} | parallel goal: {cfg.secondary_goal} \
| weighting: {cfg.goal_weighting}
WEEK TO PLAN: Monday {bundle.week_start.isoformat()}

PERIODIZATION (deterministic — do not override):
  Phase: {bundle.phase_name}   Weeks to race: {bundle.weeks_remaining}
  Weekly training-load target band: {int(bundle.load_band[0])}–{int(bundle.load_band[1])} (Garmin units)

LACTATE-ANCHORED ZONES:
{_format_zones(bundle.zones)}{lt1_note}

RECENT TRAINING & RECOVERY (auto-regulate off this):
{json.dumps(bundle.summary, indent=2)}

AVAILABILITY & STRUCTURE:
  {cfg.sessions_per_week} sessions/week: ~{cfg.runs_per_week} runs + ~{cfg.strength_per_week} \
strength/functional; the rest are rest days.
  Default rest day(s): {", ".join(cfg.rest_days)}. Long/endurance run on {cfg.long_run_day}.
  Gym access: {cfg.gym_access} — program heavy barbell and explosive/plyometric work, not only \
bodyweight circuits.
  Hyrox stations: {", ".join(HYROX_STATIONS)}.
  Strength/explosive movements: {", ".join(STRENGTH_LIBRARY)}.

GUARDRAILS:
  - Exactly 7 entries, one per weekday Monday..Sunday (use session_type "rest" for rest days).
  - Keep "hard" days separated by >= 1 easy or rest day.
  - Weight the two goals EQUALLY: balance pure running quality (threshold, long run, economy) with
    Hyrox-specific work (compromised running, stations) roughly 50/50 across the week.
  - Use the full gym: at least one strength session should include heavy compound or explosive
    lifts (squat, trap-bar deadlift, hip thrust, jumps) for running economy and sled power.
  - Keep explosive/plyometric strength OFF hard-run days (same-session concurrent training blunts
    power) — schedule it on an easy-run or standalone strength day.
  - Bias volume toward the weekly-load band; in taper cut volume but keep some race-pace intensity.
  - In build/peak include >= 1 compromised-running session and >= 1 station/strength-endurance session.
  - If readiness is LOW or TSB is strongly negative, downgrade the hardest session(s) and say so.
  - Break structured sessions (intervals, circuits, sims) into 2-5 `steps` (warm-up / main set /
    cool-down, or rounds), each a short label + detail. Leave `steps` empty ([]) for single-effort
    sessions like easy runs or rest. Always also fill the one-line `prescription` as a fallback.
  - Fill `why` for every session (the justification AND the trade-off — why not more), and the
    week-level `methodology` (principles only). Do NOT invent citations; sources are curated separately.

OUTPUT: write JSON matching this shape to {PLAN_FILE}, then run `python -m plan.persist`:
{json.dumps(schema_example, indent=2)}
"""


def main() -> None:
    """Print the generation brief to stdout."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print(render_brief(gather()))


if __name__ == "__main__":
    main()
