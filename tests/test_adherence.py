"""Tests for planned-versus-done session matching.

The cases are the ones that exposed the old date-only rule: a hike on an
easy-run day (2026-09-18) read as the run being done, and a gym-plus-run double
counted as complete when either half happened.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from dashboard import adherence as ad

_TODAY = date(2026, 9, 22)


def _activities(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    """Activities from ``(start_time_local, activity_type, distance_m)``."""
    return pd.DataFrame(
        [
            {"start_time_local": t, "activity_type": kind, "distance_m": dist}
            for t, kind, dist in rows
        ]
    )


def _session(
    day: str,
    session_type: str = "run",
    distance_m: int | None = 7000,
    kinds: tuple[str, ...] = ("run",),
    intensity: str = "easy",
    title: str = "Easy Aerobic",
    week_start: str = "2026-09-14",
) -> dict:
    return {
        "week_start": week_start,
        "session_date": day,
        "session_type": session_type,
        "title": title,
        "intensity": intensity,
        "prescription": {
            "distance_m": distance_m,
            "steps": [{"kind": k} for k in kinds],
        },
    }


class TestSessionNeeds:
    def test_a_gym_plus_run_double_needs_both_parts(self) -> None:
        needs = ad.session_needs(
            "run", {"distance_m": 9000, "steps": [{"kind": "strength"}, {"kind": "run"}]}
        )
        assert needs == ad.SessionNeeds(run_km=9.0, gym=True, station=False)

    def test_a_sim_needs_stations_even_without_station_steps(self) -> None:
        needs = ad.session_needs("sim", {"distance_m": 8000, "steps": [{"kind": "run"}]})
        assert needs.station

    def test_a_legacy_row_reads_its_gym_half_from_the_title(self) -> None:
        """Rows persisted before structured steps are a bare ``run`` type."""
        needs = ad.session_needs(
            "run", {"distance_m": 8000, "steps": []},
            "Upper Maintenance (AM) + Easy Aerobic (PM)",
        )
        assert needs.gym

    def test_the_description_names_every_part_asked_for(self) -> None:
        """A gym session with stations must not read as gym only in the tooltip."""
        needs = ad.SessionNeeds(run_km=8.0, gym=True, station=True)
        assert needs.describe() == "8.0 km + gym + stations"

    def test_the_title_fallback_matches_whole_words_only(self) -> None:
        needs = ad.session_needs("run", {"distance_m": 8000}, "Slower Long Run")
        assert not needs.gym


class TestDayActuals:
    def test_simulation_distance_counts_as_run_km(self) -> None:
        actuals = ad.day_actuals(_activities([
            ("2026-09-10T06:18:42", "multi_sport", 7698.3),
        ]))
        day = actuals[date(2026, 9, 10)]
        assert day.run_km == pytest.approx(7.70, abs=0.01)
        assert day.station

    def test_an_unmatched_activity_is_described_not_counted(self) -> None:
        actuals = ad.day_actuals(_activities([
            ("2026-09-18T10:32:59", "hiking", 5781.5),
        ]))
        day = actuals[date(2026, 9, 18)]
        assert day.run_km == 0
        assert day.other == ("hike 5.8 km",)


class TestScoreSessions:
    def _score(self, sessions: list[dict], activities: pd.DataFrame) -> pd.DataFrame:
        return ad.score_sessions(pd.DataFrame(sessions), activities, _TODAY)

    def test_a_hike_on_an_easy_run_day_is_swapped_not_done(self) -> None:
        scored = self._score(
            [_session("2026-09-18")],
            _activities([("2026-09-18T10:32:59", "hiking", 5781.5)]),
        )
        assert scored.loc[0, "status"] == "swapped"
        assert scored.loc[0, "status_detail"] == "planned 7.0 km · did hike 5.8 km"

    def test_a_day_with_nothing_recorded_is_missed(self) -> None:
        scored = self._score([_session("2026-09-17")], _activities([]))
        assert scored.loc[0, "status"] == "missed"

    def test_the_gym_without_the_run_is_partial(self) -> None:
        scored = self._score(
            [_session("2026-09-21", distance_m=9000, kinds=("strength", "run"))],
            _activities([("2026-09-21T05:56:57", "strength_training", 0.0)]),
        )
        assert scored.loc[0, "status"] == "partial"

    def test_both_halves_of_a_double_are_done(self) -> None:
        scored = self._score(
            [_session("2026-09-21", distance_m=9000, kinds=("strength", "run"))],
            _activities([
                ("2026-09-21T05:56:57", "strength_training", 0.0),
                ("2026-09-21T06:54:46", "running", 8183.4),
            ]),
        )
        assert scored.loc[0, "status"] == "done"

    def test_a_run_cut_below_the_threshold_share_is_partial(self) -> None:
        scored = self._score(
            [_session("2026-09-16", distance_m=10000)],
            _activities([("2026-09-16T17:58:33", "running", 8000.0)]),
        )
        assert scored.loc[0, "status"] == "partial"

    def test_a_future_session_is_upcoming(self) -> None:
        scored = self._score([_session("2026-09-24")], _activities([]))
        assert scored.loc[0, "status"] == "upcoming"

    def test_today_with_nothing_yet_is_upcoming_not_missed(self) -> None:
        """A morning build must not call the evening run missed."""
        scored = self._score([_session("2026-09-22")], _activities([]))
        assert scored.loc[0, "status"] == "upcoming"

    def test_skipped_active_recovery_is_never_missed(self) -> None:
        scored = self._score(
            [_session("2026-09-20", session_type="cross", distance_m=None, kinds=("note",))],
            _activities([]),
        )
        assert scored.loc[0, "status"] == "rest"

    def test_key_sessions_are_hard_work_and_long_runs(self) -> None:
        scored = self._score(
            [
                _session("2026-09-15", intensity="hard", distance_m=12000),
                _session("2026-09-19", distance_m=15000),
                _session("2026-09-16", distance_m=9000),
            ],
            _activities([]),
        )
        assert scored["is_key"].tolist() == [True, True, False]


class TestWeeklyAdherence:
    def test_the_current_week_counts_only_sessions_already_due(self) -> None:
        sessions = pd.DataFrame([
            _session("2026-09-21", distance_m=9000, week_start="2026-09-21"),
            _session("2026-09-22", distance_m=12000, intensity="hard", week_start="2026-09-21"),
            _session("2026-09-23", distance_m=10000, week_start="2026-09-21"),
        ])
        activities = _activities([
            ("2026-09-21T06:54:46", "running", 8183.4),
            ("2026-09-22T06:28:57", "running", 11505.2),
        ])
        scored = ad.score_sessions(sessions, activities, _TODAY)
        (week,) = ad.weekly_adherence(scored, activities, _TODAY)
        assert week.is_current
        assert week.planned_km == 21.0
        assert week.done_km == pytest.approx(19.7, abs=0.05)
        assert (week.key_done, week.key_planned) == (1, 1)

    def test_unplanned_runs_still_count_toward_done_km(self) -> None:
        sessions = pd.DataFrame([_session("2026-09-14", distance_m=8000)])
        activities = _activities([
            ("2026-09-14T17:23:27", "running", 8000.0),
            ("2026-09-20T09:00:00", "running", 5000.0),
        ])
        scored = ad.score_sessions(sessions, activities, _TODAY)
        (week,) = ad.weekly_adherence(scored, activities, _TODAY)
        assert week.done_km == 13.0

    def test_each_undone_session_is_listed_with_its_reason(self) -> None:
        sessions = pd.DataFrame([
            _session("2026-09-17", title="Technical Stations"),
            _session("2026-09-18"),
        ])
        activities = _activities([("2026-09-18T10:32:59", "hiking", 5781.5)])
        scored = ad.score_sessions(sessions, activities, _TODAY)
        (week,) = ad.weekly_adherence(scored, activities, _TODAY)
        assert week.misses == (
            "Thu 17 Sep · Technical Stations — planned 7.0 km · did nothing (missed)",
            "Fri 18 Sep · Easy Aerobic — planned 7.0 km · did hike 5.8 km (swapped)",
        )

    def test_nothing_planned_means_no_weeks(self) -> None:
        assert ad.weekly_adherence(pd.DataFrame(), _activities([]), _TODAY) == []
