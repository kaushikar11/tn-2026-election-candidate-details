# TN 2026 Election Dashboards

Two Streamlit dashboards, party-comparison focused.

## Setup

```bash
pip install streamlit plotly pandas
```

Place `candidates_redflags.csv` in either:
- `tn2026_output/candidates_redflags.csv`   ← default
- same folder as the scripts

## Run

```bash
# Criminal records dashboard
streamlit run dashboard_criminal.py

# Civil / wealth dashboard  
streamlit run dashboard_civil.py
```

---

## Dashboard 1: Criminal (`dashboard_criminal.py`)

| Section | What it shows |
|---|---|
| KPI row | Total with criminal cases, % tainted, convicted, serious, special-act, avg cases |
| Chart 1 | Party bar — criminal / serious / convicted side-by-side |
| Chart 2 | % tainted candidates per party (colour scale) |
| Chart 3 | Special-act charges by party (PMLA, PC Act, etc.) |
| Chart 4 | Charges framed + women-court cases stacked |
| Chart 5 | Scatter — party size vs % tainted, bubble = total cases |
| Chart 6 | Redflag score distribution stacked by top 10 parties |
| Table | Full party summary with all criminal metrics |
| Candidate table | All candidates with criminal cases, sortable |
| Drill-down | Pick a candidate → see all sections, special acts, metrics |

**Sidebar filters:** District, Party, min-cases slider, toggles for convicted / serious / special-act / women-court, name search.

---

## Dashboard 2: Civil / Wealth (`dashboard_civil.py`)

| Section | What it shows |
|---|---|
| KPI row | Crorepatis, % crorepati, non-disclosure, tax dues, no ITR, median assets |
| Chart 1 | Median vs mean assets per candidate by party |
| Chart 2 | % crorepati per party |
| Chart 3 | Box plot — asset spread by party (log scale) |
| Chart 4 | Treemap — total declared wealth by party |
| Chart 5 | Disclosure red-flags stacked (no ITR, no decl., tax dues, high cash) |
| Chart 6 | Median liabilities per candidate by party |
| Chart 7 | Education profile by party |
| Chart 8 | Median age by party |
| Table | Party summary with wealth metrics |
| Wealth table | Top 100 wealthiest candidates |
| Drill-down | Pick a candidate → assets, liabilities, net worth, all flags |

**Sidebar filters:** District, Party, toggles for crorepati / non-disclosure / tax-dues / high-cash / no-ITR, name search.
