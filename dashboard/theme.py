"""Single source of truth for the dashboard's visual theme.

The page ships both a light and a dark palette and switches between them with
``prefers-color-scheme``. Plotly bakes its colours into the rendered HTML at
build time, so the figures are built background-transparent and neutral, and the
page re-applies :func:`chart_theme_js` client-side whenever the resolved scheme
changes. Keeping the CSS custom properties and the chart colours in this one
module is what stops the chrome and the charts from drifting apart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

# Type stacks. The numeric face is monospaced so metric values and table columns
# align on the digit rather than on the glyph width.
FONT_SANS = "'Instrument Sans', ui-sans-serif, system-ui, -apple-system, sans-serif"
FONT_SERIF = "'Instrument Serif', ui-serif, Georgia, 'Times New Roman', serif"
FONT_MONO = "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace"

GOOGLE_FONTS_HREF = (
    "https://fonts.googleapis.com/css2"
    "?family=IBM+Plex+Mono:wght@400;500;600"
    "&family=Instrument+Sans:wght@400;500;600;700"
    "&family=Instrument+Serif:ital@0;1"
    "&display=swap"
)


@dataclass(frozen=True)
class Palette:
    """One resolved colour scheme, emitted as a block of CSS custom properties.

    Parameters
    ----------
    name : str
        Scheme identifier, ``"light"`` or ``"dark"``.
    tokens : dict of str to str
        CSS custom-property names (without the leading ``--``) mapped to values.
    chart : dict of str to str
        Chart-only colours consumed by :func:`chart_theme_js`, keyed by role
        (``ink``, ``muted``, ``grid``, ``line``, ``surface``).
    """

    name: str
    tokens: dict[str, str] = field(default_factory=dict)
    chart: dict[str, str] = field(default_factory=dict)

    def css_vars(self, indent: str = "    ") -> str:
        """Render the palette as CSS custom-property declarations.

        Parameters
        ----------
        indent : str, optional
            Leading whitespace applied to every declaration.

        Returns
        -------
        str
            Newline-separated ``--name: value;`` declarations.

        Examples
        --------
        >>> Palette("light", {"bg": "#fff"}).css_vars(indent="")
        '--bg: #fff;'
        """
        return "\n".join(f"{indent}--{k}: {v};" for k, v in self.tokens.items())


# Warm paper rather than the blue-grey default: every saturated colour on the page
# is data (zone dots, phase bands, chart series), so the chrome stays neutral and
# never competes with it.
LIGHT = Palette(
    name="light",
    tokens={
        "bg": "#F7F6F3",
        "surface": "#FFFFFF",
        "surface-2": "#FBFAF7",
        "surface-3": "#F1EFEA",
        "border": "#E6E2D9",
        "border-strong": "#D2CDC1",
        "text": "#17150F",
        "muted": "#6C685E",
        "faint": "#9A9488",
        "accent": "#17150F",
        "accent-contrast": "#FFFFFF",
        "link": "#2A5DB0",
        "ring": "rgba(23, 21, 15, 0.42)",
        "shadow-sm": "0 1px 2px rgba(23, 21, 15, 0.05)",
        "shadow-md": "0 1px 2px rgba(23,21,15,0.04), 0 8px 24px -12px rgba(23,21,15,0.16)",
        "inset-hi": "inset 0 1px 0 rgba(255, 255, 255, 0.9)",
        "grain-opacity": "0.03",
        "ok-bg": "#EAF6EC",
        "ok-fg": "#1B7A3D",
        "warn-bg": "#FBF1DF",
        "warn-fg": "#8A5B0B",
        "hot-bg": "#FBECEA",
        "hot-fg": "#B4291F",
        "info-bg": "#ECF1FA",
        "info-fg": "#2A4E8F",
        "info-border": "#CFDCF1",
        "neutral-bg": "#F1EFEA",
        "neutral-fg": "#5C584E",
    },
    chart={
        "ink": "#17150F",
        "muted": "#6C685E",
        "grid": "rgba(23, 21, 15, 0.09)",
        "line": "rgba(23, 21, 15, 0.18)",
        "surface": "#FFFFFF",
    },
)

DARK = Palette(
    name="dark",
    tokens={
        "bg": "#0C0D10",
        "surface": "#141619",
        "surface-2": "#181B20",
        "surface-3": "#20242A",
        "border": "#252930",
        "border-strong": "#363B44",
        "text": "#ECEAE4",
        "muted": "#949AA4",
        "faint": "#6B707A",
        "accent": "#ECEAE4",
        "accent-contrast": "#0C0D10",
        "link": "#89B0EC",
        "ring": "rgba(236, 234, 228, 0.48)",
        "shadow-sm": "0 1px 2px rgba(0, 0, 0, 0.5)",
        "shadow-md": "0 1px 2px rgba(0,0,0,0.45), 0 10px 28px -14px rgba(0,0,0,0.8)",
        "inset-hi": "inset 0 1px 0 rgba(255, 255, 255, 0.045)",
        "grain-opacity": "0.055",
        "ok-bg": "rgba(45, 168, 94, 0.14)",
        "ok-fg": "#5FD08A",
        "warn-bg": "rgba(214, 152, 33, 0.14)",
        "warn-fg": "#E3B45A",
        "hot-bg": "rgba(214, 68, 55, 0.15)",
        "hot-fg": "#F08A80",
        "info-bg": "rgba(96, 141, 214, 0.13)",
        "info-fg": "#9FBEEE",
        "info-border": "rgba(96, 141, 214, 0.28)",
        "neutral-bg": "#20242A",
        "neutral-fg": "#A2A8B2",
    },
    chart={
        "ink": "#ECEAE4",
        "muted": "#949AA4",
        "grid": "rgba(236, 234, 228, 0.09)",
        "line": "rgba(236, 234, 228, 0.16)",
        "surface": "#141619",
    },
)

PALETTES = (LIGHT, DARK)

# Data colours, shared by both schemes. Each is mid-luminance so it holds up on
# warm paper and on near-black without needing a per-scheme variant.
COLOR_CTL = "#3D7BE0"    # blue   - fitness
COLOR_ATL = "#F08A2E"    # orange - fatigue
COLOR_TSB = "#2DA85E"    # green  - form
COLOR_LOAD = "#98A1B0"   # grey   - daily load bars
COLOR_HRV = "#8B62E8"    # violet - nightly HRV
COLOR_BAND = "rgba(139, 98, 232, 0.16)"  # HRV baseline band fill
# Annotation and reference-line neutral. Mid-luminance on purpose: a near-black
# rule vanishes on the dark scheme and a near-white one vanishes on the light.
COLOR_REFERENCE = "#7A808B"


def chart_layout(**overrides) -> dict:
    """Build the shared Plotly layout, background-transparent so the card shows through.

    Figures are rendered once at build time in the light palette; the page
    recolours them on load and on scheme change using :func:`chart_theme_js`.

    Parameters
    ----------
    **overrides
        Layout keys merged over the shared base, e.g. ``height`` or ``margin``.

    Returns
    -------
    dict
        Keyword arguments for ``plotly.graph_objects.Figure.update_layout``.

    Examples
    --------
    >>> chart_layout(height=300)["height"]
    300
    >>> chart_layout()["paper_bgcolor"]
    'rgba(0,0,0,0)'
    >>> chart_layout(title="Running volume")["title"]["text"]
    'Running volume'
    """
    # Title hard left in the top margin. A centred title collides with the
    # horizontal legend that shares that margin.
    title_font = dict(family=FONT_SANS, size=14, color=LIGHT.chart["ink"])
    title_base = dict(font=title_font, x=0, xanchor="left", y=0.98, yanchor="top")
    base = dict(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_SANS, size=12, color=LIGHT.chart["muted"]),
        title=title_base,
        hoverlabel=dict(
            font=dict(family=FONT_MONO, size=12),
            bgcolor=LIGHT.chart["surface"],
            bordercolor=LIGHT.chart["line"],
        ),
    )
    base.update(overrides)
    # A caller passing ``title="..."`` would otherwise drop the styled title font,
    # since the shorthand replaces the whole title object.
    if isinstance(base.get("title"), str):
        base["title"] = dict(text=base["title"], **title_base)
    return base


def axis_style(palette: Palette) -> dict:
    """Return the per-axis colour overrides for one palette.

    Parameters
    ----------
    palette : Palette
        The scheme to render axes for.

    Returns
    -------
    dict
        Axis sub-keys (``gridcolor``, ``linecolor``, ...) mapped to colours.
    """
    return {
        "gridcolor": palette.chart["grid"],
        "zerolinecolor": palette.chart["line"],
        "linecolor": palette.chart["line"],
        "tickfont.color": palette.chart["muted"],
        "title.font.color": palette.chart["muted"],
    }


def chart_theme_js() -> str:
    """Serialise both chart palettes for the page's client-side theme switcher.

    Returns
    -------
    str
        A JSON object with ``light`` and ``dark`` keys, each holding the
        figure-level and per-axis overrides applied via ``Plotly.relayout``.

    Examples
    --------
    >>> "dark" in chart_theme_js()
    True
    """
    payload = {
        p.name: {
            "figure": {
                "font.color": p.chart["muted"],
                "title.font.color": p.chart["ink"],
                "legend.font.color": p.chart["muted"],
                "hoverlabel.bgcolor": p.chart["surface"],
                "hoverlabel.bordercolor": p.chart["line"],
                "hoverlabel.font.color": p.chart["ink"],
            },
            "axis": axis_style(p),
        }
        for p in PALETTES
    }
    return json.dumps(payload, indent=2)
