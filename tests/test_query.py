"""Tests for the dashboard's plan-week selection.

``fetch_current_plan_week`` decides which week the dashboard shows, which is the
one piece of read logic with a date-dependent branch. The Supabase client is
stubbed with a minimal fake that applies the same filters PostgREST would, so
the selection rules are exercised without a network call.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from dashboard.query import fetch_current_plan_week

# 2026-07-27 is a Monday; 2026-08-02 the Sunday that ends that week.
_PEAK_WEEK = {"week_start": "2026-07-27", "phase": "peak"}
_BASE_WEEK = {"week_start": "2026-08-03", "phase": "base"}
_TWO_WEEKS = [_PEAK_WEEK, _BASE_WEEK]


class _FakeQuery:
    """Minimal stand-in for a PostgREST query builder."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def select(self, *_args: Any, **_kwargs: Any) -> "_FakeQuery":
        return self

    def eq(self, column: str, value: Any) -> "_FakeQuery":
        self._rows = [r for r in self._rows if r[column] == value]
        return self

    def lte(self, column: str, value: Any) -> "_FakeQuery":
        self._rows = [r for r in self._rows if r[column] <= value]
        return self

    def order(self, column: str, desc: bool = False) -> "_FakeQuery":
        self._rows = sorted(self._rows, key=lambda r: r[column], reverse=desc)
        return self

    def limit(self, count: int) -> "_FakeQuery":
        self._rows = self._rows[:count]
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=list(self._rows))


class _FakeClient:
    """Supabase client stub returning a fresh query over a fixed row set."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def table(self, _name: str) -> _FakeQuery:
        return _FakeQuery(list(self._rows))


def test_sunday_looks_ahead_to_next_week() -> None:
    """On the last day of a week, show the week that starts tomorrow."""
    week = fetch_current_plan_week(_FakeClient(_TWO_WEEKS), "2026-08-02")
    assert week is not None
    assert week["week_start"] == "2026-08-03"


def test_sunday_without_a_following_week_keeps_the_current_one() -> None:
    """The lookahead never leaves the dashboard empty."""
    week = fetch_current_plan_week(_FakeClient([_PEAK_WEEK]), "2026-08-02")
    assert week is not None
    assert week["week_start"] == "2026-07-27"


def test_midweek_returns_the_week_in_progress() -> None:
    """A Wednesday still resolves to the Monday that already started."""
    week = fetch_current_plan_week(_FakeClient(_TWO_WEEKS), "2026-07-29")
    assert week is not None
    assert week["week_start"] == "2026-07-27"


def test_monday_returns_the_week_starting_today() -> None:
    """The week's own Monday counts as in progress, not as lookahead."""
    week = fetch_current_plan_week(_FakeClient(_TWO_WEEKS), "2026-08-03")
    assert week is not None
    assert week["week_start"] == "2026-08-03"


def test_saturday_does_not_look_ahead() -> None:
    """Only Sunday triggers the lookahead; Saturday still has training left."""
    week = fetch_current_plan_week(_FakeClient(_TWO_WEEKS), "2026-08-01")
    assert week is not None
    assert week["week_start"] == "2026-07-27"


def test_falls_back_to_the_earliest_upcoming_week() -> None:
    """When the whole plan is still ahead, show its first week."""
    future = [{"week_start": "2026-09-07", "phase": "build"}]
    week = fetch_current_plan_week(_FakeClient(future), "2026-08-05")
    assert week is not None
    assert week["week_start"] == "2026-09-07"


def test_returns_none_when_no_plan_exists() -> None:
    """No plan at all degrades to None rather than raising."""
    assert fetch_current_plan_week(_FakeClient([]), "2026-08-02") is None
