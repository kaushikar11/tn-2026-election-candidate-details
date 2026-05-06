"""
TN 2026 Elections — Home
"""
import streamlit as st
import pandas as pd
from utils import load_data, safe_pct, crore

st.set_page_config(
    page_title="TN 2026 Elections",
    page_icon="🗳️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    .kpi-box {
        background: #1e1e2e; border-radius: 10px; padding: 16px 20px;
        border-left: 4px solid #3498db; text-align: center;
    }
    .kpi-num { font-size: 2rem; font-weight: 700; color: #3498db; }
    .kpi-label { font-size: 0.78rem; color: #aaa; margin-top: 4px; }
</style>
""", unsafe_allow_html=True)

df = load_data()

st.markdown("# 🗳️ TN 2026 Elections — Candidate Intelligence")
n_parties = df["party"].nunique() if "party" in df.columns else "—"
st.caption(f"Data: myneta.info  |  **{len(df):,} candidates** across **{n_parties}** parties")

st.markdown("---")

# Overview KPIs
n = len(df)
n_crim  = int((df["criminal_total_cases"] > 0).sum()) if "criminal_total_cases" in df.columns else 0
n_conv  = int((df["criminal_convicted"] > 0).sum())   if "criminal_convicted" in df.columns else 0
n_crore = int(df["flag_crorepati"].sum())              if "flag_crorepati" in df.columns else 0
n_no_itr = int(df["flag_no_itr_filed"].sum())          if "flag_no_itr_filed" in df.columns else 0

cols = st.columns(5)
kpis = [
    (f"{n:,}", "Total candidates"),
    (f"{n_crim:,} ({safe_pct(n_crim, n)})", "With criminal cases"),
    (f"{n_conv:,} ({safe_pct(n_conv, n)})", "Convicted"),
    (f"{n_crore:,} ({safe_pct(n_crore, n)})", "Crorepatis"),
    (f"{n_no_itr:,} ({safe_pct(n_no_itr, n)})", "No ITR filed"),
]
for col, (val, label) in zip(cols, kpis):
    col.markdown(
        f'<div class="kpi-box"><div class="kpi-num">{val}</div>'
        f'<div class="kpi-label">{label}</div></div>',
        unsafe_allow_html=True,
    )

st.markdown("---")

# Dashboard navigation
st.markdown("### Navigate to a dashboard")
c1, c2 = st.columns(2)
with c1:
    st.page_link("pages/1_Criminal_Dashboard.py", label="⚖️ Criminal Dashboard")
    st.caption("Criminal cases, convictions, serious charges, and special-act offences by party and candidate.")
with c2:
    st.page_link("pages/2_Civil_Wealth_Dashboard.py", label="💰 Civil & Wealth Dashboard")
    st.caption("Declared assets, liabilities, crorepatis, disclosure quality, education, and age profiles.")

st.markdown("---")

# Top parties overview table
if "party" in df.columns:
    st.markdown("### Party overview (top 15 by candidate count)")

    agg: dict = {
        "candidates": ("candidate_name", "count"),
    }
    if "criminal_total_cases" in df.columns:
        agg["with_criminal"] = ("criminal_total_cases", lambda x: (x > 0).sum())
    if "flag_crorepati" in df.columns:
        agg["crorepatis"] = ("flag_crorepati", "sum")
    if "redflag_score" in df.columns:
        agg["median_score"] = ("redflag_score", "median")

    party_sum = (
        df.groupby("party")
        .agg(**agg)
        .reset_index()
        .sort_values("candidates", ascending=False)
        .head(15)
    )

    if "with_criminal" in party_sum.columns:
        party_sum["% criminal"] = party_sum.apply(
            lambda r: safe_pct(r["with_criminal"], r["candidates"]), axis=1
        )

    show_cols = ["party", "candidates"]
    for c in ["with_criminal", "% criminal", "crorepatis", "median_score"]:
        if c in party_sum.columns:
            show_cols.append(c)

    st.dataframe(party_sum[show_cols], use_container_width=True, height=450)
