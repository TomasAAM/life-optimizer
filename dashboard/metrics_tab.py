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
from dashboard import theme
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

# Two visual channels, one meaning each, across the whole running-form section.
# Colour is the surface, so a treadmill session reads the same in every panel
# and in the scatter. Dash is whether the metric is measured or derived, which
# is constant within a panel and therefore never competes with the colour.
_COLOR_OUTDOOR = "#0E7C86"
_COLOR_TREADMILL = "#C2662E"
_SURFACE_COLORS = {
    am.OUTDOOR_SURFACE: _COLOR_OUTDOOR,
    am.TREADMILL_SURFACE: _COLOR_TREADMILL,
}
_SURFACE_LABELS = {
    am.OUTDOOR_SURFACE: "Outdoor",
    am.TREADMILL_SURFACE: "Treadmill",
}
_FORM_GRID_COLS = 2

# Stride lengths drawn as reference curves on the cadence/pace plane. Four is
# enough to read a stride off the chart without the guides crowding the runs
# they sit behind; the log spans roughly 87-146 cm.
_ISOLINE_STRIDES_CM = (90.0, 105.0, 120.0, 135.0)
_COLOR_ISOLINE = "#B6BCC6"

_GRANULARITY_LABELS = {"week": "Weekly", "month": "Monthly", "year": "Yearly"}
_DEFAULT_GRANULARITY = "week"

_DAY_MS = 86_400_000
# Bar widths sized just under one period so adjacent bars do not touch.
_BAR_WIDTH_MS = {"week": 6 * _DAY_MS, "month": 26 * _DAY_MS, "year": 330 * _DAY_MS}

_VOLUME_DIV_ID = "volume-chart"

# Unified hover puts the period in the card header, so each granularity needs a
# header format matching its bucket: a week reads as a date, a year as a year.
# Literal text passes through d3 time formatting untouched.
_HOVER_DATE_FORMAT = {
    "week": "week of %d %b %Y", "month": "%B %Y", "year": "%Y",
}

_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Light grey for a rest day, deepening blue with distance.
# Rest days are a translucent neutral rather than a light grey, so the cell reads
# as "empty" against warm paper and against near-black alike.
_CALENDAR_SCALE = [
    [0.0, "rgba(125, 132, 145, 0.16)"], [0.01, "#BFD8F5"], [0.35, "#7FB3F0"],
    [0.7, "#3D7BE0"], [1.0, "#1F4FB5"],
]

def _layout(hovermode: str = "closest", **overrides) -> dict:
    """Return the shared chart layout with this tab's margins and legend applied.

    Parameters
    ----------
    hovermode : str, optional
        Plotly hover mode. ``"closest"`` suits the per-run scatter and the
        calendar, where an individual marker or cell is the thing being pointed
        at. The time series pass ``"x unified"``, so one period answers as a
        single card wherever in its column the pointer sits -- under
        ``"closest"`` a chart with two series on two axes hands back whichever
        *point* is nearest in pixels, which is not the series being pointed at.
    **overrides
        Per-figure layout keys, typically ``height`` and ``title``. ``margin``
        and ``legend`` may be overridden too: a figure carrying enough traces
        to wrap the legend onto several rows needs it below the plot, where it
        cannot collide with the title.

    Returns
    -------
    dict
        Keyword arguments for ``Figure.update_layout``.
    """
    margin = overrides.pop("margin", dict(l=50, r=30, t=58, b=40))
    legend = overrides.pop(
        "legend",
        dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
    )
    return theme.chart_layout(
        margin=margin,
        hovermode=hovermode,
        legend=legend,
        **overrides,
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
        run_counts = volume[["runs"]].to_numpy() if not volume.empty else []

        fig.add_trace(
            go.Bar(
                x=volume["period_start"],
                y=volume["km"],
                name=f"{label} distance",
                marker_color=_COLOR_KM,
                width=_BAR_WIDTH_MS[granularity],
                visible=visible,
                customdata=run_counts,
                xhoverformat=_HOVER_DATE_FORMAT[granularity],
                # No <extra></extra>: under unified hover the trace name labels
                # the row, and the period already heads the card.
                hovertemplate="%{y:.1f} km<br>%{customdata[0]} runs",
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
                xhoverformat=_HOVER_DATE_FORMAT[granularity],
                hovertemplate="%{y:.1f} h",
            ),
            secondary_y=True,
        )

    fig.update_layout(
        **_layout(height=380, title="Running volume", hovermode="x unified")
    )
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
                    xhoverformat="%d %b %Y",
                    hovertemplate="%{y:.0f} km",
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
                        xhoverformat="%d %b %Y",
                        hovertemplate="%{y:.0f} km",
                    )
                )

    fig.update_layout(
        **_layout(
            height=320,
            title=f"{today.year} cumulative distance",
            hovermode="x unified",
        )
    )
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
                # The pivot pads the first and last weeks out to seven days.
                # Those cells are not rest days, they are days outside the log,
                # and hovering them otherwise reports a blank date and 0.0 km.
                hoverongaps=False,
                hovertemplate="%{customdata}<br>%{z:.1f} km<extra></extra>",
                colorbar=dict(title="km", thickness=12, len=0.9),
            )
        )

    fig.update_layout(**_layout(height=300, title="Daily distance"))
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
            zone_label = zone or "Unclassified"
            # Zone is the marker's colour and surface is its fill; both are lost
            # on a monochrome reading of the chart, so the hover states them.
            detail = group[["activity_name", "km", "avg_hr"]].copy()
            detail["surface"] = [
                "treadmill" if t else "outdoor" for t in group["is_treadmill"]
            ]
            fig.add_trace(
                go.Scatter(
                    x=group["date"],
                    y=group["pace_s_km"],
                    name=zone_label,
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
                    customdata=detail.to_numpy(),
                    hovertemplate=(
                        "%{customdata[0]}<br>%{x|%d %b %Y}"
                        "<br>%{customdata[1]:.1f} km at %{text}/km"
                        " (%{customdata[3]})"
                        "<br>%{customdata[2]:.0f} bpm · " + zone_label
                        + "<extra></extra>"
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
    fig.update_layout(**_layout(height=400, title="Pace per run"))
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
                xhoverformat="%B %Y",
                hovertemplate="EF %{y:.3f}<br>%{customdata[0]} easy runs",
            )
        )

    fig.update_layout(
        **_layout(height=300, title="Aerobic efficiency", hovermode="x unified")
    )
    fig.update_yaxes(title_text="Metres per minute per bpm")
    return fig


def _form_grid_positions() -> list[tuple[int, int]]:
    """Place each form metric on the small-multiple grid, in order.

    Two columns, so the measured pair heads the grid and the derived pair sits
    beneath it. An odd metric out lands alone on the last row, where it is
    given the full width rather than left beside an empty cell.

    Returns
    -------
    list of (int, int)
        One-based (row, column) per metric in :data:`FORM_METRICS` order.
    """
    return [
        (i // _FORM_GRID_COLS + 1, i % _FORM_GRID_COLS + 1)
        for i in range(len(am.FORM_METRICS))
    ]


def _form_grid_specs(positions: list[tuple[int, int]]) -> list[list[dict | None]]:
    """Build the subplot spec grid, widening a lone trailing panel."""
    rows = max(row for row, _ in positions)
    specs: list[list[dict | None]] = [
        [{} for _ in range(_FORM_GRID_COLS)] for _ in range(rows)
    ]
    for row in range(1, rows + 1):
        if sum(1 for r, _ in positions if r == row) == 1:
            specs[row - 1] = [{"colspan": _FORM_GRID_COLS}, *([None] * (_FORM_GRID_COLS - 1))]
    return specs


def build_form_trend_figure(
    monthly: pd.DataFrame, runs: pd.DataFrame
) -> go.Figure:
    """Build the running-dynamics small multiples: one panel per metric.

    All five panels share a monthly x-axis so their shapes can be read against
    one another -- which is the point. The comparison worth making is that
    cadence sits nearly flat while stride length swings: this athlete changes
    speed by lengthening the stride rather than by quickening the turnover.

    Every panel carries one line per surface rather than one pooled line, so a
    treadmill block never quietly moves an outdoor trend. On the two derived
    metrics the gap between the lines is partly the belt's distance
    calibration rather than a change in running, which is why they are dashed.

    **Individual runs are drawn behind each median**, faint and small. A monthly
    median hides how much it was a median *of*: five tight runs and five runs
    spread over 8 spm plot as the same point and are not the same training. The
    markers are added before the lines so the summary always draws on top of the
    detail.

    Each y-axis is scaled to the range the metric actually occupies rather than
    to zero. On a quantity that lives between 161 and 165 spm, a zero-based axis
    would flatten every real change into a straight line.

    Parameters
    ----------
    monthly : pandas.DataFrame
        Output of :func:`dashboard.activity_metrics.monthly_form_metrics`.
    runs : pandas.DataFrame
        Output of :func:`dashboard.activity_metrics.form_runs` -- the same easy
        runs the medians are taken over.

    Returns
    -------
    plotly.graph_objects.Figure
        A panel per metric in :data:`dashboard.activity_metrics.FORM_METRICS`
        order, each with per-run markers and a median line per surface.
    """
    positions = _form_grid_positions()
    rows = max(row for row, _ in positions)
    fig = make_subplots(
        rows=rows,
        cols=_FORM_GRID_COLS,
        specs=_form_grid_specs(positions),
        subplot_titles=[
            f"{m.label} ({m.unit})" for m in am.FORM_METRICS
        ],
        vertical_spacing=0.12,
        horizontal_spacing=0.10,
    )

    def _slice(frame: pd.DataFrame, key: str, surface: str) -> pd.DataFrame:
        """Rows of a long-format frame for one metric on one surface."""
        if frame.empty:
            return frame
        return frame[(frame["metric"] == key) & (frame["surface"] == surface)]

    for index, (metric, (row, col)) in enumerate(zip(am.FORM_METRICS, positions)):
        # Markers for every surface first, then the lines, so no run ever draws
        # over the median it belongs to.
        for surface in am.SURFACES:
            per_run = _slice(runs, metric.key, surface)
            fig.add_trace(
                go.Scatter(
                    x=per_run["date"] if not per_run.empty else [],
                    y=per_run["value"] if not per_run.empty else [],
                    name=f"{_SURFACE_LABELS[surface]} runs",
                    mode="markers",
                    marker=dict(
                        size=5,
                        color=_SURFACE_COLORS[surface],
                        opacity=0.38,
                        line=dict(width=0),
                    ),
                    legendgroup=surface,
                    # The legend key belongs to the median line; toggling it
                    # takes these with it through the shared legendgroup.
                    showlegend=False,
                    # Deliberately not hoverable. A run sits at its own date and
                    # a median at the first of its month, so under unified hover
                    # a card headed "14 Mar 2026" would carry March's whole
                    # median as one of its rows -- two different time
                    # granularities presented as one reading. The runs are here
                    # to be *seen*; the spread they form is reported numerically
                    # in the median's own card instead.
                    hoverinfo="skip",
                ),
                row=row,
                col=col,
            )

        for surface in am.SURFACES:
            series = _slice(monthly, metric.key, surface)
            fig.add_trace(
                go.Scatter(
                    x=series["month_start"] if not series.empty else [],
                    y=series["value"] if not series.empty else [],
                    name=_SURFACE_LABELS[surface],
                    mode="lines+markers",
                    line=dict(
                        color=_SURFACE_COLORS[surface],
                        width=2.5,
                        dash="solid" if metric.measured else "dash",
                    ),
                    marker=dict(size=7),
                    # One key for the whole grid: the surfaces mean the same
                    # thing in all five panels, so only the first announces them.
                    legendgroup=surface,
                    showlegend=index == 0,
                    customdata=(
                        series[["runs", "low", "high"]].to_numpy()
                        if not series.empty else []
                    ),
                    xhoverformat="%B %Y",
                    # No <extra></extra> and no %{x}: unified hover heads the
                    # card with the month and labels each row with the name.
                    # The range recovers what skipping the run hovers gave up.
                    hovertemplate=(
                        f"median %{{y:.{metric.decimals}f}} {metric.unit}"
                        "<br>%{customdata[0]} easy runs, "
                        f"%{{customdata[1]:.{metric.decimals}f}}–"
                        f"%{{customdata[2]:.{metric.decimals}f}}"
                    ),
                ),
                row=row,
                col=col,
            )

    fig.update_layout(
        **_layout(
            height=200 * rows + 110,
            title="Running form by month",
            # "x unified", and it has to be. Under "closest" this panel is a
            # lottery: both surfaces' medians share an x, and each is ringed by
            # the runs it summarises, so Plotly answers with whichever mark is
            # nearest in pixels. Measured over all 60 median points, 15 came
            # back as a neighbouring run or as the other surface -- the same
            # defect the volume chart was fixed for. Unified answers by x
            # instead, and with only the medians hoverable every point in the
            # column belongs to the month in the header.
            hovermode="x unified",
            # The default legend sits just above the plot area, which on a
            # subplot grid is exactly where the first row's panel titles are.
            margin=dict(l=50, r=30, t=58, b=76),
            legend=dict(orientation="h", yanchor="top", y=-0.07, xanchor="left", x=0),
        )
    )
    # Subplot titles are annotations, and the shared layout sizes them for a
    # single chart title; shrink them so five do not shout.
    for annotation in fig.layout.annotations:
        annotation.font.size = 12
    return fig


def _stride_isoline(stride_cm: float, paces: list[int]) -> list[float]:
    """Cadence values that produce a fixed stride length across a pace range.

    Stride length is not an independent measurement: Garmin computes it as
    speed divided by cadence. Rearranged for a constant stride, that is
    ``cadence = 6e6 / (pace_s_km * stride_cm)`` -- verified against the log to
    within a tenth of a centimetre.

    Parameters
    ----------
    stride_cm : float
        The stride length the line holds constant.
    paces : list of int
        Pace values in seconds per kilometre to evaluate at.

    Returns
    -------
    list of float
        Cadence in steps per minute at each pace.
    """
    return [6_000_000.0 / (pace * stride_cm) for pace in paces]


def build_cadence_pace_figure(trend: pd.DataFrame) -> go.Figure:
    """Build the cadence-against-pace scatter with stride-length isolines.

    This chart exists to answer one question the monthly panels cannot: when
    this athlete runs faster, does the turnover quicken or does the stride
    lengthen? Because stride length is exactly ``speed / cadence``, every point
    on the plane implies a stride, and the grey curves label it. A runner who
    quickens their turnover climbs the chart; one who lengthens their stride
    tracks across it, crossing isoline after isoline.

    Treadmill runs are drawn hollow, and the distinction matters more here than
    anywhere else on the tab. The isolines are exact only where the recorded
    distance is: measured across this log, they predict Garmin's own reported
    stride to a median 0.6 cm outdoors (worst case 8.8) but are out by a median
    10.8 cm on the belt, as much as 31.4, because there the recorded distance
    and the accelerometer's stride disagree. A hollow marker therefore sits at
    its true cadence but at a pace -- and so an implied stride -- only as good
    as the belt's calibration.

    Parameters
    ----------
    trend : pandas.DataFrame
        Output of :func:`dashboard.activity_metrics.pace_trend`.

    Returns
    -------
    plotly.graph_objects.Figure
        One marker per run, coloured by zone and hollow on the treadmill, over
        the stride-length isolines.
    """
    fig = go.Figure()
    usable = (
        trend.dropna(subset=["pace_s_km", "avg_cadence"])
        if not trend.empty else trend
    )

    if not usable.empty:
        ticks, tick_text = _pace_ticks(usable["pace_s_km"])
        span = [int(usable["pace_s_km"].min()) - 5, int(usable["pace_s_km"].max()) + 5]
        grid = list(range(span[0], span[1] + 1, 5))

        for stride in _ISOLINE_STRIDES_CM:
            fig.add_trace(
                go.Scatter(
                    x=grid,
                    y=_stride_isoline(stride, grid),
                    mode="lines",
                    line=dict(color=_COLOR_ISOLINE, width=1, dash="dot"),
                    name=f"{stride:.0f} cm stride",
                    legendgroup="isolines",
                    hoverinfo="skip",
                )
            )

        median_cadence = float(usable["avg_cadence"].median())
        fig.add_trace(
            go.Scatter(
                x=span,
                y=[median_cadence, median_cadence],
                mode="lines",
                line=dict(color=_COLOR_MEDIAN, width=2, dash="dash"),
                name=f"Median cadence {median_cadence:.0f} spm",
                hoverinfo="skip",
            )
        )

        for zone in [*_ZONE_COLORS, None]:
            group = (
                usable[usable["zone"].isna()] if zone is None
                else usable[usable["zone"] == zone]
            )
            if group.empty:
                continue
            zone_label = zone or "Unclassified"
            detail = group[["activity_name", "avg_stride_length_cm"]].copy()
            detail["surface"] = [
                _SURFACE_LABELS[
                    am.TREADMILL_SURFACE if t else am.OUTDOOR_SURFACE
                ].lower()
                for t in group["is_treadmill"]
            ]
            fig.add_trace(
                go.Scatter(
                    x=group["pace_s_km"],
                    y=group["avg_cadence"],
                    name=zone_label,
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
                    customdata=detail.to_numpy(),
                    text=[seconds_to_pace(p) for p in group["pace_s_km"]],
                    # Garmin's own stride, not the one the isolines imply: on an
                    # outdoor run the two agree, and on a belt run they do not.
                    hovertemplate=(
                        "%{customdata[0]}"
                        "<br>%{text}/km at %{y:.0f} spm (%{customdata[2]})"
                        "<br>%{customdata[1]:.0f} cm stride · " + zone_label
                        + "<extra></extra>"
                    ),
                )
            )

        fig.update_xaxes(
            title_text="Pace (min/km)",
            autorange="reversed",
            tickmode="array",
            tickvals=ticks,
            ticktext=tick_text,
        )
        # Clip to the cadence the athlete actually runs at. The isolines fan
        # out well above it -- 90 cm at 4:00/km implies 167 spm, 250 spm at the
        # top of the grid -- and letting them set the range would squash every
        # run into a band a few pixels tall. They run off the top instead,
        # which is what a reference guide should do.
        low = float(usable["avg_cadence"].min())
        high = float(usable["avg_cadence"].max())
        pad = max(3.0, (high - low) * 0.12)
        fig.update_yaxes(title_text="Cadence (spm)", range=[low - pad, high + pad])

    fig.update_layout(
        **_layout(
            height=460,
            title="Cadence against pace",
            # Ten traces wrap the legend over several rows; above the plot they
            # would sit on top of the title.
            margin=dict(l=50, r=30, t=58, b=104),
            legend=dict(orientation="h", yanchor="top", y=-0.16, xanchor="left", x=0),
        )
    )
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


def _form_delta_html(headline: am.FormHeadline) -> str:
    """Render a form metric's 28-day change, coloured only where it means something.

    A metric with no good direction -- stride length -- and a change too small
    to survive rounding both render neutral. Colouring them would assert an
    improvement the number does not support.
    """
    metric = headline.metric
    if headline.delta is None:
        return "<span style='color:#94a3b8'>no prior 28 days to compare</span>"

    magnitude = f"{abs(headline.delta):.{metric.decimals}f} {metric.unit}"
    improved = headline.improved
    if improved is None and abs(headline.delta) < 0.5 * 10 ** -metric.decimals:
        return "<span style='color:#94a3b8'>level with the prior 28 days</span>"

    arrow = "▲" if headline.delta > 0 else "▼"
    if improved is None:
        return (
            f"<span style='color:#94a3b8'>{arrow} {magnitude} vs prior 28 d</span>"
        )
    color = "#16a34a" if improved else "#dc2626"
    return f"<span style='color:{color}'>{arrow} {magnitude} vs prior 28 d</span>"


def _treadmill_html(headline: am.FormHeadline) -> str:
    """Render the treadmill median beside the outdoor one it never joins."""
    if headline.treadmill_value is None:
        return "<span style='color:#94a3b8'>no treadmill runs</span>"
    metric = headline.metric
    plural = "s" if headline.treadmill_runs > 1 else ""
    return (
        f"<span style='color:{_COLOR_TREADMILL}'>treadmill "
        f"{headline.treadmill_value:.{metric.decimals}f} {escape(metric.unit)}"
        f"</span> <span style='color:#94a3b8'>({headline.treadmill_runs} "
        f"run{plural})</span>"
    )


def _form_cards(headlines: list[am.FormHeadline]) -> str:
    """Render the running-form header cards, one per metric.

    The headline number is the outdoor median and the change beneath it is
    outdoor-against-outdoor, so every card means the same thing. The treadmill
    median sits on its own line rather than being folded in.
    """
    cards = []
    for headline in headlines:
        metric = headline.metric
        if headline.value is None:
            value, sub = "—", "no outdoor easy runs in the last 28 days"
        else:
            value = f"{headline.value:.{metric.decimals}f} {metric.unit}"
            sub = _form_delta_html(headline)
        cards.append((metric.label, value, sub, _treadmill_html(headline)))

    rendered = "".join(
        f"<div class='card'><div class='card-label'>{escape(label)}</div>"
        f"<div class='card-value'>{escape(value)}</div>"
        f"<div class='card-sub'>{sub}<br>{belt}</div></div>"
        for label, value, sub, belt in cards
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
    form_monthly = am.monthly_form_metrics(trend)
    form_per_run = am.form_runs(trend)
    form_headlines = am.form_headline(trend, today)

    charts = [
        build_volume_figure(runs, today),
        build_cumulative_figure(runs, today),
        build_calendar_figure(runs, today),
        build_pace_figure(trend, monthly),
        build_efficiency_figure(efficiency),
        build_form_trend_figure(form_monthly, form_per_run),
        build_cadence_pace_figure(trend),
    ]
    div_ids = [_VOLUME_DIV_ID, None, None, None, None, None, None]
    (
        volume, cumulative, calendar, pace, efficiency_chart,
        form_trend, cadence_pace,
    ) = [
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
  summary, and is not computed here.</p>

  <h2 style="margin-top:28px">Running form</h2>
  {_form_cards(form_headlines)}
  <p class="note">The big number is the median of your <strong>outdoor</strong>
  easy runs over the last 28 days, against the 28 days before it; the treadmill
  median sits underneath it, never folded in.
  <strong>Every one of these metrics moves with pace</strong> — across this log,
  pace alone explains 95% of the variation in stride length and 96% in vertical
  ratio — so the cards and the panels below use easy runs only. Mixing in a hard
  session would report how fast you chose to run, not how you ran.</p>

  <div class="panel">{form_trend}</div>
  <p class="note">The faint dots are <strong>individual easy runs</strong>; the
  line through them is the monthly median. The spread is worth as much as the
  line — five tight runs and five scattered over 8 spm make the same median out
  of very different training — so hovering a month gives you both surfaces'
  medians, the number of runs behind each, and the range they span. The dots
  themselves are not hoverable: they sit on their own dates while a median sits
  on the first of its month, and one tooltip cannot honestly head both.</p>
  <p class="note">Teal is outdoor, orange is treadmill, in every panel and in
  the chart below. <strong>Solid</strong> panels are measured directly by the
  watch's accelerometer, so their two lines are comparable.
  <strong>Dashed</strong> panels are <em>derived</em> — stride length is
  speed ÷ cadence, vertical ratio is vertical oscillation ÷ stride length — so
  there the gap between the two lines is partly your treadmill's distance
  calibration rather than anything you did differently. The derived pair are
  shown because they are the numbers Garmin reports, but they carry no
  information the measured channels and your pace do not already hold.</p>
  <p class="src-note">Each panel is scaled to the range its metric occupies, not
  to zero — on a quantity that lives between 161 and 165 spm a zero-based axis
  would flatten every real change into a flat line. Read the axis before reading
  the slope.</p>

  <div class="panel">{cadence_pace}</div>
  <p class="note">Every point on this plane implies a stride length, because
  stride <em>is</em> speed ÷ cadence; the dotted curves label it. A runner who
  gets faster by quickening their turnover climbs the chart. One who gets faster
  by reaching further travels across it, crossing curve after curve — which is
  what this log shows: cadence holds near the dashed median across the whole
  pace range while stride length spans some 87 to 146 cm.</p>
  <p class="src-note">Hollow markers are treadmill runs, and here the
  distinction bites hardest. Checked against every run on record, the curves
  predict Garmin's own reported stride to within a median 0.6 cm outdoors, but
  are out by a median 10.8 cm — up to 31.4 — on the belt, where the recorded
  distance and the accelerometer's stride disagree. A hollow marker sits at its
  true cadence, but at an implied stride only as good as your treadmill's
  calibration. Read the solid markers for the shape of the relationship.</p>

  <p class="src-note">Nothing in this section averages a treadmill run together
  with an outdoor one. Cadence, vertical oscillation and ground contact are
  accelerometer measurements and are as valid on a belt as on the street, so
  their two lines are directly comparable; stride length and vertical ratio are
  computed from recorded distance, so their treadmill line carries the belt's
  calibration with it. Splitting rather than excluding is what keeps every
  session on the page — a third of this log is indoors — while still letting an
  outdoor trend stand on its own.</p>"""
