"""Render the training dashboard to a self-contained HTML file.

Produces a two-panel Plotly figure (training-load model + HRV trend) wrapped in
a lightweight HTML shell with a header of current-state cards and a weekly
summary table. Plotly.js is loaded from a CDN to keep the committed file small.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard import zones
from dashboard.metrics import CTL_WARMUP_DAYS, ReadinessSnapshot

_COLOR_CTL = "#2563eb"   # blue  - fitness
_COLOR_ATL = "#f97316"   # orange - fatigue
_COLOR_TSB = "#16a34a"   # green - form
_COLOR_LOAD = "#cbd5e1"  # grey  - daily load bars
_COLOR_HRV = "#7c3aed"   # violet - nightly HRV
_COLOR_BAND = "rgba(124, 58, 237, 0.15)"  # HRV baseline band fill


def build_figure(load_series: pd.DataFrame, hrv_series: pd.DataFrame) -> go.Figure:
    """Build the two-panel training/recovery figure.

    Parameters
    ----------
    load_series : pandas.DataFrame
        Output of :func:`dashboard.metrics.build_load_series`.
    hrv_series : pandas.DataFrame
        Output of :func:`dashboard.metrics.build_hrv_series`.

    Returns
    -------
    plotly.graph_objects.Figure
        Figure with a load panel (row 1) and an HRV panel (row 2).
    """
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.09,
        row_heights=[0.62, 0.38],
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
        subplot_titles=("Training load: fitness, fatigue & form", "HRV vs baseline"),
    )

    # --- Row 1: daily load bars + CTL/ATL lines (primary), TSB (secondary) ---
    fig.add_trace(
        go.Bar(
            x=load_series.index,
            y=load_series["load"],
            name="Daily load",
            marker_color=_COLOR_LOAD,
            opacity=0.7,
            hovertemplate="%{x|%a %d %b}<br>Load: %{y:.0f}<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=load_series.index,
            y=load_series["ctl"],
            name="CTL (fitness)",
            line=dict(color=_COLOR_CTL, width=2.5),
            hovertemplate="%{x|%a %d %b}<br>CTL: %{y:.1f}<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=load_series.index,
            y=load_series["atl"],
            name="ATL (fatigue)",
            line=dict(color=_COLOR_ATL, width=1.8),
            hovertemplate="%{x|%a %d %b}<br>ATL: %{y:.1f}<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=False,
    )
    # TSB is unreliable during the CTL warm-up (CTL seeds from zero), so mask
    # that window to NaN: the line simply starts once the value is meaningful,
    # which also keeps the secondary axis scaled to the usable range.
    tsb_display = load_series["tsb"].copy()
    if len(tsb_display) > CTL_WARMUP_DAYS:
        tsb_display.iloc[:CTL_WARMUP_DAYS] = float("nan")
    fig.add_trace(
        go.Scatter(
            x=load_series.index,
            y=tsb_display,
            name="TSB (form)",
            line=dict(color=_COLOR_TSB, width=1.6, dash="dot"),
            connectgaps=False,
            hovertemplate="%{x|%a %d %b}<br>TSB: %{y:.1f}<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=True,
    )

    # Shade the CTL warm-up window where TSB is unreliable.
    if len(load_series) > 0:
        warmup_end = load_series.index[min(CTL_WARMUP_DAYS, len(load_series) - 1)]
        fig.add_vrect(
            x0=load_series.index[0],
            x1=warmup_end,
            fillcolor="rgba(148, 163, 184, 0.12)",
            line_width=0,
            row=1,
            col=1,
            annotation_text="warm-up (TSB unreliable)",
            annotation_position="top left",
            annotation_font_size=10,
        )

    # Zero reference for TSB on the secondary axis.
    fig.add_hline(y=0, line=dict(color="#94a3b8", width=1, dash="dash"),
                  row=1, col=1, secondary_y=True)

    # --- Row 2: HRV nightly + baseline band ---
    if not hrv_series.empty:
        fig.add_trace(
            go.Scatter(
                x=hrv_series.index,
                y=hrv_series["baseline_high"],
                name="Baseline high",
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            ),
            row=2,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=hrv_series.index,
                y=hrv_series["baseline_low"],
                name="Baseline band",
                fill="tonexty",
                fillcolor=_COLOR_BAND,
                line=dict(width=0),
                hoverinfo="skip",
            ),
            row=2,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=hrv_series.index,
                y=hrv_series["hrv_night"],
                name="HRV (last night)",
                mode="lines+markers",
                line=dict(color=_COLOR_HRV, width=2),
                marker=dict(size=5),
                hovertemplate="%{x|%a %d %b}<br>HRV: %{y:.0f} ms<extra></extra>",
            ),
            row=2,
            col=1,
        )

    fig.update_yaxes(title_text="Load / CTL / ATL", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="TSB", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="HRV (ms)", row=2, col=1)
    fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.05), row=2, col=1)

    fig.update_layout(
        height=760,
        template="plotly_white",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="left", x=0),
        margin=dict(l=60, r=30, t=70, b=30),
        barmode="overlay",
    )
    return fig


def _snapshot_cards(snapshot: ReadinessSnapshot) -> str:
    """Render the header cards (CTL/ATL/TSB/HRV) as an HTML fragment."""
    hrv_text = (
        f"{snapshot.hrv_night:.0f} ms" if snapshot.hrv_night is not None else "n/a"
    )
    hrv_status = snapshot.hrv_status or "n/a"
    cards = [
        ("Fitness (CTL)", f"{snapshot.ctl:.1f}", "42-day load average"),
        ("Fatigue (ATL)", f"{snapshot.atl:.1f}", "7-day load average"),
        ("Form (TSB)", f"{snapshot.tsb:+.1f}", snapshot.tsb_label),
        ("HRV last night", hrv_text, f"status: {hrv_status}"),
    ]
    items = "".join(
        f"""
        <div class="card">
            <div class="card-label">{label}</div>
            <div class="card-value">{value}</div>
            <div class="card-sub">{sub}</div>
        </div>"""
        for label, value, sub in cards
    )
    return f'<div class="cards">{items}</div>'


def _weekly_table(weekly: pd.DataFrame) -> str:
    """Render the weekly summary DataFrame as an HTML table fragment."""
    if weekly.empty:
        return "<p>No weekly data yet.</p>"

    header = (
        "<tr><th>Week of</th><th>Total load</th><th>Training days</th>"
        "<th>Form (TSB)</th><th>HRV status</th></tr>"
    )
    body = "".join(
        f"<tr><td>{r.week_start}</td><td>{r.total_load:.0f}</td>"
        f"<td>{r.training_days}</td><td>{r.end_tsb:+.1f}</td>"
        f"<td>{r.end_hrv_status or '-'}</td></tr>"
        for r in weekly.itertuples()
    )
    return f"<table class='weekly'>{header}{body}</table>"


def render_html(
    fig: go.Figure,
    snapshot: ReadinessSnapshot,
    weekly: pd.DataFrame,
    zones_fig: go.Figure,
    pace_fig: go.Figure,
) -> str:
    """Assemble the full HTML document.

    Parameters
    ----------
    fig : plotly.graph_objects.Figure
        The two-panel figure from :func:`build_figure`.
    snapshot : ReadinessSnapshot
        Current-state snapshot for the header cards.
    weekly : pandas.DataFrame
        Weekly summary from :func:`dashboard.metrics.weekly_summary`.
    zones_fig : plotly.graph_objects.Figure
        The HR-zone comparison band chart from
        :func:`dashboard.zones.build_zone_comparison_figure`.
    pace_fig : plotly.graph_objects.Figure
        The pace-zone comparison band chart from
        :func:`dashboard.zones.build_pace_comparison_figure`.

    Returns
    -------
    str
        A complete, self-contained HTML document.
    """
    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")
    # plotly.js is already loaded by the chart above; don't ship it twice.
    zones_chart_html = zones_fig.to_html(full_html=False, include_plotlyjs=False)
    pace_chart_html = pace_fig.to_html(full_html=False, include_plotlyjs=False)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    as_of = snapshot.date.strftime("%A, %d %B %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Training Dashboard</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         margin: 0; background: #f8fafc; color: #0f172a; }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px 18px 60px; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 2px; }}
  .as-of {{ color: #64748b; font-size: 0.9rem; margin-bottom: 20px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
           gap: 12px; margin-bottom: 24px; }}
  .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
          padding: 16px 18px; }}
  .card-label {{ font-size: 0.8rem; color: #64748b; }}
  .card-value {{ font-size: 1.8rem; font-weight: 600; margin: 4px 0; }}
  .card-sub {{ font-size: 0.8rem; color: #475569; }}
  .panel {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
           padding: 10px; margin-bottom: 24px; }}
  h2 {{ font-size: 1.1rem; margin: 8px 4px 12px; }}
  table.weekly {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
  table.weekly th, table.weekly td {{ text-align: left; padding: 8px 10px;
          border-bottom: 1px solid #e2e8f0; }}
  table.weekly th {{ color: #64748b; font-weight: 600; }}
  table.weekly tr:first-child td {{ font-weight: 600; }}
  /* tabs */
  .tabs {{ display: flex; gap: 4px; border-bottom: 1px solid #e2e8f0; margin-bottom: 20px; }}
  .tab-btn {{ background: none; border: none; padding: 10px 16px; font-size: 0.95rem;
          color: #64748b; cursor: pointer; border-bottom: 2px solid transparent; }}
  .tab-btn:hover {{ color: #0f172a; }}
  .tab-btn.active {{ color: #2563eb; border-bottom-color: #2563eb; font-weight: 600; }}
  .tab-panel {{ display: none; }}
  .tab-panel.active {{ display: block; }}
  /* zone comparison table */
  table.zones {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
  table.zones th, table.zones td {{ text-align: center; padding: 8px 10px;
          border-bottom: 1px solid #e2e8f0; }}
  table.zones th:first-child, table.zones td:first-child {{ text-align: left; }}
  table.zones th {{ color: #64748b; font-weight: 600; }}
  table.zones .muted {{ color: #94a3b8; font-size: 0.85rem; }}
  .callout {{ background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 10px;
          padding: 12px 16px; margin: 0 0 18px; font-size: 0.95rem; color: #1e3a8a; }}
  .note {{ color: #475569; font-size: 0.88rem; line-height: 1.5; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Training Dashboard</h1>
  <div class="as-of">As of {as_of}</div>

  <div class="tabs">
    <button class="tab-btn active" data-tab="training">Training load</button>
    <button class="tab-btn" data-tab="zones">Zones</button>
  </div>

  <div class="tab-panel active" id="tab-training">
    {_snapshot_cards(snapshot)}
    <div class="panel">{chart_html}</div>
    <h2>Weekly summary</h2>
    <div class="panel">{_weekly_table(weekly)}</div>
  </div>

  <div class="tab-panel" id="tab-zones">
    <h2>Heart-rate zones: lab vs platforms</h2>
    <div class="callout">{zones.example_hr_callout(165)}</div>
    <div class="panel">{zones_chart_html}</div>
    <div class="panel">{zones.zone_table_html()}</div>
    <p class="note">Your <strong>Lab</strong> zones are anchored on the measured
    anaerobic threshold (LT2 ≈ {zones.LAB_LT2_HR} bpm) from the 2026-06-19 lactate
    test. <strong>Garmin</strong> and <strong>Strava</strong> anchor on an assumed
    maximum heart rate (~200 and ~190), not threshold — so their hard zones sit
    well above your real ones. Garmin even stores a threshold HR of 175 but uses
    %max-HR for the zones. Net effect: a heart rate the lab calls threshold/VO2max
    still reads as Z3-Z4 on the platforms.</p>

    <h2 style="margin-top:28px">Pace zones: lab vs Strava</h2>
    <div class="callout">{zones.example_pace_callout("4:30")}</div>
    <div class="panel">{pace_chart_html}</div>
    <div class="panel">{zones.pace_table_html()}</div>
    <p class="note">Lab pace zones come from the same test (threshold pace
    ≈ {zones.format_pace(zones.LAB_LT2_PACE_S)}/km). <strong>Strava</strong> derives
    its pace zones from an <em>estimated</em> 5 km time (19:29), which runs
    optimistic, so its zones sit faster than the measured ones.
    <strong>Garmin</strong> does not publish running pace zones for this athlete.</p>
  </div>

  <footer>Generated {generated} · Garmin training load + HRV · TSB bands follow
  TrainingPeaks conventions. CTL warm-up window shaded; treat early TSB with caution.</footer>
</div>
<script>
  document.querySelectorAll('.tab-btn').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      document.querySelectorAll('.tab-btn').forEach(function (b) {{ b.classList.remove('active'); }});
      document.querySelectorAll('.tab-panel').forEach(function (p) {{ p.classList.remove('active'); }});
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
      window.dispatchEvent(new Event('resize'));  // let Plotly size the hidden chart
    }});
  }});
</script>
</body>
</html>"""
