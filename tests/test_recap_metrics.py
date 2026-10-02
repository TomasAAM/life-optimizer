"""Tests for the monthly recap model.

The recap restates numbers the other tabs already show, so the risk is not a
crash but a quiet disagreement: a month in progress compared with a whole
month, a multisport session counted as running, a guessed lift named, or a
first-ever entry announced as a personal record. Each of those would still
produce a plausible story card, which is why they are pinned here.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from dashboard import activity_metrics as am
from dashboard import adherence as ad
from dashboard import body_metrics as bm
from dashboard import metrics
from dashboard import recap_metrics as rm
from dashboard import strength_metrics as sm
from plan.config import Race

from tests.test_activity_metrics import _activity, _zones

_TODAY = date(2026, 10, 2)


def _frame(rows: list[dict]) -> pd.DataFrame:
    """Activities with sequential ids, as the strength join needs them."""
    return pd.DataFrame([{**row, "activity_id": i} for i, row in enumerate(rows, start=1)])


def _session(day: str, km: float | None = 8.0, kinds: tuple[str, ...] = ("run",),
             intensity: str = "easy", title: str = "Easy", session_type: str = "run") -> dict:
    return {
        "week_start": day,
        "session_date": day,
        "session_type": session_type,
        "title": title,
        "intensity": intensity,
        "prescription": {
            "distance_m": None if km is None else km * 1000,
            "steps": [{"kind": k} for k in kinds],
        },
    }


def _recap(
    month: date,
    activities: pd.DataFrame,
    planned: list[dict] | None = None,
    sets: pd.DataFrame | None = None,
    weigh_ins: pd.DataFrame | None = None,
    hrv: pd.DataFrame | None = None,
    races: tuple[Race, ...] = (),
    today: date = _TODAY,
) -> rm.MonthRecap:
    planned_frame = pd.DataFrame(planned or [])
    scored = ad.score_sessions(planned_frame, activities, today)
    return rm.build_month_recap(
        month, today, activities, am.prepare_runs(activities), _zones(), scored,
        sets if sets is not None else pd.DataFrame(columns=["day", "settled"]),
        weigh_ins if weigh_ins is not None else bm.prepare_weigh_ins(pd.DataFrame()),
        hrv if hrv is not None else metrics.build_hrv_series(pd.DataFrame()),
        races,
    )


class TestMonthArithmetic:
    def test_a_finished_month_compares_with_the_whole_previous_month(self) -> None:
        assert rm.comparison_window(date(2026, 9, 1), date(2026, 9, 30)) == (
            date(2026, 8, 1), date(2026, 8, 31))

    def test_a_month_in_progress_compares_with_the_same_elapsed_days(self) -> None:
        assert rm.comparison_window(date(2026, 10, 1), date(2026, 10, 2)) == (
            date(2026, 9, 1), date(2026, 9, 2))

    def test_the_elapsed_span_clamps_to_a_shorter_previous_month(self) -> None:
        assert rm.comparison_window(date(2026, 3, 1), date(2026, 3, 30)) == (
            date(2026, 2, 1), date(2026, 2, 28))

    def test_months_run_newest_first_from_the_first_activity(self) -> None:
        activities = _frame([_activity("2026-07-20"), _activity("2026-09-03")])
        assert rm.available_months(activities, _TODAY) == [
            date(2026, 10, 1), date(2026, 9, 1), date(2026, 8, 1), date(2026, 7, 1)]

    def test_no_activities_means_no_months(self) -> None:
        assert rm.available_months(pd.DataFrame(), _TODAY) == []


class TestHeadlineAndCalendar:
    @pytest.fixture(name="recap")
    def _september(self) -> rm.MonthRecap:
        activities = _frame([
            _activity("2026-09-01", km=10.0),
            _activity("2026-09-01", activity_type="strength_training", km=0.0, minutes=60),
            _activity("2026-09-02", km=12.0),
            _activity("2026-09-03", activity_type="multi_sport", km=8.0),
            _activity("2026-09-10", activity_type="hiking", km=6.0),
            _activity("2026-08-05", km=10.0),
        ])
        return _recap(date(2026, 9, 1), activities)

    def test_active_days_count_days_not_activities(self, recap: rm.MonthRecap) -> None:
        assert recap.active_days == 4
        assert recap.sessions == 5

    def test_the_calendar_has_one_mark_per_day_of_the_month(self, recap: rm.MonthRecap) -> None:
        assert len(recap.calendar) == 30
        first = recap.calendar[0]
        assert first.kinds == (rm.KIND_RUN, rm.KIND_GYM)
        assert first.run_km == pytest.approx(10.0)

    def test_multisport_is_hyrox_on_the_calendar_and_not_running_km(
        self, recap: rm.MonthRecap
    ) -> None:
        assert recap.calendar[2].kinds == (rm.KIND_HYROX,)
        assert recap.calendar[2].run_km == 0.0
        assert recap.running.km == pytest.approx(22.0)

    def test_unknown_activity_types_are_other(self, recap: rm.MonthRecap) -> None:
        assert recap.calendar[9].kinds == (rm.KIND_OTHER,)
        assert recap.calendar[9].others == ("Hike 6",)

    def test_sessions_are_counted_by_kind(self, recap: rm.MonthRecap) -> None:
        assert recap.kind_counts == {"run": 2, "gym": 1, "hyrox": 1, "other": 1}

    def test_the_streak_counts_consecutive_active_days(self, recap: rm.MonthRecap) -> None:
        assert recap.longest_streak == 3

    def test_running_compares_with_the_previous_month(self, recap: rm.MonthRecap) -> None:
        assert recap.running.prev_km == pytest.approx(10.0)


class TestRunning:
    def test_an_implausible_pace_is_excluded_and_counted(self) -> None:
        activities = _frame([
            _activity("2026-09-05", km=10.0),
            _activity("2026-09-06", km=13.7, minutes=19.5),
        ])
        running = _recap(date(2026, 9, 1), activities).running
        assert running.km == pytest.approx(10.0)
        assert running.excluded_runs == 1

    def test_surface_split_and_longest_run(self) -> None:
        activities = _frame([
            _activity("2026-09-05", km=18.0, name="Long"),
            _activity("2026-09-06", activity_type="treadmill_running", km=8.0),
        ])
        running = _recap(date(2026, 9, 1), activities).running
        assert (running.outdoor_km, running.treadmill_km) == (18.0, 8.0)
        assert running.longest_km == 18.0
        assert running.longest_label.startswith("Long")

    def test_week_bars_are_clipped_to_the_days_of_the_month(self) -> None:
        activities = _frame([
            _activity("2026-08-31", km=10.0),
            _activity("2026-09-01", km=7.0),
            _activity("2026-09-30", km=5.0),
        ])
        weeks = _recap(date(2026, 9, 1), activities).running.weeks
        assert weeks[0].week_start == date(2026, 8, 31)
        assert (weeks[0].first_day, weeks[0].last_day) == (date(2026, 9, 1), date(2026, 9, 6))
        assert weeks[0].km == pytest.approx(7.0)
        assert (weeks[-1].first_day, weeks[-1].last_day) == (date(2026, 9, 28), date(2026, 9, 30))

    def test_bands_split_km_by_average_hr(self) -> None:
        activities = _frame([
            _activity("2026-09-05", km=10.0, avg_hr=135.0),
            _activity("2026-09-06", km=6.0, avg_hr=150.0),
            _activity("2026-09-07", km=4.0, avg_hr=170.0),
        ])
        bands = _recap(date(2026, 9, 1), activities).running.band_km
        assert bands == {"Easy": 10.0, "Tempo": 6.0, "Threshold+": 4.0}

    def test_easy_pace_ignores_the_treadmill(self) -> None:
        activities = _frame([
            _activity("2026-09-05", km=10.0, minutes=60, avg_hr=135.0),
            _activity("2026-09-06", activity_type="treadmill_running", km=10.0,
                      minutes=45, avg_hr=135.0),
        ])
        assert _recap(date(2026, 9, 1), activities).running.easy_pace_s == pytest.approx(360.0)


class TestPlan:
    def test_no_plan_means_no_plan_card(self) -> None:
        assert _recap(date(2026, 9, 1), _frame([_activity("2026-09-05")])).plan is None

    def test_sessions_are_scored_part_by_part(self) -> None:
        activities = _frame([
            _activity("2026-09-01", km=8.0),
            _activity("2026-09-02", km=3.0),
            _activity("2026-09-03", activity_type="hiking", km=5.0),
        ])
        planned = [
            _session("2026-09-01"),
            _session("2026-09-02"),
            _session("2026-09-03"),
            _session("2026-09-04", km=16.0, title="Long"),
            _session("2026-09-05", km=None, kinds=(), session_type="rest", title="Rest"),
        ]
        plan = _recap(date(2026, 9, 1), activities, planned).plan
        assert plan.status_counts == {"done": 1, "partial": 1, "swapped": 1, "missed": 1}
        assert plan.sessions_due == 4
        assert (plan.key_planned, plan.key_done) == (1, 0)
        assert plan.planned_km == pytest.approx(40.0)
        assert plan.done_km == pytest.approx(11.0)

    def test_sessions_still_to_come_are_not_due(self) -> None:
        planned = [_session("2026-10-01"), _session("2026-10-05")]
        plan = _recap(date(2026, 10, 1), _frame([_activity("2026-10-01")]), planned).plan
        assert plan.sessions_due == 1


class TestStrength:
    @staticmethod
    def _sets(activities: pd.DataFrame, rows: list[dict]) -> pd.DataFrame:
        defaults = {"set_type": "ACTIVE", "duration_s": 40.0, "reps": 3,
                    "category": "DEADLIFT", "exercise_name": "BARBELL_DEADLIFT",
                    "probability_pct": 100.0}
        raw = pd.DataFrame([{**defaults, "set_index": i, **row} for i, row in enumerate(rows)])
        return sm.prepare_sets(raw, activities)

    def test_no_strength_session_means_no_card(self) -> None:
        assert _recap(date(2026, 9, 1), _frame([_activity("2026-09-05")])).strength is None

    def test_a_heavier_set_than_any_earlier_month_is_a_pr(self) -> None:
        activities = _frame([
            _activity("2026-08-05", activity_type="strength_training", km=0.0, minutes=50),
            _activity("2026-09-05", activity_type="strength_training", km=0.0, minutes=55),
        ])
        sets = self._sets(activities, [
            {"activity_id": 1, "weight_kg": 130.0},
            {"activity_id": 2, "weight_kg": 140.0},
        ])
        strength = _recap(date(2026, 9, 1), activities, sets=sets).strength
        assert strength.lifts[0].weight_kg == 140.0
        assert strength.lifts[0].is_pr
        assert strength.hours == pytest.approx(55 / 60, abs=0.05)

    def test_a_first_ever_entry_is_not_a_pr(self) -> None:
        activities = _frame([
            _activity("2026-09-05", activity_type="strength_training", km=0.0),
        ])
        sets = self._sets(activities, [{"activity_id": 1, "weight_kg": 140.0}])
        assert not _recap(date(2026, 9, 1), activities, sets=sets).strength.lifts[0].is_pr

    def test_a_guessed_set_counts_as_work_but_is_never_named(self) -> None:
        activities = _frame([
            _activity("2026-09-05", activity_type="strength_training", km=0.0),
        ])
        sets = self._sets(activities, [
            {"activity_id": 1, "weight_kg": 120.0, "probability_pct": 45.3,
             "category": "SHRUG", "exercise_name": None},
        ])
        strength = _recap(date(2026, 9, 1), activities, sets=sets).strength
        assert strength.lifts == ()
        assert (strength.working_sets, strength.settled_sets) == (1, 0)
        assert strength.tonnage_kg == 360


class TestBodyAndRaces:
    def test_the_weight_trend_starts_from_before_the_month(self) -> None:
        weigh_ins = bm.prepare_weigh_ins(pd.DataFrame([
            {"measured_at_local": "2026-08-30T07:00:00", "weight_kg": 82.0},
            {"measured_at_local": "2026-09-15T07:00:00", "weight_kg": 84.0},
        ]))
        body = _recap(date(2026, 9, 1), _frame([_activity("2026-09-05")]),
                      weigh_ins=weigh_ins).body
        assert body.weigh_ins == 1
        assert body.trend_start_kg == 82.0
        assert body.trend_end_kg == 84.0

    def test_hrv_is_averaged_over_the_month_and_the_comparison_span(self) -> None:
        hrv = metrics.build_hrv_series(pd.DataFrame([
            {"date": "2026-08-10", "hrv_avg_night": 50, "hrv_weekly_avg": 50,
             "hrv_baseline_low": 40, "hrv_baseline_high": 60, "hrv_status": "BALANCED"},
            {"date": "2026-09-10", "hrv_avg_night": 44, "hrv_weekly_avg": 45,
             "hrv_baseline_low": 41, "hrv_baseline_high": 62, "hrv_status": "BALANCED"},
            {"date": "2026-09-11", "hrv_avg_night": 46, "hrv_weekly_avg": 45,
             "hrv_baseline_low": 42, "hrv_baseline_high": 63, "hrv_status": "BALANCED"},
        ]))
        body = _recap(date(2026, 9, 1), _frame([_activity("2026-09-05")]), hrv=hrv).body
        assert (body.hrv_avg, body.prev_hrv_avg, body.hrv_nights) == (45.0, 50.0, 2)
        assert (body.baseline_low, body.baseline_high) == (42.0, 63.0)

    def test_races_inside_and_after_the_month(self) -> None:
        races = (Race("hyrox", date(2026, 8, 2)), Race("hyrox", date(2026, 12, 13)))
        recap = _recap(date(2026, 8, 1), _frame([_activity("2026-08-05")]), races=races)
        assert recap.races.raced == (races[0],)
        assert recap.races.next_race == races[1]
        assert recap.races.days_to_next == (date(2026, 12, 13) - date(2026, 8, 31)).days

    def test_a_month_in_progress_counts_down_from_the_build_date(self) -> None:
        races = (Race("hyrox", date(2026, 12, 13)),)
        recap = _recap(date(2026, 10, 1), _frame([_activity("2026-10-01")]), races=races)
        assert recap.in_progress
        assert recap.races.days_to_next == 72


class TestTakeaways:
    def test_lines_come_from_the_cards(self) -> None:
        activities = _frame([
            _activity("2026-08-05", km=10.0),
            _activity("2026-09-05", km=12.0, avg_hr=135.0),
        ])
        planned = [_session("2026-09-05", km=12.0, intensity="hard", title="Threshold")]
        lines = _recap(date(2026, 9, 1), activities, planned).takeaways
        assert lines[0] == "Running km up 20% on August (10 → 12 km)."
        assert lines[1] == "1 of 1 key sessions done, 100% of planned km."

    def test_no_baseline_means_no_percentage(self) -> None:
        lines = _recap(date(2026, 9, 1), _frame([_activity("2026-09-05")])).takeaways
        assert lines[0] == "10 km run across 1 runs."
        assert all("%" not in line or "easy heart rate" in line for line in lines)
