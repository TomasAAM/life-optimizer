"""Tests for the Recap tab's markup.

Every month is in the DOM at once and switched client-side, so the failures
worth pinning are the ones the week strip already taught: ids and file names
that collide across months, more than one month shown, and a story whose
progress bar has a different number of segments from its cards.
"""

from __future__ import annotations

import re
from datetime import date

import pandas as pd

from dashboard import recap_tab as rt
from dashboard import render

from tests.test_activity_metrics import _activity
from tests.test_recap_metrics import _frame, _recap, _session


def _months() -> list:
    activities = _frame([
        _activity("2026-08-05", km=10.0),
        _activity("2026-09-05", km=12.0),
        _activity("2026-09-06", activity_type="strength_training", km=0.0),
    ])
    planned = [_session("2026-09-05", km=12.0)]
    return [_recap(date(2026, m, 1), activities, planned) for m in (9, 8)]


def test_one_story_per_month_and_exactly_one_active() -> None:
    html = rt.recap_section_html(_months(), "2026-09")
    assert html.count("<section class='story") == 2
    assert html.count("<section class='story active'") == 1
    assert "data-recap-month='2026-09'" in html
    assert html.count("aria-pressed='true'") == 1


def test_file_names_are_namespaced_by_month() -> None:
    html = rt.recap_section_html(_months(), "2026-09")
    files = re.findall(r"data-file='([^']+)'", html)
    assert len(files) == len(set(files))
    assert "recap-2026-08-cover.png" in files


def test_every_story_has_one_progress_segment_per_card() -> None:
    for recap in _months():
        story = rt._story_html(recap, active=False)
        assert story.count("class='seg'") == story.count("<article class='story-card")


def test_cards_without_data_are_skipped() -> None:
    september, august = _months()
    assert [re.search(r"data-card='(\w+)'", c).group(1) for c in rt.story_cards(september)] == [
        "cover", "running", "strength", "body", "closing"]
    assert "data-card='strength'" not in "".join(rt.story_cards(august))


def test_there_is_no_plan_card_even_with_a_plan() -> None:
    september = _months()[0]
    assert september.plan is not None
    assert "data-card='plan'" not in "".join(rt.story_cards(september))


def test_week_bars_are_labelled_by_days_of_the_month() -> None:
    september = _months()[0]
    svg = rt._week_bars_svg(september.running.weeks)
    assert ">1–6<" in svg
    assert ">28–30<" in svg


def test_a_six_week_month_gets_the_compact_calendar() -> None:
    august = _months()[1]
    assert "class='cal rows-6'" in rt._calendar_html(august)
    assert "class='cal rows-6'" not in rt._calendar_html(_months()[0])


def test_changes_read_as_plain_text() -> None:
    assert rt._change(204.0, 198.0, "Aug") == "+3% on Aug"
    assert rt._change(7.0, 8.0, "Aug", unit="", decimals=0) == "−1 on Aug"
    assert rt._change(10.0, 10.0, "Aug") == "same as Aug"
    assert rt._change(10.0, 0.0, "Aug") == ""


def test_cards_are_numbered_page_by_page() -> None:
    cards = rt.story_cards(_months()[0])
    assert "<span>01/05</span>" in cards[0]
    assert "<span>05/05</span>" in cards[-1]
    assert not any("__PAGE__" in c for c in cards)


def test_long_titles_shrink_to_fit() -> None:
    assert rt._title_fit("SEPTEMBER") == ""
    assert rt._title_fit("Plan vs done") == " style='font-size:50px'"


class TestCalendarCells:
    """Every kind of session is visible on its own, not only runs."""

    @staticmethod
    def _mark(kinds: tuple[str, ...], km: float = 0.0, others: tuple[str, ...] = ()):
        from dashboard import recap_metrics as rm
        return rm.DayMark(day=date(2026, 9, 3), kinds=kinds, run_km=km, others=others)

    def test_a_run_shows_its_km(self) -> None:
        html = rt._cell(self._mark(("run",), 10.2), date(2026, 9, 30))
        assert "class='c run'" in html and "<em>10</em>" in html

    def test_a_run_double_carries_a_band_per_extra_session(self) -> None:
        html = rt._cell(self._mark(("run", "gym", "hyrox"), 7.0), date(2026, 9, 30))
        assert "has-band" in html
        assert ">GYM<" in html and ">HX<" in html

    def test_gym_hyrox_and_other_days_are_labelled(self) -> None:
        through = date(2026, 9, 30)
        assert "class='c gym'" in rt._cell(self._mark(("gym",)), through)
        assert ">HYROX<" in rt._cell(self._mark(("hyrox",)), through)
        assert ">RIDE 21<" in rt._cell(self._mark(("other",), others=("Ride 21",)), through)

    def test_days_after_the_build_date_are_marked_future(self) -> None:
        assert "future" in rt._cell(self._mark(("run",), 5.0), date(2026, 9, 2))

    def test_the_legend_counts_sessions_by_kind(self) -> None:
        html = rt._calendar_html(_months()[0])
        assert "1 run<" in html and "1 gym<" in html and "0 Hyrox<" in html


def test_method_notes_live_on_the_page_not_on_the_images() -> None:
    html = rt.recap_section_html(_months(), "2026-09")
    assert "How these numbers are made" in html
    cards = "".join(rt.story_cards(_months()[0]))
    assert "proxy" not in cards


def test_the_export_is_a_1080_by_1920_story() -> None:
    assert rt.EXPORT_WIDTH_PX / rt.CARD_WIDTH_PX == 3
    assert rt.CARD_HEIGHT_PX * 3 == 1920
    assert "EXPORT_RATIO = 3" in rt.recap_script()
    assert f"backgroundColor: '{rt.PAPER}'" in rt.recap_script()


def test_no_months_renders_nothing() -> None:
    assert rt.recap_section_html([], "") == ""


def test_the_page_carries_the_tab_and_the_export_library() -> None:
    import plotly.graph_objects as go
    from dashboard.metrics import ReadinessSnapshot

    snapshot = ReadinessSnapshot(
        date=pd.Timestamp("2026-10-02"), ctl=1.0, atl=1.0, tsb=0.0, tsb_label="Neutral",
        hrv_night=None, hrv_status=None,
    )
    html = render.render_html(
        go.Figure(), snapshot, pd.DataFrame(), go.Figure(), go.Figure(),
        recap_html=rt.recap_section_html(_months(), "2026-09"),
    )
    assert 'data-tab="recap"' in html
    assert 'id="tab-recap"' in html
    assert rt.HTML_TO_IMAGE_SRC in html
    assert rt.RECAP_FONTS_HREF in html
    assert "crossorigin>" in html
