"""
Narrative text generation and source citations.
Template-based descriptive paragraphs — no LLM calls.
"""
from utils.formatting import fmt_number, fmt_pct
import pandas as pd


def source_citation(name: str, url: str, frequency: str) -> str:
    """Return a source citation string for st.caption()."""
    return f"Source: [{name}]({url}) — {frequency}"


def format_industry_list(names: list[str]) -> str:
    """Join 1, 2, or 3+ industry names with correct comma/conjunction usage."""
    if len(names) == 0:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def narrate_employment_trends(
    county_name: str,
    start_year: int,
    end_year: int,
    start_empl: float,
    end_empl: float,
) -> str:
    """Describe employment level change over a multi-year period."""
    
    if pd.isna(start_empl) or pd.isna(end_empl) or (not pd.isna(start_empl) and start_empl == 0):
        return (
            f"Between {start_year} and {end_year}, employment data for "
            f"{county_name} is incomplete."
        )
    change_pct = (end_empl - start_empl) / start_empl * 100
    direction = "an increase" if change_pct >= 0 else "a decrease"
    return (
        f"Between {start_year} and {end_year}, employment in {county_name} "
        f"went from {fmt_number(start_empl)} to {fmt_number(end_empl)}, "
        f"{direction} of {fmt_pct(abs(change_pct))}."
    )
