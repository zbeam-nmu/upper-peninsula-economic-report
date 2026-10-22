"""
A time series spanning [t1] to [t2] years of the median house value per year for every county
in the UP.

## Future upgrades ##
Add trend line prediction like in employment_trends.py if possible
"""
from __future__ import annotations

import plotly.graph_objects as go
import pandas as pd
from data.constants import COUNTY_COLORS, FAU_BLUE, FAU_SKY_BLUE, PLOTLY_FONT
from utils.narratives import narrate_median_house_value_trends, source_citation

METHODOLOGY_NOTE = (
    "Chart shows the median house value per year for every county in the Upper Peninsula."
    "Any data missing from the U.S  is omitted from the chart. Dataa is sourced from the U.S. Census Bureau's American Community Survey (ACS) 5-year estimates."
)

# t-series graph
def _build_chart(
    totals: pd.DataFrame,
    title: str,
    color: str,
) -> go.Figure:
    county_mhv = totals.sort_values("year")
    fig = go.Figure([go.Scatter(
        x=county_mhv["year"],
        y=county_mhv["median_home_value"],
        mode="lines",
        line=dict(color=color, width=3),
        name=title,
    )])
    fig.update_layout(title=title)
    return fig

# rendering the chart in streamlit
def render(df: pd.DataFrame):
    """Render t-series of med_house_value for a single county."""
    import streamlit as st

    st.header("Median Home Value Trends")

    totals = df.sort_values("year")

    if totals.empty:
        st.info("No trend data available.")
        return

    county_name = str(totals["county_name"].iloc[0])
    earliest, latest = totals.iloc[0], totals.iloc[-1]

    med_house_value_text = narrate_median_house_value_trends(
        county_name=county_name,
        start_year=int(earliest["year"]),
        end_year=int(latest["year"]),
        start_value=earliest["median_home_value"],
        end_value=latest["median_home_value"],
    )

    # Escape `$` so Streamlit's markdown doesn't parse "$58,240 to $76,180"
    # as a LaTeX math span.
    st.markdown((med_house_value_text).replace("$", "\\$"))

    color = COUNTY_COLORS.get(county_name, FAU_BLUE)

    st.plotly_chart(
        _build_chart(
            totals=totals,
            title="Median Home Value",
            color=color,
        ),
        use_container_width=True,
    )

    st.caption(source_citation("U.S. Census Bureau ACS", "https://www.census.gov/programs-surveys/acs/", "Annual"))
    st.caption(f"_{METHODOLOGY_NOTE}_")



