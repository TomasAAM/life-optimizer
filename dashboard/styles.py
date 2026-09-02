"""The dashboard stylesheet, built from the tokens in :mod:`dashboard.theme`.

Kept out of :func:`dashboard.render.render_html` because that function is one
large f-string, which forces every CSS brace to be doubled and makes the rules
effectively unreadable. Here the CSS is a plain string, so it reads as CSS.
"""

from __future__ import annotations

from dashboard import theme

# Fine noise laid over the page: the tooth of paper in the light scheme, and
# enough break-up to stop the dark scheme reading as flat black. The opacity is
# per-palette so neither becomes dirty. One octave on a small stitched tile — the
# texture is barely-there at these opacities, and extra octaves only cost
# rasterisation time on a page that already carries five Plotly figures.
_GRAIN = (
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
    "width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence "
    "type='fractalNoise' baseFrequency='0.9' numOctaves='1' stitchTiles='stitch'/"
    "%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/"
    "%3E%3C/svg%3E\")"
)


def _tokens_css() -> str:
    """Emit the light palette on ``:root`` and the dark one behind a media query."""
    return (
        ":root {\n"
        "    color-scheme: light dark;\n"
        f"{theme.LIGHT.css_vars()}\n"
        "}\n\n"
        "@media (prefers-color-scheme: dark) {\n"
        "  :root {\n"
        f"{theme.DARK.css_vars(indent='    ')}\n"
        "  }\n"
        "}"
    )


def stylesheet() -> str:
    """Build the complete stylesheet for the dashboard page.

    Returns
    -------
    str
        CSS text for the document's single inline ``<style>`` element.

    Examples
    --------
    >>> "--bg:" in stylesheet() or "--bg: " in stylesheet()
    True
    """
    return f"""
{_tokens_css()}

/* ---------- base ---------- */
*, *::before, *::after {{ box-sizing: border-box; }}
html {{ -webkit-text-size-adjust: 100%; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: {theme.FONT_SANS};
  font-size: 16px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}}
body::before {{
  content: "";
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-image: {_GRAIN};
  opacity: var(--grain-opacity);
}}
.wrap {{
  position: relative;
  z-index: 1;
  max-width: 1140px;
  margin: 0 auto;
  padding: 40px 24px 80px;
}}
a {{ color: var(--link); }}
:focus-visible {{ outline: 2px solid var(--ring); outline-offset: 2px; border-radius: 4px; }}
::selection {{ background: var(--accent); color: var(--accent-contrast); }}

/* Numerals align on the digit, so columns of figures scan vertically. */
.num, .card-value, table.weekly td, table.zones td, .sess-meta, .seg-metric {{
  font-variant-numeric: tabular-nums;
}}

/* ---------- masthead ---------- */
.masthead {{
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding-bottom: 18px;
  margin-bottom: 22px;
  border-bottom: 1px solid var(--border);
}}
h1 {{
  font-family: {theme.FONT_SERIF};
  font-weight: 400;
  font-size: clamp(2.1rem, 5vw, 3rem);
  line-height: 1;
  letter-spacing: -0.015em;
  margin: 0;
}}
.as-of {{
  font-family: {theme.FONT_MONO};
  font-size: 0.7rem;
  font-weight: 500;
  letter-spacing: 0.11em;
  text-transform: uppercase;
  color: var(--muted);
  white-space: nowrap;
  padding-bottom: 4px;
}}

/* ---------- tabs ---------- */
.tabs {{
  display: flex;
  gap: 2px;
  padding: 4px;
  margin-bottom: 26px;
  background: var(--surface-3);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow-x: auto;
  scrollbar-width: none;
}}
.tabs::-webkit-scrollbar {{ display: none; }}
.tab-btn {{
  flex: 1 0 auto;
  background: none;
  border: none;
  border-radius: 9px;
  padding: 9px 18px;
  font: inherit;
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--muted);
  white-space: nowrap;
  cursor: pointer;
  transition: background 0.18s ease, color 0.18s ease;
}}
.tab-btn:hover {{ color: var(--text); }}
.tab-btn.active {{
  background: var(--accent);
  color: var(--accent-contrast);
  font-weight: 600;
  box-shadow: var(--shadow-sm);
}}
.tab-panel {{ display: none; }}
.tab-panel.active {{ display: block; }}

/* ---------- headings ---------- */
h2 {{
  font-family: {theme.FONT_SERIF};
  font-weight: 400;
  font-size: 1.6rem;
  letter-spacing: -0.01em;
  margin: 0 0 16px;
}}
.section-label {{
  display: flex;
  align-items: center;
  gap: 12px;
  font-family: {theme.FONT_MONO};
  font-size: 0.66rem;
  font-weight: 600;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 2px 0 12px;
}}
/* Hairline that runs out to the panel edge, framing the label as a rule. */
.section-label::after {{
  content: "";
  flex: 1;
  height: 1px;
  background: var(--border);
}}

/* ---------- cards ---------- */
.cards {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px;
  margin-bottom: 26px;
}}
.card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px 18px 18px;
  box-shadow: var(--shadow-sm), var(--inset-hi);
  transition: border-color 0.18s ease, transform 0.18s ease, box-shadow 0.18s ease;
}}
.card:hover {{
  border-color: var(--border-strong);
  transform: translateY(-1px);
  box-shadow: var(--shadow-md), var(--inset-hi);
}}
.card-label {{
  font-family: {theme.FONT_MONO};
  font-size: 0.64rem;
  font-weight: 500;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
}}
.card-value {{
  font-family: {theme.FONT_MONO};
  font-size: clamp(1.35rem, 2.6vw, 1.75rem);
  font-weight: 500;
  letter-spacing: -0.03em;
  line-height: 1.15;
  margin: 8px 0 5px;
  overflow-wrap: anywhere;
}}
.card-sub {{ font-size: 0.8rem; color: var(--muted); }}

/* ---------- panels ---------- */
.panel {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px 18px;
  margin-bottom: 22px;
  box-shadow: var(--shadow-sm), var(--inset-hi);
}}

/* ---------- tables ---------- */
table.weekly, table.zones {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}}
table.weekly th, table.zones th {{
  font-family: {theme.FONT_MONO};
  font-size: 0.63rem;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
}}
table.weekly th, table.weekly td {{
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
}}
table.zones th, table.zones td {{
  text-align: center;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
}}
table.zones th:first-child, table.zones td:first-child {{ text-align: left; }}
table.weekly tr:last-child td, table.zones tr:last-child td {{ border-bottom: none; }}
table.weekly tbody tr:hover td, table.zones tbody tr:hover td {{ background: var(--surface-2); }}
table.weekly tr:first-child td {{ font-weight: 600; }}
table.zones .muted {{ color: var(--faint); }}

/* ---------- block strip ---------- */
.phase-strip {{
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 2px 2px 8px;
  scrollbar-width: thin;
}}
.phase-cell {{
  flex: 0 0 auto;
  min-width: 92px;
  border-radius: 12px;
  padding: 10px 12px;
  text-align: center;
  background: var(--surface-2);
  border: 1px solid var(--border);
  font: inherit;
  color: inherit;
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease, transform 0.18s ease;
}}
.phase-cell:hover {{
  background: var(--surface);
  border-color: var(--border-strong);
  transform: translateY(-1px);
}}
/* Ring rather than a thicker border, so selecting never shifts the strip. */
.phase-cell.selected {{
  background: var(--surface);
  border-color: var(--accent);
  box-shadow: 0 0 0 1.5px var(--accent), var(--shadow-sm);
}}
.phase-dot {{ width: 100%; height: 4px; border-radius: 2px; margin-bottom: 8px; }}
.phase-wk {{
  font-family: {theme.FONT_MONO};
  font-size: 0.76rem;
  font-weight: 600;
  letter-spacing: -0.01em;
}}
.phase-name {{ font-size: 0.72rem; color: var(--muted); text-transform: capitalize; }}
.phase-sub {{ font-size: 0.66rem; color: var(--faint); margin-top: 2px; }}
.plan-hint {{ font-size: 0.78rem; color: var(--faint); margin: -4px 0 14px; }}

/* Every block week is in the DOM; only the selected one is shown. */
.wk-cards {{ display: none; }}
.wk-cards.active {{ display: grid; }}
.wk-pane {{ display: none; }}
.wk-pane.active {{ display: block; }}

/* ---------- session list ---------- */
.sess-list {{ display: flex; flex-direction: column; gap: 8px; }}
.sess {{
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  background: var(--surface);
  transition: border-color 0.18s ease;
}}
.sess:hover {{ border-color: var(--border-strong); }}
.sess-row {{
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 13px 15px;
  cursor: pointer;
  transition: background 0.15s ease;
}}
.sess-row:hover {{ background: var(--surface-2); }}
.sess-row.open {{ background: var(--surface-2); }}
.zdot {{
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex: none;
  box-shadow: 0 0 0 3px var(--surface-3);
}}
.sess-main {{ flex: 1; min-width: 0; }}
.sess-title {{ font-size: 0.94rem; font-weight: 600; letter-spacing: -0.01em; }}
.sess-meta {{
  font-family: {theme.FONT_MONO};
  font-size: 0.72rem;
  color: var(--muted);
  margin-top: 3px;
}}
.sdot {{ width: 7px; height: 7px; border-radius: 50%; flex: none; }}
.sdot.s-done {{ background: {theme.COLOR_TSB}; }}
.sdot.s-missed {{ background: #D64437; }}
.sdot.s-upcoming {{ background: var(--faint); }}
.sdot.s-rest {{ background: var(--border-strong); }}
.chev {{ color: var(--faint); font-size: 0.7rem; transition: transform 0.22s ease; }}
.sess-row.open .chev {{ transform: rotate(180deg); }}
.sess-body {{
  display: none;
  padding: 6px 15px 16px 36px;
  border-top: 1px solid var(--border);
}}
.sess-body.open {{ display: block; animation: reveal 0.22s ease-out; }}
.sess-step {{ display: flex; gap: 10px; align-items: baseline; padding: 5px 0; }}
.sess-step .sk {{
  min-width: 84px;
  font-family: {theme.FONT_MONO};
  font-size: 0.7rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
}}
.sess-step .sv {{ font-size: 0.88rem; color: var(--text); line-height: 1.55; }}

/* ---------- session segments ---------- */
.seg-list {{
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  margin-top: 6px;
}}
.seg-band {{
  padding: 7px 12px;
  font-family: {theme.FONT_MONO};
  font-size: 0.66rem;
  font-weight: 600;
  color: #fff;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}}
.seg-row {{
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-top: 1px solid var(--border);
  background: var(--surface);
}}
.seg-list > .seg-row:first-child {{ border-top: none; }}
.seg-num {{
  width: 18px;
  text-align: center;
  color: var(--faint);
  font-family: {theme.FONT_MONO};
  font-size: 0.72rem;
  flex: none;
}}
.seg-main {{ flex: 1; min-width: 0; }}
.seg-metric {{ font-size: 0.88rem; color: var(--text); }}
.seg-metric b {{ font-weight: 600; }}
.seg-load {{ color: var(--muted); font-weight: 600; }}
.seg-target {{ font-size: 0.76rem; color: var(--muted); margin-top: 2px; }}
.seg-tag {{
  font-family: {theme.FONT_MONO};
  font-size: 0.62rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  flex: none;
}}

/* ---------- session notes ---------- */
.sess-purpose {{
  font-size: 0.82rem;
  color: var(--muted);
  font-style: italic;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}}
.sess-why {{
  font-size: 0.84rem;
  color: var(--text);
  margin-top: 10px;
  padding: 10px 12px;
  background: var(--surface-2);
  border-left: 2px solid var(--border-strong);
  border-radius: 0 8px 8px 0;
}}
.why-label {{
  display: block;
  font-family: {theme.FONT_MONO};
  font-size: 0.62rem;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  margin-bottom: 4px;
}}

/* ---------- badges ---------- */
.ibadge {{
  font-size: 0.7rem;
  font-weight: 600;
  border-radius: 999px;
  padding: 3px 10px;
  text-transform: capitalize;
  white-space: nowrap;
}}
.ibadge.i-hard {{ background: var(--hot-bg); color: var(--hot-fg); }}
.ibadge.i-moderate {{ background: var(--warn-bg); color: var(--warn-fg); }}
.ibadge.i-easy {{ background: var(--ok-bg); color: var(--ok-fg); }}
.ibadge.i-none {{ background: var(--neutral-bg); color: var(--neutral-fg); }}
.tier {{
  font-family: {theme.FONT_MONO};
  font-size: 0.62rem;
  font-weight: 600;
  border-radius: 999px;
  padding: 3px 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  white-space: nowrap;
}}
.tier.t-strong {{ background: var(--ok-bg); color: var(--ok-fg); }}
.tier.t-contested {{ background: var(--warn-bg); color: var(--warn-fg); }}
.tier.t-emerging {{ background: var(--neutral-bg); color: var(--neutral-fg); }}
.focus {{
  font-size: 0.68rem;
  background: var(--info-bg);
  color: var(--info-fg);
  border-radius: 999px;
  padding: 2px 8px;
  margin-left: 8px;
  white-space: nowrap;
}}
.badge {{
  color: #fff;
  font-size: 0.7rem;
  font-weight: 600;
  border-radius: 999px;
  padding: 3px 10px;
  text-transform: capitalize;
}}

/* ---------- sources ---------- */
.methodology {{ font-size: 0.88rem; color: var(--text); line-height: 1.65; margin: 0 0 16px; }}
.src-list {{ display: flex; flex-direction: column; gap: 6px; }}
.src {{
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-2);
  transition: border-color 0.18s ease;
}}
.src:hover {{ border-color: var(--border-strong); }}
.src-main {{ flex: 1; min-width: 0; }}
.src-claim {{ font-size: 0.86rem; color: var(--text); }}
.src-cite {{ font-size: 0.76rem; color: var(--link); text-decoration: none; }}
.src-cite:hover {{ text-decoration: underline; }}
.src-note {{ font-size: 0.76rem; color: var(--faint); margin: 14px 0 2px; line-height: 1.6; }}

/* ---------- misc ---------- */
.rationale {{ font-size: 0.86rem; color: var(--text); margin: 16px 0 2px; line-height: 1.6; }}
.zone-note {{ font-size: 0.78rem; color: var(--faint); margin: 12px 0 2px; line-height: 1.6; }}
.note {{ color: var(--muted); font-size: 0.86rem; line-height: 1.65; margin: 0 0 20px; }}
.callout {{
  background: var(--info-bg);
  border: 1px solid var(--info-border);
  border-radius: 12px;
  padding: 13px 16px;
  margin: 0 0 18px;
  font-size: 0.9rem;
  color: var(--info-fg);
}}
code {{
  font-family: {theme.FONT_MONO};
  font-size: 0.85em;
  background: var(--surface-3);
  border-radius: 5px;
  padding: 1px 5px;
}}
footer {{
  color: var(--faint);
  font-size: 0.78rem;
  line-height: 1.6;
  margin-top: 36px;
  padding-top: 18px;
  border-top: 1px solid var(--border);
}}

/* ---------- granularity toggle ---------- */
.gran-toggle {{
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  margin: 0 0 14px;
  background: var(--surface-3);
  border: 1px solid var(--border);
  border-radius: 10px;
}}
.gran-btn {{
  background: none;
  border: none;
  border-radius: 8px;
  padding: 6px 14px;
  font: inherit;
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--muted);
  cursor: pointer;
  transition: background 0.18s ease, color 0.18s ease;
}}
.gran-btn:hover {{ color: var(--text); }}
.gran-btn.active {{
  background: var(--accent);
  color: var(--accent-contrast);
  font-weight: 600;
  box-shadow: var(--shadow-sm);
}}

/* ---------- plotly ---------- */
.js-plotly-plot .modebar {{ background: transparent !important; }}
.js-plotly-plot .modebar-btn svg path {{ fill: var(--faint) !important; }}
.js-plotly-plot .modebar-btn:hover svg path {{ fill: var(--text) !important; }}

/* ---------- motion ---------- */
@keyframes rise {{
  from {{ opacity: 0; transform: translateY(8px); }}
  to {{ opacity: 1; transform: none; }}
}}
@keyframes reveal {{
  from {{ opacity: 0; transform: translateY(-4px); }}
  to {{ opacity: 1; transform: none; }}
}}
/* One orchestrated entrance, on first load only. Scoped to ``body.intro``, which
   the page drops once the stagger has run: replaying it on every tab switch would
   put a delay in front of data the athlete is tabbing between. */
body.intro .tab-panel.active > * {{
  animation: rise 0.42s cubic-bezier(0.22, 0.8, 0.3, 1) backwards;
}}
body.intro .tab-panel.active > *:nth-child(1) {{ animation-delay: 0.02s; }}
body.intro .tab-panel.active > *:nth-child(2) {{ animation-delay: 0.06s; }}
body.intro .tab-panel.active > *:nth-child(3) {{ animation-delay: 0.10s; }}
body.intro .tab-panel.active > *:nth-child(4) {{ animation-delay: 0.14s; }}
body.intro .tab-panel.active > *:nth-child(5) {{ animation-delay: 0.18s; }}
body.intro .tab-panel.active > *:nth-child(n + 6) {{ animation-delay: 0.22s; }}

@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }}
  .card:hover, .phase-cell:hover {{ transform: none; }}
}}

/* ---------- responsive ---------- */
@media (max-width: 720px) {{
  .wrap {{ padding: 26px 16px 60px; }}
  .masthead {{ align-items: flex-start; flex-direction: column; gap: 6px; }}
  .as-of {{ padding-bottom: 0; }}
  .cards {{ grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }}
  .card {{ padding: 14px; }}
  .panel {{ padding: 14px; border-radius: 12px; }}
  .tab-btn {{ padding: 9px 14px; }}
  .sess-body {{ padding-left: 15px; }}
  .sess-step {{ flex-direction: column; gap: 2px; }}
  h2 {{ font-size: 1.35rem; }}
}}
"""
