"""Render the planned-versus-done panel for the training-plan tab.

Consumes :mod:`dashboard.adherence` and emits one HTML fragment. Like the other
tab modules it stays out of :mod:`dashboard.render`, which only receives the
finished fragment through :class:`dashboard.render.PlanView`, so neither module
imports the other.
"""

from __future__ import annotations

from html import escape

import plotly.graph_objects as go

from dashboard import theme
from dashboard.adherence import DONE_KM_FRACTION, LONG_RUN_MIN_KM, WeekAdherence

_COLOR_PLANNED = theme.COLOR_LOAD   # grey - what the plan asked for
_COLOR_DONE = "#2563eb"             # blue - what was run, same as the volume chart

# Completed weeks summarised in the headline cards.
_HEADLINE_WEEKS = 4
# Most recent partial, swapped or missed sessions listed under the chart.
_MISSES_SHOWN = 8


def _week_label(week: WeekAdherence) -> str:
    """Category label for a week, marking the one still in progress."""
    label = week.week_start.strftime("%d %b")
    return f"{label} (to date)" if week.is_current else label


def build_adherence_figure(weeks: list[WeekAdherence]) -> go.Figure:
    """Build the planned-versus-done km chart, one bar pair per plan week.

    Weeks are categories rather than dates, so unified hover heads each card
    with the week label and needs no per-granularity date format.

    Parameters
    ----------
    weeks : list of WeekAdherence
        Output of :func:`dashboard.adherence.weekly_adherence`.

    Returns
    -------
    plotly.graph_objects.Figure
        Grouped bars: planned km (due sessions) beside done km.
    """
    labels = [_week_label(w) for w in weeks]
    pct = [[w.km_pct if w.km_pct is not None else 0.0] for w in weeks]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=labels,
            y=[w.planned_km for w in weeks],
            name="Planned",
            marker_color=_COLOR_PLANNED,
            # No <extra></extra> and no %{x}: under unified hover the trace name
            # labels the row and the week already heads the card.
            hovertemplate="%{y:.1f} km",
        )
    )
    fig.add_trace(
        go.Bar(
            x=labels,
            y=[w.done_km for w in weeks],
            name="Done",
            marker_color=_COLOR_DONE,
            customdata=pct,
            hovertemplate="%{y:.1f} km (%{customdata[0]:.0f}% of plan)",
        )
    )
    fig.update_layout(
        **theme.chart_layout(
            height=320,
            title="Running km: planned vs done",
            hovermode="x unified",
            barmode="group",
            margin=dict(l=50, r=30, t=58, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
        )
    )
    fig.update_yaxes(title_text="Distance (km)", rangemode="tozero")
    return fig


def _ratio(done: int, planned: int) -> str:
    return f"{done}/{planned}" if planned else "—"


def _cards(weeks: list[WeekAdherence]) -> str:
    """Headline cards over the last few completed weeks."""
    completed = [w for w in weeks if not w.is_current][-_HEADLINE_WEEKS:]
    planned = sum(w.planned_km for w in completed)
    done = sum(w.done_km for w in completed)
    km_pct = f"{100 * done / planned:.0f}%" if planned else "—"
    key_done = sum(w.key_done for w in completed)
    key_planned = sum(w.key_planned for w in completed)
    gym_done = sum(w.gym_done for w in completed)
    gym_planned = sum(w.gym_planned for w in completed)
    span = f"last {len(completed)} completed weeks"
    cards = [
        ("Km executed", km_pct, f"{done:.0f} of {planned:.0f} km · {span}"),
        ("Key sessions", _ratio(key_done, key_planned), f"threshold, sims, long runs · {span}"),
        ("Gym sessions", _ratio(gym_done, gym_planned), span),
    ]
    rendered = "".join(
        f"<div class='card'><div class='card-label'>{escape(label)}</div>"
        f"<div class='card-value'>{escape(value)}</div>"
        f"<div class='card-sub'>{escape(sub)}</div></div>"
        for label, value, sub in cards
    )
    return f"<div class='cards'>{rendered}</div>"


def _table(weeks: list[WeekAdherence]) -> str:
    """Per-week figures, newest first."""
    header = (
        "<tr><th>Week</th><th>Planned km</th><th>Done km</th><th>%</th>"
        "<th>Key sessions</th><th>Gym</th><th>Not done</th></tr>"
    )
    rows = "".join(
        f"<tr><td>{escape(_week_label(w))}</td><td>{w.planned_km:.1f}</td>"
        f"<td>{w.done_km:.1f}</td>"
        f"<td>{'—' if w.km_pct is None else f'{w.km_pct:.0f}%'}</td>"
        f"<td>{_ratio(w.key_done, w.key_planned)}</td>"
        f"<td>{_ratio(w.gym_done, w.gym_planned)}</td><td>{len(w.misses)}</td></tr>"
        for w in reversed(weeks)
    )
    return f"<table class='weekly'>{header}{rows}</table>"


def _misses(weeks: list[WeekAdherence]) -> str:
    """The most recent sessions that were not fully done, newest first."""
    lines = [m for w in reversed(weeks) for m in reversed(w.misses)][:_MISSES_SHOWN]
    if not lines:
        return "<p class='src-note'>Every due session was done.</p>"
    items = "".join(f"<li>{escape(line)}</li>" for line in lines)
    return f"<ul class='miss-list'>{items}</ul>"


def adherence_section_html(weeks: list[WeekAdherence]) -> str:
    """Render the planned-versus-done panel.

    Parameters
    ----------
    weeks : list of WeekAdherence
        Output of :func:`dashboard.adherence.weekly_adherence`, chronological.

    Returns
    -------
    str
        An HTML fragment for the training-plan tab, or an empty string when no
        plan week has a due session yet.
    """
    if not weeks:
        return ""
    chart = build_adherence_figure(weeks).to_html(full_html=False, include_plotlyjs=False)
    return f"""<div class="panel">
    <div class="section-label">Planned vs done</div>
    {_cards(weeks)}
    {chart}
    {_table(weeks)}
    <div class="section-label" style="margin-top:18px">Recently not fully done</div>
    {_misses(weeks)}
    <p class="src-note">Each session is checked part by part against that day's
    Garmin activities. A run counts as done at {DONE_KM_FRACTION:.0%} of its planned
    km; runs, treadmill runs and Hyrox simulations all count toward km, because the
    plan counts simulation km too. A gym part needs a strength activity that day, and
    station work needs a strength, Hyrox-class or multisport activity.
    <b>Partial</b> means some of it happened, and <b>swapped</b> means something else
    did (a hike instead of a run). Key sessions are anything prescribed as hard plus
    runs of {LONG_RUN_MIN_KM:.0f} km or more. The current week counts only sessions
    already due, and done km includes runs the plan did not ask for.</p>
  </div>"""
