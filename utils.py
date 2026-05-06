"""
Shared helpers for the TN 2026 Elections Streamlit app.
"""
import streamlit as st
import pandas as pd
from pathlib import Path

NUM_COLS = [
    "criminal_total_cases", "criminal_pending", "criminal_convicted",
    "criminal_charges_framed", "criminal_serious_count",
    "criminal_special_acts_count", "criminal_women_court_count",
    "redflag_score", "assets_inr", "liab_inr", "net_worth_inr",
    "movable_total_inr", "immovable_total_inr", "itr_self_latest",
    "itr_self_5y_total", "age_int", "liab_bank_loans_inr",
    "liab_income_tax_dues_inr", "liquid_assets_inr",
    "wealth_to_income_ratio", "liab_to_asset_ratio",
]


@st.cache_data
def load_data() -> pd.DataFrame:
    for p in [
        "tn2026_output/candidates_redflags.csv",
        "candidates_redflags.csv",
    ]:
        if Path(p).exists():
            df = pd.read_csv(p, low_memory=False)
            for c in NUM_COLS:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            for c in [col for col in df.columns if col.startswith("flag_")]:
                df[c] = df[c].map(
                    lambda x: str(x).strip().lower() in {"true", "1", "yes"}
                    if pd.notna(x) else False
                )
            return df
    st.error("❌ Could not find candidates_redflags.csv. Place it in tn2026_output/ or the same folder.")
    st.stop()


def safe_pct(numerator, denominator, decimals: int = 1, fallback: str = "—") -> str:
    """Percentage that returns a fallback string when denominator is 0."""
    if denominator and denominator > 0:
        return f"{numerator / denominator * 100:.{decimals}f}%"
    return fallback


def crore(val) -> str:
    if pd.isna(val):
        return "—"
    return f"₹{val / 1e7:.2f} Cr"


def sidebar_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Render common sidebar filters (district, party, name) and return filtered dataframe.

    When no party is selected, all parties are shown (not filtered to zero rows).
    """
    st.sidebar.markdown("---")
    st.sidebar.title("🔍 Filters")

    all_districts = sorted(df["district"].dropna().unique()) if "district" in df.columns else []
    sel_districts = st.sidebar.multiselect("District", all_districts)

    all_parties = sorted(df["party"].dropna().unique())
    sel_parties = st.sidebar.multiselect("Party", all_parties)

    name_search = st.sidebar.text_input("Search candidate name")

    out = df.copy()
    if sel_districts:
        out = out[out["district"].isin(sel_districts)]
    if sel_parties:
        out = out[out["party"].isin(sel_parties)]
    else:
        st.sidebar.caption("All parties shown — select specific parties to filter.")
    if name_search:
        out = out[out["candidate_name"].str.contains(name_search, case=False, na=False)]

    return out
