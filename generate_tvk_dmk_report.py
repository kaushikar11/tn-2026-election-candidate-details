"""
TVK vs DMK — Comparative Analysis Report Generator (hardened)
Run: python3 generate_tvk_dmk_report.py
Output: tvk_vs_dmk_report.docx

Edge cases handled:
- Whitespace / case variations in party labels
- DMK is matched EXACTLY (so AIADMK, DMDK, TTV's "Anna Puratchi Thalaivar
  Amma Dravida Munnetra Kazhagam", and various other Munnetra/Kazhagam
  parties are correctly excluded — they aren't DMK)
- TVK = "Tamilaga Vettri Kazhagam" only (so "Puthiya Tamilagam" and
  "Tamilaga Makkal Nala Katchi" are excluded)
- Optional --include-allies flag to also count DMK alliance partners
- Diagnostic listing of every distinct party label that DID and DID NOT
  match each filter, so you can audit
- Missing columns or all-NaN columns degrade gracefully instead of
  crashing
- Top lists expanded from 3 to 10 candidates so you see meaningful
  coverage of who's in each party
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import warnings
from typing import Iterable

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser()
parser.add_argument(
    "--csv",
    default=None,
    help="Path to candidates_redflags.csv. Auto-detects if not given.",
)
parser.add_argument(
    "--output",
    default="tvk_vs_dmk_report.docx",
    help="Output .docx filename",
)
parser.add_argument(
    "--include-allies",
    action="store_true",
    help="Include DMK alliance partners (INC, CPI, CPI(M), VCK, MDMK) "
         "in the DMK group. Off by default — DMK proper only.",
)
parser.add_argument(
    "--top-n",
    type=int,
    default=10,
    help="How many candidates to list in 'top by cases' / 'top by assets' "
         "tables. Default 10.",
)
args = parser.parse_args()


# ---------------------------------------------------------------------------
# Locate and load the CSV
# ---------------------------------------------------------------------------
def find_csv():
    if args.csv and os.path.exists(args.csv):
        return args.csv
    candidates = [
        "tn2026_output/candidates_redflags.csv",
        "candidates_redflags.csv",
        "../tn2026_output/candidates_redflags.csv",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    print("❌ Could not find candidates_redflags.csv. Use --csv to specify.")
    sys.exit(1)


csv_path = find_csv()
df = pd.read_csv(csv_path, low_memory=False)
print(f"✓ Loaded {len(df)} candidates from {csv_path}")


# ---------------------------------------------------------------------------
# Normalize types and party labels
# ---------------------------------------------------------------------------
num_cols = [
    "criminal_total_cases", "criminal_pending", "criminal_convicted",
    "criminal_charges_framed", "criminal_serious_count",
    "criminal_special_acts_count", "criminal_women_court_count",
    "redflag_score", "assets_inr", "liab_inr", "net_worth_inr",
    "itr_self_latest", "itr_self_5y_total", "age_int",
    "movable_total_inr", "immovable_total_inr", "wealth_to_income_ratio",
]
for c in num_cols:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")

# Coerce flag_* columns to bool (handles "True"/"true"/"1"/"yes"/True/1)
bool_flags = [c for c in df.columns if c.startswith("flag_")]
for c in bool_flags:
    df[c] = df[c].map(
        lambda x: str(x).strip().lower() in {"true", "1", "yes"}
        if pd.notna(x) else False
    )

# Normalize party for matching: strip whitespace, collapse internal spaces.
# Keep the original around for display.
df["party_orig"] = df["party"].fillna("").astype(str)
df["party_norm"] = (
    df["party_orig"].str.strip()
                    .str.replace(r"\s+", " ", regex=True)
)


# ---------------------------------------------------------------------------
# Party filters — explicit, auditable
# ---------------------------------------------------------------------------
# DMK proper. Match the EXACT canonical label, case-insensitively, ignoring
# whitespace. We intentionally do NOT substring-match on "DMK" because that
# would catch AIADMK; nor on "Dravida Munnetra Kazhagam" because it appears
# in several breakaway/rival party names (TTV's faction, DMDK, etc.).
DMK_LABELS = {"DMK", "Dravida Munnetra Kazhagam"}

# TVK — Vijay's party. Exact label only.
TVK_LABELS = {"Tamilaga Vettri Kazhagam", "TVK"}

# DMK alliance partners (only used if --include-allies). Based on the 2026
# alliance composition.
DMK_ALLIES = {
    "INC", "Indian National Congress",
    "CPI", "Communist Party of India",
    "CPI(M)", "CPM", "Communist Party of India (Marxist)",
    "Communist Party of India  (Marxist)",  # double-space variant seen in source
    "VCK", "Viduthalai Chiruthaigal Katchi",
    "MDMK", "Marumalarchi Dravida Munnetra Kazhagam",
}


def make_filter(labels: Iterable[str]) -> pd.Series:
    """Case-insensitive set membership against the normalized party column."""
    label_set = {s.strip().lower() for s in labels}
    return df["party_norm"].str.lower().isin(label_set)


tvk_mask = make_filter(TVK_LABELS)
if args.include_allies:
    dmk_mask = make_filter(DMK_LABELS | DMK_ALLIES)
else:
    dmk_mask = make_filter(DMK_LABELS)

tvk = df[tvk_mask].copy()
dmk = df[dmk_mask].copy()

# ---------------------------------------------------------------------------
# Diagnostic — what got matched and what's adjacent but excluded
# ---------------------------------------------------------------------------
print()
print(f"✓ TVK: {len(tvk)} candidates from labels: "
      f"{sorted(tvk['party_norm'].unique().tolist())}")
print(f"✓ DMK: {len(dmk)} candidates from labels: "
      f"{sorted(dmk['party_norm'].unique().tolist())}")
print()

# Show what we explicitly chose NOT to include but is "near" the filter,
# so you can audit
nearby_dmk = (
    df[~dmk_mask]
    .loc[df["party_norm"].str.contains(
        r"DMK|Dravida|Munnetra|Kazhagam", case=False, regex=True, na=False
    ), "party_norm"]
    .value_counts()
)
nearby_tvk = (
    df[~tvk_mask]
    .loc[df["party_norm"].str.contains(
        r"Vettri|Tamilaga|TVK", case=False, regex=True, na=False
    ), "party_norm"]
    .value_counts()
)
if not nearby_dmk.empty:
    print("ℹ Nearby labels NOT counted as DMK (different parties):")
    for label, n in nearby_dmk.items():
        print(f"     {n:>3}  {label}")
    print()
if not nearby_tvk.empty:
    print("ℹ Nearby labels NOT counted as TVK (different parties):")
    for label, n in nearby_tvk.items():
        print(f"     {n:>3}  {label}")
    print()

if len(tvk) == 0:
    print("⚠ No TVK candidates matched. Check the --csv path or label spellings.")
    sys.exit(1)
if len(dmk) == 0:
    print("⚠ No DMK candidates matched. Check the --csv path or label spellings.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers — every numeric op must tolerate missing columns / all-NaN
# ---------------------------------------------------------------------------
def col(grp: pd.DataFrame, name: str) -> pd.Series:
    """Return the column if present, else an all-NaN series of right length."""
    if name in grp.columns:
        return grp[name]
    return pd.Series([np.nan] * len(grp), index=grp.index)


def safe_int_count(grp: pd.DataFrame, name: str, predicate) -> int:
    s = col(grp, name)
    if s.dropna().empty:
        return 0
    return int(predicate(s).sum())


def safe_sum(grp: pd.DataFrame, name: str) -> float:
    s = col(grp, name).dropna()
    return float(s.sum()) if len(s) else 0.0


def safe_max(grp: pd.DataFrame, name: str):
    s = col(grp, name).dropna()
    return float(s.max()) if len(s) else None


def safe_median(s: pd.Series):
    s = s.dropna()
    return float(s.median()) if len(s) else None


def safe_mean(s: pd.Series):
    s = s.dropna()
    return float(s.mean()) if len(s) else None


def pct(n, d):
    return round(n / d * 100, 1) if d > 0 else 0.0


def crore(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    if v >= 1e7:
        return f"₹{v/1e7:.2f} Cr"
    if v >= 1e5:
        return f"₹{v/1e5:.2f} L"
    if v >= 1e3:
        return f"₹{v/1e3:.1f} K"
    return f"₹{v:,.0f}"


# ---------------------------------------------------------------------------
# Compute stats per party — entire population, not a sample
# ---------------------------------------------------------------------------
def compute_stats(grp: pd.DataFrame, label: str, top_n: int):
    n = len(grp)
    s = {"label": label, "n": n}

    # Criminal — all gracefully default to 0 if column absent
    s["crim_count"]      = safe_int_count(grp, "criminal_total_cases",   lambda x: x > 0)
    s["crim_pct"]        = pct(s["crim_count"], n)
    s["convicted"]       = safe_int_count(grp, "criminal_convicted",     lambda x: x > 0)
    s["convicted_pct"]   = pct(s["convicted"], n)
    s["serious"]         = safe_int_count(grp, "criminal_serious_count", lambda x: x > 0)
    s["serious_pct"]     = pct(s["serious"], n)
    s["special_act"]     = safe_int_count(grp, "criminal_special_acts_count", lambda x: x > 0)
    s["special_pct"]     = pct(s["special_act"], n)
    s["women_court"]     = safe_int_count(grp, "criminal_women_court_count", lambda x: x > 0)
    s["charges_framed"]  = safe_int_count(grp, "criminal_charges_framed", lambda x: x > 0)
    s["chg_pct"]         = pct(s["charges_framed"], n)
    s["total_cases"]     = int(safe_sum(grp, "criminal_total_cases"))
    mx = safe_max(grp, "criminal_total_cases")
    s["max_cases"]       = int(mx) if mx is not None else 0

    # Top-N criminal (use top_n parameter, default 10 — was 3 in original)
    if "criminal_total_cases" in grp.columns:
        topcrim = (
            grp[grp["criminal_total_cases"].fillna(0) > 0]
            .nlargest(top_n, "criminal_total_cases")
        )
    else:
        topcrim = pd.DataFrame()
    s["top_criminal"] = [
        {
            "name": str(r["candidate_name"]),
            "constituency": str(r.get("constituency", "—")),
            "cases": int(r["criminal_total_cases"])
                       if pd.notna(r.get("criminal_total_cases")) else 0,
            "serious": int(r["criminal_serious_count"])
                       if pd.notna(r.get("criminal_serious_count")) else 0,
            "convicted": int(r["criminal_convicted"])
                       if pd.notna(r.get("criminal_convicted")) else 0,
            "sections": str(r.get("all_sections", "—") or "—")[:140],
            "special_acts": (
                str(r.get("all_special_acts", "—") or "—")[:140]
                if pd.notna(r.get("all_special_acts")) else "—"
            ),
        }
        for _, r in topcrim.iterrows()
    ]

    # Assets
    s["has_assets"]     = int(col(grp, "assets_inr").notna().sum())
    s["median_assets"]  = safe_median(col(grp, "assets_inr"))
    s["mean_assets"]    = safe_mean(col(grp, "assets_inr"))
    s["max_assets"]     = safe_max(grp, "assets_inr")
    s["crorepatis"]     = safe_int_count(grp, "assets_inr", lambda x: x >= 1e7)
    s["crore_pct"]      = pct(s["crorepatis"], n)
    s["total_wealth"]   = safe_sum(grp, "assets_inr")

    if "assets_inr" in grp.columns:
        topwealthy = (
            grp[grp["assets_inr"].notna()]
            .nlargest(top_n, "assets_inr")
        )
    else:
        topwealthy = pd.DataFrame()
    s["top_wealthy"] = [
        {
            "name": str(r["candidate_name"]),
            "constituency": str(r.get("constituency", "—")),
            "assets": crore(r["assets_inr"]),
            "liab":   crore(r.get("liab_inr")),
            "cases":  int(r["criminal_total_cases"])
                       if pd.notna(r.get("criminal_total_cases")) else 0,
        }
        for _, r in topwealthy.iterrows()
    ]

    # Liabilities
    s["median_liab"] = safe_median(col(grp, "liab_inr"))
    s["mean_liab"]   = safe_mean(col(grp, "liab_inr"))

    # ITR
    itr_latest = col(grp, "itr_self_latest")
    itr_pos = itr_latest.notna() & (itr_latest > 0)
    s["itr_filed"]     = int(itr_pos.sum())
    s["itr_filed_pct"] = pct(s["itr_filed"], n)
    s["median_itr"]    = safe_median(itr_latest[itr_pos])

    # Disclosure flags
    flag_map = {
        "no_asset_disclosure": "flag_assets_not_disclosed",
        "no_itr":              "flag_no_itr_filed",
        "pan_missing":         "flag_pan_not_given",
        "tax_dues":            "flag_tax_dues",
        "high_cash":           "flag_high_cash",
        "govt_dues":           "flag_govt_dues",
        "disputed_liability":  "flag_disputed_liability",
        "voter_mismatch":      "flag_voter_constituency_mismatch",
        "many_companies":      "flag_many_companies",
        "profession_blank":    "flag_profession_blank",
    }
    s["flags"] = {}
    for k, c_ in flag_map.items():
        if c_ in grp.columns:
            cnt = int(grp[c_].sum())
            s["flags"][k] = {"count": cnt, "pct": pct(cnt, n)}
        else:
            s["flags"][k] = {"count": 0, "pct": 0.0}

    # Redflag score
    s["median_score"] = safe_median(col(grp, "redflag_score"))
    s["mean_score"]   = safe_mean(col(grp, "redflag_score"))
    if "redflag_score" in grp.columns:
        sd = grp["redflag_score"].dropna().astype(int).value_counts().sort_index()
        s["score_dist"] = {int(k): int(v) for k, v in sd.items()}
    else:
        s["score_dist"] = {}

    # Age
    s["median_age"] = safe_median(col(grp, "age_int"))
    s["mean_age"]   = safe_mean(col(grp, "age_int"))
    s["under_40"]   = safe_int_count(grp, "age_int", lambda x: x < 40)
    s["over_60"]    = safe_int_count(grp, "age_int", lambda x: x > 60)
    s["under40_pct"] = pct(s["under_40"], n)
    s["over60_pct"]  = pct(s["over_60"], n)

    # Education
    edu_col = "education_summary" if "education_summary" in grp.columns else "education"
    if edu_col in grp.columns:
        edu = grp[edu_col].fillna("Not declared").value_counts().head(8)
        s["education"] = [
            {"level": str(k), "count": int(v), "pct": pct(int(v), n)}
            for k, v in edu.items()
        ]
    else:
        s["education"] = []

    # Coverage
    s["districts"] = (
        int(grp["district"].nunique()) if "district" in grp.columns else 0
    )
    s["constituencies"] = (
        int(grp["constituency"].nunique()) if "constituency" in grp.columns else n
    )

    # Distinct party labels lumped into this group (helpful for allies mode)
    s["source_labels"] = sorted(grp["party_norm"].unique().tolist())

    return s


tvk_s = compute_stats(tvk, "TVK", args.top_n)
dmk_s = compute_stats(dmk, "DMK" + (" + Allies" if args.include_allies else ""),
                       args.top_n)

print(f"✓ Stats computed (top-N candidate lists = {args.top_n})")
stats_json = json.dumps({"tvk": tvk_s, "dmk": dmk_s}, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Node.js DOCX generation (same as before, lightly cleaned)
# ---------------------------------------------------------------------------
js_script = r"""
const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType,
  VerticalAlign, PageNumber, LevelFormat, Footer
} = require('docx');

const data = JSON.parse(fs.readFileSync('/tmp/tvk_dmk_stats.json','utf8'));
const tvk = data.tvk;
const dmk = data.dmk;

const RED="C0392B", GREEN="1E8449";
const TVKC="1A5276", DMKC="C0392B";
const LIGHT_GREY="F2F3F4", HEADER_BLUE="1B4F72";
const BORDER = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const ALL = { top: BORDER, bottom: BORDER, left: BORDER, right: BORDER };

function cell(text, opts = {}) {
  const { bold=false, color="000000", shade=null, align=AlignmentType.LEFT, size=20, width=null } = opts;
  return new TableCell({
    borders: ALL,
    width: width ? { size: width, type: WidthType.DXA } : undefined,
    shading: shade ? { fill: shade, type: ShadingType.CLEAR } : undefined,
    verticalAlign: VerticalAlign.CENTER,
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({
      alignment: align,
      children: [new TextRun({ text: String(text), bold, color, size, font: "Arial" })]
    })]
  });
}

function headerCell(text, shade = HEADER_BLUE) {
  return new TableCell({
    borders: ALL,
    shading: { fill: shade, type: ShadingType.CLEAR },
    verticalAlign: VerticalAlign.CENTER,
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: String(text), bold: true, color: "FFFFFF", size: 20, font: "Arial" })]
    })]
  });
}

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    children: [new TextRun({ text, bold: true, size: 36, font: "Arial", color: HEADER_BLUE })],
    spacing: { before: 360, after: 200 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: HEADER_BLUE, space: 1 } },
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    children: [new TextRun({ text, bold: true, size: 26, font: "Arial", color: "2C3E50" })],
    spacing: { before: 280, after: 120 },
  });
}
function para(text, opts = {}) {
  const { bold=false, color="2C3E50", size=20, spacing={before:80,after:80}, align=AlignmentType.LEFT } = opts;
  return new Paragraph({
    alignment: align, spacing,
    children: [new TextRun({ text: String(text), bold, color, size, font: "Arial" })]
  });
}
function spacer() { return para(" ", { spacing: { before: 40, after: 40 } }); }

function compTable(rows, widths=[2520,2520,2520,1800]) {
  const total = widths.reduce((a,b)=>a+b,0);
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: widths,
    rows: [
      new TableRow({ children: [
        headerCell("Metric"),
        headerCell(tvk.label || "TVK", TVKC),
        headerCell(dmk.label || "DMK", DMKC),
        headerCell("Edge"),
      ]}),
      ...rows.map(r => new TableRow({ children: [
        cell(r[0], { bold: true, shade: LIGHT_GREY, width: widths[0] }),
        cell(r[1], { width: widths[1], align: AlignmentType.CENTER,
          color: r[4]==="tvk" ? GREEN : (r[4]==="dmk" ? RED : "000000") }),
        cell(r[2], { width: widths[2], align: AlignmentType.CENTER,
          color: r[4]==="dmk" ? GREEN : (r[4]==="tvk" ? RED : "000000") }),
        cell(r[3] || "—", { width: widths[3], align: AlignmentType.CENTER,
          bold: true, color: "555555" }),
      ]}))
    ]
  });
}

function namedTable(headers, rows, widths) {
  const total = widths.reduce((a,b)=>a+b,0);
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: widths,
    rows: [
      new TableRow({ children: headers.map(h => headerCell(h)) }),
      ...rows.map(r => new TableRow({
        children: r.map((v,i) => cell(v, {
          width: widths[i],
          align: i===0 ? AlignmentType.LEFT : AlignmentType.CENTER
        }))
      }))
    ]
  });
}

function lowerIsBetter(a, b) {
  const t = parseFloat(a), d = parseFloat(b);
  if (isNaN(t)||isNaN(d)) return "";
  return t < d ? "tvk" : (d < t ? "dmk" : "");
}
function higherIsBetter(a, b) {
  const t = parseFloat(a), d = parseFloat(b);
  if (isNaN(t)||isNaN(d)) return "";
  return t > d ? "tvk" : (d > t ? "dmk" : "");
}
function crore(v) {
  if (v==null||isNaN(v)) return "N/A";
  if (v>=1e7) return "₹"+(v/1e7).toFixed(2)+" Cr";
  if (v>=1e5) return "₹"+(v/1e5).toFixed(2)+" L";
  return "₹"+v.toFixed(0);
}
function na(v) { return (v==null||isNaN(v)) ? "N/A" : v; }

const children = [];

children.push(spacer(), spacer());
children.push(new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: 0, after: 120 },
  children: [new TextRun({ text: "TN 2026 ELECTIONS", bold: true, size: 52, font: "Arial", color: HEADER_BLUE })]
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: 0, after: 80 },
  children: [new TextRun({ text: "Comparative Candidate Analysis", size: 36, font: "Arial", color: "555555" })]
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: 0, after: 200 },
  children: [new TextRun({ text: `${tvk.label}  vs  ${dmk.label}`, bold: true, size: 44, font: "Arial" })]
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { before: 0, after: 80 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: HEADER_BLUE, space: 1 } },
  children: [new TextRun({
    text: `Source: myneta.info  |  Candidates analysed: ${tvk.label} ${tvk.n}, ${dmk.label} ${dmk.n}`,
    size: 18, font: "Arial", color: "777777"
  })]
}));
children.push(spacer());

// 1. Overview
children.push(h1("1. Overview"));
children.push(para(
  `This report compares candidates fielded by ${tvk.label} and ${dmk.label} in the Tamil Nadu 2026 ` +
  `Legislative Assembly elections. The analysis covers criminal background, declared assets and liabilities, ` +
  `income tax compliance, disclosure quality, education profile, and overall transparency risk scores. ` +
  `All data is sourced from candidate affidavits filed with the Election Commission of India and ` +
  `compiled by myneta.info.`
));
children.push(spacer());

// Show source labels (only useful when --include-allies flag is on)
if (tvk.source_labels.length > 1 || dmk.source_labels.length > 1) {
  children.push(para(`${tvk.label} = ${tvk.source_labels.join(", ")}`, { color: "777777", size: 18 }));
  children.push(para(`${dmk.label} = ${dmk.source_labels.join(", ")}`, { color: "777777", size: 18 }));
  children.push(spacer());
}

children.push(compTable([
  ["Total candidates", tvk.n, dmk.n, "", ""],
  ["Districts covered", na(tvk.districts), na(dmk.districts), "", ""],
  ["Constituencies", na(tvk.constituencies), na(dmk.constituencies), "", ""],
  ["Median redflag score",
    tvk.median_score!=null?tvk.median_score.toFixed(1):"N/A",
    dmk.median_score!=null?dmk.median_score.toFixed(1):"N/A",
    tvk.median_score < dmk.median_score ? `${tvk.label} cleaner` :
    dmk.median_score < tvk.median_score ? `${dmk.label} cleaner` : "Equal",
    lowerIsBetter(tvk.median_score, dmk.median_score)],
]));
children.push(spacer());

// 2. Criminal
children.push(new Paragraph({ children: [new TextRun({ text: "", size: 20 })], pageBreakBefore: true }));
children.push(h1("2. Criminal Background"));
children.push(para(
  "This section analyses how many candidates from each party have pending or decided criminal cases, " +
  "including cases involving serious charges (cognizable offences carrying 5+ years), special-act offences " +
  "(PMLA, Prevention of Corruption Act, NDPS, etc.), and cases before women's courts."
));
children.push(spacer());

children.push(h2("2.1 Criminal Case Summary"));
children.push(compTable([
  ["With criminal cases",
    `${tvk.crim_count} (${tvk.crim_pct}%)`, `${dmk.crim_count} (${dmk.crim_pct}%)`,
    "", lowerIsBetter(tvk.crim_pct, dmk.crim_pct)],
  ["Convicted",
    `${tvk.convicted} (${tvk.convicted_pct}%)`, `${dmk.convicted} (${dmk.convicted_pct}%)`,
    "", lowerIsBetter(tvk.convicted_pct, dmk.convicted_pct)],
  ["Serious crimes",
    `${tvk.serious} (${tvk.serious_pct}%)`, `${dmk.serious} (${dmk.serious_pct}%)`,
    "", lowerIsBetter(tvk.serious_pct, dmk.serious_pct)],
  ["Charges framed",
    `${tvk.charges_framed} (${tvk.chg_pct}%)`, `${dmk.charges_framed} (${dmk.chg_pct}%)`,
    "", lowerIsBetter(tvk.chg_pct, dmk.chg_pct)],
  ["Special-act offences",
    `${tvk.special_act} (${tvk.special_pct}%)`, `${dmk.special_act} (${dmk.special_pct}%)`,
    "", lowerIsBetter(tvk.special_pct, dmk.special_pct)],
  ["Women-court cases",
    tvk.women_court, dmk.women_court, "", lowerIsBetter(tvk.women_court, dmk.women_court)],
  ["Total cases (cumulative)",
    tvk.total_cases, dmk.total_cases, "", lowerIsBetter(tvk.total_cases, dmk.total_cases)],
  ["Max cases (single candidate)",
    tvk.max_cases, dmk.max_cases, "", lowerIsBetter(tvk.max_cases, dmk.max_cases)],
]));
children.push(spacer());

children.push(h2(`2.2 Top ${tvk.top_criminal.length} Criminal Records — ${tvk.label}`));
if (tvk.top_criminal.length > 0) {
  children.push(namedTable(
    ["Candidate","Constituency","Cases","Serious","Convicted","Sections"],
    tvk.top_criminal.map(c=>[c.name, c.constituency, c.cases, c.serious, c.convicted, c.sections]),
    [1900,1700,720,720,900,2420]
  ));
} else {
  children.push(para("No candidates with criminal cases.", { color: "777777" }));
}
children.push(spacer());

children.push(h2(`2.3 Top ${dmk.top_criminal.length} Criminal Records — ${dmk.label}`));
if (dmk.top_criminal.length > 0) {
  children.push(namedTable(
    ["Candidate","Constituency","Cases","Serious","Convicted","Sections"],
    dmk.top_criminal.map(c=>[c.name, c.constituency, c.cases, c.serious, c.convicted, c.sections]),
    [1900,1700,720,720,900,2420]
  ));
} else {
  children.push(para("No candidates with criminal cases.", { color: "777777" }));
}
children.push(spacer());

// 3. Assets
children.push(new Paragraph({ children: [new TextRun({ text: "", size: 20 })], pageBreakBefore: true }));
children.push(h1("3. Declared Assets & Wealth"));
children.push(para(
  "Candidates are required to declare total movable and immovable assets in their affidavits. " +
  "This section compares wealth levels, the proportion of crorepati candidates (assets ≥ ₹1 crore), " +
  "and median declared liabilities."
));
children.push(spacer());

children.push(h2("3.1 Asset Summary"));
children.push(compTable([
  ["Candidates with declared assets",
    `${tvk.has_assets} of ${tvk.n}`, `${dmk.has_assets} of ${dmk.n}`,
    "", higherIsBetter(tvk.has_assets/tvk.n, dmk.has_assets/dmk.n)],
  ["Median declared assets", crore(tvk.median_assets), crore(dmk.median_assets), "", ""],
  ["Mean declared assets",   crore(tvk.mean_assets),   crore(dmk.mean_assets),   "", ""],
  ["Highest single candidate", crore(tvk.max_assets),  crore(dmk.max_assets),    "", ""],
  ["Crorepati candidates",
    `${tvk.crorepatis} (${tvk.crore_pct}%)`,
    `${dmk.crorepatis} (${dmk.crore_pct}%)`, "", ""],
  ["Median liabilities", crore(tvk.median_liab), crore(dmk.median_liab), "", ""],
  ["Mean liabilities",   crore(tvk.mean_liab),   crore(dmk.mean_liab),   "", ""],
]));
children.push(spacer());

children.push(h2(`3.2 Wealthiest Candidates — ${tvk.label}`));
if (tvk.top_wealthy.length > 0) {
  children.push(namedTable(
    ["Candidate","Constituency","Assets","Liabilities","Cases"],
    tvk.top_wealthy.map(c=>[c.name, c.constituency, c.assets, c.liab, c.cases]),
    [2100, 2000, 1800, 1800, 760]
  ));
}
children.push(spacer());

children.push(h2(`3.3 Wealthiest Candidates — ${dmk.label}`));
if (dmk.top_wealthy.length > 0) {
  children.push(namedTable(
    ["Candidate","Constituency","Assets","Liabilities","Cases"],
    dmk.top_wealthy.map(c=>[c.name, c.constituency, c.assets, c.liab, c.cases]),
    [2100, 2000, 1800, 1800, 760]
  ));
}
children.push(spacer());

// 4. ITR & disclosure
children.push(new Paragraph({ children: [new TextRun({ text: "", size: 20 })], pageBreakBefore: true }));
children.push(h1("4. Income Tax & Disclosure Quality"));
children.push(para(
  "This section examines transparency in financial disclosure. Candidates who fail to file income tax returns, " +
  "omit PAN, leave assets undeclared, or have outstanding tax/government dues are assigned disclosure red-flags."
));
children.push(spacer());

children.push(h2("4.1 ITR Compliance"));
children.push(compTable([
  ["Filed ITR (latest year > 0)",
    `${tvk.itr_filed} (${tvk.itr_filed_pct}%)`,
    `${dmk.itr_filed} (${dmk.itr_filed_pct}%)`,
    "", higherIsBetter(tvk.itr_filed_pct, dmk.itr_filed_pct)],
  ["Median latest-year ITR", crore(tvk.median_itr), crore(dmk.median_itr), "", ""],
]));
children.push(spacer());

children.push(h2("4.2 Disclosure Red-Flags"));
const flagLabels = {
  no_asset_disclosure: "Assets not disclosed",
  no_itr: "No ITR filed",
  pan_missing: "PAN not given",
  tax_dues: "Outstanding tax dues",
  high_cash: "Unusually high cash",
  govt_dues: "Govt. dept. dues",
  disputed_liability: "Disputed liabilities",
  voter_mismatch: "Voter-constituency mismatch",
  many_companies: "Large company holdings",
  profession_blank: "Profession not declared",
};
const flagRows = Object.entries(flagLabels).map(([k, label]) => {
  const tf = tvk.flags[k] || {count:0,pct:0};
  const df_ = dmk.flags[k] || {count:0,pct:0};
  return [
    label,
    `${tf.count} (${tf.pct}%)`,
    `${df_.count} (${df_.pct}%)`,
    "",
    lowerIsBetter(tf.pct, df_.pct),
  ];
});
children.push(compTable(flagRows));
children.push(spacer());

// 5. Demographics
children.push(new Paragraph({ children: [new TextRun({ text: "", size: 20 })], pageBreakBefore: true }));
children.push(h1("5. Education & Demographics"));
children.push(spacer());

children.push(h2("5.1 Age Profile"));
children.push(compTable([
  ["Median age",
    tvk.median_age!=null?Math.round(tvk.median_age)+" yrs":"N/A",
    dmk.median_age!=null?Math.round(dmk.median_age)+" yrs":"N/A", "", ""],
  ["Mean age",
    tvk.mean_age!=null?tvk.mean_age.toFixed(1)+" yrs":"N/A",
    dmk.mean_age!=null?dmk.mean_age.toFixed(1)+" yrs":"N/A", "", ""],
  ["Candidates under 40",
    `${tvk.under_40} (${tvk.under40_pct}%)`,
    `${dmk.under_40} (${dmk.under40_pct}%)`, "", ""],
  ["Candidates over 60",
    `${tvk.over_60} (${tvk.over60_pct}%)`,
    `${dmk.over_60} (${dmk.over60_pct}%)`, "", ""],
]));
children.push(spacer());

children.push(h2("5.2 Education Profile"));
const maxEduRows = Math.max(tvk.education.length, dmk.education.length);
const eduRows = [];
for (let i = 0; i < maxEduRows; i++) {
  const te = tvk.education[i], de = dmk.education[i];
  eduRows.push([
    te ? te.level : "—",
    te ? `${te.count} (${te.pct}%)` : "—",
    de ? de.level : "—",
    de ? `${de.count} (${de.pct}%)` : "—",
  ]);
}
children.push(new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [2700, 1980, 2700, 1980],
  rows: [
    new TableRow({ children: [
      headerCell(`${tvk.label} Education Level`, TVKC),
      headerCell(`${tvk.label} Count`, TVKC),
      headerCell(`${dmk.label} Education Level`, DMKC),
      headerCell(`${dmk.label} Count`, DMKC),
    ]}),
    ...eduRows.map(r => new TableRow({ children: [
      cell(r[0], { width: 2700 }),
      cell(r[1], { width: 1980, align: AlignmentType.CENTER }),
      cell(r[2], { width: 2700 }),
      cell(r[3], { width: 1980, align: AlignmentType.CENTER }),
    ]}))
  ]
}));
children.push(spacer());

// 6. Redflag scores
children.push(new Paragraph({ children: [new TextRun({ text: "", size: 20 })], pageBreakBefore: true }));
children.push(h1("6. Composite Redflag Score"));
children.push(para(
  "The redflag score is a composite integer score assigned to each candidate based on the number of " +
  "transparency and accountability flags triggered. A higher score indicates more concerns about a " +
  "candidate's background or disclosure quality."
));
children.push(spacer());

const sumScoreFrom = (dist, threshold) =>
  Object.entries(dist).filter(([k]) => parseInt(k) >= threshold)
        .reduce((a,[,v])=>a+v, 0);

children.push(compTable([
  ["Median score",
    tvk.median_score!=null?tvk.median_score.toFixed(1):"N/A",
    dmk.median_score!=null?dmk.median_score.toFixed(1):"N/A",
    "", lowerIsBetter(tvk.median_score, dmk.median_score)],
  ["Mean score",
    tvk.mean_score!=null?tvk.mean_score.toFixed(2):"N/A",
    dmk.mean_score!=null?dmk.mean_score.toFixed(2):"N/A",
    "", lowerIsBetter(tvk.mean_score, dmk.mean_score)],
  ["Score = 0 (clean)",
    `${tvk.score_dist[0]||0} (${pct(tvk.score_dist[0]||0,tvk.n).toFixed(1)}%)`,
    `${dmk.score_dist[0]||0} (${pct(dmk.score_dist[0]||0,dmk.n).toFixed(1)}%)`,
    "", higherIsBetter(tvk.score_dist[0]||0, dmk.score_dist[0]||0)],
  ["Score ≥ 3",
    `${sumScoreFrom(tvk.score_dist,3)} (${pct(sumScoreFrom(tvk.score_dist,3),tvk.n).toFixed(1)}%)`,
    `${sumScoreFrom(dmk.score_dist,3)} (${pct(sumScoreFrom(dmk.score_dist,3),dmk.n).toFixed(1)}%)`,
    "", ""],
  ["Score ≥ 5 (high concern)",
    `${sumScoreFrom(tvk.score_dist,5)} (${pct(sumScoreFrom(tvk.score_dist,5),tvk.n).toFixed(1)}%)`,
    `${sumScoreFrom(dmk.score_dist,5)} (${pct(sumScoreFrom(dmk.score_dist,5),dmk.n).toFixed(1)}%)`,
    "", ""],
]));

function pct(n, d) { return d > 0 ? (n/d*100) : 0; }

children.push(spacer());

children.push(h2("6.1 Score Distribution Detail"));
const allScores = [...new Set([
  ...Object.keys(tvk.score_dist),
  ...Object.keys(dmk.score_dist)
])].map(s => parseInt(s)).sort((a,b)=>a-b);
children.push(new Table({
  width: { size: 6480, type: WidthType.DXA },
  columnWidths: [1440, 2160, 2160, 720],
  rows: [
    new TableRow({ children: [
      headerCell("Score"),
      headerCell(`${tvk.label} candidates`, TVKC),
      headerCell(`${dmk.label} candidates`, DMKC),
      headerCell("Diff"),
    ]}),
    ...allScores.map(s => {
      const tv = tvk.score_dist[s]||0, dv = dmk.score_dist[s]||0;
      const tvp = (tv/tvk.n*100).toFixed(1), dvp = (dv/dmk.n*100).toFixed(1);
      return new TableRow({ children: [
        cell(s, { width:1440, align: AlignmentType.CENTER, bold: true, shade: LIGHT_GREY }),
        cell(`${tv} (${tvp}%)`, { width:2160, align: AlignmentType.CENTER }),
        cell(`${dv} (${dvp}%)`, { width:2160, align: AlignmentType.CENTER }),
        cell(tv-dv>0?`+${tv-dv}`:tv-dv, { width:720, align: AlignmentType.CENTER }),
      ]});
    })
  ]
}));
children.push(spacer());

// 7. Summary
children.push(new Paragraph({ children: [new TextRun({ text: "", size: 20 })], pageBreakBefore: true }));
children.push(h1("7. Summary & Key Findings"));

const findings = [
  `Candidate pool: ${tvk.label} fielded ${tvk.n} candidates across ${tvk.districts||"multiple"} districts; ${dmk.label} fielded ${dmk.n}.`,
  `Criminal exposure: ${tvk.crim_pct}% of ${tvk.label} candidates have criminal cases vs ${dmk.crim_pct}% for ${dmk.label}. ` +
    `Conviction rates are ${tvk.convicted_pct}% (${tvk.label}) and ${dmk.convicted_pct}% (${dmk.label}).`,
  `Serious charges: ${tvk.label} has ${tvk.serious} candidates with serious charges (${tvk.serious_pct}%); ` +
    `${dmk.label} has ${dmk.serious} (${dmk.serious_pct}%). Special-act charges: ${tvk.label} ${tvk.special_act}, ${dmk.label} ${dmk.special_act}.`,
  `Wealth: ${tvk.label} median declared assets are ${crore(tvk.median_assets)} vs ${dmk.label}'s ${crore(dmk.median_assets)}. ` +
    `${tvk.crore_pct}% of ${tvk.label} candidates are crorepatis vs ${dmk.crore_pct}% of ${dmk.label} candidates.`,
  `ITR compliance: ${tvk.itr_filed_pct}% of ${tvk.label} candidates filed ITR vs ${dmk.itr_filed_pct}% for ${dmk.label}.`,
  `Disclosure: "no ITR" — ${tvk.label} ${tvk.flags.no_itr.pct}%, ${dmk.label} ${dmk.flags.no_itr.pct}%; ` +
    `"no asset disclosure" — ${tvk.label} ${tvk.flags.no_asset_disclosure.pct}%, ${dmk.label} ${dmk.flags.no_asset_disclosure.pct}%.`,
  `Redflag score: ${tvk.label} median ${tvk.median_score!=null?tvk.median_score.toFixed(1):"N/A"} vs ${dmk.label} median ${dmk.median_score!=null?dmk.median_score.toFixed(1):"N/A"}.`,
  `Age: ${tvk.label} median ${tvk.median_age!=null?Math.round(tvk.median_age):"-"} yrs vs ${dmk.label} ${dmk.median_age!=null?Math.round(dmk.median_age):"-"} yrs. ` +
    `${tvk.label} has ${tvk.under40_pct}% under 40 vs ${dmk.label}'s ${dmk.under40_pct}%.`,
];

for (const f of findings) {
  children.push(new Paragraph({
    spacing: { before: 60, after: 60 },
    numbering: { reference: "bullets", level: 0 },
    children: [new TextRun({ text: f, size: 20, font: "Arial", color: "2C3E50" })]
  }));
}

children.push(spacer(), spacer());
children.push(para(
  "Note: This analysis is based solely on data submitted by candidates in their statutory affidavits " +
  "to the Election Commission of India. Accuracy depends on the completeness of those disclosures. " +
  "Pending criminal cases do not imply guilt unless conviction is specifically indicated.",
  { color: "777777", size: 18 }
));

const doc = new Document({
  numbering: {
    config: [{
      reference: "bullets",
      levels: [{
        level: 0, format: LevelFormat.BULLET, text: "\u2022",
        alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } }
      }]
    }]
  },
  styles: {
    default: { document: { run: { font: "Arial", size: 20 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: HEADER_BLUE },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial", color: "2C3E50" },
        paragraph: { spacing: { before: 280, after: 120 }, outlineLevel: 1 } },
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 }
      }
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: `TN 2026 | ${tvk.label} vs ${dmk.label} | Page `, size: 16, color: "999999", font: "Arial" }),
            new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "999999", font: "Arial" }),
            new TextRun({ text: " of ", size: 16, color: "999999", font: "Arial" }),
            new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, color: "999999", font: "Arial" }),
          ]
        })]
      })
    },
    children
  }]
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync('/tmp/tvk_vs_dmk_report.docx', buf);
  console.log('✓ Report written to /tmp/tvk_vs_dmk_report.docx');
}).catch(e => { console.error(e); process.exit(1); });
"""


# ---------------------------------------------------------------------------
# Run Node.js to render the .docx
# ---------------------------------------------------------------------------
with open("/tmp/tvk_dmk_stats.json", "w", encoding="utf-8") as f:
    f.write(stats_json)

with open("/tmp/gen_report.js", "w", encoding="utf-8") as f:
    f.write(js_script)

print("✓ Stats and script written, running Node.js...")

env = os.environ.copy()
# Add common node_modules locations so users on different setups work
for path in ["/opt/homebrew/lib/node_modules", "/usr/local/lib/node_modules",
             "/usr/lib/node_modules"]:
    if os.path.exists(path):
        env["NODE_PATH"] = path + ":" + env.get("NODE_PATH", "")

result = subprocess.run(
    ["node", "/tmp/gen_report.js"],
    capture_output=True, text=True, env=env,
)
if result.returncode != 0:
    print("Node error:", result.stderr)
    print("If 'docx' module is missing: npm install -g docx")
    sys.exit(1)
print(result.stdout.strip())

shutil.copy("/tmp/tvk_vs_dmk_report.docx", args.output)
print(f"✓ Saved to {args.output}")
