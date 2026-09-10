"""Body-composition ingestion from the Health Connect relay sheet.

The smart scale (Vitalia, via the Fitdays app) writes to Android Health
Connect, which is an **on-device** store: the Jetpack read API is Kotlin-only
and exposes no REST, server-side or CLI access, so this pipeline cannot read it
directly. An on-device exporter using Health Connect's documented background
read permission auto-exports the body-measurement records to a Google Sheet,
and that sheet -- published to the web as CSV -- is what this module reads.
Publishing avoids a service account: the URL is the only credential, which is
also why it must stay unguessable.

The whole sheet is re-read on every run and upserted on ``measured_at_local``,
so the
ingest is idempotent and self-healing -- a row corrected in the sheet corrects
in Supabase on the next run, with no incremental-sync state to drift.

Column names are matched by alias rather than by position, because the
exporter's header text is not a stable contract. Anything unmatched is logged
rather than dropped silently, so a header change surfaces in the CI log as a
named column instead of as a column of nulls.
"""

from __future__ import annotations

import io
import logging
import os
import re
from typing import Any

import pandas as pd
import requests
from supabase import Client

logger = logging.getLogger(__name__)

_SHEET_URL_ENV = "BODY_SHEET_CSV_URL"
_REQUEST_TIMEOUT_S = 30

# Header aliases, matched after ``_normalise_header`` strips case, punctuation
# and any parenthesised unit. The exporter, a manual sheet and a hand-rolled CSV
# all spell these differently.
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "measured_at_local": ("time", "date", "datetime", "timestamp", "starttime", "instant"),
    "weight_kg": ("weight", "weightkg", "weightgrams", "bodyweight", "mass"),
    "body_fat_pct": ("bodyfat", "bodyfatpercentage", "bodyfatpct", "fat", "fatpercentage"),
    "lean_mass_kg": ("leanbodymass", "leanmass", "musclemass"),
    "bone_mass_kg": ("bonemass", "bone"),
    "body_water_kg": ("bodywatermass", "bodywater", "water"),
    "source": ("datasource", "sourceapp", "origin", "packagename", "app", "source"),
}

_NUMERIC_COLUMNS = (
    "weight_kg", "body_fat_pct", "lean_mass_kg", "bone_mass_kg", "body_water_kg",
)
_MASS_COLUMNS = ("weight_kg", "lean_mass_kg", "bone_mass_kg", "body_water_kg")

# A human weight in kilograms cannot exceed this, so anything above it is a
# reading in grams -- which is how Garmin and some Health Connect exporters
# serialise mass.
_MAX_PLAUSIBLE_KG = 300.0
# Body fat expressed as a fraction (0.18) rather than percentage points (18.0).
# No adult's body fat sits at or below 1%, so the boundary is unambiguous.
_MAX_FAT_FRACTION = 1.0

# The athlete's timezone, used to turn an offset-bearing export back into the
# clock they actually read. Santiago rather than UTC because that is where the
# weigh-ins happen, and the fasted-morning protocol is defined in local time.
_LOCAL_TZ = "America/Santiago"
_OFFSET_SUFFIX = r"(?:Z|[+-]\d{2}:?\d{2})$"


def _normalise_header(name: str) -> str:
    """Reduce a CSV header to a comparable key.

    Lowercases, drops any parenthesised unit and strips every non-alphanumeric
    character, so ``"Weight (kg)"`` and ``"WEIGHT"`` both collapse to
    ``"weight"``.

    Parameters
    ----------
    name : str
        Raw header text from the CSV.

    Returns
    -------
    str
        Normalised comparison key.

    Examples
    --------
    >>> _normalise_header("Body Fat (%)")
    'bodyfat'
    >>> _normalise_header("Lean body mass")
    'leanbodymass'
    """
    without_unit = re.sub(r"\(.*?\)", "", name)
    return re.sub(r"[^a-z0-9]", "", without_unit.lower())


def _map_columns(headers: list[str]) -> dict[str, str]:
    """Map raw CSV headers onto ``body_composition`` column names.

    Parameters
    ----------
    headers : list of str
        The CSV's header row.

    Returns
    -------
    dict
        Raw header mapped to schema column name, for the headers recognised.

    Examples
    --------
    >>> _map_columns(["Time", "Weight (kg)", "Steps"])
    {'Time': 'measured_at_local', 'Weight (kg)': 'weight_kg'}
    """
    lookup = {
        alias: column
        for column, aliases in _COLUMN_ALIASES.items()
        for alias in aliases
    }
    mapping: dict[str, str] = {}
    for header in headers:
        column = lookup.get(_normalise_header(header))
        # First header wins: an exporter emitting both "Weight" and "Weight (lb)"
        # would otherwise have the second silently overwrite the first.
        if column is not None and column not in mapping.values():
            mapping[header] = column
    return mapping


def _to_kg(values: pd.Series) -> pd.Series:
    """Convert a mass column to kilograms, deciding per value.

    Parameters
    ----------
    values : pandas.Series
        Mass readings in kilograms, grams, or a mix of the two.

    Returns
    -------
    pandas.Series
        The same readings in kilograms.
    """
    return values.where(values <= _MAX_PLAUSIBLE_KG, values / 1000.0)


def _to_percent(values: pd.Series) -> pd.Series:
    """Convert a body-fat column to percentage points, deciding per value.

    Parameters
    ----------
    values : pandas.Series
        Body fat as percentage points, as a fraction, or a mix of the two.

    Returns
    -------
    pandas.Series
        Body fat in percentage points.
    """
    return values.where(values > _MAX_FAT_FRACTION, values * 100.0)


def _to_wall_clock(values: pd.Series) -> pd.Series:
    """Parse timestamps to the wall clock the athlete read them off.

    Time of day is data here, not metadata: ``BENCHMARKS.md`` prescribes
    weighing fasted in the morning, so a reading's hour decides whether it is on
    protocol. Getting this wrong is not a cosmetic error -- normalising a
    Santiago 07:12 weigh-in to 10:12 UTC would flag a correctly taken reading as
    an evening one.

    Two shapes have to be handled, because which one arrives depends on an
    exporter nobody here controls. A naive timestamp is already local and is
    taken at face value. Anything carrying an offset -- the phone's own, or a
    ``Z`` from an exporter that normalised to UTC -- is resolved to an instant
    and then expressed in :data:`_LOCAL_TZ`, which is correct either way.

    Parameters
    ----------
    values : pandas.Series
        Raw timestamp column from the sheet.

    Returns
    -------
    pandas.Series
        Timezone-naive timestamps holding local wall-clock time.
    """
    text = values.astype("string").str.strip()
    has_offset = text.str.contains(_OFFSET_SUFFIX, regex=True, na=False)

    if not has_offset.any():
        return pd.to_datetime(text, errors="coerce")

    if not has_offset.all():
        # ``utc=True`` reads an offsetless value as UTC, so in a mixed sheet the
        # naive rows get shifted into the wrong hour. Rare enough to accept and
        # too consequential to swallow.
        logger.warning(
            "Relay sheet mixes offset-bearing and naive timestamps; the %d "
            "naive row(s) will be read as UTC and may land on the wrong hour",
            int((~has_offset).sum()),
        )

    # Parsed via UTC rather than natively: a column carrying more than one
    # offset cannot share a tz-aware dtype and comes back as ``object``, which
    # has no ``.dt`` accessor at all.
    instants = pd.to_datetime(text, errors="coerce", utc=True)
    try:
        return instants.dt.tz_convert(_LOCAL_TZ).dt.tz_localize(None)
    except Exception as exc:  # noqa: BLE001 - missing tz database, not bad data
        logger.warning(
            "Could not resolve timezone %s (%s); falling back to UTC wall clock",
            _LOCAL_TZ,
            exc,
        )
        return instants.dt.tz_localize(None)


def parse_sheet(csv_text: str) -> list[dict[str, Any]]:
    """Parse the relay sheet's CSV into ``body_composition`` rows.

    Timestamps are kept as local wall clock -- see :func:`_to_wall_clock`.
    Rows without a parseable timestamp or without a weight are dropped. A
    weigh-in is defined by those two fields, and the exporter emits one row per
    Health Connect record, so a body-fat record with no matching weight record
    can legitimately appear.

    Parameters
    ----------
    csv_text : str
        Raw CSV body from the published sheet.

    Returns
    -------
    list of dict
        Rows ready to upsert into ``body_composition``, oldest first. Empty
        when the sheet has no usable rows or is missing a required column.
    """
    frame = pd.read_csv(io.StringIO(csv_text))
    if frame.empty:
        return []

    mapping = _map_columns(list(frame.columns))
    unmatched = [c for c in frame.columns if c not in mapping]
    if unmatched:
        logger.info("Relay sheet columns not recognised, ignored: %s", unmatched)

    missing = {"measured_at_local", "weight_kg"} - set(mapping.values())
    if missing:
        logger.error(
            "Relay sheet is missing required column(s) %s; headers were %s",
            sorted(missing),
            list(frame.columns),
        )
        return []

    frame = frame.rename(columns=mapping)[list(mapping.values())]

    frame["measured_at_local"] = _to_wall_clock(frame["measured_at_local"])
    for column in _NUMERIC_COLUMNS:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    for column in _MASS_COLUMNS:
        if column in frame:
            frame[column] = _to_kg(frame[column])
    if "body_fat_pct" in frame:
        frame["body_fat_pct"] = _to_percent(frame["body_fat_pct"])

    frame = frame.dropna(subset=["measured_at_local", "weight_kg"])
    # The sheet grows by append and an exporter re-run can repeat a record; the
    # last spelling of a given instant wins.
    frame = frame.drop_duplicates(subset=["measured_at_local"], keep="last")
    frame = frame.sort_values("measured_at_local")

    rows: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        row: dict[str, Any] = {
            "measured_at_local": record["measured_at_local"].isoformat(),
            "weight_kg": float(record["weight_kg"]),
        }
        for column in _NUMERIC_COLUMNS[1:]:
            value = record.get(column)
            row[column] = None if value is None or pd.isna(value) else float(value)
        source = record.get("source")
        row["source"] = None if source is None or pd.isna(source) else str(source)
        rows.append(row)
    return rows


def ingest(supabase: Client, sheet_url: str | None = None) -> None:
    """Fetch the relay sheet and upsert every weigh-in into Supabase.

    A missing ``BODY_SHEET_CSV_URL`` is not an error: the rest of the pipeline
    predates this feed and has to keep running before the sheet is wired up.

    Parameters
    ----------
    supabase : supabase.Client
        Authenticated Supabase client.
    sheet_url : str or None, optional
        Published-CSV URL of the relay sheet. Defaults to the
        ``BODY_SHEET_CSV_URL`` environment variable.
    """
    url = sheet_url or os.environ.get(_SHEET_URL_ENV)
    if not url:
        logger.info("%s not set; skipping body-composition ingestion", _SHEET_URL_ENV)
        return

    try:
        response = requests.get(url, timeout=_REQUEST_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Could not fetch the body-composition sheet: %s", exc)
        return

    try:
        rows = parse_sheet(response.text)
    except (ValueError, pd.errors.ParserError) as exc:
        logger.error("Could not parse the body-composition sheet: %s", exc)
        return

    if not rows:
        logger.info("No body-composition rows found in the relay sheet")
        return

    supabase.table("body_composition").upsert(
        rows, on_conflict="measured_at_local"
    ).execute()
    with_fat = sum(1 for r in rows if r.get("body_fat_pct") is not None)
    logger.info(
        "Body composition ingestion complete: %d weigh-ins (%d with body fat), "
        "%s to %s",
        len(rows),
        with_fat,
        rows[0]["measured_at_local"],
        rows[-1]["measured_at_local"],
    )
