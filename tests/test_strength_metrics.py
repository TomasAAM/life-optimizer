"""Tests for the strength aggregations.

The rules pinned here are the ones that decide whether a number on the page is
training history or an artefact of how Garmin records it: a guessed exercise
label must never be charted as a lift, the top set is what progression is read
off, unattributed work still counts toward totals, and the load era starts
where the loads do rather than where the log does.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from dashboard import strength_metrics as sm
from plan import config

_TODAY = date(2026, 9, 9)


def _activities(rows: list[tuple[int, str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "activity_id": aid,
                "start_time_local": stamp,
                "activity_type": kind,
                "activity_name": "Fuerza",
            }
            for aid, stamp, kind in rows
        ]
    )


def _sets(rows: list[dict]) -> pd.DataFrame:
    """Build raw ``garmin_exercise_sets`` rows, defaulted to settled ACTIVE."""
    defaults = {
        "set_type": "ACTIVE",
        "start_time": "2026-09-08T10:31:10+00:00",
        "duration_s": 40.0,
        "reps": 3,
        "weight_kg": 100.0,
        "category": "SQUAT",
        "exercise_name": "BARBELL_SIFF_SQUAT",
        "probability_pct": 100.0,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


@pytest.fixture(name="activities")
def _activities_fixture() -> pd.DataFrame:
    return _activities(
        [
            (1, "2026-07-01T06:30:00", "strength_training"),
            (2, "2026-08-04T06:30:00", "strength_training"),
            (3, "2026-09-08T07:31:10", "strength_training"),
        ]
    )


class TestLabelling:
    """A name is only ever as specific as Garmin actually got."""

    def test_the_specific_lift_wins(self) -> None:
        assert sm.exercise_label("SQUAT", "BARBELL_SIFF_SQUAT") == "Barbell siff squat"

    def test_the_category_stands_alone_when_that_is_all_there_is(self) -> None:
        assert sm.exercise_label("SHOULDER_PRESS", "") == "Shoulder press"

    def test_unknown_is_named_as_unidentified_not_as_a_lift(self) -> None:
        assert sm.exercise_label("UNKNOWN", None) == "Unidentified"

    def test_an_unmapped_category_falls_to_other_rather_than_vanishing(self) -> None:
        assert sm.movement_pattern("OLYMPIC_LIFT") == sm.OTHER_PATTERN
        assert sm.movement_pattern(None) == sm.OTHER_PATTERN

    def test_known_categories_map_to_their_pattern(self) -> None:
        assert sm.movement_pattern("DEADLIFT") == "Hinge"
        assert sm.movement_pattern("LUNGE") == "Squat"


class TestPrepareSets:
    """Rests are dropped, the session date is joined on, settled is decided."""

    def test_rest_sets_are_excluded_from_the_working_frame(
        self, activities: pd.DataFrame
    ) -> None:
        raw = _sets([{"activity_id": 3, "set_index": 0},
                     {"activity_id": 3, "set_index": 1, "set_type": "REST"}])
        prepared = sm.prepare_sets(raw, activities)
        assert len(prepared) == 1

    def test_the_session_date_is_the_local_wall_clock(
        self, activities: pd.DataFrame
    ) -> None:
        """A UTC date would push a 07:31 Santiago session onto the wrong day."""
        prepared = sm.prepare_sets(_sets([{"activity_id": 3, "set_index": 0}]), activities)
        assert prepared["day"].iloc[0] == date(2026, 9, 8)

    def test_only_an_exact_hundred_counts_as_settled(
        self, activities: pd.DataFrame
    ) -> None:
        """Garmin reports 99.6 on sets it flatly failed to identify, so any
        threshold below 100 would promote the clearest non-answers in the log."""
        raw = _sets([
            {"activity_id": 3, "set_index": 0, "probability_pct": 100.0},
            {"activity_id": 3, "set_index": 1, "probability_pct": 99.609375},
            {"activity_id": 3, "set_index": 2, "probability_pct": 45.3},
        ])
        assert list(sm.prepare_sets(raw, activities)["settled"]) == [True, False, False]

    def test_a_set_whose_activity_is_unknown_is_dropped(
        self, activities: pd.DataFrame
    ) -> None:
        raw = _sets([{"activity_id": 999, "set_index": 0}])
        assert sm.prepare_sets(raw, activities).empty

    def test_empty_in_empty_out(self, activities: pd.DataFrame) -> None:
        assert sm.prepare_sets(pd.DataFrame(), activities).empty


class TestTopSets:
    """Progression is the heaviest set of the session, from settled sets only."""

    def test_the_heaviest_set_of_the_day_wins(self, activities: pd.DataFrame) -> None:
        """Not the mean: a heavy triple plus two back-offs is a heavier session
        than three sets at the back-off weight, and an average says otherwise."""
        raw = _sets([
            {"activity_id": 3, "set_index": 0, "weight_kg": 70.0, "reps": 5},
            {"activity_id": 3, "set_index": 1, "weight_kg": 100.0, "reps": 3},
            {"activity_id": 3, "set_index": 2, "weight_kg": 90.0, "reps": 3},
        ])
        top = sm.top_sets(sm.prepare_sets(raw, activities))
        assert len(top) == 1
        assert top["weight_kg"].iloc[0] == 100.0
        assert top["reps"].iloc[0] == 3
        assert top["sets"].iloc[0] == 3

    def test_a_guessed_set_never_becomes_a_lift(self, activities: pd.DataFrame) -> None:
        """A 120 kg "shrug" at 45% is a compound lift wearing a label the watch
        picked from a shortlist -- charted, it invents a personal best."""
        raw = _sets([
            {"activity_id": 3, "set_index": 0, "category": "SHRUG",
             "exercise_name": None, "weight_kg": 120.0, "probability_pct": 45.3},
        ])
        assert sm.top_sets(sm.prepare_sets(raw, activities)).empty

    def test_unidentified_work_is_never_charted(self, activities: pd.DataFrame) -> None:
        raw = _sets([
            {"activity_id": 3, "set_index": 0, "category": "UNKNOWN",
             "exercise_name": None, "weight_kg": 130.0, "probability_pct": 100.0},
        ])
        assert sm.top_sets(sm.prepare_sets(raw, activities)).empty

    def test_a_bodyweight_set_carries_no_top_set(self, activities: pd.DataFrame) -> None:
        raw = _sets([{"activity_id": 3, "set_index": 0, "weight_kg": None}])
        assert sm.top_sets(sm.prepare_sets(raw, activities)).empty

    def test_a_lift_needs_three_days_before_it_earns_a_line(
        self, activities: pd.DataFrame
    ) -> None:
        two_days = _sets([
            {"activity_id": 1, "set_index": 0},
            {"activity_id": 2, "set_index": 0},
        ])
        assert sm.trending_lifts(sm.top_sets(sm.prepare_sets(two_days, activities))) == []

        three_days = _sets([
            {"activity_id": 1, "set_index": 0},
            {"activity_id": 2, "set_index": 0},
            {"activity_id": 3, "set_index": 0},
        ])
        assert sm.trending_lifts(
            sm.top_sets(sm.prepare_sets(three_days, activities))
        ) == ["Barbell siff squat"]


class TestWeightEra:
    """The load charts start where the loads do, not where the log does."""

    def test_the_first_weighted_day_is_found_not_assumed(
        self, activities: pd.DataFrame
    ) -> None:
        raw = _sets([
            {"activity_id": 1, "set_index": 0, "weight_kg": None},
            {"activity_id": 2, "set_index": 0, "weight_kg": 100.0},
        ])
        assert sm.first_weighted_day(sm.prepare_sets(raw, activities)) == date(2026, 8, 4)

    def test_a_log_with_no_loads_has_no_era(self, activities: pd.DataFrame) -> None:
        raw = _sets([{"activity_id": 1, "set_index": 0, "weight_kg": None}])
        assert sm.first_weighted_day(sm.prepare_sets(raw, activities)) is None


class TestWeeklyVolume:
    """Tonnage and set counts, grouped the way a programme is balanced."""

    @pytest.fixture(name="exercises")
    def _exercises(self, activities: pd.DataFrame) -> pd.DataFrame:
        raw = pd.DataFrame([
            {"activity_id": 1, "category": "SQUAT", "sub_category": "",
             "sets": 4, "reps": 12, "volume_kg": 1200.0, "max_weight_kg": 100.0,
             "active_duration_s": 200.0},
            {"activity_id": 3, "category": "DEADLIFT", "sub_category": "BARBELL_DEADLIFT",
             "sets": 4, "reps": 12, "volume_kg": 1470.0, "max_weight_kg": 130.0,
             "active_duration_s": 120.0},
            {"activity_id": 3, "category": "UNKNOWN", "sub_category": "",
             "sets": 3, "reps": 20, "volume_kg": 600.0, "max_weight_kg": 30.0,
             "active_duration_s": 90.0},
        ])
        return sm.prepare_exercises(raw, activities)

    def test_weeks_start_on_monday(self, exercises: pd.DataFrame) -> None:
        weekly = sm.weekly_volume(exercises)
        assert all(w.weekday() == 0 for w in weekly["week_start"])

    def test_patterns_are_summed_separately(self, exercises: pd.DataFrame) -> None:
        weekly = sm.weekly_volume(exercises)
        hinge = weekly[weekly["pattern"] == "Hinge"]
        assert hinge["volume_kg"].iloc[0] == 1470.0

    def test_unattributed_work_is_counted_rather_than_dropped(
        self, exercises: pd.DataFrame
    ) -> None:
        """It was trained, so it belongs in the total; it is never named."""
        weekly = sm.weekly_volume(exercises)
        other = weekly[weekly["pattern"] == sm.OTHER_PATTERN]
        assert other["volume_kg"].iloc[0] == 600.0
        assert other["sets"].iloc[0] == 3

    def test_the_since_cutoff_drops_the_unweighted_era(
        self, exercises: pd.DataFrame
    ) -> None:
        weekly = sm.weekly_volume(exercises, since=date(2026, 8, 1))
        assert weekly["week_start"].min() >= date(2026, 8, 1)

    def test_empty_in_empty_out(self) -> None:
        assert sm.weekly_volume(pd.DataFrame()).empty


class TestLoadChecks:
    """The hand-maintained config against what was actually lifted."""

    def test_a_load_that_has_moved_past_the_config_is_flagged(
        self, activities: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pinned so the test does not move every time the live config is updated.
        monkeypatch.setitem(
            config.ATHLETE_LOADS, "trap_bar_deadlift", "130 kg for top triples @ RPE 8"
        )
        raw = _sets([
            {"activity_id": 3, "set_index": 0, "category": "DEADLIFT",
             "exercise_name": "BARBELL_DEADLIFT", "weight_kg": 140.0},
        ])
        checks = {c.lift: c for c in sm.load_checks(sm.prepare_sets(raw, activities), _TODAY)}
        deadlift = checks["trap_bar_deadlift"]
        assert deadlift.config_kg == 130.0
        assert deadlift.measured_kg == 140.0
        assert deadlift.gap_kg == 10.0
        assert deadlift.is_stale

    def test_a_matching_load_is_not_flagged(self, activities: pd.DataFrame) -> None:
        raw = _sets([{"activity_id": 3, "set_index": 0, "weight_kg": 100.0}])
        checks = {c.lift: c for c in sm.load_checks(sm.prepare_sets(raw, activities), _TODAY)}
        assert not checks["back_squat"].is_stale

    def test_a_guessed_set_never_settles_a_load_check(
        self, activities: pd.DataFrame
    ) -> None:
        raw = _sets([
            {"activity_id": 3, "set_index": 0, "category": "DEADLIFT",
             "weight_kg": 200.0, "probability_pct": 46.0},
        ])
        checks = {c.lift: c for c in sm.load_checks(sm.prepare_sets(raw, activities), _TODAY)}
        assert checks["trap_bar_deadlift"].measured_kg is None

    def test_a_lift_outside_the_window_does_not_count_as_current(
        self, activities: pd.DataFrame
    ) -> None:
        """Ninety days, so a check reports the working load rather than a best
        set from a block that has since ended."""
        old = _activities([(9, "2026-01-05T06:30:00", "strength_training")])
        raw = _sets([{"activity_id": 9, "set_index": 0, "weight_kg": 100.0}])
        checks = {c.lift: c for c in sm.load_checks(sm.prepare_sets(raw, old), _TODAY)}
        assert checks["back_squat"].measured_kg is None

    def test_only_the_unambiguous_total_load_lifts_are_checked(self) -> None:
        """Per-hand and bodyweight-plus prescriptions are excluded, because the
        figure in the string is not the load that was on the bar."""
        checked = set(sm.CONFIG_LIFT_CATEGORIES)
        assert "weighted_step_up" not in checked
        assert "dumbbell_bench_press" not in checked
        assert "pull_up" not in checked
        assert checked <= set(config.ATHLETE_LOADS)

    def test_empty_in_empty_out(self) -> None:
        assert sm.load_checks(pd.DataFrame(), _TODAY) == []


class TestSessionDetail:
    """One session, laid out as exercises and the sets behind them."""

    def test_identical_sets_collapse(self) -> None:
        frame = pd.DataFrame({"reps": [3, 3, 3], "weight_kg": [100.0] * 3})
        assert sm._format_sets(frame) == "3 x 3 @ 100 kg"

    def test_differing_sets_are_spelled_out(self) -> None:
        """A working-up sequence has to stay legible as one."""
        frame = pd.DataFrame({"reps": [5, 3, 3], "weight_kg": [70.0, 100.0, 100.0]})
        assert sm._format_sets(frame) == "5 @ 70 kg, 3 @ 100 kg, 3 @ 100 kg"

    def test_bodyweight_sets_show_reps_without_a_load(self) -> None:
        frame = pd.DataFrame({"reps": [12, 12], "weight_kg": [None, None]})
        assert sm._format_sets(frame) == "2 x 12"

    def test_a_session_marks_whether_its_sets_were_settled(
        self, activities: pd.DataFrame
    ) -> None:
        raw_ex = pd.DataFrame([
            {"activity_id": 3, "category": "SQUAT", "sub_category": "BARBELL_SIFF_SQUAT",
             "sets": 2, "reps": 6, "volume_kg": 600.0, "max_weight_kg": 100.0,
             "active_duration_s": 80.0},
        ])
        raw_sets = _sets([
            {"activity_id": 3, "set_index": 0},
            {"activity_id": 3, "set_index": 1, "probability_pct": 45.0},
        ])
        detail = sm.session_detail(
            sm.prepare_exercises(raw_ex, activities),
            sm.prepare_sets(raw_sets, activities),
            3,
        )
        assert not bool(detail["settled"].iloc[0])


class TestHeadline:
    """The header cards."""

    def test_an_empty_log_reports_zeros_rather_than_failing(self) -> None:
        headline = sm.headline(pd.DataFrame(), pd.DataFrame(), _TODAY)
        assert headline.sessions_28d == 0
        assert headline.heaviest_kg is None

    def test_the_heaviest_lift_is_named_with_its_date(
        self, activities: pd.DataFrame
    ) -> None:
        raw_ex = pd.DataFrame([
            {"activity_id": 3, "category": "DEADLIFT", "sub_category": "BARBELL_DEADLIFT",
             "sets": 1, "reps": 3, "volume_kg": 390.0, "max_weight_kg": 130.0,
             "active_duration_s": 30.0},
        ])
        raw_sets = _sets([
            {"activity_id": 3, "set_index": 0, "category": "DEADLIFT",
             "exercise_name": "BARBELL_DEADLIFT", "weight_kg": 130.0},
        ])
        headline = sm.headline(
            sm.prepare_exercises(raw_ex, activities),
            sm.prepare_sets(raw_sets, activities),
            _TODAY,
        )
        assert headline.heaviest_lift == "Barbell deadlift"
        assert headline.heaviest_kg == 130.0
        assert headline.heaviest_on == date(2026, 9, 8)
        assert headline.total_tonnage_kg == 390.0
