"""Render the metrics tab: running volume, consistency and performance trend.

Consumes the aggregations in :mod:`dashboard.activity_metrics` and emits Plotly
figures plus one self-contained HTML fragment, the same way
:mod:`dashboard.zones` supplies the zone tab. Keeping it separate from
:mod:`dashboard.render` avoids a circular import: ``build`` wires the fragment
into the page, so ``render`` never has to know this module exists.

The volume chart carries all three granularities as trace pairs and toggles
their visibility client-side, because the page is a static file with no server
to re-aggregate on demand.
"""

from __future__ import annotations

from datetime import date
from html import escape

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard import activity_metrics as am
from plan.pace import seconds_to_pace

_COLOR_KM = "#2563eb"       # blue   - distance bars
_COLOR_HOURS = "#f97316"    # orange - moving time
_COLOR_PROJECTION = "#94a3b8"
_COLOR_EFFICIENCY = "#7c3aed"
_COLOR_MEDIAN = "#0f172a"

# Mirrors the zone accents on the plan tab so a zone reads the same colour
# wherever it appears on the dashboard.
_ZONE_COLORS = {
    "Recovery": "#639922", "Endurance": "#97C459", "Tempo": "#EF9F27",
    "Threshold": "#D85A30", "VO2max": "#E24B4A",
}
_UNKNOWN_ZONE_COLOR = "#94a3b8"

_GRANULARITY_LABELS = {"week": "Weekly", "month": "Monthly", "year": "Yearly"}
_DEFAULT_GRANULARITY = "week"

_DAY_MS = 86_400_000
# Bar widths sized just under one period so adjacent bars do not touch.
_BAR_WIDTH_MS = {"week": 6 * _DAY_MS, "month": 26 * _DAY_MS, "year": 330 * _DAY_MS}

_VOLUME_DIV_ID = "volume-chart"

_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Light grey for a rest day, deepening blue with distance.
_CALENDAR_SCALE = [
    [0.0, "#f1f5f9"], [0.01, "#dbeafe"], [0.35, "#93c5fd"],
    [0.7, "#3b82f6"], [1.0, "#1d4ed8"],
]

_LAYOUT = dict(
    template="plotly_white",
    margin=dict(l=50, r=30, t=50, b=40),
    hovermode="closest",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
)


def build_volume_figure(runs: pd.DataFrame, today: date) -> go.Figure:
    """Build the running-volume chart with all three granularities loaded.

    Emits one bar trace (distance) and one line trace (moving time) per
    granularity, in the order week, month, year. Only the weekly pair starts
    visible; the page toggles the rest. That trace order is the contract the
    client-side granularity buttons rely on.

    Parameters
    ----------
    runs : pandas.DataFrame
        Output of :func:`dashboard.activity_metrics.prepare_runs`.
    today : datetime.date
        Extends the zero-fill through the current period.

    Returns
    -------
    plotly.graph_objects.Figure
        Distance bars on the primary axis, moving hours on the secondary.
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    for granularity in am.GRANULARITIES:
        volume = am.volume_by_period(runs, granularity, through=today)
        visible = granularity == _DEFAULT_GRANULARITY
        label = _GRANULARITY_LABELS[granularity]
        custom = volume[["label", "runs"]].to_numpy() if not volume.empty else []

        fig.add_trace(
            go.Bar(
                x=volume["period_start"],
                y=volume["km"],
                name=f"{label} distance",
                marker_color=_COLOR_KM,
                width=_BAR_WIDTH_MS[granularity],
                visible=visible,
                customdata=custom,
                hovertemplate=(
                    "%{customdata[0]}<br>%{y:.1f} km"
                    "<br>%{customdata[1]} runs<extra></extra>"
                ),
            ),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(
                x=volume["period_start"],
                y=volume["hours"],
                name=f"{label} moving time",
                mode="lines+markers",
                line=dict(color=_COLOR_HOURS, width=2),
                marker=dict(size=5),
                visible=visible,
                customdata=custom,
                hovertemplate="%{customdata[0]}<br>%{y:.1f} h<extra></extra>",
            ),
            secondary_y=True,
        )

    fig.update_layout(height=380, title="Running volume", **_LAYOUT)
    fig.update_yaxes(title_text="Distance (km)", secondary_y=False, rangemode="tozero")
    fig.update_yaxes(
        title_text="Moving time (h)", secondary_y=True,
        rangemode="tozero", showgrid=False,
    )
    return fig


def build_cumulative_figure(runs: pd.DataFrame, today: date) -> go.Figure:
    """Build the year-to-date cumulative distance curve with a year-end pace.

    The dashed extension is a straight-line projection at the current daily
    rate, not a forecast: it answers "where does this year land if nothing
    changes", which is the only claim the data supports.

    Parameters
    ----------
    runs : pandas.DataFrame
        Output of :func:`dashboard.activity_metrics.prepare_runs`.
    today : datetime.date
        Last day of the actual curve and the origin of the projection.

    Returns
    -------
    plotly.graph_objects.Figure
        Cumulative distance for the current year, with the projection.
    """
    fig = go.Figure()
    usable = am.valid_runs(runs)
    year_start = date(today.year, 1, 1)

    if not usable.empty:
        in_year = usable[usable["date"].dt.date >= year_start]
        if not in_year.empty:
            daily = in_year.groupby("date")["km"].sum()
            span = pd.date_range(pd.Timestamp(year_start), pd.Timestamp(today), freq="D")
            cumulative = daily.reindex(span, fill_value=0.0).cumsum()

            fig.add_trace(
                go.Scatter(
                    x=cumulative.index,
                    y=cumulative.to_numpy(),
                    name="Cumulative",
                    mode="lines",
                    line=dict(color=_COLOR_KM, width=2.5),
                    fill="tozeroy",
                    fillcolor="rgba(37, 99, 235, 0.10)",
                    hovertemplate="%{x|%d %b}<br>%{y:.0f} km<extra></extra>",
                )
            )

            year_end = date(today.year, 12, 31)
            days_done = (today - year_start).days + 1
            days_left = (year_end - today).days
            total = float(cumulative.iloc[-1])
            if days_left > 0 and days_done > 0:
                projected = total + (total / days_done) * days_left
                fig.add_trace(
                    go.Scatter(
                        x=[pd.Timestamp(today), pd.Timestamp(year_end)],
                        y=[total, projected],
                        name=f"At this rate: {projected:,.0f} km",
                        mode="lines",
                        line=dict(color=_COLOR_PROJECTION, width=2, dash="dash"),
                        hovertemplate="%{x|%d %b}<br>%{y:.0f} km<extra></extra>",
                    )
                )

    fig.update_layout(height=320, title=f"{today.year} cumulative distance", **_LAYOUT)
    fig.update_yaxes(title_text="Distance (km)", rangemode="tozero")
    return fig


def build_calendar_figure(runs: pd.DataFrame, today: date) -> go.Figure:
    """Build the daily-distance calendar heatmap, weeks across, days down.

    Parameters
    ----------
    runs : pandas.DataFrame
        Output of :func:`dashboard.activity_metrics.prepare_runs`.
    today : datetime.date
        Last day of the calendar.

    Returns
    -------
    plotly.graph_objects.Figure
        One tile per day; rest days are rendered as empty tiles, not gaps.
    """
    fig = go.Figure()
    daily = am.daily_distance(runs, today)

    if not daily.empty:
        grid = daily.pivot(index="weekday", columns="week_start", values="km")
        grid = grid.reindex(range(7))
        dates = daily.pivot(index="weekday", columns="week_start", values="date")
        dates = dates.reindex(range(7))
        labels = dates.map(lambda d: f"{d:%a %d %b %Y}" if pd.notna(d) else "")

        fig.add_trace(
            go.Heatmap(
                x=grid.columns,
                y=_WEEKDAY_NAMES,
                z=grid.to_numpy(),
                customdata=labels.to_numpy(),
                colorscale=_CALENDAR_SCALE,
                zmin=0,
                xgap=3,
                ygap=3,
                hovertemplate="%{customdata}<br>%{z:.1f} km<extra></extra>",
                colorbar=dict(title="km", thickness=12, len=0.9),
            )
        )

    fig.update_layout(height=300, title="Daily distance", **_LAYOUT)
    fig.update_yaxes(autorange="reversed")
    return fig


def _pace_ticks(paces: pd.Series) -> tuple[list[int], list[str]]:
    """Pick round 30-second tick positions spanning a pace series."""
    if paces.empty:
        return [], []
    low = int(paces.min() // 30 * 30)
    high = int(paces.max() // 30 * 30 + 30)
    values = list(range(low, high + 1, 30))
    return values, [seconds_to_pace(v) for v in values]


def build_pace_figure(trend: pd.DataFrame, monthly: pd.DataFrame) -> go.Figure:
    """Build the per-run pace scatter, coloured by zone, faster runs higher.

    Treadmill runs use hollow markers: belt pace is chosen rather than earned,
    so it is shown but never allowed to drive the trend line.

    Parameters
    ----------
    trend : pandas.DataFrame
        Output of :func:`dashboard.activity_metrics.pace_trend`.
    monthly : pandas.DataFrame
        Output of :func:`dashboard.activity_metrics.monthly_easy_pace`.

    Returns
    -------
    plotly.graph_objects.Figure
        One trace per zone plus the easy-run median line.
    """
    fig = go.Figure()

    if not trend.empty:
        for zone in [*_ZONE_COLORS, None]:
            group = (
                trend[trend["zone"].isna()] if zone is None
                else trend[trend["zone"] == zone]
            )
            if group.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=group["date"],
                    y=group["pace_s_km"],
                    name=zone or "Unclassified",
                    mode="markers",
                    marker=dict(
                        size=9,
                        color=_ZONE_COLORS.get(zone, _UNKNOWN_ZONE_COLOR),
                        symbol=[
                            "circle-open" if t else "circle"
                            for t in group["is_treadmill"]
                        ],
                        line=dict(
                            width=2,
                            color=_ZONE_COLORS.get(zone, _UNKNOWN_ZONE_COLOR),
                        ),
                    ),
                    customdata=group[["activity_name", "km", "avg_hr"]].to_numpy(),
                    hovertemplate=(
                        "%{customdata[0]}<br>%{x|%d %b %Y}"
                        "<br>%{customdata[1]:.1f} km at %{text}/km"
                        "<br>%{customdata[2]:.0f} bpm<extra></extra>"
                    ),
                    text=[seconds_to_pace(p) for p in group["pace_s_km"]],
                )
            )

    if not monthly.empty:
        fig.add_trace(
            go.Scatter(
                x=monthly["month_start"],
                y=monthly["pace_s_km"],
                name="Easy-run median",
                mode="lines+markers",
                line=dict(color=_COLOR_MEDIAN, width=2, dash="dot"),
                marker=dict(size=7, symbol="diamond"),
                text=[seconds_to_pace(p) for p in monthly["pace_s_km"]],
                hovertemplate="%{x|%b %Y}<br>Median %{text}/km<extra></extra>",
            )
        )

    ticks, tick_text = _pace_ticks(
        trend["pace_s_km"].dropna() if not trend.empty else pd.Series(dtype=float)
    )
    fig.update_layout(height=400, title="Pace per run", **_LAYOUT)
    fig.update_yaxes(
        title_text="Pace (min/km)",
        autorange="reversed",
        tickmode="array",
        tickvals=ticks,
        ticktext=tick_text,
    )
    return fig


def build_efficiency_figure(efficiency: pd.DataFrame) -> go.Figure:
    """Build the monthly aerobic-efficiency line for easy outdoor runs.

    Parameters
    ----------
    efficiency : pandas.DataFrame
        Output of :func:`dashboard.activity_metrics.aerobic_efficiency`.

    Returns
    -------
    plotly.graph_objects.Figure
        Efficiency factor per month; rising means fitter.
    """
    fig = go.Figure()

    if not efficiency.empty:
        fig.add_trace(
            go.Scatter(
                x=efficiency["month_start"],
                y=efficiency["efficiency"],
                name="Efficiency factor",
                mode="lines+markers",
                line=dict(color=_COLOR_EFFICIENCY, width=2.5),
                marker=dict(size=8),
                customdata=efficiency[["runs"]].to_numpy(),
                hovertemplate=(
                    "%{x|%b %Y}<br>EF %{y:.3f}"
                    "<br>%{customdata[0]} easy runs<extra></extra>"
                ),
            )
        )

    fig.update_layout(height=300, title="Aerobic efficiency", **_LAYOUT)
    fig.update_yaxes(title_text="Metres per minute per bpm")
    return fig


def _delta_html(delta: float, unit: str = "km") -> str:
    """Render a signed period-over-period change with a direction colour."""
    if abs(delta) < 0.05:
        return "<span style='color:#94a3b8'>level with last period</span>"
    color = "#16a34a" if delta > 0 else "#dc2626"
    arrow = "▲" if delta > 0 else "▼"
    return f"<span style='color:{color}'>{arrow} {abs(delta):.1f} {unit}</span>"


def _cards(headline: am.VolumeHeadline, streaks: am.ConsistencySummary) -> str:
    """Render the metrics header cards."""
    since_run = (
        "no runs recorded" if streaks.days_since_last_run is None
        else "ran today" if streaks.days_since_last_run == 0
        else f"last run {streaks.days_since_last_run} d ago"
    )
    cards = [
        ("This week", f"{headline.km_week:.1f} km",
         f"{_delta_html(headline.week_delta)} vs same point last week"),
        ("This month", f"{headline.km_month:.1f} km",
         f"{_delta_html(headline.month_delta)} vs same point last month"),
        ("Year to date", f"{headline.km_year:,.0f} km",
         f"{headline.runs_total} runs on record"),
        ("Training days", f"{streaks.training_days_28}/28",
         f"{streaks.rest_days_28} rest days in the last 4 weeks"),
        ("Current streak", f"{streaks.current_streak} d",
         f"longest {streaks.longest_streak} d · {since_run}"),
    ]
    rendered = "".join(
        f"<div class='card'><div class='card-label'>{escape(label)}</div>"
        f"<div class='card-value'>{escape(value)}</div>"
        f"<div class='card-sub'>{sub}</div></div>"
        for label, value, sub in cards
    )
    return f"<div class='cards'>{rendered}</div>"


def _granularity_buttons() -> str:
    """Render the week/month/year toggle for the volume chart."""
    buttons = "".join(
        f"<button class='gran-btn{' active' if g == _DEFAULT_GRANULARITY else ''}' "
        f"data-gran='{g}'>{_GRANULARITY_LABELS[g]}</button>"
        for g in am.GRANULARITIES
    )
    return f"<div class='gran-toggle'>{buttons}</div>"


def metrics_section_html(
    runs: pd.DataFrame,
    activities: pd.DataFrame,
    zones: pd.DataFrame,
    today: date,
) -> str:
    """Render the whole metrics tab: cards, charts and their caveats.

    Parameters
    ----------
    runs : pandas.DataFrame
        Output of :func:`dashboard.activity_metrics.prepare_runs`.
    activities : pandas.DataFrame
        Every activity, for the training-day streaks.
    zones : pandas.DataFrame
        Lactate zones, used to colour each run by intensity.
    today : datetime.date
        The day the dashboard is being built for.

    Returns
    -------
    str
        An HTML fragment for the metrics tab panel.
    """
    if runs.empty:
        return (
            "<h2>Metrics</h2><div class='panel'><p>No running activities on "
            "record yet.</p></div>"
        )

    headline = am.volume_headline(runs, today)
    streaks = am.consistency(activities, runs, today)
    trend = am.pace_trend(runs, zones)
    monthly = am.monthly_easy_pace(trend)
    efficiency = am.aerobic_efficiency(trend)

    charts = [
        build_volume_figure(runs, today),
        build_cumulative_figure(runs, today),
        build_calendar_figure(runs, today),
        build_pace_figure(trend, monthly),
        build_efficiency_figure(efficiency),
    ]
    div_ids = [_VOLUME_DIV_ID, None, None, None, None]
    volume, cumulative, calendar, pace, efficiency_chart = [
        fig.to_html(full_html=False, include_plotlyjs=False, div_id=div_id)
        for fig, div_id in zip(charts, div_ids)
    ]

    excluded_note = ""
    if headline.excluded_runs:
        plural = "s" if headline.excluded_runs > 1 else ""
        excluded_note = (
            f" {headline.excluded_runs} run{plural} excluded for an implausible "
            f"recorded pace (outside "
            f"{seconds_to_pace(am.MIN_PLAUSIBLE_PACE_S_KM)}–"
            f"{seconds_to_pace(am.MAX_PLAUSIBLE_PACE_S_KM)}/km) — a corrupt "
            "distance, not a performance."
        )

    return f"""<h2>Running volume</h2>
  {_cards(headline, streaks)}
  {_granularity_buttons()}
  <div class="panel">{volume}</div>
  <p class="src-note">Distance covers outdoor and treadmill running only;
  Hyrox and multisport sessions record mixed distance and are left out.
  Time is Garmin's moving duration.{excluded_note}</p>

  <div class="panel">{cumulative}</div>
  <div class="panel">{calendar}</div>
  <p class="src-note">Every day since your first recorded run, rest days
  included — the empty tiles are the point.</p>

  <h2 style="margin-top:28px">Performance trend</h2>
  <div class="panel">{pace}</div>
  <p class="note">Each marker is one run, placed by its average pace and
  coloured by the lactate zone its <em>average</em> heart rate falls in.
  Hollow markers are treadmill runs. The dotted line is the monthly median
  pace of easy outdoor runs — the fairest like-for-like comparison, since
  easy pace at a steady effort tracks fitness rather than how hard you
  decided to run that day.</p>

  <div class="panel">{efficiency_chart}</div>
  <p class="note">Efficiency factor is metres per minute per heartbeat on easy
  outdoor runs. Rising means the same heart rate is buying more speed.</p>

  <p class="src-note">Zone colouring uses each session's <em>average</em> heart
  rate, which flattens an interval workout into a single bucket — a tempo
  session with hard reps and easy floats can average out into Endurance. True
  time-in-zone needs the per-reading heart-rate series rather than the activity
  summary, and is not computed here.</p>"""
