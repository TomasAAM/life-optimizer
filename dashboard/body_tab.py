"""Render the body-composition tab: weight trend, composition split, strength ratios.

Consumes the aggregations in :mod:`dashboard.body_metrics` and emits Plotly
figures plus one self-contained HTML fragment, the same way
:mod:`dashboard.metrics_tab` supplies the metrics tab. ``build`` wires the
fragment into the page, so :mod:`dashboard.render` never has to know this module
exists.

Two presentation rules follow from what the scale actually measures:

* **Dashed means derived**, matching the running-form section. The fat/lean
  split is computed from one bioimpedance estimate, so its boundaries are drawn
  dashed to say that no independent measurement stands behind them.
* **Relative strength is a card row, not a chart.** The working loads are
  constants, so a load-over-bodyweight curve is the weight curve inverted and
  rescaled -- it would look like a second finding while carrying no information
  the weight chart does not already show.
"""

from __future__ import annotations

from datetime import date
from html import escape

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard import body_metrics as bm
from dashboard import theme
from plan import config

_COLOR_TREND = "#2563eb"     # blue  - the trend line, the number to read
_COLOR_RAW = "#94a3b8"       # grey  - individual readings, deliberately quiet
_COLOR_FAT = "#F08A2E"       # orange - fat mass
_COLOR_LEAN = "#0E7C86"      # teal   - lean mass, matching "outdoor" elsewhere
_COLOR_NEUTRAL = "#94a3b8"
_COLOR_GOOD = "#16a34a"
_COLOR_BAD = "#dc2626"

# Weigh-ins are instants, not days, and the hour is what tells you whether a
# reading was on protocol -- so the unified hover header carries the clock.
_HOVER_STAMP = "%a %d %b %Y, %H:%M"

# Below this the config constant and the measured weight are close enough that
# flagging the gap would be noise.
_CONFIG_GAP_TOLERANCE_KG = 1.0


def _layout(hovermode: str = "x unified", **overrides) -> dict:
    """Return the shared chart layout with this tab's margins applied.

    Defaults to ``"x unified"`` rather than ``"closest"``: every figure here is
    a time series carrying more than one series, which is exactly the case the
    2026-09-08 hover fix addressed -- under ``"closest"`` such a chart answers
    with the nearest *point* rather than the reading being pointed at.

    Parameters
    ----------
    hovermode : str, optional
        Plotly hover mode.
    **overrides
        Per-figure layout keys, typically ``height`` and ``title``.

    Returns
    -------
    dict
        Keyword arguments for ``Figure.update_layout``.
    """
    margin = overrides.pop("margin", dict(l=54, r=30, t=58, b=40))
    legend = overrides.pop(
        "legend",
        dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
    )
    return theme.chart_layout(
        margin=margin, hovermode=hovermode, legend=legend, **overrides
    )


def build_weight_figure(weigh_ins: pd.DataFrame) -> go.Figure:
    """Build the weight chart: individual readings under a trailing-mean trend.

    Both series are drawn because neither alone is honest. The trend is the
    number worth reading, but shown by itself it implies a precision the scale
    does not have; the raw points make the roughly one-kilogram day-to-day
    spread visible, which is the context that stops a single reading being
    mistaken for a change.

    Parameters
    ----------
    weigh_ins : pandas.DataFrame
        Output of :func:`dashboard.body_metrics.prepare_weigh_ins`.

    Returns
    -------
    plotly.graph_objects.Figure
        Raw readings as markers, the trend as a line.
    """
    fig = go.Figure()

    if not weigh_ins.empty:
        trend = bm.trend_series(weigh_ins)
        fig.add_trace(
            go.Scatter(
                x=weigh_ins["measured_at_local"],
                y=weigh_ins["weight_kg"],
                name="Reading",
                mode="markers",
                marker=dict(size=7, color=_COLOR_RAW),
                xhoverformat=_HOVER_STAMP,
                # No <extra></extra>: under unified hover the trace name labels
                # the row and the timestamp already heads the card.
                hovertemplate="%{y:.2f} kg",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=trend["measured_at_local"],
                y=trend["trend_kg"],
                name=f"{bm.TREND_WINDOW_DAYS}-day trend",
                mode="lines",
                line=dict(color=_COLOR_TREND, width=2.5),
                xhoverformat=_HOVER_STAMP,
                hovertemplate="%{y:.2f} kg",
            )
        )

    fig.update_layout(**_layout(height=340, title="Bodyweight"))
    # Not zero-based on purpose: bodyweight lives in a narrow band, and a
    # zero-based axis would flatten every real change into a flat line.
    fig.update_yaxes(title_text="Weight (kg)")
    return fig


def build_composition_figure(composition: pd.DataFrame) -> go.Figure:
    """Build the fat/lean split as two independently scaled panels.

    Deliberately *not* a stacked area, though that was the obvious choice. Lean
    mass is four to five times fat mass, so on one shared zero-based axis a real
    1 kg shift in fat is a sliver a pixel or two high and both bands read as
    flat -- the chart would look like an answer while showing nothing. Two
    panels, each scaled to the range its own series occupies, is the same
    trade-off the running-form small multiples settled on 2026-09-09: read the
    axis before reading the slope.

    Nothing is lost by unstacking. The two series sum to bodyweight by
    construction, since both are derived from it, so the total is already the
    weight chart above.

    Parameters
    ----------
    composition : pandas.DataFrame
        Output of :func:`dashboard.body_metrics.composition_series`.

    Returns
    -------
    plotly.graph_objects.Figure
        Fat mass and lean mass side by side, each on its own scale.
    """
    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("Fat mass", "Lean mass"),
        horizontal_spacing=0.12,
    )

    if not composition.empty:
        panels = (
            (1, "fat_mass_kg", "Fat mass", _COLOR_FAT),
            (2, "lean_mass_kg", "Lean mass", _COLOR_LEAN),
        )
        for col, column, name, color in panels:
            fig.add_trace(
                go.Scatter(
                    x=composition["measured_at_local"],
                    y=composition[column],
                    name=name,
                    mode="lines+markers",
                    # Dashed throughout: both series rest on one bioimpedance
                    # estimate rather than on a measurement.
                    line=dict(color=color, width=2, dash="dash"),
                    marker=dict(size=6),
                    showlegend=False,
                    xhoverformat=_HOVER_STAMP,
                    hovertemplate="%{y:.2f} kg",
                ),
                row=1,
                col=col,
            )

    fig.update_layout(
        **_layout(height=320, title="Composition (estimated)", margin=dict(
            l=54, r=30, t=76, b=40,
        ))
    )
    # Auto-scaled rather than zero-based, for the reason in the docstring.
    fig.update_yaxes(title_text="kg", row=1, col=1)
    fig.update_yaxes(title_text="kg", row=1, col=2)
    for annotation in fig.layout.annotations:
        annotation.font.size = 12
    return fig


def _weight_delta_html(headline: bm.BodyHeadline) -> str:
    """Render the 28-day trend change, uncoloured.

    Deliberately neutral. A rising or falling bodyweight has no universally
    good direction -- for a concurrent Hyrox and 21k build, holding weight
    while the loads go up is the goal -- so colouring it would assert a verdict
    the number does not support. The rate card carries the one judgement that
    is defensible.
    """
    if headline.delta_kg is None:
        return f"<span style='color:{_COLOR_NEUTRAL}'>no prior 28 days to compare</span>"
    if abs(headline.delta_kg) < 0.05:
        return f"<span style='color:{_COLOR_NEUTRAL}'>level over 28 days</span>"
    arrow = "▲" if headline.delta_kg > 0 else "▼"
    return (
        f"<span style='color:{_COLOR_NEUTRAL}'>{arrow} "
        f"{abs(headline.delta_kg):.2f} kg over 28 days</span>"
    )


def _rate_html(rate: float | None) -> str:
    """Render the fitted rate of change, coloured only past the loss floor.

    The only claim the data supports is that losing faster than
    :data:`dashboard.body_metrics.AGGRESSIVE_LOSS_KG_WEEK` costs lean mass and
    session quality, so that is the only case coloured as a problem.
    """
    if rate is None:
        return (
            f"<span style='color:{_COLOR_NEUTRAL}'>needs 3 readings over "
            f"a week to fit</span>"
        )
    if rate < bm.AGGRESSIVE_LOSS_KG_WEEK:
        return (
            f"<span style='color:{_COLOR_BAD}'>faster than "
            f"{abs(bm.AGGRESSIVE_LOSS_KG_WEEK):.1f} kg/wk — costs lean mass</span>"
        )
    if abs(rate) < 0.1:
        return f"<span style='color:{_COLOR_GOOD}'>holding steady</span>"
    direction = "losing" if rate < 0 else "gaining"
    return f"<span style='color:{_COLOR_NEUTRAL}'>{direction} steadily</span>"


def _cards(headline: bm.BodyHeadline) -> str:
    """Render the body-composition header cards."""
    if headline.trend_weight_kg is None:
        return ""

    fat = (
        "—" if headline.body_fat_pct is None
        else f"{headline.body_fat_pct:.1f}%"
    )
    fat_sub = (
        f"<span style='color:{_COLOR_NEUTRAL}'>no impedance reading</span>"
        if headline.fat_mass_kg is None
        else f"<span style='color:{_COLOR_NEUTRAL}'>"
             f"{headline.fat_mass_kg:.1f} kg of fat mass</span>"
    )
    lean = (
        "—" if headline.lean_mass_kg is None
        else f"{headline.lean_mass_kg:.1f} kg"
    )
    # The unit lives in the label rather than the value: "-0.25 kg/wk" is
    # wide enough to wrap the mono card value onto a second line.
    rate = (
        "—" if headline.rate_kg_week is None
        else f"{headline.rate_kg_week:+.2f}"
    )
    off = headline.off_protocol
    protocol_sub = (
        f"<span style='color:{_COLOR_GOOD}'>all on protocol</span>" if off == 0
        else f"<span style='color:{_COLOR_NEUTRAL}'>{off} taken after "
             f"{bm.PROTOCOL_LATEST_HOUR:02d}:00</span>"
    )

    cards = [
        ("Weight (trend)", f"{headline.trend_weight_kg:.1f} kg",
         _weight_delta_html(headline)),
        ("Rate of change (kg/wk)", rate, _rate_html(headline.rate_kg_week)),
        ("Body fat", fat, fat_sub),
        ("Lean mass", lean,
         f"<span style='color:{_COLOR_NEUTRAL}'>weight less fat mass</span>"),
        ("Weigh-ins", f"{headline.readings}", protocol_sub),
    ]
    rendered = "".join(
        f"<div class='card'><div class='card-label'>{escape(label)}</div>"
        f"<div class='card-value'>{escape(value)}</div>"
        f"<div class='card-sub'>{sub}</div></div>"
        for label, value, sub in cards
    )
    return f"<div class='cards'>{rendered}</div>"


def _strength_cards(ratios: list[bm.RelativeStrength]) -> str:
    """Render each working load as a multiple of the measured trend weight."""
    if not ratios:
        return ""
    rendered = "".join(
        f"<div class='card'><div class='card-label'>{escape(r.label)}</div>"
        f"<div class='card-value'>{r.ratio:.2f}×</div>"
        f"<div class='card-sub'><span style='color:{_COLOR_NEUTRAL}'>"
        f"{r.load_kg:.0f} kg working load</span></div></div>"
        for r in ratios
    )
    return f"<div class='cards'>{rendered}</div>"


def _config_callout(gap: float | None) -> str:
    """Warn when the plan config's bodyweight constant has drifted from reality.

    ``BENCHMARKS.md`` computes every relative-strength figure against
    :data:`plan.config.ATHLETE_BODYWEIGHT_KG`. A stale constant rescales all of
    them at once, silently, which is precisely the sort of error that survives
    for months -- so the gap is stated on the page.
    """
    if gap is None or abs(gap) < _CONFIG_GAP_TOLERANCE_KG:
        return ""
    direction = "heavier" if gap > 0 else "lighter"
    return (
        f"<div class='callout'>Your measured trend weight is "
        f"<strong>{abs(gap):.1f} kg {direction}</strong> than the "
        f"<code>ATHLETE_BODYWEIGHT_KG = {config.ATHLETE_BODYWEIGHT_KG:.1f}</code> "
        f"constant in <code>plan/config.py</code>. Every relative-strength "
        f"figure in <code>BENCHMARKS.md</code> is computed against that "
        f"constant, so until it is updated they are all misscaled by this "
        f"much.</div>"
    )


def _empty_html() -> str:
    """Render the tab before the feed has delivered anything.

    Says what to do rather than only that there is nothing, because the setup
    is a handful of steps outside this repo and forgetting one of them looks
    exactly like having no data.
    """
    return (
        "<h2>Body composition</h2>"
        "<div class='panel'><p>No weigh-ins on record yet.</p>"
        "<p class='note'>This tab reads the <code>body_composition</code> table, "
        "which is fed from the smart scale through Android Health Connect: the "
        "Fitdays app writes each measurement to Health Connect, an on-device "
        "exporter auto-exports the body-measurement records to a Google Sheet, "
        "and that sheet — published to the web as CSV — is read by "
        "<code>ingest/body_composition.py</code>. Set "
        "<code>BODY_SHEET_CSV_URL</code> to the published-CSV link to switch the "
        "feed on. Health Connect is an on-device store with no server-side API, "
        "so the sheet is what makes the data reachable from CI at all.</p></div>"
    )


def body_section_html(body: pd.DataFrame, today: date) -> str:
    """Render the whole body-composition tab: cards, charts and their caveats.

    Parameters
    ----------
    body : pandas.DataFrame
        Rows as returned by :func:`dashboard.query.fetch_body_composition`.
    today : datetime.date
        The day the dashboard is being built for.

    Returns
    -------
    str
        An HTML fragment for the body-composition tab panel.
    """
    weigh_ins = bm.prepare_weigh_ins(body)
    if weigh_ins.empty:
        return _empty_html()

    headline = bm.headline(weigh_ins, today)
    composition = bm.composition_series(weigh_ins)
    ratios = bm.relative_strength(headline.trend_weight_kg)
    gap = bm.config_weight_disagreement(headline.trend_weight_kg)

    weight_chart = build_weight_figure(weigh_ins).to_html(
        full_html=False, include_plotlyjs=False
    )
    composition_chart = build_composition_figure(composition).to_html(
        full_html=False, include_plotlyjs=False
    )

    composition_block = ""
    if composition.empty:
        composition_block = (
            "<p class='note'>No reading yet carries a body-fat estimate, so "
            "there is no fat/lean split to show. A weigh-in with bare feet on "
            "the electrodes is what produces one; weight records on its own "
            "either way.</p>"
        )
    else:
        composition_block = f"""<div class="panel">{composition_chart}</div>
  <p class="note">The one question worth asking of a weight change is which
  tissue left, and these two panels answer it: read the fall in each against
  the fall in your weight above. <strong>Both are dashed because the split is
  derived, not measured.</strong> The scale passes a small current between your
  feet and infers everything from its impedance through the vendor's
  undisclosed regression, so fat and lean mass are one estimate shown two ways
  rather than two findings. Read the direction over months; ignore the wobble
  between readings, which is mostly how hydrated you were.</p>
  <p class="src-note">Each panel is scaled to its own range rather than to
  zero, and they are not stacked. Lean mass is four to five times fat mass, so
  a shared zero-based axis renders a real 1 kg shift in fat as a sliver and
  both series read as flat — the same reason the running-form panels are scaled
  individually. Nothing is lost by unstacking: the two sum to your bodyweight
  by construction, because both are derived from it.</p>"""

    strength_block = ""
    if ratios:
        strength_block = f"""<h2 style="margin-top:28px">Relative strength</h2>
  {_strength_cards(ratios)}
  <p class="note">Each working load from <code>plan/config.py</code> over your
  measured trend weight, rather than over the self-reported constant the plan
  engine uses. Power-to-weight is what the running half of Hyrox rewards, so
  absolute kilograms alone mislead — the same load gets stronger in this sense
  every kilogram you drop, and weaker every kilogram you add.</p>
  <p class="src-note">Only the four lifts recorded as an unambiguous total in
  kilograms appear. The weighted pull-up is excluded because its load
  <em>is</em> bodyweight, which makes a bodyweight ratio circular; step-ups and
  dumbbell bench press are recorded per hand, so the figure in the
  prescription is half the load lifted. This is a card row rather than a chart
  on purpose: the loads are constants, so plotting the ratio over time would
  just redraw the weight curve upside down and dress it up as a second
  finding.</p>"""

    protocol_note = ""
    if headline.off_protocol:
        plural = "s" if headline.off_protocol > 1 else ""
        protocol_note = (
            f"<p class='src-note'>{headline.off_protocol} reading{plural} "
            f"{'were' if headline.off_protocol > 1 else 'was'} taken at or "
            f"after {bm.PROTOCOL_LATEST_HOUR:02d}:00, off the fasted-morning "
            f"protocol in <code>BENCHMARKS.md</code>. A same-day evening "
            f"weigh-in reads 1–1.5 kg heavier than a fasted morning one from "
            f"food and fluid alone, so those points sit high for a reason that "
            f"has nothing to do with training. They are kept and flagged rather "
            f"than dropped — the timestamp is in every tooltip.</p>"
        )

    return f"""<h2>Body composition</h2>
  {_cards(headline)}
  {_config_callout(gap)}
  <div class="panel">{weight_chart}</div>
  <p class="note">The grey dots are individual weigh-ins; the blue line is the
  {bm.TREND_WINDOW_DAYS}-day trailing mean. <strong>The line is the number to
  read and the dots are why.</strong> A single reading carries roughly a
  kilogram of hydration, glycogen and gut content, so two readings a day apart
  can differ by more than a month of real change. The window is
  {bm.TREND_WINDOW_DAYS} days rather than 7 because the prescribed cadence is
  weekly — a 7-day window over weekly readings contains one reading and smooths
  nothing.</p>
  <p class="src-note">Rate of change is a least-squares fit over the last
  {bm.RATE_WINDOW_DAYS} days, not the difference between two readings, which
  would carry the full noise of both. It is withheld entirely below three
  readings spanning a week: a slope fitted to less than that is noise scaled up
  to a weekly figure.</p>
  {protocol_note}

  <h2 style="margin-top:28px">Composition</h2>
  {composition_block}
  {strength_block}

  <p class="src-note">Weight comes off the scale's load cell and is a
  measurement. Everything else on this tab comes from one bioimpedance
  reading. The scale also reports visceral fat, metabolic age, physique rating
  and BMI, none of which appear here: Health Connect has no record type for
  them, and each is another transform of that same impedance number, so nothing
  independent is lost in transit.</p>"""
