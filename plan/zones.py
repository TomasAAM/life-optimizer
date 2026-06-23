"""Seed the ``training_zones`` table from the lactate lab test.

The five zones are anchored on LT2 (the only threshold the last step test
resolved); LT1 was not captured, so the Recovery/Endurance bound is an
approximation flagged downstream. The current values are embedded as
``_SEED_ZONES`` so the dashboard DB has authoritative zones without depending on
the garmin-pipeline filesystem. :func:`load_from_results_json` refreshes them
from a garmin-pipeline ``results_<date>.json`` after a new test.

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

# Current zones, derived from the 2026-06-19 step test (consensus LT2: 4:34/km @
# 163 bpm). pace_low = slower bound (s/km), pace_high = faster bound; None = open.
_SOURCE_TEST_DATE = "2026-06-19"
_LT2_HR = 163
_LT2_PACE_S = pace_to_seconds("4:34")

_SEED_ZONES: list[dict[str, Any]] = [
    {
        "zone_index": 1, "zone_name": "Recovery",
        "hr_low": None, "hr_high": 139,
        "pace_low_s_per_km": None, "pace_high_s_per_km": pace_to_seconds("5:22"),
    },
    {
        "zone_index": 2, "zone_name": "Endurance",
        "hr_low": 139, "hr_high": 147,
        "pace_low_s_per_km": pace_to_seconds("5:22"), "pace_high_s_per_km": pace_to_seconds("5:04"),
    },
    {
        "zone_index": 3, "zone_name": "Tempo",
        "hr_low": 147, "hr_high": 155,
        "pace_low_s_per_km": pace_to_seconds("5:04"), "pace_high_s_per_km": pace_to_seconds("4:48"),
    },
    {
        "zone_index": 4, "zone_name": "Threshold",
        "hr_low": 155, "hr_high": 163,
        "pace_low_s_per_km": pace_to_seconds("4:48"), "pace_high_s_per_km": pace_to_seconds("4:34"),
    },
    {
        "zone_index": 5, "zone_name": "VO2max",
        "hr_low": 163, "hr_high": None,
        "pace_low_s_per_km": pace_to_seconds("4:34"), "pace_high_s_per_km": None,
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
