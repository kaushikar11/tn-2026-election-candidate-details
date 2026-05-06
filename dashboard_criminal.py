"""
TN 2026 Elections — Criminal Dashboard
Focus: Party-level criminal case analysis
Run: streamlit run dashboard_criminal.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(
    page_title="TN 2026 — Criminal Dashboard",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    .kpi-box {
        background: #1e1e2e; border-radius: 10px; padding: 16px 20px;
        border-left: 4px solid #e74c3c; text-align: center;
    }
    .kpi-num { font-size: 2rem; font-weight: 700; color: #e74c3c; }
    .kpi-label { font-size: 0.78rem; color: #aaa; margin-top: 4px; }
    .section-title { font-size: 1.15rem; font-weight: 600;
        border-bottom: 2px solid #e74c3c; padding-bottom: 4px; margin: 16px 0 8px; }
</style>
""", unsafe_allow_html=True)

# ── Data loading ─────────────────────────────────────────────────────────────
@st.cache_data
def load_data():
    candidates = [
        "tn2026_output/candidates_redflags.csv",
        "candidates_redflags.csv",
    ]
    for p in candidates:
        if Path(p).exists():
            df = pd.read_csv(p, low_memory=False)
            return df
    st.error("❌ Could not find candidates_redflags.csv. Place it in tn2026_output/ or the same folder.")
    st.stop()

df_all = load_data()

# Normalise numeric cols
num_cols = ["criminal_total_cases","criminal_pending","criminal_convicted",
            "criminal_charges_framed","criminal_serious_count",
            "criminal_special_acts_count","criminal_women_court_count",
            "redflag_score","assets_inr","liab_inr","age_int"]
for c in num_cols:
    if c in df_all.columns:
        df_all[c] = pd.to_numeric(df_all[c], errors="coerce")

bool_flags = [c for c in df_all.columns if c.startswith("flag_")]
for c in bool_flags:
    df_all[c] = df_all[c].map(lambda x: bool(x) if pd.notna(x) else False)

# ── Sidebar filters ───────────────────────────────────────────────────────────
st.sidebar.markdown("## ⚖️ TN 2026 Elections\n### Criminal Dashboard")
st.sidebar.markdown("---")
st.sidebar.title("🔍 Filters")

all_districts = sorted(df_all["district"].dropna().unique()) if "district" in df_all.columns else []
sel_districts = st.sidebar.multiselect("District", all_districts)

all_parties = sorted(df_all["party"].dropna().unique())
sel_parties = st.sidebar.multiselect("Party", all_parties)

_max_cases = int(df_all["criminal_total_cases"].dropna().max()) if df_all["criminal_total_cases"].notna().any() else 0
min_cases = st.sidebar.slider("Min criminal cases", 0, max(1, _max_cases), 0)
only_criminal  = st.sidebar.toggle("Only candidates WITH criminal cases", value=False)
only_convicted = st.sidebar.toggle("Only convicted candidates", value=False)
only_serious   = st.sidebar.toggle("Only serious crimes", value=False)
only_special   = st.sidebar.toggle("Only special-act offences", value=False)
only_women_court = st.sidebar.toggle("Only women-court cases", value=False)
name_search = st.sidebar.text_input("Search candidate name")

# ── Apply filters ─────────────────────────────────────────────────────────────
df = df_all.copy()
if sel_districts: df = df[df["district"].isin(sel_districts)]
if sel_parties:   df = df[df["party"].isin(sel_parties)]
if only_criminal: df = df[df["criminal_total_cases"] > 0]
if only_convicted: df = df[df["criminal_convicted"] > 0]
if only_serious:  df = df[df["criminal_serious_count"] > 0]
if only_special:  df = df[df["criminal_special_acts_count"] > 0]
if only_women_court: df = df[df["criminal_women_court_count"] > 0]
if min_cases > 0: df = df[df["criminal_total_cases"] >= min_cases]
if name_search:   df = df[df["candidate_name"].str.contains(name_search, case=False, na=False)]

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("## ⚖️ TN 2026 Elections — Criminal Record Dashboard")
st.caption(f"Showing **{len(df):,}** of {len(df_all):,} candidates | Data: myneta.info")

# ── KPI row ───────────────────────────────────────────────────────────────────
total_crim = int((df["criminal_total_cases"] > 0).sum())
total_convicted = int((df["criminal_convicted"] > 0).sum())
total_serious = int((df["criminal_serious_count"] > 0).sum())
total_special = int((df["criminal_special_acts_count"] > 0).sum())
total_women = int((df["criminal_women_court_count"] > 0).sum())
avg_cases = df.loc[df["criminal_total_cases"] > 0, "criminal_total_cases"].mean()

cols = st.columns(6)
kpis = [
    (total_crim,      "With criminal cases"),
    (f"{total_crim/len(df)*100:.1f}%", "% tainted candidates"),
    (total_convicted, "Convicted"),
    (total_serious,   "Serious crimes"),
    (total_special,   "Special-act charges"),
    (f"{avg_cases:.1f}" if not pd.isna(avg_cases) else "—", "Avg cases/tainted cand."),
]
for col, (val, label) in zip(cols, kpis):
    col.markdown(f'<div class="kpi-box"><div class="kpi-num">{val}</div><div class="kpi-label">{label}</div></div>', unsafe_allow_html=True)

st.markdown("---")

# ── Party-level aggregation ───────────────────────────────────────────────────
party_agg = (
    df.groupby("party").agg(
        total_candidates=("candidate_name","count"),
        with_criminal=("criminal_total_cases", lambda x: (x > 0).sum()),
        total_cases=("criminal_total_cases","sum"),
        convicted=("criminal_convicted", lambda x: (x > 0).sum()),
        serious=("criminal_serious_count", lambda x: (x > 0).sum()),
        special_act=("criminal_special_acts_count", lambda x: (x > 0).sum()),
        women_court=("criminal_women_court_count", lambda x: (x > 0).sum()),
        charges_framed=("criminal_charges_framed", lambda x: (x > 0).sum()),
    ).reset_index()
)
party_agg["pct_tainted"] = (party_agg["with_criminal"] / party_agg["total_candidates"] * 100).round(1)
party_agg["avg_cases"] = (party_agg["total_cases"] / party_agg["total_candidates"]).round(2)
party_agg = party_agg.sort_values("with_criminal", ascending=False)

# Filter to parties with at least some candidates
MIN_CANDS = st.sidebar.slider("Min candidates per party (charts)", 1, 20, 2)
party_chart = party_agg[party_agg["total_candidates"] >= MIN_CANDS]

# ── Row 1: two main charts ────────────────────────────────────────────────────
st.markdown('<div class="section-title">📊 Criminal Cases by Party</div>', unsafe_allow_html=True)
c1, c2 = st.columns(2)

with c1:
    top_n = st.slider("Show top N parties", 5, 40, 20, key="top_n_bar")
    top = party_chart.nlargest(top_n, "with_criminal")
    fig = go.Figure()
    fig.add_bar(x=top["party"], y=top["with_criminal"], name="Criminal cases", marker_color="#e74c3c")
    fig.add_bar(x=top["party"], y=top["serious"], name="Serious crimes", marker_color="#c0392b")
    fig.add_bar(x=top["party"], y=top["convicted"], name="Convicted", marker_color="#7f1d1d")
    fig.update_layout(
        barmode="group", title="Candidates with criminal records (Top N parties)",
        xaxis_tickangle=-45, height=420, legend=dict(orientation="h"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
    )
    st.plotly_chart(fig, use_container_width=True)

with c2:
    top2 = party_chart.nlargest(top_n, "pct_tainted")
    fig2 = px.bar(
        top2, x="party", y="pct_tainted",
        color="pct_tainted", color_continuous_scale="Reds",
        title="% Tainted candidates per party",
        labels={"pct_tainted": "% tainted", "party": "Party"},
        text=top2["pct_tainted"].astype(str) + "%",
    )
    fig2.update_layout(
        xaxis_tickangle=-45, height=420, showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
    )
    st.plotly_chart(fig2, use_container_width=True)

# ── Row 2: special acts + women court ─────────────────────────────────────────
st.markdown('<div class="section-title">🔴 Special Acts & Serious Offences by Party</div>', unsafe_allow_html=True)
c3, c4 = st.columns(2)

with c3:
    top3 = party_chart[party_chart["special_act"] > 0].nlargest(20, "special_act")
    fig3 = px.bar(
        top3, x="party", y="special_act",
        color="special_act", color_continuous_scale="OrRd",
        title="Candidates with Special-Act charges (PMLA, PC Act, etc.)",
        labels={"special_act": "Candidates", "party": "Party"},
    )
    fig3.update_layout(
        xaxis_tickangle=-45, height=380,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
    )
    st.plotly_chart(fig3, use_container_width=True)

with c4:
    top4 = party_chart.nlargest(20, "charges_framed")
    fig4 = go.Figure()
    fig4.add_bar(x=top4["party"], y=top4["charges_framed"], name="Charges framed", marker_color="#f39c12")
    fig4.add_bar(x=top4["party"], y=top4["women_court"], name="Women-court cases", marker_color="#e91e63")
    fig4.update_layout(
        barmode="stack", title="Charges Framed & Women-court cases",
        xaxis_tickangle=-45, height=380, legend=dict(orientation="h"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
    )
    st.plotly_chart(fig4, use_container_width=True)

# ── Row 3: scatter + redflag distribution ─────────────────────────────────────
st.markdown('<div class="section-title">🎯 Criminal Intensity vs Party Size</div>', unsafe_allow_html=True)
c5, c6 = st.columns(2)

with c5:
    fig5 = px.scatter(
        party_chart,
        x="total_candidates", y="pct_tainted",
        size="total_cases", color="serious",
        hover_name="party",
        color_continuous_scale="Reds",
        title="Party size vs % tainted (bubble = total cases, colour = serious)",
        labels={"total_candidates":"Total candidates","pct_tainted":"% tainted","serious":"Serious"},
    )
    fig5.update_layout(
        height=380,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
    )
    st.plotly_chart(fig5, use_container_width=True)

with c6:
    score_dist = df.groupby(["party","redflag_score"]).size().reset_index(name="count")
    top_parties_list = party_chart.nlargest(10,"with_criminal")["party"].tolist()
    score_dist_top = score_dist[score_dist["party"].isin(top_parties_list)]
    fig6 = px.bar(
        score_dist_top, x="redflag_score", y="count", color="party",
        title="Redflag score distribution (Top 10 parties by criminal count)",
        barmode="stack",
        labels={"redflag_score":"Redflag score","count":"Candidates"},
    )
    fig6.update_layout(
        height=380,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#ccc"),
    )
    st.plotly_chart(fig6, use_container_width=True)

# ── Party summary table ───────────────────────────────────────────────────────
st.markdown('<div class="section-title">📋 Party Summary Table</div>', unsafe_allow_html=True)
show_cols = ["party","total_candidates","with_criminal","pct_tainted",
             "total_cases","convicted","serious","special_act","women_court","charges_framed","avg_cases"]
st.dataframe(
    party_agg[show_cols].style
        .format({"pct_tainted":"{:.1f}%","avg_cases":"{:.2f}"}),
    use_container_width=True, height=400,
)

# ── Candidate-level table ─────────────────────────────────────────────────────
st.markdown('<div class="section-title">🧑‍⚖️ Candidate-level Criminal Detail</div>', unsafe_allow_html=True)

cand_cols = ["candidate_name","party","constituency","district",
             "criminal_total_cases","criminal_pending","criminal_convicted",
             "criminal_charges_framed","criminal_serious_count",
             "criminal_special_acts_count","criminal_women_court_count",
             "redflag_score","all_sections","all_special_acts","candidate_url"]
available = [c for c in cand_cols if c in df.columns]
df_crim = df[df["criminal_total_cases"] > 0][available].sort_values("criminal_total_cases", ascending=False)

# Make URLs clickable
if "candidate_url" in df_crim.columns:
    df_crim = df_crim.copy()
    df_crim["myneta_link"] = df_crim["candidate_url"].apply(
        lambda u: f'<a href="{u}" target="_blank">🔗 View</a>' if pd.notna(u) else ""
    )

st.dataframe(df_crim.drop(columns=["candidate_url"], errors="ignore"),
             use_container_width=True, height=500)

# ── Drill-down ────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">🔎 Candidate Drill-down</div>', unsafe_allow_html=True)
crim_names = df_crim["candidate_name"].dropna().tolist()
if crim_names:
    chosen = st.selectbox("Pick a candidate", crim_names)
    row = df[df["candidate_name"] == chosen].iloc[0]
    dc1, dc2, dc3 = st.columns(3)
    dc1.metric("Total cases", int(row.get("criminal_total_cases", 0) or 0))
    dc2.metric("Convicted", int(row.get("criminal_convicted", 0) or 0))
    dc3.metric("Serious crimes", int(row.get("criminal_serious_count", 0) or 0))
    dc4, dc5, dc6 = st.columns(3)
    dc4.metric("Charges framed", int(row.get("criminal_charges_framed", 0) or 0))
    dc5.metric("Special-act charges", int(row.get("criminal_special_acts_count", 0) or 0))
    dc6.metric("Women-court cases", int(row.get("criminal_women_court_count", 0) or 0))
    st.write(f"**Party:** {row.get('party','—')} | **Constituency:** {row.get('constituency','—')} | **District:** {row.get('district','—')}")
    if pd.notna(row.get("all_sections")):
        st.write(f"**IPC Sections:** `{row['all_sections']}`")
    if pd.notna(row.get("all_special_acts")):
        st.write(f"**Special Acts:** {row['all_special_acts']}")
    if pd.notna(row.get("candidate_url")):
        st.markdown(f"[🔗 Open myneta profile]({row['candidate_url']})")
