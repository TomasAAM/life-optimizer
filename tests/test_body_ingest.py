"""Tests for parsing the Health Connect relay sheet.

The sheet is the one part of this feed nobody controls: its headers are written
by a third-party exporter, its units depend on how that exporter serialises a
Health Connect ``Mass``, and it grows by append so a re-run can repeat a record.
Every test here pins a defect that would otherwise land as plausible-looking
numbers rather than as an error -- a weight in grams stored as 82000 kg, a body
fat of 0.185%, or a stale duplicate winning over a correction.
"""

from __future__ import annotations

from ingest import body_composition as bc


def _csv(*rows: str) -> str:
    """Build a CSV body with the exporter's typical header row."""
    header = "Time,Weight (kg),Body Fat (%),Lean body mass (kg),Data source"
    return "\n".join((header, *rows)) + "\n"


class TestHeaderMatching:
    """Headers are matched by alias, because their text is not a contract."""

    def test_normalises_case_punctuation_and_units(self) -> None:
        assert bc._normalise_header("Body Fat (%)") == "bodyfat"
        assert bc._normalise_header("Lean_body-mass") == "leanbodymass"
        assert bc._normalise_header("WEIGHT") == "weight"

    def test_maps_known_headers_and_ignores_the_rest(self) -> None:
        mapping = bc._map_columns(["Time", "Weight (kg)", "Steps", "Sleep"])
        assert mapping == {"Time": "measured_at_local", "Weight (kg)": "weight_kg"}

    def test_first_spelling_of_a_column_wins(self) -> None:
        """A second weight column must not overwrite the first."""
        mapping = bc._map_columns(["Time", "Weight", "Mass"])
        assert list(mapping) == ["Time", "Weight"]

    def test_a_sheet_without_weight_yields_nothing(self) -> None:
        assert bc.parse_sheet("Time,Steps\n2026-09-08 07:00,9000\n") == []


class TestUnitGuards:
    """Mass in grams and body fat as a fraction are both silently plausible."""

    def test_grams_are_converted_to_kilograms(self) -> None:
        rows = bc.parse_sheet(_csv("2026-09-08 07:12,82000,18.2,66.6,fitdays"))
        assert rows[0]["weight_kg"] == 82.0

    def test_kilograms_are_left_alone(self) -> None:
        rows = bc.parse_sheet(_csv("2026-09-08 07:12,81.4,18.2,66.6,fitdays"))
        assert rows[0]["weight_kg"] == 81.4

    def test_a_body_fat_fraction_becomes_percentage_points(self) -> None:
        rows = bc.parse_sheet(_csv("2026-09-08 07:12,81.4,0.185,66.6,fitdays"))
        assert rows[0]["body_fat_pct"] == 18.5

    def test_body_fat_already_in_percent_is_left_alone(self) -> None:
        rows = bc.parse_sheet(_csv("2026-09-08 07:12,81.4,18.5,66.6,fitdays"))
        assert rows[0]["body_fat_pct"] == 18.5


class TestRowSelection:
    """A row is a weigh-in only if it carries an instant and a weight."""

    def test_a_row_without_weight_is_dropped(self) -> None:
        """Health Connect stores body fat as its own record type, so a
        fat-only row is legitimate rather than corrupt."""
        rows = bc.parse_sheet(_csv("2026-08-25 19:40,,17.9,,fitdays"))
        assert rows == []

    def test_an_unparseable_timestamp_is_dropped(self) -> None:
        rows = bc.parse_sheet(_csv("not a date,81.4,18.2,66.6,fitdays"))
        assert rows == []

    def test_a_repeated_instant_keeps_the_last_spelling(self) -> None:
        rows = bc.parse_sheet(
            _csv(
                "2026-09-08 07:12,81.4,18.2,66.6,fitdays",
                "2026-09-08 07:12,81.9,18.4,66.1,fitdays",
            )
        )
        assert len(rows) == 1
        assert rows[0]["weight_kg"] == 81.9

    def test_rows_come_back_oldest_first(self) -> None:
        rows = bc.parse_sheet(
            _csv(
                "2026-09-08 07:12,81.4,18.2,66.6,fitdays",
                "2026-09-01 07:30,82.0,18.6,66.8,fitdays",
            )
        )
        assert [r["measured_at_local"] for r in rows] == [
            "2026-09-01T07:30:00",
            "2026-09-08T07:12:00",
        ]

    def test_absent_optional_metrics_are_null_not_missing(self) -> None:
        """The upsert needs every column present, so gaps must be explicit."""
        rows = bc.parse_sheet(_csv("2026-09-08 07:12,81.4,,,fitdays"))
        assert rows[0]["body_fat_pct"] is None
        assert rows[0]["bone_mass_kg"] is None
        assert rows[0]["source"] == "fitdays"


class TestWallClock:
    """Time of day decides whether a reading is on protocol, so it must survive.

    The defect pinned here: parsing straight to UTC shifted a Santiago morning
    weigh-in three or four hours, turning an on-protocol 07:12 reading into an
    off-protocol 10:12 one. Every shape below is the same 07:12 local instant
    written differently, and all of them must land on 07:12.
    """

    def test_a_naive_timestamp_is_taken_at_face_value(self) -> None:
        rows = bc.parse_sheet(_csv("2026-09-08 07:12,81.4,18.2,66.6,fitdays"))
        assert rows[0]["measured_at_local"] == "2026-09-08T07:12:00"

    def test_a_phone_offset_resolves_to_the_same_clock(self) -> None:
        rows = bc.parse_sheet(_csv("2026-09-08T07:12:00-03:00,81.4,18.2,66.6,fitdays"))
        assert rows[0]["measured_at_local"] == "2026-09-08T07:12:00"

    def test_an_exporter_that_normalised_to_utc_is_converted_back(self) -> None:
        """A ``Z`` stamp is a UTC instant, not a local clock, so it has to be
        moved into the athlete's zone rather than read literally."""
        rows = bc.parse_sheet(_csv("2026-09-08T10:12:00Z,81.4,18.2,66.6,fitdays"))
        assert rows[0]["measured_at_local"] == "2026-09-08T07:12:00"

    def test_mixed_offsets_stay_deterministic(self) -> None:
        """A column carrying two different offsets has no shared tz-aware dtype
        and comes back as ``object``, which has no ``.dt`` accessor -- so it is
        routed through UTC rather than parsed natively."""
        rows = bc.parse_sheet(
            _csv(
                "2026-09-08T07:12:00-03:00,81.4,18.2,66.6,fitdays",
                "2026-09-01T07:30:00+02:00,82.0,18.6,66.8,fitdays",
            )
        )
        assert [r["measured_at_local"] for r in rows] == [
            "2026-09-01T01:30:00",
            "2026-09-08T07:12:00",
        ]

    def test_mixing_naive_and_offset_rows_is_reported(self, caplog) -> None:
        """The naive rows in such a sheet get read as UTC and land on the wrong
        hour; too consequential to swallow silently."""
        import logging

        with caplog.at_level(logging.WARNING, logger=bc.logger.name):
            bc.parse_sheet(
                _csv(
                    "2026-09-08T07:12:00-03:00,81.4,18.2,66.6,fitdays",
                    "2026-09-01 07:30,82.0,18.6,66.8,fitdays",
                )
            )
        assert any("naive timestamps" in r.message for r in caplog.records)


class TestIngestGuards:
    """The feed is newer than the pipeline and must never break it."""

    def test_an_unset_url_is_a_no_op(self, monkeypatch) -> None:
        monkeypatch.delenv(bc._SHEET_URL_ENV, raising=False)
        calls: list[object] = []

        class _Supabase:
            def table(self, name: str):  # pragma: no cover - must not be reached
                calls.append(name)
                raise AssertionError("ingest must not touch Supabase with no URL")

        bc.ingest(_Supabase())
        assert calls == []
