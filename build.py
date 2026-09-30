#!/usr/bin/env python3
# Static site builder: turns the cleaned QCEW, FRED, and IRS data into the
# published dashboard pages (main dashboard, landing page, and iframe embeds)
# under docs/.
"""
Build static HTML dashboard from QCEW data for GitHub Pages.

Loads and cleans the QCEW data (data/fetch.py, data/clean.py), builds each
Plotly chart as a JSON figure, and embeds that JSON in self-contained HTML
pages, where Plotly.js draws the charts in the browser. The output is
docs/index.html (full dashboard), docs/custom-page.html (landing page), and
docs/embeds/ (standalone pages for iframes).

Usage:
    python build.py
"""
from __future__ import annotations

import html as _html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from data.fetch import fetch_all_data
from data.clean import (
    clean, get_total_covered, get_latest_quarter, get_growth_quadrant_data,
)
from data.analysis import deseasonalize_trend, project_trend, periods_to_current_quarter
from components.growth_quadrant import (
    build_figure as build_growth_quadrant_fig,
    METHODOLOGY_NOTE as _GROWTH_QUADRANT_TEXT,
)
# Wraps the growth quadrant's methodology text in a small source-note paragraph.
GROWTH_QUADRANT_NOTE = f'<p class="source"><em>{_GROWTH_QUADRANT_TEXT}</em></p>'
from data.constants import (
    FAU_BLUE, FAU_RED, FAU_DARK_GRAY, FAU_GRAY,
    FAU_ELECTRIC_BLUE, FAU_SKY_BLUE, COUNTY_COLORS, COUNTIES,
    NMU_FONT_FAMILY, GOOGLE_FONTS_IMPORT, PLOTLY_FONT,
    NMU_LINK, NMU_MUTED, NMU_BORDER,
)
from utils.formatting import fmt_number, fmt_currency, fmt_pct
from utils.narratives import narrate_employment_trends, format_industry_list

# Sets the output folder (docs/, which GitHub Pages serves) and a minimum
# employment threshold.
DOCS_DIR = Path(__file__).parent / "docs"
MIN_EMPLOYMENT = 100

# Sets how many counties get their own detail tab and embed pages, chosen as
# the largest county economies by latest employment. At 15 this covers every
# UP county: 15 KPI embeds plus 60 chart embeds (15 counties x 4 sections).
DETAIL_COUNTY_N = 15


# Returns the names of the largest county economies, which get detail tabs and
# embeds.
def _detail_counties(df) -> list[str]:
    """Ask components.top_counties.get_top_counties for the top DETAIL_COUNTY_N counties.

    Returns their county_name values as a list. If that comes back empty, it
    falls back to the first DETAIL_COUNTY_N names in COUNTIES.
    """
    from components.top_counties import get_top_counties
    top = get_top_counties(df, DETAIL_COUNTY_N)
    if not top.empty:
        return top["county_name"].tolist()
    return list(COUNTIES.values())[:DETAIL_COUNTY_N]

# ── CSS ──────────────────────────────────────────────────────────────────────

# Shared WCAG 2.1 AA layer, appended to BOTH the main and embed stylesheets.
# It (a) overrides the few brand colors that fail contrast on white — bright
# gold links, #888 muted text, #CCCCCC borders — with accessible tokens, and
# (b) adds styles for the new accessible components (visible focus rings,
# screen-reader-only text, collapsible data tables, keyboard year buttons).
# Placed LAST so its rules win on source order over the base definitions.
A11Y_CSS = """
/* ── Accessibility (WCAG 2.1 AA) ─────────────────────────────────────────── */
.kpi-period, .kpi-caption, .source, .footer { color: """ + NMU_MUTED + """; }
.source a, .footer a { color: """ + NMU_LINK + """; text-decoration: underline; }
.tab-bar { border-bottom-color: """ + NMU_BORDER + """; }
.kpi-row.secondary { border-top-color: """ + NMU_BORDER + """; }
.kpi-label { line-height: 1.1; }

/* 2.4.7 Focus Visible — a clearly visible keyboard focus indicator (≥3:1). */
a:focus-visible, button:focus-visible, summary:focus-visible,
[tabindex]:focus-visible {
    outline: 3px solid """ + FAU_BLUE + """;
    outline-offset: 2px;
    border-radius: 2px;
}

/* Screen-reader-only text (visually hidden, still announced). */
.sr-only {
    position: absolute; width: 1px; height: 1px;
    padding: 0; margin: -1px; overflow: hidden;
    clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}

/* Each chart is a figure with a visible caption. */
figure.chart-figure { margin: 0; }
figure.chart-figure > figcaption { margin-bottom: 0.75rem; }

/* Collapsible data tables — the machine-readable alternative to each chart. */
.data-table-details { margin: 0.25rem 0 0.75rem; }
.data-table-details > summary {
    cursor: pointer; font-size: 0.9rem; font-weight: 600;
    color: """ + FAU_BLUE + """; padding: 0.35rem 0;
}
.data-table-details > summary:hover { text-decoration: underline; }
.table-scroll { overflow-x: auto; }
table.data-table {
    border-collapse: collapse; width: 100%;
    font-size: 0.85rem; margin-top: 0.5rem;
}
table.data-table caption {
    text-align: left; font-size: 0.85rem;
    color: """ + NMU_MUTED + """; padding-bottom: 0.35rem;
}
table.data-table th, table.data-table td {
    border: 1px solid """ + NMU_BORDER + """;
    padding: 0.3rem 0.55rem; text-align: right;
}
table.data-table thead th { background: """ + FAU_SKY_BLUE + """; color: """ + FAU_BLUE + """; }
table.data-table th[scope="row"] { text-align: left; }

/* Keyboard-operable year selector (treemap) — real buttons, not Plotly SVG. */
.year-select { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.5rem 0 0.25rem; }
.year-select .year-btn {
    font-family: inherit; font-size: 0.85rem; cursor: pointer;
    padding: 0.3rem 0.7rem; border: 1px solid """ + NMU_BORDER + """;
    background: #fff; color: """ + FAU_DARK_GRAY + """; border-radius: 4px;
}
.year-select .year-btn[aria-pressed="true"] {
    background: """ + FAU_BLUE + """; color: #fff; border-color: """ + FAU_BLUE + """;
}
"""

# Stylesheet for the main dashboard page (index.html), with the accessibility
# layer appended last. The landing page also starts from this and adds its own.
CSS = GOOGLE_FONTS_IMPORT + """
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: """ + NMU_FONT_FAMILY + """;
    background-color: #FFFFFF;
    color: """ + FAU_DARK_GRAY + """;
    line-height: 1.6;
    max-width: 1200px;
    margin: 0 auto;
    padding: 1rem 2rem;
}

h1, h2, h3, h4 { color: """ + FAU_BLUE + """; }

/* Header */
.main-title { font-size: 2.2rem; font-weight: 700; margin-bottom: 0; }
.main-subtitle { font-size: 1.0rem; margin-top: 0.25rem; color: """ + FAU_DARK_GRAY + """; }

.data-badge {
    display: inline-block;
    background-color: """ + FAU_SKY_BLUE + """;
    color: """ + FAU_BLUE + """;
    padding: 0.25rem 0.75rem;
    border-radius: 20px;
    font-size: 0.85rem;
    font-weight: 500;
    margin: 1rem 0;
}

/* KPI cards */
.snapshot-row { display: flex; gap: 1rem; margin-bottom: 1.5rem; }
.county-card {
    flex: 1;
    background: linear-gradient(135deg, #F8F9FA 0%, #FFFFFF 100%);
    border-radius: 12px;
    padding: 1.5rem;
    border-left: 5px solid;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.county-card h3 { margin: 0 0 0.8rem 0; font-size: 1.3rem; }
.kpi-row { display: flex; justify-content: space-between; gap: 0.8rem; }
.kpi-item { flex: 1; text-align: center; }
.kpi-label {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 0.2rem;
    color: """ + FAU_DARK_GRAY + """;
    min-height: 1.8rem;
    line-height: 0.9rem;
}
.kpi-value { font-size: 1.4rem; font-weight: 700; color: """ + FAU_BLUE + """; }
.kpi-delta { font-size: 0.8rem; margin-top: 0.1rem; }
.kpi-delta.positive { color: #2E7D32; }
.kpi-delta.negative { color: """ + FAU_RED + """; }
/* Secondary KPI row — typography matches the primary row; only the
   separator (border-top) distinguishes them. */
.kpi-row.secondary {
    margin-top: 0.9rem;
    padding-top: 0.7rem;
    border-top: 1px solid """ + FAU_GRAY + """;
}
.kpi-period { font-size: 0.7rem; color: #888; margin-top: 0.15rem; }
.kpi-caption {
    font-size: 0.78rem;
    color: #888;
    margin: -0.5rem 0 1.5rem 0;
    line-height: 1.3;
}

/* Tabs */
.tab-bar { display: flex; border-bottom: 2px solid """ + FAU_GRAY + """; margin: 1.5rem 0 0 0; }
.tab-btn {
    padding: 0.75rem 1.5rem;
    font-weight: 500;
    color: """ + FAU_DARK_GRAY + """;
    background: none;
    border: none;
    cursor: pointer;
    font-size: 1rem;
    border-bottom: 3px solid transparent;
    margin-bottom: -2px;
    font-family: inherit;
}
.tab-btn:hover { color: """ + FAU_BLUE + """; }
.tab-btn.active { border-bottom-color: """ + FAU_BLUE + """; color: """ + FAU_BLUE + """; }

.tab-content { display: none; padding-top: 1rem; }
.tab-content.active { display: block; }

/* Chart sections */
.section { margin: 2rem 0; }
.section h2 { font-size: 1.5rem; margin-bottom: 0.5rem; }
.section p { margin-bottom: 0.75rem; }

.chart-row { display: flex; gap: 1rem; }
.chart-col { flex: 1; min-width: 0; }

.divider { border-top: 1px solid #EEEEEE; margin: 2rem 0; }

.source {
    font-size: 0.8rem;
    color: #888;
    margin-top: 0.25rem;
}
.source a { color: """ + FAU_ELECTRIC_BLUE + """; text-decoration: none; }
.source a:hover { text-decoration: underline; }

.footer {
    font-size: 0.8rem;
    color: #888;
    text-align: center;
    margin-top: 2rem;
    padding: 1rem 0;
    border-top: 1px solid #EEE;
}
.footer a { color: """ + FAU_ELECTRIC_BLUE + """; }

@media (max-width: 768px) {
    .snapshot-row, .chart-row { flex-direction: column; }
    body { padding: 0.5rem 1rem; }
    .tab-btn { padding: 0.5rem 1rem; font-size: 0.9rem; }
}
""" + A11Y_CSS

# ── JavaScript ───────────────────────────────────────────────────────────────

# Keyboard-accessible treemap year selector: HTML buttons toggle which Plotly
# trace (one per year) is visible, replacing Plotly's non-focusable SVG
# updatemenus. Shared by the main dashboard and the embeds.
TREEMAP_JS = """
function selectTreemapYear(btn) {
    var target = btn.getAttribute('data-target');
    var idx = parseInt(btn.getAttribute('data-trace'), 10);
    var n = parseInt(btn.getAttribute('data-count'), 10);
    var vis = [];
    for (var i = 0; i < n; i++) { vis.push(i === idx); }
    Plotly.restyle(target, {visible: vis});
    btn.parentNode.querySelectorAll('.year-btn').forEach(function(b) {
        b.setAttribute('aria-pressed', b === btn ? 'true' : 'false');
    });
}
"""

# Script for the main dashboard: county tab switching (with a chart resize so
# hidden charts redraw correctly) and drawing every chart in figureData.
JS = TREEMAP_JS + """
function showTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(function(el) { el.classList.remove('active'); });
    document.querySelectorAll('.tab-btn').forEach(function(el) {
        el.classList.remove('active');
        el.setAttribute('aria-pressed', 'false');
    });
    document.getElementById(tabId).classList.add('active');
    var btn = document.querySelector('[data-tab="' + tabId + '"]');
    btn.classList.add('active');
    btn.setAttribute('aria-pressed', 'true');
    setTimeout(function() {
        document.querySelectorAll('#' + tabId + ' .plotly-chart').forEach(function(el) {
            if (el.data) Plotly.Plots.resize(el);
        });
    }, 50);
}

Object.keys(figureData).forEach(function(divId) {
    var fig = figureData[divId];
    Plotly.newPlot(divId, fig.data, fig.layout, {responsive: true, displayModeBar: false});
});
"""

# ── Embed CSS / JS (used by wrap_as_embed) ───────────────────────────────────
# Trimmed copy of CSS — drops .tab-*, .main-title, .main-subtitle, .data-badge,
# .footer (none of which appear in embed pages). body { max-width:none } so the
# embed fills the iframe width rather than the desktop 1200px cap. Includes a
# media query so the KPI embed stacks its 3 county cards vertically below 768px.

EMBED_CSS = GOOGLE_FONTS_IMPORT + """
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: """ + NMU_FONT_FAMILY + """;
    background-color: #FFFFFF;
    color: """ + FAU_DARK_GRAY + """;
    line-height: 1.6;
    padding: 0.5rem;
}

h1, h2, h3, h4 { color: """ + FAU_BLUE + """; }

/* KPI cards */
.snapshot-row { display: flex; gap: 1rem; margin-bottom: 1rem; }
.snapshot-row.single-county { display: block; max-width: 480px; margin: 0 auto 1rem; }
.county-card {
    flex: 1;
    background: linear-gradient(135deg, #F8F9FA 0%, #FFFFFF 100%);
    border-radius: 12px;
    padding: 1.5rem;
    border-left: 5px solid;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.county-card h3 { margin: 0 0 0.8rem 0; font-size: 1.3rem; }
.kpi-row { display: flex; justify-content: space-between; gap: 0.8rem; }
.kpi-item { flex: 1; text-align: center; }
.kpi-label {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 0.2rem;
    color: """ + FAU_DARK_GRAY + """;
    min-height: 1.8rem;
    line-height: 0.9rem;
}
.kpi-value { font-size: 1.4rem; font-weight: 700; color: """ + FAU_BLUE + """; }
.kpi-delta { font-size: 0.8rem; margin-top: 0.1rem; }
.kpi-delta.positive { color: #2E7D32; }
.kpi-delta.negative { color: """ + FAU_RED + """; }
.kpi-row.secondary {
    margin-top: 0.9rem;
    padding-top: 0.7rem;
    border-top: 1px solid """ + FAU_GRAY + """;
}
.kpi-period { font-size: 0.7rem; color: #888; margin-top: 0.15rem; }
.kpi-caption {
    font-size: 0.78rem;
    color: #888;
    margin: 0.75rem 0 0 0;
    line-height: 1.3;
}

/* Chart sections */
.section { margin: 0; }
.section h2 { font-size: 1.5rem; margin-bottom: 0.5rem; }
.section p { margin-bottom: 0.75rem; }

.chart-row { display: flex; gap: 1rem; }
.chart-col { flex: 1; min-width: 0; }

.source {
    font-size: 0.8rem;
    color: #888;
    margin-top: 0.25rem;
}
.source a { color: """ + FAU_ELECTRIC_BLUE + """; text-decoration: none; }
.source a:hover { text-decoration: underline; }

@media (max-width: 768px) {
    .snapshot-row, .chart-row { flex-direction: column; }
    body { padding: 0.3rem; }
}
""" + A11Y_CSS

# Each embed posts its rendered height to the parent host page via postMessage.
# Debounce (100 ms) + last-height dedupe kill the feedback loop where Plotly's
# responsive: true would re-fire layout when the parent resizes the iframe.
EMBED_JS = TREEMAP_JS + """
Object.keys(figureData).forEach(function(divId) {
    var fig = figureData[divId];
    Plotly.newPlot(divId, fig.data, fig.layout, {responsive: true, displayModeBar: false});
});

(function() {
  var lastHeight = 0, timer;
  function postHeight() {
    clearTimeout(timer);
    timer = setTimeout(function() {
      var h = document.documentElement.scrollHeight;
      if (h === lastHeight) return;
      lastHeight = h;
      window.parent.postMessage({type: 'uper-resize', height: h}, '*');
    }, 100);
  }
  window.addEventListener('load', postHeight);
  window.addEventListener('resize', postHeight);
  setTimeout(postHeight, 800);
  document.querySelectorAll('.plotly-chart').forEach(function(el) {
    el.on && el.on('plotly_afterplot', postHeight);
  });
})();
"""


# Wraps an HTML fragment into a complete, standalone page that can be shown in
# an iframe on another site.
def wrap_as_embed(body_html: str, figures: dict, page_title: str) -> str:
    """Build a full HTML document around body_html using EMBED_CSS and EMBED_JS.

    Each embed is a standalone HTML document: loads Plotly from CDN, bundles
    the trimmed embed CSS, renders the included figures, and posts its content
    height to the parent via postMessage. It also adds a visually hidden h1
    containing page_title (HTML-escaped) so the page has a valid heading
    outline, and serializes `figures` to JSON as the `figureData` variable
    that EMBED_JS reads. CSS isolation is automatic — iframes have their own
    document, so styles cannot collide with the host page.
    """
    figures_json = json.dumps(figures)
    return "\n".join([
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f"<title>{page_title}</title>",
        '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>',
        "<style>",
        EMBED_CSS,
        "</style>",
        "</head>",
        "<body>",
        "<main>",
        # Each embed is its own document, so it needs exactly one h1 for a valid
        # heading outline. It's visually hidden (the design has no visible page
        # title inside the iframe) but announced by screen readers.
        f'<h1 class="sr-only">{_html.escape(page_title)}</h1>',
        body_html,
        "</main>",
        "<script>",
        f"var figureData = {figures_json};",
        EMBED_JS,
        "</script>",
        "</body>",
        "</html>",
    ])


# ── Helpers ──────────────────────────────────────────────────────────────────

# Standard source line shown under every chart section.
SOURCE = '<p class="source">Source: <a href="https://www.bls.gov/cew/">BLS QCEW</a> — Quarterly</p>'
# Methodology note shown under the trends section, explaining the STL trend and
# the projection.
TRENDS_NOTE = (
    '<p class="source"><em>Chart shows the STL trend (raw quarterly values omitted '
    'for clarity). Trend computed via STL decomposition (period=4, robust); salary '
    'on log scale. Projection extrapolates a linear fit through the last 4 trend '
    'points to the current calendar quarter — the horizon shrinks as new QCEW data '
    'is published. BLS does not publish seasonally adjusted QCEW — this is a custom '
    'estimate.</em></p>'
)


# Converts a Plotly figure into a JSON-serializable dict.
def _fig_json(fig):
    """Serialize the figure with fig.to_json() and parse it back with json.loads."""
    return json.loads(fig.to_json())


# ── Accessibility helpers ────────────────────────────────────────────────────
# Each chart is paired with (a) a role="img" mount point carrying a concise
# aria-label and (b) a collapsible, machine-readable data table built from the
# same DataFrame that feeds the chart — the WCAG 1.1.1 text alternative.

# Returns the empty <div> where Plotly will draw a chart, labeled for screen readers.
def _chart_div(div_id, aria_label):
    """Plotly mount point exposed to assistive tech as one labeled image.

    role="img" makes screen readers announce `aria_label` and skip the SVG
    internals Plotly injects at runtime; the adjacent data table carries the
    full numbers. The label is HTML-escaped.
    """
    return (
        f'<div id="{div_id}" class="plotly-chart" role="img" '
        f'aria-label="{_html.escape(aria_label)}"></div>'
    )


# Formats a percentage for a table cell, using a dash when the value is missing.
def _pct_str(v):
    """Return "—" if v is NaN, otherwise v with a sign and one decimal, like "+2.3%"."""
    return "—" if pd.isna(v) else f"{v:+.1f}%"


# Builds a collapsible HTML data table that serves as the text alternative to a chart.
def _data_table_html(caption, columns, rows):
    """Build a WCAG-compliant, collapsible data table.

    columns: header labels; the first names the row-header column.
    rows: iterable of tuples; each row's first cell becomes a <th scope="row">.
    Cell values are pre-formatted strings. All text is HTML-escaped, and the
    table is wrapped in a <details> element with a scrollable container.
    """
    head = "".join(f'<th scope="col">{_html.escape(str(c))}</th>' for c in columns)
    body = []
    for row in rows:
        cells = [f'<th scope="row">{_html.escape(str(row[0]))}</th>']
        cells += [f"<td>{_html.escape(str(v))}</td>" for v in row[1:]]
        body.append("<tr>" + "".join(cells) + "</tr>")
    cap = _html.escape(caption)
    return (
        '<details class="data-table-details">'
        f"<summary>Show data table — {cap}</summary>"
        '<div class="table-scroll">'
        f'<table class="data-table"><caption>{cap}</caption>'
        f"<thead><tr>{head}</tr></thead>"
        f'<tbody>{"".join(body)}</tbody></table>'
        "</div></details>"
    )


# Builds the data table that accompanies the county map, one row per county.
def _map_table_html(summary):
    """Sort the county summary by employment (largest first) and format each row.

    Columns are employment, establishments, average salary, and YoY employment
    growth, formatted with fmt_number, fmt_currency, and _pct_str.
    """
    ordered = summary.sort_values("employment", ascending=False, na_position="last")
    rows = [
        (
            f'{r["county_name"]} County',
            fmt_number(r["employment"]),
            fmt_number(r["qtrly_estabs"]),
            fmt_currency(r["avg_annual_wage"]),
            _pct_str(r.get("oty_emp_pct")),
        )
        for _, r in ordered.iterrows()
    ]
    return _data_table_html(
        "Upper Peninsula counties — latest-quarter employment, establishments, "
        "average salary, and year-over-year employment growth",
        ["County", "Employment", "Establishments", "Average Salary",
         "YoY Employment Growth"],
        rows,
    )


# Builds the data table that accompanies the largest-county growth comparison.
def _top_table_html(top):
    """Format one row per county with its YoY employment, establishment, and wage growth."""
    rows = [
        (
            f'{r["county_name"]} County',
            _pct_str(r["oty_emp_pct"]),
            _pct_str(r["oty_estab_pct"]),
            _pct_str(r["oty_wage_pct"]),
        )
        for _, r in top.iterrows()
    ]
    return _data_table_html(
        "Largest Upper Peninsula county economies — year-over-year growth in "
        "employment, establishments, and wages",
        ["County", "YoY Employment", "YoY Establishments", "YoY Wages"],
        rows,
    )


# Returns the small year-over-year change badge (arrow and percent) shown on KPI
# cards, or an empty string if the value is missing.
def _delta_html(pct):
    """Render a YoY percent-change badge.

    Direction is conveyed three ways (WCAG 1.4.1 — never color alone): the
    ▲/▼ glyph, the value, and an aria-label word for screen readers. Zero or
    positive values use the "positive" style and an up arrow; negative values
    use the "negative" style and a down arrow.
    """
    if pd.isna(pct):
        return ""
    css = "positive" if pct >= 0 else "negative"
    arrow = "&#9650;" if pct >= 0 else "&#9660;"
    word = "increased" if pct >= 0 else "decreased"
    label = f"{word} {abs(pct):.1f} percent year over year"
    return f'<div class="kpi-delta {css}" aria-label="{label}">{arrow} {abs(pct):.1f}% YoY</div>'


# ── KPI Card ─────────────────────────────────────────────────────────────────

# Builds the second row of a KPI card: real GDP, unemployment rate, and net
# migration. Any missing value shows "—" and "(unavailable)".
def _secondary_row_html(secondary):
    """Build the second KPI row HTML — Real GDP, Unemployment, Net Migration.

    `secondary` is a dict with optional "gdp", "unrate", and "irs" entries (the
    outputs of the latest_* helpers in data/clean.py). GDP shows billions and a
    YoY badge. Unemployment shows the rate and a percentage-point badge, with
    the color inverted (rising is red, falling is green) because lower is
    better. Migration shows a signed net count with its filing-year window and
    no arrow.
    """
    secondary = secondary or {}
    gdp = secondary.get("gdp") or {}
    unr = secondary.get("unrate") or {}
    irs = secondary.get("irs") or {}

    if gdp:
        gdp_value = f"${gdp['value_billions']:.1f}B"
        growth = gdp["yoy_growth"]
        arrow = "&#9650;" if growth >= 0 else "&#9660;"
        cls = "positive" if growth >= 0 else "negative"
        word = "increased" if growth >= 0 else "decreased"
        glabel = f"{word} {abs(growth)*100:.1f} percent year over year"
        gdp_delta = f'<div class="kpi-delta {cls}" aria-label="{glabel}">{arrow} {abs(growth)*100:.1f}% YoY</div>'
        gdp_period = f'<div class="kpi-period">({gdp["year"]})</div>'
    else:
        gdp_value, gdp_delta, gdp_period = "—", "", '<div class="kpi-period">(unavailable)</div>'

    if unr:
        unr_value = f"{unr['rate']:.1f}%"
        delta = unr["yoy_delta_pp"]
        # Arrow tracks rate direction (▲ rose, ▼ fell). Color INVERTED:
        # rising = red (bad), falling = green (good) — lower-is-better.
        arrow = "&#9650;" if delta >= 0 else "&#9660;"
        cls = "negative" if delta >= 0 else "positive"
        word = "rose" if delta >= 0 else "fell"
        ulabel = f"{word} {abs(delta):.1f} percentage points year over year"
        unr_delta = f'<div class="kpi-delta {cls}" aria-label="{ulabel}">{arrow} {abs(delta):.1f}pp YoY</div>'
        unr_period = f'<div class="kpi-period">({unr["month_label"]})</div>'
    else:
        unr_value, unr_delta, unr_period = "—", "", '<div class="kpi-period">(unavailable)</div>'

    if irs:
        sign = "+" if irs["net_exemptions"] >= 0 else "−"
        irs_value = f"{sign}{abs(irs['net_exemptions']):,}"
        irs_delta = ""  # no arrow on migration — sign is the headline
        irs_period = (
            f'<div class="kpi-period">'
            f'({irs["origin_year"]}→{irs["dest_year"]} filings, US + foreign)'
            f'</div>'
        )
    else:
        irs_value, irs_delta, irs_period = "—", "", '<div class="kpi-period">(unavailable)</div>'

    return (
        f'<div class="kpi-row secondary">'
        f'<div class="kpi-item"><div class="kpi-label">Real GDP</div>'
        f'<div class="kpi-value">{gdp_value}</div>{gdp_delta}{gdp_period}</div>'
        f'<div class="kpi-item"><div class="kpi-label">Unemployment rate</div>'
        f'<div class="kpi-value">{unr_value}</div>{unr_delta}{unr_period}</div>'
        f'<div class="kpi-item"><div class="kpi-label">Net Migration</div>'
        f'<div class="kpi-value">{irs_value}</div>{irs_delta}{irs_period}</div>'
        f'</div>'
    )


# Builds the HTML for one county's KPI card: employment, establishments, and
# average salary, plus the optional second row.
def build_kpi_card(county_df, county_name, color, secondary=None):
    """Generate HTML for one county KPI card (primary + optional secondary row).

    Takes the county's latest-quarter total-covered row and shows its
    employment, establishment count, and average annual wage, each with a YoY
    badge from the BLS over-the-year columns. The secondary row comes from
    _secondary_row_html. If the county has no total-covered data, it returns a
    card that says "No data available." The county color is used for the left
    border and the name.
    """
    totals = get_total_covered(county_df)
    latest = get_latest_quarter(totals)

    if latest.empty:
        return (
            f'<div class="county-card" style="border-left-color: {color};">'
            f'<h3 style="color: {color};">{county_name} County</h3>'
            f'<p>No data available.</p></div>'
        )

    row = latest.iloc[0]
    secondary_html = _secondary_row_html(secondary)
    return (
        f'<div class="county-card" style="border-left-color: {color};">'
        f'<h3 style="color: {color};">{county_name} County</h3>'
        f'<div class="kpi-row">'
        f'<div class="kpi-item"><div class="kpi-label">Employment</div>'
        f'<div class="kpi-value">{fmt_number(row["employment"])}</div>'
        f'{_delta_html(row.get("oty_month3_emplvl_pct_chg"))}</div>'
        f'<div class="kpi-item"><div class="kpi-label">Establishments</div>'
        f'<div class="kpi-value">{fmt_number(row["qtrly_estabs"])}</div>'
        f'{_delta_html(row.get("oty_qtrly_estabs_pct_chg"))}</div>'
        f'<div class="kpi-item"><div class="kpi-label">Average Salary</div>'
        f'<div class="kpi-value">{fmt_currency(row["avg_annual_wage"])}</div>'
        f'{_delta_html(row.get("oty_avg_wkly_wage_pct_chg"))}</div>'
        f'</div>{secondary_html}</div>'
    )


# ── Section Builders ─────────────────────────────────────────────────────────
# Each function builds Plotly figures, adds them to `figures` dict,
# and returns the HTML for that dashboard section.

# Builds one trend line chart (the STL trend plus a dotted projection) for a
# county's employment or salary series.
def _trends_chart(totals, y_col, title, color, tickformat, hover_prefix, log_transform):
    """Side-by-side STL-trend chart with linear projection through the current quarter.

    Computes the STL trend of y_col (from quarters that are not suppressed and
    have an establishment count), aligned to all of the county's quarters.
    The projection horizon is periods_to_current_quarter of the last trend
    date, and project_trend extends the trend using a fit on its last 4
    points. The solid "Trend" line and the dotted "Projected" line (with open
    markers) share the county color, and the projected span is shaded and
    labeled "PROJECTED". Hover text shows the year-quarter label, with
    projected points labeled "(projected)". Use log_transform=True for wages.
    """
    indexed = totals.set_index("date").sort_index()
    labels = indexed["year_qtr"]

    stl_input = totals[~totals.get("is_suppressed", False).fillna(False)]
    stl_input = stl_input[stl_input["qtrly_estabs"].notna()]
    trend = deseasonalize_trend(
        stl_input.set_index("date")[y_col].sort_index(),
        log_transform=log_transform,
    ).reindex(indexed.index)

    hovertemplate = (
        "%{customdata}<br>%{fullData.name}: " + hover_prefix + "%{y:,.0f}<extra></extra>"
    )

    trend_observed = trend.dropna()
    periods = (
        periods_to_current_quarter(trend_observed.index[-1])
        if not trend_observed.empty else 0
    )
    projection = project_trend(trend, periods=periods, lookback=4, log_transform=log_transform)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=trend.index, y=trend.values, customdata=labels.values,
        mode="lines", name="Trend",
        line=dict(color=color, width=3), hovertemplate=hovertemplate,
    ))
    if not projection.empty:
        last_trend_x = trend.dropna().index[-1]
        last_trend_y = trend.dropna().iloc[-1]
        proj_x = [last_trend_x] + list(projection.index)
        proj_y = [last_trend_y] + list(projection.values)
        proj_labels = ["Latest trend"] + [
            f"{d.year} Q{ {2:1, 5:2, 8:3, 11:4}[d.month] } (projected)"
            for d in projection.index
        ]
        fig.add_trace(go.Scatter(
            x=proj_x, y=proj_y, customdata=proj_labels,
            mode="lines+markers", name="Projected",
            line=dict(color=color, dash="dot", width=2.5),
            marker=dict(size=7, color=color, symbol="circle-open",
                        line=dict(width=2, color=color)),
            hovertemplate=hovertemplate,
        ))
        fig.add_vrect(
            x0=last_trend_x, x1=projection.index[-1],
            fillcolor=FAU_SKY_BLUE, opacity=0.5,
            layer="below", line_width=0,
            annotation_text="PROJECTED", annotation_position="top right",
            annotation_font=dict(size=9, color=color),
        )

    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        font=dict(family=PLOTLY_FONT),
        plot_bgcolor="white", paper_bgcolor="white",
        hovermode="x unified", height=440,
        margin=dict(t=50, b=90, l=100, r=20),
        legend=dict(orientation="h", yanchor="top", y=-0.22, x=0),
        xaxis=dict(
            showgrid=False,
            title=dict(text="Quarter", standoff=15),
            showline=True, linecolor="black", linewidth=2, mirror=False,
            ticks="outside", tickcolor="black", ticklen=4,
        ),
        yaxis=dict(
            showgrid=False, tickformat=tickformat,
            title=dict(text=title, standoff=15),
            showline=True, linecolor="black", linewidth=2, mirror=False,
            ticks="outside", tickcolor="black", ticklen=4,
        ),
    )
    return fig


# Builds the Employment & Salary Trends section for one county: a narrative,
# two side-by-side trend charts, and a data table. Returns (html, figures).
def build_trends(county_df, county_name, county_id, heading_level=2):
    """Employment & Salary Trends — raw + STL-trend overlays, side by side.

    Returns (html_fragment, figures_dict) so the caller can either merge the
    figures into the main dashboard's master dict (index.html path) or write
    the fragment as a standalone embed page. ``heading_level`` controls the
    section heading tag: 2 for standalone embeds (under their sr-only h1), 4
    for the index detail tabs (under the h3 county name below "County Detail").

    The narrative comes from narrate_employment_trends, extended with the
    change in average annual wage between the first and last quarters. The
    charts come from _trends_chart (employment on a linear scale, salary on a
    log scale). If the county has no total-covered data, it returns a short
    "No trend data available." section and an empty figures dict.
    """
    h, _h = f"h{heading_level}", f"/h{heading_level}"
    totals = get_total_covered(county_df)
    if totals.empty:
        return f'<div class="section"><{h}>Employment &amp; Salary Trends<{_h}><p>No trend data available.</p></div>', {}

    totals = totals.sort_values("date")
    earliest, latest = totals.iloc[0], totals.iloc[-1]
    color = COUNTY_COLORS.get(county_name, FAU_BLUE)

    narrative = narrate_employment_trends(
        county_name=county_name,
        start_year=int(earliest["year"]), end_year=int(latest["year"]),
        start_empl=earliest["employment"], end_empl=latest["employment"],
    )
    sw, ew = earliest["avg_annual_wage"], latest["avg_annual_wage"]
    if pd.notna(sw) and pd.notna(ew) and sw > 0:
        wc = (ew - sw) / sw * 100
        narrative += (
            f" Average annual wages went from {fmt_currency(sw)} to "
            f"{fmt_currency(ew)}, {'rising' if wc >= 0 else 'falling'} "
            f"{abs(wc):.1f}% over the same period."
        )

    fig_e = _trends_chart(totals, "employment", "Total Employment", color, ",.0f", "", log_transform=False)
    fig_w = _trends_chart(totals, "avg_annual_wage", "Average Salary", color, "$,.0f", "$", log_transform=True)

    eid, wid = f"{county_id}-trends-empl", f"{county_id}-trends-wage"
    figures = {eid: _fig_json(fig_e), wid: _fig_json(fig_w)}

    yr0, yr1 = int(earliest["year"]), int(latest["year"])
    empl_aria = f"Trend line of total employment in {county_name} County, {yr0} to {yr1}."
    wage_aria = (
        f"Trend line of average annual salary in {county_name} County, "
        f"{yr0} to {yr1}, on a logarithmic scale."
    )
    table = _data_table_html(
        f"{county_name} County — quarterly total employment and average salary",
        ["Quarter", "Total Employment", "Average Salary"],
        [
            (r["year_qtr"], fmt_number(r["employment"]), fmt_currency(r["avg_annual_wage"]))
            for _, r in totals.iterrows()
        ],
    )

    html = (
        f'<div class="section"><{h}>Employment &amp; Salary Trends<{_h}>'
        f'<figure class="chart-figure"><figcaption>{narrative}</figcaption>'
        f'<div class="chart-row">'
        f'<div class="chart-col">{_chart_div(eid, empl_aria)}</div>'
        f'<div class="chart-col">{_chart_div(wid, wage_aria)}</div>'
        f'</div></figure>{table}{SOURCE}{TRENDS_NOTE}</div>'
    )
    return html, figures


# Builds the Industry Landscape section for one county: a narrative, the growth
# quadrant bubble chart, and a data table. Returns (html, figures).
def build_growth_quadrant(county_df, county_name, county_id, heading_level=2):
    """Growth Quadrant — YoY employment vs salary growth, domain-colored bubbles.

    Gets the chart data from get_growth_quadrant_data. The narrative names up
    to 3 of the largest industries growing on both measures (both rates above
    zero) and up to 2 of the largest shrinking on both (both below zero);
    industries at exactly zero are in neither list. The figure comes from
    components.growth_quadrant, and the data table is sorted by employment. If
    there is no disclosable data, it returns a short message section and an
    empty figures dict.
    """
    h, _h = f"h{heading_level}", f"/h{heading_level}"
    plot_data = get_growth_quadrant_data(county_df)
    if plot_data.empty:
        return f'<div class="section"><{h}>Industry Landscape<{_h}><p>No disclosable industry growth data.</p></div>', {}

    year, qtr = int(plot_data["year"].iloc[0]), int(plot_data["qtr"].iloc[0])

    ne = plot_data[(plot_data["oty_month3_emplvl_pct_chg"] > 0) & (plot_data["oty_avg_wkly_wage_pct_chg"] > 0)]
    sw = plot_data[(plot_data["oty_month3_emplvl_pct_chg"] < 0) & (plot_data["oty_avg_wkly_wage_pct_chg"] < 0)]

    parts = [
        f"Each bubble is a 2-digit NAICS industry in {year} Q{qtr}; size reflects "
        f"total employment. The horizontal split at 0% salary growth and the vertical "
        f"split at 0% employment growth define four regions. Both growth rates are "
        f"year over year."
    ]
    if not ne.empty:
        names = ne.nlargest(3, "employment")["industry_label"].tolist()
        parts.append(f" Industries expanding on both fronts (jobs and pay): {format_industry_list(names)}.")
    if not sw.empty:
        names = sw.nlargest(2, "employment")["industry_label"].tolist()
        parts.append(f" {format_industry_list(names)} are losing both jobs and pay growth.")
    narrative = "".join(parts)

    fig = build_growth_quadrant_fig(plot_data)
    div_id = f"{county_id}-growth-quadrant"
    figures = {div_id: _fig_json(fig)}

    aria = (
        f"Bubble chart of {len(plot_data)} industries in {county_name} County, "
        f"{year} Q{qtr}, plotted by year-over-year employment growth (horizontal) "
        f"and wage growth (vertical); bubble size reflects employment."
    )
    table = _data_table_html(
        f"{county_name} County — industry employment and year-over-year growth, {year} Q{qtr}",
        ["Industry", "Employment", "YoY Employment Growth", "YoY Wage Growth"],
        [
            (
                r["industry_label"],
                fmt_number(r["employment"]),
                _pct_str(r["oty_month3_emplvl_pct_chg"]),
                _pct_str(r["oty_avg_wkly_wage_pct_chg"]),
            )
            for _, r in plot_data.sort_values("employment", ascending=False).iterrows()
        ],
    )

    html = (
        f'<div class="section"><{h}>Industry Landscape<{_h}>'
        f'<figure class="chart-figure"><figcaption>{narrative}</figcaption>'
        f"{_chart_div(div_id, aria)}</figure>{table}{SOURCE}{GROWTH_QUADRANT_NOTE}</div>"
    )
    return html, figures


# Wraps the firm-formation and treemap methodology texts in source-note paragraphs.
from components.firm_formation import METHODOLOGY_NOTE as _FIRM_FORMATION_TEXT
FIRM_FORMATION_NOTE = f'<p class="source"><em>{_FIRM_FORMATION_TEXT}</em></p>'

from components.employment_treemap import METHODOLOGY_NOTE as _EMPLOYMENT_TREEMAP_TEXT
EMPLOYMENT_TREEMAP_NOTE = f'<p class="source"><em>{_EMPLOYMENT_TREEMAP_TEXT}</em></p>'


# Builds the Firm Openings & Closings section for one county: a narrative, the
# quarterly establishment-change chart, and a data table. Returns (html, figures).
def build_firm_formation(county_df, county_name, county_id, heading_level=2):
    """Firm Openings & Closings — quarterly establishment churn (industry-level decomposition).

    Gets the per-quarter additions, subtractions, and net from
    get_firm_formation_data. It also tries to load the U.S. national
    benchmark (get_national_qoq_pct of fetch_national_data) and the county's
    prior-quarter establishment counts, and falls back to None for either one
    if loading fails, so the chart degrades to a version without the
    benchmark. The narrative describes the most recent quarter as expanded,
    contracted, or flat. If there is not enough data, it returns a short
    message section and an empty figures dict.
    """
    from components.firm_formation import build_figure as firm_formation_fig
    from data.clean import get_firm_formation_data, get_national_qoq_pct
    from data.fetch import fetch_national_data

    h, _h = f"h{heading_level}", f"/h{heading_level}"
    plot_data = get_firm_formation_data(county_df)
    if plot_data.empty:
        return f'<div class="section"><{h}>Firm Openings &amp; Closings<{_h}><p>Not enough establishment data to compute quarterly churn.</p></div>', {}

    # National benchmark — graceful fallback to 3-trace chart if the fetch fails.
    try:
        national_pct = get_national_qoq_pct(fetch_national_data())
        if national_pct.empty:
            national_pct = None
    except Exception:
        national_pct = None
    try:
        county_prev_estabs = (
            get_total_covered(county_df).set_index("date")["qtrly_estabs"]
            .sort_index().shift(1)
        )
    except Exception:
        county_prev_estabs = None

    latest = plot_data.iloc[-1]
    direction = "expanded" if latest["net"] > 0 else ("contracted" if latest["net"] < 0 else "held flat")
    narrative = (
        f"In the most recent quarter ({latest['year_qtr']}), the county's "
        f"establishment count {direction} by {abs(int(latest['net'])):,} firms — "
        f"the net of {int(latest['additions']):,} added across growing industries "
        f"and {int(abs(latest['subtractions'])):,} lost across shrinking ones."
    )

    fig = firm_formation_fig(plot_data, national_pct, county_prev_estabs)
    div_id = f"{county_id}-firm-formation"
    figures = {div_id: _fig_json(fig)}

    aria = (
        f"Bar chart of quarterly establishment additions and losses in "
        f"{county_name} County, with a net-change line overlay."
    )
    table = _data_table_html(
        f"{county_name} County — quarterly establishment additions, losses, and net change",
        ["Quarter", "Establishments Added", "Establishments Lost", "Net Change"],
        [
            (
                r["year_qtr"],
                f"{int(r['additions']):+,}",
                f"{int(r['subtractions']):+,}",
                "—" if pd.isna(r["net"]) else f"{int(r['net']):+,}",
            )
            for _, r in plot_data.iterrows()
        ],
    )

    html = (
        f'<div class="section"><{h}>Firm Openings &amp; Closings<{_h}>'
        f'<figure class="chart-figure"><figcaption>{narrative}</figcaption>'
        f"{_chart_div(div_id, aria)}</figure>{table}{SOURCE}{FIRM_FORMATION_NOTE}</div>"
    )
    return html, figures


# ── HTML Assembly ────────────────────────────────────────────────────────────

# Builds the Workforce Composition section for one county: a narrative, the
# treemap with year buttons, and a data table. Returns (html, figures).
def build_employment_treemap(county_df, county_name, county_id, heading_level=2):
    """Workforce Composition — multi-trace treemap with year-selector buttons.

    Gets one snapshot per year from get_treemap_snapshots and draws them as
    separate traces with components.employment_treemap. The narrative names
    the three largest private-sector employers in the latest snapshot. Plotly's
    built-in year menu is removed, and when there is more than one year,
    keyboard-operable HTML buttons (handled by selectTreemapYear in the page
    script) toggle which trace is visible, with the latest year selected by
    default. The data table covers the latest snapshot. If there is no
    disclosable data, it returns a short message section and an empty figures
    dict.
    """
    from components.employment_treemap import build_figure as treemap_fig
    from data.clean import get_treemap_snapshots

    h, _h = f"h{heading_level}", f"/h{heading_level}"
    snapshots = get_treemap_snapshots(county_df)
    if not snapshots:
        return f'<div class="section"><{h}>Workforce Composition<{_h}><p>No disclosable employment data.</p></div>', {}

    year, qtr, latest = snapshots[-1]
    top3 = latest.head(3)
    items = [
        f"{r['industry_label']} ({r['share']*100:.1f}%)"
        for _, r in top3.iterrows()
    ]
    narrative = (
        f"In {year} Q{qtr}, the county's largest private-sector employers are "
        f"{format_industry_list(items)}."
    )

    fig = treemap_fig(snapshots)
    # Plotly's year menu is a non-focusable SVG control (fails WCAG 2.1.1).
    # Strip it and drive the same trace-visibility toggle from real HTML
    # buttons (built below), which are keyboard-operable and expose state.
    # (Assign the property directly — update_layout(updatemenus=[]) merges and
    # would leave the existing menu in place.)
    fig.layout.updatemenus = []
    div_id = f"{county_id}-employment-treemap"
    figures = {div_id: _fig_json(fig)}

    n = len(snapshots)
    default_idx = n - 1
    year_selector = ""
    if n > 1:
        btns = "".join(
            f'<button type="button" class="year-btn" '
            f'aria-pressed="{"true" if i == default_idx else "false"}" '
            f'data-target="{div_id}" data-trace="{i}" data-count="{n}" '
            f'onclick="selectTreemapYear(this)">{yr}</button>'
            for i, (yr, _q, _snap) in enumerate(snapshots)
        )
        year_selector = (
            f'<div class="year-select" role="group" '
            f'aria-label="Select year for the {county_name} County workforce treemap">'
            f"{btns}</div>"
        )

    aria = (
        f"Treemap of private-sector employment by industry in {county_name} "
        f"County, {year} Q{qtr}; rectangle size reflects employment."
    )
    table = _data_table_html(
        f"{county_name} County — private employment by industry sector, {year} Q{qtr}",
        ["Sector", "Employment", "Share of Private Workforce", "Establishments",
         "Average Salary"],
        [
            (
                r["industry_label"],
                fmt_number(r["employment"]),
                f'{r["share"] * 100:.1f}%',
                fmt_number(r["qtrly_estabs"]),
                fmt_currency(r["avg_annual_wage"]),
            )
            for _, r in latest.iterrows()
        ],
    )

    html = (
        f'<div class="section"><{h}>Workforce Composition<{_h}>'
        f'<figure class="chart-figure"><figcaption>{narrative}</figcaption>'
        f"{_chart_div(div_id, aria)}{year_selector}</figure>"
        f"{table}{SOURCE}{EMPLOYMENT_TREEMAP_NOTE}</div>"
    )
    return html, figures


# Lists the four per-county sections in display order. Both the detail tabs in
# index.html and the standalone embeds loop over this list.
# (slug, builder) pairs — the slug is used as the embed filename under
# docs/embeds/<county>/<slug>.html.
SECTION_BUILDERS = [
    ("trends", build_trends),
    ("workforce-composition", build_employment_treemap),
    ("industry-landscape", build_growth_quadrant),
    ("firm-formation", build_firm_formation),
]
