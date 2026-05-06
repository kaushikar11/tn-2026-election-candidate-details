#!/usr/bin/env python3
"""
Build a single per-candidate red-flag table from the 6 myneta CSVs.

Inputs (in --input-dir, default ./tn2026_output/):
    candidates_list.csv       - one row per candidate, basic summary
    candidates_summary.csv    - one row per candidate, richer profile
    criminal_cases.csv        - one row per case
    movable_assets.csv        - itemized movable assets
    immovable_assets.csv      - itemized immovable assets
    liabilities.csv           - itemized liabilities
    itr_income.csv            - ITR income per relation

Output:
    candidates_redflags.csv   - one row per candidate, all red-flag columns
    candidates_redflags.xlsx  - same, as Excel

Usage:
    python build_redflag_table.py
    python build_redflag_table.py --input-dir ./mydata --output-dir ./out
"""

import argparse
import re
from pathlib import Path

import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Reference lists for severity classification
# ---------------------------------------------------------------------------

# IPC sections ADR/ECI flag as "serious" (cognizable, non-bailable, ≥5y punishment).
# Plus their BNS equivalents (BNS = Bharatiya Nyaya Sanhita 2023 replaced IPC in 2024).
SERIOUS_IPC_SECTIONS = {
    # Murder / culpable homicide
    "302", "303", "304", "304A", "304B", "307", "308",
    # Kidnapping / abduction
    "363", "364", "364A", "365", "366", "366A", "366B", "367", "368", "369", "370", "370A",
    # Sexual offences
    "354", "354A", "354B", "354C", "354D", "375", "376", "376A", "376B", "376C", "376D", "376E",
    "377",
    # Hurt with weapons / acid
    "324", "326", "326A", "326B",
    # Robbery / dacoity
    "392", "393", "394", "395", "396", "397", "398", "399", "400", "401", "402",
    # Criminal intimidation / extortion
    "383", "384", "385", "386", "387", "506",
    # Rioting with deadly weapons / unlawful assembly causing harm
    "148", "149",
    # Cheating / criminal breach of trust (large)
    "406", "409", "420",
    # Forgery
    "467", "468", "471",
    # Counterfeiting
    "489A", "489B", "489C", "489D",
    # Trafficking
    "370", "370A",
}

SERIOUS_BNS_SECTIONS = {
    # Murder / culpable homicide (BNS 100-105, 109-110)
    "100", "101", "102", "103", "104", "105", "109", "110",
    # Kidnapping / abduction / trafficking
    "137", "138", "139", "140", "141", "142", "143", "144",
    # Sexual offences
    "63", "64", "65", "66", "67", "68", "69", "70", "71", "72", "73", "74", "75", "76", "77", "78",
    # Hurt with weapons / acid
    "118", "119", "120", "121", "122", "123", "124", "125",
    # Robbery / dacoity
    "309", "310", "311",
    # Criminal intimidation
    "351",
    # Rioting / unlawful assembly with deadly weapons
    "189", "190", "191", "192",
    # Cheating / breach of trust
    "316", "318", "319",
    # Forgery
    "336", "338", "340",
}

SERIOUS_SECTIONS = SERIOUS_IPC_SECTIONS | SERIOUS_BNS_SECTIONS

# Special acts that are always treated as red flags
SPECIAL_ACTS = [
    "PMLA", "Prevention of Money Laundering",
    "UAPA", "Unlawful Activities",
    "NDPS", "Narcotic Drugs",
    "Prevention of Corruption",
    "POCSO", "Protection of Children",
    "Arms Act",
    "Explosive",
    "MCOCA",
    "TADA",
    "PASA", "Anti-Social",
    "Goonda",
    "Dowry Prohibition",
    "Domestic Violence",
    "SC/ST", "Scheduled Castes and Scheduled Tribes",
    "Immoral Traffic",
    "Foreign Exchange", "FEMA",
    "Customs",
    "Income Tax Act",
]
SPECIAL_ACTS_RE = re.compile("|".join(re.escape(a) for a in SPECIAL_ACTS), re.I)

WOMEN_COURT_RE = re.compile(r"women|mahila", re.I)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_rupees_text(s):
    """'Rs 1,69,90,582 1 Crore+' -> 16990582 (int) or None.
    The earlier scrape's `total_inr` is broken (digits got concatenated with the
    suffix). We re-parse from the comma-formatted number itself.
    """
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return None
    s = str(s)
    if s.strip().lower() in {"nil", "none", "", "nan"}:
        return None
    # Grab the FIRST run of digits-with-commas — that's the rupees figure.
    m = re.search(r"([\d,]+)", s.replace("Rs", ""))
    if not m:
        return None
    digits = m.group(1).replace(",", "")
    return int(digits) if digits.isdigit() else None


def is_blank(v):
    if v is None:
        return True
    if isinstance(v, float) and np.isnan(v):
        return True
    s = str(v).strip().lower()
    return s in {"", "nil", "none", "nan", "na", "n/a"}


def split_sections(s):
    """'143, 188, 341' -> {'143','188','341'}.  Also handles '376(2)' -> '376'."""
    if is_blank(s):
        return set()
    out = set()
    for part in re.split(r"[,;/]", str(s)):
        part = part.strip()
        # Strip subsection: 376(2) -> 376, 351(2) -> 351
        m = re.match(r"(\d+[A-Za-z]?)", part)
        if m:
            out.add(m.group(1).upper())
    return out


# ---------------------------------------------------------------------------
# Per-table aggregations
# ---------------------------------------------------------------------------

def aggregate_criminal(df_crim: pd.DataFrame) -> pd.DataFrame:
    """One row per candidate with criminal aggregates."""
    if df_crim.empty:
        return pd.DataFrame(columns=["candidate_id"])

    df = df_crim.copy()
    df["candidate_id"] = df["candidate_id"].astype(str)

    # Per-row flags
    df["is_convicted"] = df["case_type"].astype(str).str.lower().eq("convicted")
    df["charges_framed"] = (
        df["charges_framed_or_punishment"].astype(str).str.strip().str.lower().eq("yes")
        & ~df["is_convicted"]
    )

    df["sections_set"] = df["sections"].apply(split_sections)
    df["has_serious_section"] = df["sections_set"].apply(
        lambda s: bool(s & SERIOUS_SECTIONS)
    )
    df["has_special_act"] = df["other_acts"].fillna("").astype(str).apply(
        lambda s: bool(SPECIAL_ACTS_RE.search(s)) if s else False
    )
    df["in_women_court"] = df["court"].fillna("").astype(str).apply(
        lambda s: bool(WOMEN_COURT_RE.search(s))
    )

    # Police station extraction (for repeat-station detection)
    df["police_station"] = df["fir_no"].fillna("").astype(str).str.extract(
        r"([A-Za-z][A-Za-z .]+?(?:PS|Police Station))", expand=False
    ).fillna("").str.strip()

    grouped = df.groupby("candidate_id")

    out = pd.DataFrame({
        "criminal_total_cases": grouped.size(),
        "criminal_pending": grouped.apply(lambda g: int((~g["is_convicted"]).sum())),
        "criminal_convicted": grouped["is_convicted"].sum().astype(int),
        "criminal_charges_framed": grouped["charges_framed"].sum().astype(int),
        "criminal_serious_count": grouped["has_serious_section"].sum().astype(int),
        "criminal_special_acts_count": grouped["has_special_act"].sum().astype(int),
        "criminal_women_court_count": grouped["in_women_court"].sum().astype(int),
    })

    # Concatenated section list and special-acts list (for inspection)
    out["all_sections"] = grouped["sections"].apply(
        lambda s: "; ".join(sorted({x for x in s.dropna().astype(str) if x.strip()}))
    )
    out["all_special_acts"] = grouped["other_acts"].apply(
        lambda s: "; ".join(sorted({x for x in s.dropna().astype(str)
                                     if x.strip() and SPECIAL_ACTS_RE.search(str(x))}))
    )

    # Repeat-station flag: ≥3 cases at the same police station
    def repeat_station(g):
        ps = g["police_station"][g["police_station"] != ""]
        if ps.empty:
            return False
        return ps.value_counts().max() >= 3
    out["criminal_repeat_station"] = grouped.apply(repeat_station).astype(bool)

    # Appeal: did they appeal any conviction?
    def appeal_on_conviction(g):
        conv = g[g["is_convicted"]]
        if conv.empty:
            return np.nan  # not applicable
        return float((conv["appeal_filed"].astype(str).str.lower() == "yes").any())
    out["appeal_filed_on_conviction"] = grouped.apply(appeal_on_conviction)

    # Derived booleans
    out["flag_has_criminal_case"] = out["criminal_total_cases"] > 0
    out["flag_convicted"] = out["criminal_convicted"] > 0
    out["flag_charges_framed"] = out["criminal_charges_framed"] > 0
    out["flag_serious_crime"] = out["criminal_serious_count"] > 0
    out["flag_special_act"] = out["criminal_special_acts_count"] > 0
    out["flag_women_court"] = out["criminal_women_court_count"] > 0

    return out.reset_index()


def aggregate_movable(df_mov: pd.DataFrame) -> pd.DataFrame:
    if df_mov.empty:
        return pd.DataFrame(columns=["candidate_id"])
    df = df_mov.copy()
    df["candidate_id"] = df["candidate_id"].astype(str)

    # Drop summary/total rows
    df = df[~df["sr_no"].astype(str).str.lower().str.contains(
        "total|gross", na=False)]

    desc = df["description"].fillna("").astype(str).str.lower()
    df["bucket"] = np.select(
        [
            desc.str.contains("cash"),
            desc.str.contains("deposit"),
            desc.str.contains("bond|debenture|share"),
            desc.str.contains("nss|postal"),
            desc.str.contains("lic|insurance"),
            desc.str.contains("personal loan|advance given"),
            desc.str.contains("motor|vehicle"),
            desc.str.contains("jewel"),
        ],
        ["cash", "deposits", "shares", "nss", "lic",
         "loans_given", "vehicles", "jewellery"],
        default="other_movable",
    )

    # Sum across self+spouse+huf+dependents per row, parsed properly
    relation_cols = ["self", "spouse", "huf", "dependent1", "dependent2", "dependent3"]
    for c in relation_cols:
        df[c + "_inr"] = df[c].apply(parse_rupees_text)
    df["row_total_inr"] = df[[c + "_inr" for c in relation_cols]].sum(axis=1, min_count=1)

    # Per-bucket totals
    pivot = df.pivot_table(
        index="candidate_id", columns="bucket",
        values="row_total_inr", aggfunc="sum", fill_value=0,
    )
    pivot.columns = [f"movable_{c}_inr" for c in pivot.columns]
    pivot["movable_total_inr"] = pivot.sum(axis=1)

    # Spouse-share when there's a meaningful difference
    spouse_total = df.groupby("candidate_id")["spouse_inr"].sum()
    self_total   = df.groupby("candidate_id")["self_inr"].sum()
    pivot["movable_self_inr"] = self_total
    pivot["movable_spouse_inr"] = spouse_total

    # Number of distinct shareholdings/companies (for shell-company sniff)
    shares = df[df["bucket"] == "shares"].copy()
    if not shares.empty:
        shares["_text"] = shares[relation_cols].fillna("").astype(str).agg(" ".join, axis=1)
        shares["_count"] = shares["_text"].str.count(
            r"\bP(?:vt|rivate)\.?\s*Ltd\b|\bLLP\b|\bLtd\b", flags=re.I
        )
        company_count = shares.groupby("candidate_id")["_count"].sum()
    else:
        company_count = pd.Series(dtype=int)
    pivot["movable_company_holdings_count"] = company_count
    pivot["movable_company_holdings_count"] = pivot["movable_company_holdings_count"].fillna(0).astype(int)

    return pivot.reset_index()


def aggregate_immovable(df_imm: pd.DataFrame) -> pd.DataFrame:
    if df_imm.empty:
        return pd.DataFrame(columns=["candidate_id"])
    df = df_imm.copy()
    df["candidate_id"] = df["candidate_id"].astype(str)
    df = df[~df["sr_no"].astype(str).str.lower().str.contains(
        "total|gross", na=False)]

    desc = df["description"].fillna("").astype(str).str.lower()
    df["bucket"] = np.select(
        [
            desc.str.contains("agricultural") & ~desc.str.contains("non"),
            desc.str.contains("non agricultural|non-agricultural"),
            desc.str.contains("commercial"),
            desc.str.contains("residential"),
        ],
        ["agri_land", "non_agri_land", "commercial_bldg", "residential_bldg"],
        default="other_immovable",
    )

    relation_cols = ["self", "spouse", "huf", "dependent1", "dependent2", "dependent3"]
    for c in relation_cols:
        df[c + "_inr"] = df[c].apply(parse_rupees_text)
    df["row_total_inr"] = df[[c + "_inr" for c in relation_cols]].sum(axis=1, min_count=1)

    pivot = df.pivot_table(
        index="candidate_id", columns="bucket",
        values="row_total_inr", aggfunc="sum", fill_value=0,
    )
    pivot.columns = [f"immovable_{c}_inr" for c in pivot.columns]
    pivot["immovable_total_inr"] = pivot.sum(axis=1)

    # Disclosure-gap: zero purchase cost on non-inherited property
    full_text = (df[relation_cols].fillna("").astype(str).agg(" ".join, axis=1))
    zero_cost_non_inherited = full_text.str.contains(
        r"Whether Inherited\s*N\s*Purchase Date.*?Purchase Cost\s*0(?:\.0+)?", regex=True
    )
    pivot["immovable_zero_cost_non_inherited_count"] = (
        df.assign(flag=zero_cost_non_inherited)
          .groupby("candidate_id")["flag"].sum().astype(int)
    )

    # Property outside Tamil Nadu (rough heuristic)
    other_state_re = re.compile(
        r"\b(?:Kerala|Karnataka|Andhra|Telangana|Mumbai|Delhi|NCR|Bengaluru|Bangalore|Goa|Maharashtra)\b",
        re.I,
    )
    pivot["immovable_outside_tn_flag"] = (
        df.assign(other=full_text.str.contains(other_state_re))
          .groupby("candidate_id")["other"].any()
    )

    return pivot.reset_index()


def aggregate_liabilities(df_liab: pd.DataFrame) -> pd.DataFrame:
    if df_liab.empty:
        return pd.DataFrame(columns=["candidate_id"])
    df = df_liab.copy()
    df["candidate_id"] = df["candidate_id"].astype(str)
    df = df[~df["sr_no"].astype(str).str.lower().str.contains(
        "total|gross|grand", na=False)]

    desc = df["description"].fillna("").astype(str).str.lower()
    relation_cols = ["self", "spouse", "huf", "dependent1", "dependent2", "dependent3"]
    for c in relation_cols:
        df[c + "_inr"] = df[c].apply(parse_rupees_text)
    df["row_total_inr"] = df[[c + "_inr" for c in relation_cols]].sum(axis=1, min_count=1)

    df["bucket"] = np.select(
        [
            desc.str.contains("loans from banks|loans from fis"),
            desc.str.contains("loans due to individual|loans due to entity"),
            desc.str.contains("income tax"),
            desc.str.contains("wealth tax"),
            desc.str.contains("service tax|gst|sales tax"),
            desc.str.contains("property tax"),
            desc.str.contains("government accommodation|water|electricity|telephone|transport"),
            desc.str.contains("dispute"),
        ],
        ["bank_loans", "personal_loans", "income_tax_dues", "wealth_tax_dues",
         "indirect_tax_dues", "property_tax_dues", "govt_dept_dues", "disputed_liability"],
        default="other_liability",
    )

    pivot = df.pivot_table(
        index="candidate_id", columns="bucket",
        values="row_total_inr", aggfunc="sum", fill_value=0,
    )
    pivot.columns = [f"liab_{c}_inr" for c in pivot.columns]
    pivot["liab_total_inr"] = pivot.sum(axis=1)

    # Tax-dues flag
    tax_cols = [c for c in pivot.columns if "tax_dues" in c]
    pivot["flag_tax_dues"] = pivot[tax_cols].sum(axis=1) > 0 if tax_cols else False
    pivot["flag_govt_dues"] = pivot.get("liab_govt_dept_dues_inr", 0) > 0
    pivot["flag_disputed_liability"] = pivot.get("liab_disputed_liability_inr", 0) > 0

    return pivot.reset_index()


def aggregate_itr(df_itr: pd.DataFrame) -> pd.DataFrame:
    if df_itr.empty:
        return pd.DataFrame(columns=["candidate_id"])
    df = df_itr.copy()
    df["candidate_id"] = df["candidate_id"].astype(str)

    # Parse the "income_text" — typically 5 years smushed together.
    # Format: "2024 - 2025 ** Rs 7,89,780 ~ 7 Lacs+ 2023 - 2024 ** ..."
    def extract_incomes(s):
        if is_blank(s):
            return []
        return [int(m.replace(",", "")) for m in re.findall(r"Rs\s*([\d,]+)", str(s))]

    df["incomes"] = df["income_text"].apply(extract_incomes)
    df["income_sum_5y"] = df["incomes"].apply(lambda xs: sum(xs) if xs else 0)
    df["latest_income"] = df["incomes"].apply(lambda xs: xs[0] if xs else 0)

    # Self row
    self_df = df[df["relation_type"] == "self"]
    spouse_df = df[df["relation_type"] == "spouse"]

    out = pd.DataFrame({"candidate_id": df["candidate_id"].unique()}).set_index("candidate_id")
    out["itr_self_pan_given"] = self_df.set_index("candidate_id")["pan_given"]
    out["itr_self_5y_total"]  = self_df.set_index("candidate_id")["income_sum_5y"]
    out["itr_self_latest"]    = self_df.set_index("candidate_id")["latest_income"]
    out["itr_spouse_5y_total"]= spouse_df.set_index("candidate_id")["income_sum_5y"]

    out["flag_pan_not_given"] = out["itr_self_pan_given"].fillna("").astype(str).str.upper().eq("N")
    out["flag_no_itr_filed"]  = out["itr_self_5y_total"].fillna(0).eq(0)

    return out.reset_index()


# ---------------------------------------------------------------------------
# Master combine
# ---------------------------------------------------------------------------
def build(input_dir: Path, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading from {input_dir}")
    candidates_list    = pd.read_csv(input_dir / "candidates_list.csv",    dtype={"candidate_id": str})
    candidates_summary = pd.read_csv(input_dir / "candidates_summary.csv", dtype={"candidate_id": str})
    criminal_cases     = pd.read_csv(input_dir / "criminal_cases.csv",     dtype={"candidate_id": str})
    movable_assets     = pd.read_csv(input_dir / "movable_assets.csv",     dtype={"candidate_id": str})
    immovable_assets   = pd.read_csv(input_dir / "immovable_assets.csv",   dtype={"candidate_id": str})
    liabilities        = pd.read_csv(input_dir / "liabilities.csv",        dtype={"candidate_id": str})
    itr_income         = pd.read_csv(input_dir / "itr_income.csv",         dtype={"candidate_id": str})

    print(f"  candidates_list:    {len(candidates_list):>5} rows")
    print(f"  candidates_summary: {len(candidates_summary):>5} rows")
    print(f"  criminal_cases:     {len(criminal_cases):>5} rows")
    print(f"  movable_assets:     {len(movable_assets):>5} rows")
    print(f"  immovable_assets:   {len(immovable_assets):>5} rows")
    print(f"  liabilities:        {len(liabilities):>5} rows")
    print(f"  itr_income:         {len(itr_income):>5} rows")

    # --- Identity base: prefer richer summary, fall back to list ---
    base = candidates_summary.merge(
        candidates_list[["candidate_id", "party", "constituency", "district",
                          "education", "age_int", "criminal_cases_int",
                          "total_assets_inr", "liabilities_inr",
                          "total_assets", "liabilities"]],
        on="candidate_id", how="outer", suffixes=("", "_list"),
    )
    # Fill missing identity fields
    for col in ["party", "constituency", "district"]:
        if col in base.columns and (col + "_list") in base.columns:
            base[col] = base[col].fillna(base[col + "_list"])
            base = base.drop(columns=[col + "_list"])

    # Re-parse asset / liability totals from text (the original *_inr column is buggy)
    base["assets_total_inr_clean"] = base.get("total_assets", "").apply(parse_rupees_text)
    base["liab_total_inr_clean"]   = base.get("liabilities", "").apply(parse_rupees_text)

    # Disclosure gaps based on blank top-line fields
    base["flag_assets_not_disclosed"] = base.get("total_assets", "").apply(is_blank)
    base["flag_liab_not_disclosed"]   = base.get("liabilities", "").apply(is_blank)
    base["flag_education_unknown"]    = base.get("education", "").apply(
        lambda v: is_blank(v) or str(v).strip().lower() in {"others", "illiterate"}
    )
    base["flag_profession_blank"]     = base.get("self_profession", "").apply(is_blank)

    # Voter-enrolled mismatch
    def voter_mismatch(row):
        ve = str(row.get("voter_enrolled", "")).lower()
        co = str(row.get("constituency", "")).lower()
        if not ve or not co or co == "nan":
            return False
        return co not in ve
    base["flag_voter_constituency_mismatch"] = base.apply(voter_mismatch, axis=1)

    # --- Merge aggregates ---
    print("Aggregating tables...")
    agg_crim = aggregate_criminal(criminal_cases)
    agg_mov  = aggregate_movable(movable_assets)
    agg_imm  = aggregate_immovable(immovable_assets)
    agg_liab = aggregate_liabilities(liabilities)
    agg_itr  = aggregate_itr(itr_income)

    out = base
    for tbl in [agg_crim, agg_mov, agg_imm, agg_liab, agg_itr]:
        out = out.merge(tbl, on="candidate_id", how="left")

    # --- Derived metrics ---
    out["assets_inr"] = out["assets_total_inr_clean"]
    out["liab_inr"]   = out["liab_total_inr_clean"]
    out["net_worth_inr"] = out["assets_inr"].fillna(0) - out["liab_inr"].fillna(0)

    out["liab_to_asset_ratio"] = np.where(
        out["assets_inr"].fillna(0) > 0,
        out["liab_inr"].fillna(0) / out["assets_inr"].replace(0, np.nan),
        np.nan,
    )

    out["wealth_to_income_ratio"] = np.where(
        out["itr_self_5y_total"].fillna(0) > 0,
        out["assets_inr"].fillna(0) / out["itr_self_5y_total"].replace(0, np.nan),
        np.nan,
    )

    # Liquid (cash + jewellery) share
    cash = out.get("movable_cash_inr", 0).fillna(0)
    jewel = out.get("movable_jewellery_inr", 0).fillna(0)
    out["liquid_assets_inr"] = cash + jewel
    movable_total = out.get("movable_total_inr", pd.Series(0, index=out.index)).fillna(0)
    out["liquid_share_of_movable"] = np.where(
        movable_total > 0,
        out["liquid_assets_inr"] / movable_total.replace(0, np.nan),
        np.nan,
    )

    # Spouse-as-housewife with high spouse assets
    spouse_movable = out.get("movable_spouse_inr", 0).fillna(0)
    is_housewife = out.get("spouse_profession", "").fillna("").astype(str).str.lower().str.contains(
        "house|home maker|nil|none", na=False
    )
    out["flag_spouse_housewife_with_high_assets"] = is_housewife & (spouse_movable > 5_000_000)

    # --- Top-line flags (the user's explicit list) ---
    out["flag_crorepati"]            = out["assets_inr"].fillna(0) >= 1_00_00_000
    out["flag_high_cash"]            = cash >= 5_00_000  # ≥5 lakh in cash
    out["flag_many_companies"]       = out.get("movable_company_holdings_count", 0).fillna(0) >= 5
    # Criminal flags come from agg_crim already

    flag_cols = [c for c in out.columns if c.startswith("flag_")]

    # Coerce all flag columns to bool (NaN -> False) so the score doesn't choke
    for c in flag_cols:
        out[c] = out[c].fillna(False).astype(bool)

    # Composite red-flag score (count of triggered booleans)
    out["redflag_score"] = out[flag_cols].sum(axis=1)

    # ---------- Final column order ----------
    identity_cols = [
        "candidate_id", "candidate_name", "party", "constituency", "district",
        "age_detail", "age_int", "education", "education_full",
        "self_profession", "spouse_profession",
        "s_o_d_o_w_o", "voter_enrolled", "candidate_url",
    ]
    financial_cols = [
        "assets_inr", "liab_inr", "net_worth_inr", "liab_to_asset_ratio",
        "movable_total_inr", "movable_cash_inr", "movable_deposits_inr",
        "movable_shares_inr", "movable_jewellery_inr", "movable_vehicles_inr",
        "movable_loans_given_inr", "movable_company_holdings_count",
        "immovable_total_inr", "immovable_agri_land_inr",
        "immovable_non_agri_land_inr", "immovable_commercial_bldg_inr",
        "immovable_residential_bldg_inr", "immovable_zero_cost_non_inherited_count",
        "immovable_outside_tn_flag",
        "liab_bank_loans_inr", "liab_personal_loans_inr",
        "liab_income_tax_dues_inr", "liab_property_tax_dues_inr",
        "liab_govt_dept_dues_inr", "liab_disputed_liability_inr",
        "liquid_assets_inr", "liquid_share_of_movable",
        "movable_self_inr", "movable_spouse_inr",
    ]
    income_cols = [
        "itr_self_pan_given", "itr_self_5y_total", "itr_self_latest",
        "itr_spouse_5y_total", "wealth_to_income_ratio",
    ]
    criminal_cols = [
        "criminal_total_cases", "criminal_pending", "criminal_convicted",
        "criminal_charges_framed", "criminal_serious_count",
        "criminal_special_acts_count", "criminal_women_court_count",
        "criminal_repeat_station", "appeal_filed_on_conviction",
        "all_sections", "all_special_acts",
    ]
    flag_cols_ordered = sorted([c for c in out.columns if c.startswith("flag_")])
    final_cols = (
        identity_cols
        + financial_cols
        + income_cols
        + criminal_cols
        + flag_cols_ordered
        + ["redflag_score"]
    )
    final_cols = [c for c in final_cols if c in out.columns]
    extras = [c for c in out.columns if c not in final_cols]
    out = out[final_cols + extras]

    # Sort: highest red-flag score first
    out = out.sort_values(
        ["redflag_score", "criminal_total_cases", "assets_inr"],
        ascending=[False, False, False],
        na_position="last",
    )

    # Write
    csv_path  = output_dir / "candidates_redflags.csv"
    xlsx_path = output_dir / "candidates_redflags.xlsx"
    out.to_csv(csv_path, index=False)
    out.to_excel(xlsx_path, index=False, engine="openpyxl")

    print(f"\nWrote {len(out)} candidate rows to:")
    print(f"  {csv_path}")
    print(f"  {xlsx_path}")
    print(f"\nRed-flag score distribution:")
    print(out["redflag_score"].value_counts().sort_index().to_string())
    print(f"\nTop 5 by red-flag score:")
    print(out.head(5)[["candidate_name", "party", "constituency",
                        "redflag_score", "criminal_total_cases", "assets_inr"]].to_string())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir",  default="tn2026_output", type=Path)
    p.add_argument("--output-dir", default="tn2026_output", type=Path)
    args = p.parse_args()
    build(args.input_dir, args.output_dir)


if __name__ == "__main__":
    main()