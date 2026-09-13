"""Typed ingestion outcomes and persistent source-health tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from supabase import Client

SourceStatus = Literal["success", "degraded", "failed", "skipped"]


@dataclass(frozen=True)
class SourceResult:
    """Outcome of one independently observable ingestion stage.

    Parameters
    ----------
    source : str
        Stable source identifier stored in ``ingestion_source_status``.
    status : SourceStatus
        Overall stage outcome.
    attempted : int
        Number of provider requests or source units attempted.
    succeeded : int
        Number of attempted units completed successfully.
    rows_written : int
        Number of database rows written during the stage.
    detail_code : str or None
        Fixed, non-sensitive machine-readable reason for degraded or failed runs.

    Examples
    --------
    >>> SourceResult.from_counts("garmin_activities", 1, 1, 3).status
    'success'
    """

    source: str
    status: SourceStatus
    attempted: int = 0
    succeeded: int = 0
    rows_written: int = 0
    detail_code: str | None = None

    @property
    def failed(self) -> int:
        """Return the number of attempted units that did not succeed.

        Returns
        -------
        int
            Non-negative failed-unit count.

        Examples
        --------
        >>> SourceResult("feed", "degraded", 3, 2).failed
        1
        """
        return max(self.attempted - self.succeeded, 0)

    @property
    def refreshed(self) -> bool:
        """Return whether this attempt produced a valid provider response.

        Returns
        -------
        bool
            Whether at least one unit completed in a non-failed attempt.

        Examples
        --------
        >>> SourceResult("feed", "success", 1, 1).refreshed
        True
        """
        return self.status in {"success", "degraded"} and self.succeeded > 0

    @classmethod
    def from_counts(
        cls,
        source: str,
        attempted: int,
        succeeded: int,
        rows_written: int,
        detail_code: str | None = None,
    ) -> "SourceResult":
        """Build a status from attempted and successful unit counts.

        Parameters
        ----------
        source : str
            Stable source identifier.
        attempted : int
            Number of source units attempted.
        succeeded : int
            Number of source units completed successfully.
        rows_written : int
            Number of rows written.
        detail_code : str or None, optional
            Safe reason code retained for non-success outcomes.

        Returns
        -------
        SourceResult
            Classified source result.

        Examples
        --------
        >>> SourceResult.from_counts("garmin_wellness", 5, 4, 12).status
        'degraded'
        """
        if attempted < 0 or succeeded < 0 or rows_written < 0:
            raise ValueError("Ingestion result counts cannot be negative.")
        if succeeded > attempted:
            raise ValueError("Successful units cannot exceed attempted units.")
        if attempted == 0:
            status: SourceStatus = "skipped"
        elif succeeded == 0:
            status = "failed"
        elif succeeded < attempted:
            status = "degraded"
        else:
            status = "success"
        return cls(
            source=source,
            status=status,
            attempted=attempted,
            succeeded=succeeded,
            rows_written=rows_written,
            detail_code=detail_code if status != "success" else None,
        )


def record_source_result(
    supabase: Client,
    result: SourceResult,
    attempted_at: datetime | None = None,
) -> None:
    """Persist one source outcome while retaining its prior success timestamp.

    Parameters
    ----------
    supabase : supabase.Client
        Authenticated backend client.
    result : SourceResult
        Stage outcome to persist.
    attempted_at : datetime or None, optional
        UTC attempt time. Defaults to the current UTC instant.

    Examples
    --------
    Persist a result after completing an ingestion stage::

        result = SourceResult.from_counts("garmin_activities", 1, 1, 12)
        record_source_result(supabase, result)
    """
    stamp = attempted_at or datetime.now(timezone.utc)
    row = {
        "source": result.source,
        "status": result.status,
        "last_attempt_at": stamp.isoformat(),
        "attempted": result.attempted,
        "succeeded": result.succeeded,
        "failed": result.failed,
        "rows_written": result.rows_written,
        "detail_code": result.detail_code,
        "updated_at": stamp.isoformat(),
    }
    if result.refreshed:
        row["last_success_at"] = stamp.isoformat()
    supabase.table("ingestion_source_status").upsert(
        row, on_conflict="source"
    ).execute()


def source_is_stale(
    supabase: Client,
    source: str,
    max_age: timedelta,
    now: datetime | None = None,
) -> bool:
    """Return whether a source lacks a sufficiently recent successful attempt.

    Parameters
    ----------
    supabase : supabase.Client
        Authenticated backend client.
    source : str
        Source identifier to inspect.
    max_age : datetime.timedelta
        Maximum permitted age of the last successful attempt.
    now : datetime or None, optional
        Reference UTC time, primarily for deterministic tests.

    Returns
    -------
    bool
        ``True`` when the source has no success timestamp or it is too old.

    Examples
    --------
    Check the deployment gate against a 36-hour threshold::

        stale = source_is_stale(supabase, "garmin_wellness", timedelta(hours=36))
    """
    response = (
        supabase.table("ingestion_source_status")
        .select("last_success_at")
        .eq("source", source)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows or not rows[0].get("last_success_at"):
        return True

    last_success = datetime.fromisoformat(
        str(rows[0]["last_success_at"]).replace("Z", "+00:00")
    )
    if last_success.tzinfo is None:
        last_success = last_success.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    return reference - last_success.astimezone(timezone.utc) > max_age
