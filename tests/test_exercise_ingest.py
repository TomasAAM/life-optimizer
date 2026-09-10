"""Tests for parsing Garmin's exercise payloads.

Every test here pins a defect that would otherwise land as plausible-looking
numbers rather than as an error: a 130 kg deadlift stored as 130000, a "no
weight" sentinel counted as a real load of -1 or 0, a whole session's sets
collapsed onto one row by a null key, or a Santiago morning stored as a UTC
morning.
"""

from __future__ import annotations

from ingest import exercise_sets as es
from ingest import garmin_activities as ga


def _active(**overrides) -> dict:
    """Build one ACTIVE set, defaulted to a settled 3 x 100 kg squat."""
    raw = {
        "setType": "ACTIVE",
        "startTime": "2026-09-08T10:31:10.0",
        "duration": 43.192,
        "repetitionCount": 3,
        "weight": 100000.0,
        "exercises": [
            {"category": "SQUAT", "name": "BARBELL_SIFF_SQUAT", "probability": 100.0}
        ],
    }
    raw.update(overrides)
    return raw


class TestWeightConversion:
    """Grams look like kilograms and both sentinels look like loads."""

    def test_grams_become_kilograms(self) -> None:
        assert ga.grams_to_kg(130000.0) == 130.0

    def test_the_minus_one_sentinel_becomes_null(self) -> None:
        """Garmin's marker for a set whose weight was never entered."""
        assert ga.grams_to_kg(-1.0) is None

    def test_the_zero_sentinel_becomes_null(self) -> None:
        """Garmin's marker for a bodyweight movement. Stored as 0 it would drag
        every mean load down while looking like a measurement."""
        assert ga.grams_to_kg(0.0) is None

    def test_a_missing_weight_becomes_null(self) -> None:
        assert ga.grams_to_kg(None) is None


class TestSetBearingDetection:
    """Which sessions have exercises is Garmin's answer, not an activity-type list."""

    def test_a_summarised_payload_marks_the_session(self) -> None:
        assert ga.has_exercise_sets({"summarizedExerciseSets": [{"category": "SQUAT"}]})

    def test_a_run_has_none(self) -> None:
        assert not ga.has_exercise_sets({"activityType": {"typeKey": "running"}})

    def test_an_empty_list_is_not_a_set_bearing_session(self) -> None:
        """An empty list must not cost a per-session API call."""
        assert not ga.has_exercise_sets({"summarizedExerciseSets": []})


class TestExerciseSummary:
    """The per-exercise row that rides along in the activity payload."""

    def test_volume_and_max_weight_convert(self) -> None:
        row = ga._parse_exercise(
            1,
            {
                "category": "SQUAT",
                "subCategory": "BARBELL_SIFF_SQUAT",
                "reps": 22,
                "sets": 6,
                "volume": 1730000,
                "maxWeight": 100000,
                "duration": 249417.0,
            },
        )
        assert row["volume_kg"] == 1730.0
        assert row["max_weight_kg"] == 100.0

    def test_duration_converts_from_milliseconds(self) -> None:
        """The summary is in milliseconds while the per-set payload is already
        in seconds -- two units for the same quantity in one session."""
        row = ga._parse_exercise(1, {"category": "SQUAT", "duration": 249417.0})
        assert row["active_duration_s"] == 249.417

    def test_a_missing_sub_category_becomes_an_empty_string(self) -> None:
        """It is part of the primary key, and Postgres will not key on a null."""
        row = ga._parse_exercise(1, {"category": "SHOULDER_PRESS"})
        assert row["sub_category"] == ""

    def test_a_bodyweight_exercise_carries_no_volume(self) -> None:
        row = ga._parse_exercise(1, {"category": "PUSH_UP", "volume": 0, "maxWeight": 0})
        assert row["volume_kg"] is None
        assert row["max_weight_kg"] is None


class TestSetParsing:
    """The individual set, and the confidence that comes only with it."""

    def test_sets_are_keyed_by_position(self) -> None:
        """Garmin's own messageIndex is populated on old sessions and null on
        recent ones, so keying on it would collapse a session onto one row."""
        rows = es.parse_sets(
            7, {"exerciseSets": [_active(messageIndex=None), _active(messageIndex=None)]}
        )
        assert [r["set_index"] for r in rows] == [0, 1]
        assert {r["activity_id"] for r in rows} == {7}

    def test_a_settled_identification_is_kept_with_its_probability(self) -> None:
        row = es.parse_sets(7, {"exerciseSets": [_active()]})[0]
        assert row["category"] == "SQUAT"
        assert row["exercise_name"] == "BARBELL_SIFF_SQUAT"
        assert row["probability_pct"] == 100.0

    def test_only_the_top_candidate_survives(self) -> None:
        """Garmin returns three when it is unsure; the runner-ups drive no
        reading of this data, and the probability already says it guessed."""
        row = es.parse_sets(
            7,
            {
                "exerciseSets": [
                    _active(
                        exercises=[
                            {"category": "DEADLIFT", "name": "BARBELL_DEADLIFT",
                             "probability": 41.4},
                            {"category": "DEADLIFT", "name": "STRAIGHT_LEG_DEADLIFT",
                             "probability": 34.4},
                            {"category": "LUNGE", "name": None, "probability": 23.0},
                        ]
                    )
                ]
            },
        )[0]
        assert row["exercise_name"] == "BARBELL_DEADLIFT"
        assert row["probability_pct"] == 41.4

    def test_a_rest_set_carries_no_exercise_or_load(self) -> None:
        """Rest must not inherit the movement that happened to precede it."""
        rows = es.parse_sets(
            7,
            {
                "exerciseSets": [
                    _active(),
                    {"setType": "REST", "duration": 126.1, "repetitionCount": None,
                     "weight": None, "exercises": []},
                ]
            },
        )
        rest = rows[1]
        assert rest["set_type"] == "REST"
        assert rest["category"] is None
        assert rest["weight_kg"] is None
        assert rest["reps"] is None

    def test_a_set_weight_converts_and_honours_the_sentinels(self) -> None:
        rows = es.parse_sets(
            7,
            {"exerciseSets": [_active(weight=130000.0), _active(weight=-1.0),
                              _active(weight=0.0)]},
        )
        assert [r["weight_kg"] for r in rows] == [130.0, None, None]

    def test_an_empty_payload_yields_nothing(self) -> None:
        assert es.parse_sets(7, None) == []
        assert es.parse_sets(7, {"exerciseSets": []}) == []


class TestSetTimestamps:
    """Set times are GMT with no marker, like the activity's own startTimeGMT."""

    def test_an_offset_is_spelled_out(self) -> None:
        """Without it PostgREST stores a Santiago 07:31 as a UTC 07:31, moving
        every set three hours."""
        assert es._to_utc_iso("2026-09-08T10:31:10.0") == "2026-09-08T10:31:10.0+00:00"

    def test_a_missing_timestamp_stays_null(self) -> None:
        assert es._to_utc_iso(None) is None
