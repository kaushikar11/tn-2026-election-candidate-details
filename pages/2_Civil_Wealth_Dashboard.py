"""
TN 2026 Elections — Civil / Wealth Dashboard
Focus: Party-level assets, wealth, disclosures, education, liabilities
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from utils import load_data, safe_pct, crore, sidebar_filters

st.set_page_config(
    page_title="TN 2026 — Civil / Wealth Dashboard",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    .kpi-box {
        background: #1e2e1e; border-radius: 10px; padding: 16px 20px;
        border-left: 4px solid #27ae60; text-align: center;
    }
    .kpi-num { font-size: 2rem; font-weight: 700; color: #27ae60; }
    .kpi-label { font-size: 0.78rem; color: #aaa; margin-top: 4px; }
    .section-title { font-size: 1.15rem; font-weight: 600;
        border-bottom: 2px solid #27ae60; padding-bottom: 4px; margin: 16px 0 8px; }
</style>
""", unsafe_allow_html=True)

# ── Data ──────────────────────────────────────────────────────────────────────
df_all = load_data()

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.markdown("## 💰 TN 2026 Elections\n### Civil & Wealth Dashboard")

df_f = sidebar_filters(df_all)

# Wealth-specific filters
def _flag(df, col):
    return df[col].astype(bool) if col in df.columns else pd.Series(False, index=df.index)

only_crorepati = st.sidebar.toggle("Only crorepatis (assets ≥ 1 Cr)", False)
only_nodiscl   = st.sidebar.toggle("Only non-disclosure of assets",    False)
only_tax_dues  = st.sidebar.toggle("Only with tax dues",               False)
only_high_cash = st.sidebar.toggle("Only high-cash candidates",        False)
only_no_itr    = st.sidebar.toggle("Only no ITR filed",                False)
MIN_CANDS      = st.sidebar.slider("Min candidates per party (charts)", 1, 20, 3)

if only_crorepati: df_f = df_f[_flag(df_f, "flag_crorepati")]
if only_nodiscl:   df_f = df_f[_flag(df_f, "flag_assets_not_disclosed")]
if only_tax_dues:  df_f = df_f[_flag(df_f, "flag_tax_dues")]
if only_high_cash: df_f = df_f[_flag(df_f, "flag_high_cash")]
if only_no_itr:    df_f = df_f[_flag(df_f, "flag_no_itr_filed")]

# ── Empty-filter guard ────────────────────────────────────────────────────────
if df_f.empty:
    st.warning(
        "No candidates match the current filters. "
        "Open the sidebar (tap ☰ at the top-left on mobile) "
        "and select at least one party, district, or constituency."
    )
    st.stop()

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## 💰 TN 2026 Elections — Civil & Wealth Dashboard")
st.caption(f"Showing **{len(df_f):,}** of {len(df_all):,} candidates | Data: myneta.info")

# ── KPIs ──────────────────────────────────────────────────────────────────────
n             = len(df_f)
crorepatis    = int(df_f["flag_crorepati"].sum())           if "flag_crorepati" in df_f.columns else 0
no_disclosure = int(df_f["flag_assets_not_disclosed"].sum()) if "flag_assets_not_disclosed" in df_f.columns else 0
tax_dues      = int(df_f["flag_tax_dues"].sum())            if "flag_tax_dues" in df_f.columns else 0
no_itr        = int(df_f["flag_no_itr_filed"].sum())        if "flag_no_itr_filed" in df_f.columns else 0
median_assets = df_f["assets_inr"].dropna().median() if "assets_inr" in df_f.columns else None

cols = st.columns(6)
kpis = [
    (crorepatis,                          "Crorepatis"),
    (safe_pct(crorepatis, n),             "% crorepatis"),
    (no_disclosure,                       "Non-disclosure"),
    (tax_dues,                            "With tax dues"),
    (no_itr,                              "No ITR filed"),
    (crore(median_assets),                "Median assets"),
]
for col, (val, label) in zip(cols, kpis):
    col.markdown(
        f'<div class="kpi-box"><div class="kpi-num">{val}</div>'
        f'<div class="kpi-label">{label}</div></div>',
        unsafe_allow_html=True,
    )

st.markdown("---")

# ── Party aggregation ─────────────────────────────────────────────────────────
# Ensure flag columns exist (add False column if missing so agg doesn't fail)
for _flag_col in ["flag_crorepati", "flag_no_itr_filed",
                  "flag_assets_not_disclosed", "flag_tax_dues", "flag_high_cash"]:
    if _flag_col not in df_f.columns:
        df_f[_flag_col] = False

_agg_spec = dict(
    total_candidates=("candidate_name",  "count"),
    median_assets=("assets_inr",         "median"),
    mean_assets=("assets_inr",           "mean"),
    total_assets=("assets_inr",          "sum"),
    median_liab=("liab_inr",             "median"),
    median_itr=("itr_self_latest",       "median"),
    crorepatis=("flag_crorepati",              "sum"),
    no_itr=("flag_no_itr_filed",               "sum"),
    no_disclosure=("flag_assets_not_disclosed","sum"),
    tax_dues=("flag_tax_dues",                 "sum"),
    high_cash=("flag_high_cash",               "sum"),
)

party_agg = df_f.groupby("party").agg(**_agg_spec).reset_index()
party_agg["pct_crorepati"]  = (party_agg["crorepatis"] / party_agg["total_candidates"] * 100).round(1)
party_agg["median_assets_cr"] = party_agg["median_assets"] / 1e7
party_agg["mean_assets_cr"]   = party_agg["mean_assets"] / 1e7
party_agg = party_agg.sort_values("median_assets", ascending=False)
party_chart = party_agg[party_agg["total_candidates"] >= MIN_CANDS]

# ── Row 1: assets ─────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">💼 Wealth Distribution by Party</div>', unsafe_allow_html=True)
c1, c2 = st.columns(2)

with c1:
    top_n = st.slider("Show top N parties", 5, 40, 20, key="top_n_assets")
    top = party_chart.nlargest(top_n, "median_assets")
    fig = go.Figure()
    fig.add_bar(x=top["party"], y=top["median_assets_cr"], name="Median assets (Cr)", marker_color="#27ae60")
    fig.add_bar(x=top["party"], y=top["mean_assets_cr"],   name="Mean assets (Cr)",   marker_color="#1abc9c")
    fig.update_layout(
        barmode="group", title="Median vs Mean assets per candidate (₹ Crore)",
        xaxis_tickangle=-45, height=420, legend=dict(orientation="h"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#ccc"),
    )
    st.plotly_chart(fig, use_container_width=True)

with c2:
    top2 = party_chart.nlargest(top_n, "pct_crorepati")
    fig2 = px.bar(
        top2, x="party", y="pct_crorepati",
        color="pct_crorepati", color_continuous_scale="Greens",
        title="% Crorepati candidates per party",
        text=top2["pct_crorepati"].astype(str) + "%",
        labels={"pct_crorepati": "% crorepati", "party": "Party"},
    )
    fig2.update_layout(
        xaxis_tickangle=-45, height=420,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#ccc"),
    )
    st.plotly_chart(fig2, use_container_width=True)

# ── Row 2: box plot + treemap ─────────────────────────────────────────────────
st.markdown('<div class="section-title">📦 Asset Spread by Party</div>', unsafe_allow_html=True)
c3, c4 = st.columns(2)

with c3:
    top_parties_for_box = party_chart.nlargest(12, "total_candidates")["party"].tolist()
    df_box = df_f[df_f["party"].isin(top_parties_for_box) & df_f["assets_inr"].notna()].copy()
    if df_box.empty:
        st.info("No asset data for the current selection.")
    else:
        df_box["assets_cr"] = df_box["assets_inr"] / 1e7
        fig3 = px.box(
            df_box, x="party", y="assets_cr", color="party",
            title="Asset distribution (₹ Crore) — Top 12 parties by candidate count",
            labels={"assets_cr": "Assets (₹ Cr)", "party": "Party"},
            log_y=True,
        )
        fig3.update_layout(
            xaxis_tickangle=-45, height=400, showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#ccc"),
        )
        st.plotly_chart(fig3, use_container_width=True)

with c4:
    top_by_assets = party_chart.nlargest(20, "total_assets").copy()
    top_by_assets["total_assets_cr"] = top_by_assets["total_assets"] / 1e7
    if top_by_assets.empty or top_by_assets["total_assets_cr"].sum() == 0:
        st.info("No asset data for the current selection.")
    else:
        fig4 = px.treemap(
            top_by_assets, path=["party"],
            values="total_assets_cr", color="pct_crorepati",
            color_continuous_scale="Greens",
            title="Total declared wealth by party (₹ Cr, colour = % crorepati)",
        )
        fig4.update_layout(height=400, paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#ccc"))
        st.plotly_chart(fig4, use_container_width=True)

# ── Row 3: disclosure + liabilities ──────────────────────────────────────────
st.markdown('<div class="section-title">📑 Disclosure Quality & Liabilities by Party</div>', unsafe_allow_html=True)
c5, c6 = st.columns(2)

with c5:
    top3 = party_chart.nlargest(top_n, "total_candidates")
    fig5 = go.Figure()
    fig5.add_bar(x=top3["party"], y=top3["no_itr"],        name="No ITR",         marker_color="#e67e22")
    fig5.add_bar(x=top3["party"], y=top3["no_disclosure"], name="No asset decl.", marker_color="#e74c3c")
    fig5.add_bar(x=top3["party"], y=top3["tax_dues"],      name="Tax dues",       marker_color="#9b59b6")
    fig5.add_bar(x=top3["party"], y=top3["high_cash"],     name="High cash",      marker_color="#f1c40f")
    fig5.update_layout(
        barmode="stack", title="Disclosure red-flags by party",
        xaxis_tickangle=-45, height=400, legend=dict(orientation="h"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#ccc"),
    )
    st.plotly_chart(fig5, use_container_width=True)

with c6:
    df_liab = df_f[df_f["liab_inr"].notna() & (df_f["liab_inr"] > 0)].copy()
    if df_liab.empty:
        st.info("No liability data for the current selection.")
    else:
        df_liab["liab_cr"] = df_liab["liab_inr"] / 1e7
        party_liab = (
            df_liab.groupby("party")
            .agg(median_liab_cr=("liab_cr", "median"), count=("liab_cr", "count"))
            .reset_index()
        )
        party_liab = party_liab[party_liab["count"] >= MIN_CANDS].nlargest(20, "median_liab_cr")
        if party_liab.empty:
            st.info("Not enough data for liability chart with current filters.")
        else:
            fig6 = px.bar(
                party_liab, x="party", y="median_liab_cr",
                color="median_liab_cr", color_continuous_scale="Purples",
                title="Median liabilities per candidate (₹ Cr)",
                labels={"median_liab_cr": "Median liab (₹ Cr)", "party": "Party"},
            )
            fig6.update_layout(
                xaxis_tickangle=-45, height=400,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#ccc"),
            )
            st.plotly_chart(fig6, use_container_width=True)

# ── Row 4: education + age ────────────────────────────────────────────────────
st.markdown('<div class="section-title">🎓 Education & Demographics by Party</div>', unsafe_allow_html=True)
c7, c8 = st.columns(2)

with c7:
    if "education_summary" in df_f.columns:
        edu_party = df_f.groupby(["party", "education_summary"]).size().reset_index(name="count")
        top_p = party_chart.nlargest(12, "total_candidates")["party"].tolist()
        edu_party_top = edu_party[edu_party["party"].isin(top_p)]
        if edu_party_top.empty:
            st.info("No education data for the current selection.")
        else:
            fig7 = px.bar(
                edu_party_top, x="party", y="count", color="education_summary",
                title="Education profile by party (Top 12)",
                labels={"count": "Candidates", "education_summary": "Education"},
                barmode="stack",
            )
            fig7.update_layout(
                xaxis_tickangle=-45, height=400, legend=dict(orientation="h"),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#ccc"),
            )
            st.plotly_chart(fig7, use_container_width=True)

with c8:
    if "age_int" in df_f.columns:
        age_party = (
            df_f[df_f["age_int"].notna()]
            .groupby("party")["age_int"]
            .median()
            .reset_index()
        )
        age_party.columns = ["party", "median_age"]
        age_party = (
            age_party[age_party["party"].isin(party_chart["party"])]
            .sort_values("median_age")
        )
        if age_party.empty:
            st.info("No age data for the current selection.")
        else:
            fig8 = px.bar(
                age_party.tail(25), x="party", y="median_age",
                color="median_age", color_continuous_scale="Blues",
                title="Median candidate age by party",
                labels={"median_age": "Median age", "party": "Party"},
            )
            fig8.update_layout(
                xaxis_tickangle=-45, height=400,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#ccc"),
            )
            st.plotly_chart(fig8, use_container_width=True)

# ── Party summary table ───────────────────────────────────────────────────────
st.markdown('<div class="section-title">📋 Party Summary Table</div>', unsafe_allow_html=True)
tbl = party_agg.copy()
tbl["median_assets_cr"] = (tbl["median_assets"] / 1e7).round(2)
tbl["mean_assets_cr"]   = (tbl["mean_assets"] / 1e7).round(2)
show = ["party", "total_candidates", "pct_crorepati", "median_assets_cr", "mean_assets_cr",
        "no_itr", "no_disclosure", "tax_dues", "high_cash"]
show = [c for c in show if c in tbl.columns]
st.dataframe(
    tbl[show].style
        .background_gradient(subset=["pct_crorepati", "median_assets_cr"], cmap="Greens")
        .format({"pct_crorepati": "{:.1f}%", "median_assets_cr": "₹{:.2f} Cr",
                 "mean_assets_cr": "₹{:.2f} Cr"}),
    use_container_width=True, height=400,
)

# ── Top wealth candidates ─────────────────────────────────────────────────────
st.markdown('<div class="section-title">🏆 Wealthiest Candidates</div>', unsafe_allow_html=True)
wcols = ["candidate_name", "party", "constituency", "district",
         "assets_inr", "liab_inr", "net_worth_inr", "itr_self_latest",
         "wealth_to_income_ratio", "redflag_score", "candidate_url"]
wcols_avail = [c for c in wcols if c in df_f.columns]
df_rich = (
    df_f[df_f["assets_inr"].notna()][wcols_avail]
    .sort_values("assets_inr", ascending=False)
    .head(100)
    .copy()
)
if df_rich.empty:
    st.info("No asset data for the current selection.")
else:
    for col in ["assets_inr", "liab_inr", "net_worth_inr"]:
        if col in df_rich.columns:
            df_rich[col] = df_rich[col].apply(lambda x: f"₹{x/1e7:.2f} Cr" if pd.notna(x) else "—")
    st.dataframe(
        df_rich.drop(columns=["candidate_url"], errors="ignore"),
        use_container_width=True, height=500,
    )

# ── Candidate drill-down ──────────────────────────────────────────────────────
st.markdown('<div class="section-title">🔎 Candidate Drill-down</div>', unsafe_allow_html=True)
bool_flags = [c for c in df_f.columns if c.startswith("flag_")]
candidate_names = sorted(df_f["candidate_name"].dropna().unique())
if not candidate_names:
    st.info("No candidates available for drill-down in the current selection.")
else:
    chosen = st.selectbox("Pick a candidate", candidate_names)
    rows = df_f[df_f["candidate_name"] == chosen]
    if rows.empty:
        st.info("Candidate not found in the current filter.")
    else:
        row = rows.iloc[0]
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Total assets", crore(row.get("assets_inr")))
        d2.metric("Liabilities",  crore(row.get("liab_inr")))
        d3.metric("Net worth",    crore(row.get("net_worth_inr")))
        d4.metric("Latest ITR",   crore(row.get("itr_self_latest")))

        flags_fired = [
            c.replace("flag_", "").replace("_", " ")
            for c in bool_flags if c in row.index and row[c]
        ]
        if flags_fired:
            st.write("**Red flags:** " + " | ".join([f"`{f}`" for f in flags_fired]))

        age_display = int(row["age_int"]) if pd.notna(row.get("age_int")) else "—"
        st.write(
            f"**Party:** {row.get('party', '—')} | "
            f"**Constituency:** {row.get('constituency', '—')} | "
            f"**Education:** {row.get('education', '—')} | "
            f"**Age:** {age_display}"
        )
        if pd.notna(row.get("candidate_url")):
            st.markdown(f"[🔗 Open myneta profile]({row['candidate_url']})")
