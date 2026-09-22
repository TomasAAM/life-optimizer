"""Seed the ``training_zones`` table from the athlete's current LT2 anchor.

The five zones are anchored on LT2; LT1 has never been captured, so the
Recovery/Endurance bound is an approximation flagged downstream. The current
values are embedded as ``_SEED_ZONES`` so the dashboard DB has authoritative
zones without depending on the garmin-pipeline filesystem.
:func:`load_from_results_json` refreshes them from a garmin-pipeline
``results_<date>.json`` after a new lab test.

The anchor is *not* required to come from a lab test. The 2026-06-19 step test
was superseded by field data on 2026-09-06 and again on 2026-09-22 (see
``_SOURCE_TEST_DATE`` below),
because the lab pair contradicted every subsequent race and training run.

Run directly to (re)seed: ``python -m plan.zones``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

from plan.pace import pace_to_seconds

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

# Current zones, re-anchored on 2026-09-22 to LT2 = 4:10/km @ 178 bpm. Field
# evidence, no lab test:
#
# * The athlete's own pace-HR relation (6:02/km -> 133 bpm; 5:05 -> 154;
#   3:58 -> 183) is near-linear at ~2.3 s/km per bpm. Evaluated at 178 bpm it
#   gives 4:10/km from either end of the curve.
# * Three ~30-40 min maximal efforts put LTHR at ~178-180: the 2026-08-30 10 km
#   (avg HR 183), the 2026-09-13 official 10 km (avg HR 181) and the naive
#   last-20-min average of the 2026-08-11 TT (179.6). A race of that length
#   averages ~1-2% above LTHR.
# * The 2026-09-22 3x8 min session held 4:12/km at avg HR 174 in a steady rep,
#   while 4:09/km drifted from 177 to 181 within the rep: threshold sits between.
#
# This supersedes the 2026-09-06 anchor (4:16/km @ 175 bpm), which took the
# curve's 175 bpm point on the assumption that LTHR was 175. Before that, the
# 2026-06-19 lab pair (4:34/km @ 163 bpm) was contradicted by every easy run.
#
# HR bounds keep the same fractions of LTHR as before (81 / 89 / 93 / 100%);
# pace bounds keep the same fractions of threshold speed. Threshold *intervals*
# are prescribed at 4:12-4:08/km, capped at ~180 bpm on the final rep, since HR
# drifts up across a rep.
#
# pace_low = slower bound (s/km), pace_high = faster bound; None = open.
_SOURCE_TEST_DATE = "2026-09-22"
_LT2_HR = 178
_LT2_PACE_S = pace_to_seconds("4:10")

_SEED_ZONES: list[dict[str, Any]] = [
    {
        "zone_index": 1, "zone_name": "Recovery",
        "hr_low": None, "hr_high": 144,
        "pace_low_s_per_km": None, "pace_high_s_per_km": pace_to_seconds("5:37"),
    },
    {
        "zone_index": 2, "zone_name": "Endurance",
        "hr_low": 144, "hr_high": 158,
        "pace_low_s_per_km": pace_to_seconds("5:37"), "pace_high_s_per_km": pace_to_seconds("4:58"),
    },
    {
        "zone_index": 3, "zone_name": "Tempo",
        "hr_low": 158, "hr_high": 166,
        "pace_low_s_per_km": pace_to_seconds("4:58"), "pace_high_s_per_km": pace_to_seconds("4:27"),
    },
    {
        "zone_index": 4, "zone_name": "Threshold",
        "hr_low": 166, "hr_high": 178,
        "pace_low_s_per_km": pace_to_seconds("4:27"), "pace_high_s_per_km": pace_to_seconds("4:10"),
    },
    {
        "zone_index": 5, "zone_name": "VO2max",
        "hr_low": 178, "hr_high": None,
        "pace_low_s_per_km": pace_to_seconds("4:10"), "pace_high_s_per_km": None,
    },
]


def _get_client() -> Client:
    """Create a Supabase client from environment variables."""
    load_dotenv(_PROJECT_ROOT / ".env", override=True)
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def _rows_from_zones(
    zones: list[dict[str, Any]],
    source_test_date: str,
    lt2_hr: int | None,
    lt2_pace_s: int | None,
    lt1_hr: int | None,
    lt1_pace_s: int | None,
) -> list[dict[str, Any]]:
    """Attach the shared test-anchor columns to each zone row."""
    return [
        {
            **zone,
            "source_test_date": source_test_date,
            "lt2_hr": lt2_hr,
            "lt2_pace_s_per_km": lt2_pace_s,
            "lt1_hr": lt1_hr,
            "lt1_pace_s_per_km": lt1_pace_s,
        }
        for zone in zones
    ]


def load_from_results_json(path: str | Path) -> list[dict[str, Any]]:
    """Build zone rows from a garmin-pipeline ``results_<date>.json`` file.

    Parameters
    ----------
    path : str or pathlib.Path
        Path to the lactate analysis results JSON (contains ``test_date``,
        ``lt2``, and a ``zones`` list with pace/HR bounds).

    Returns
    -------
    list of dict
        Rows ready to upsert into ``training_zones``.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    lt2 = data.get("lt2") or {}
    lt1 = data.get("lt1") or {}

    def _pace_s(value: str | None) -> int | None:
        return pace_to_seconds(value) if value else None

    zones = [
        {
            "zone_index": z["number"],
            "zone_name": z["name"],
            "hr_low": z.get("hr_low"),
            "hr_high": z.get("hr_high"),
            "pace_low_s_per_km": _pace_s(z.get("pace_slow")),
            "pace_high_s_per_km": _pace_s(z.get("pace_fast")),
        }
        for z in data.get("zones", [])
    ]
    return _rows_from_zones(
        zones,
        source_test_date=data["test_date"],
        lt2_hr=lt2.get("hr"),
        lt2_pace_s=_pace_s(lt2.get("pace")),
        lt1_hr=lt1.get("hr"),
        lt1_pace_s=_pace_s(lt1.get("pace")),
    )


def seed(supabase: Client | None = None, rows: list[dict[str, Any]] | None = None) -> int:
    """Upsert training zones into Supabase.

    Parameters
    ----------
    supabase : supabase.Client, optional
        Authenticated client; created from the environment when omitted.
    rows : list of dict, optional
        Zone rows to upsert; defaults to the embedded ``_SEED_ZONES``.

    Returns
    -------
    int
        Number of zone rows written.
    """
    supabase = supabase or _get_client()
    if rows is None:
        rows = _rows_from_zones(
            _SEED_ZONES,
            source_test_date=_SOURCE_TEST_DATE,
            lt2_hr=_LT2_HR,
            lt2_pace_s=_LT2_PACE_S,
            lt1_hr=None,
            lt1_pace_s=None,
        )
    supabase.table("training_zones").upsert(rows, on_conflict="zone_index").execute()
    logger.info("Seeded %d training zones (source test %s)", len(rows), rows[0]["source_test_date"])
    return len(rows)


def main() -> None:
    """Seed zones from the embedded lab values."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    seed()


if __name__ == "__main__":
    main()
