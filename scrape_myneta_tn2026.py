#!/usr/bin/env python3
"""
Scrape candidate affidavit data for Tamil Nadu 2026 elections from myneta.info.

Usage:
    pip install requests beautifulsoup4 lxml pandas openpyxl tqdm
    python scrape_myneta_tn2026.py

Output (in ./tn2026_output/):
    candidates_summary.csv          - one row per candidate (overview)
    criminal_cases.csv              - one row per criminal case
    movable_assets.csv              - itemized movable assets
    immovable_assets.csv            - itemized immovable assets
    liabilities.csv                 - itemized liabilities
    itr_income.csv                  - 5 years of ITR income per relation
    tn2026_full.xlsx                - all of the above as separate sheets

Behaviour:
    - Resumable: caches every fetched page to disk; safe to re-run.
    - Polite: sleeps between requests, retries with backoff on failures.
    - Idempotent: parses from cache, so you can re-parse without re-downloading.
"""

import os
import re
import sys
import time
import json
import random
import hashlib
import logging
from pathlib import Path
from urllib.parse import urljoin, parse_qs, urlparse

import requests
from bs4 import BeautifulSoup
import pandas as pd
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = "https://www.myneta.info/TamilNadu2026/"
OUTPUT_DIR = Path("tn2026_output")
CACHE_DIR = OUTPUT_DIR / "cache"
LOG_FILE = OUTPUT_DIR / "scrape.log"

REQUEST_DELAY_RANGE = (0.8, 1.6)   # seconds between requests (random)
MAX_RETRIES = 4
BACKOFF_BASE = 3                    # seconds; exponential
TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

session = requests.Session()
session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
})


# ---------------------------------------------------------------------------
# HTTP with disk cache + retries
# ---------------------------------------------------------------------------
def _cache_path(url: str) -> Path:
    h = hashlib.md5(url.encode()).hexdigest()
    return CACHE_DIR / f"{h}.html"


def fetch(url: str, force: bool = False) -> str:
    """GET url with disk cache, retries, and polite delay."""
    cache = _cache_path(url)
    if cache.exists() and not force:
        return cache.read_text(encoding="utf-8", errors="replace")

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            time.sleep(random.uniform(*REQUEST_DELAY_RANGE))
            resp = session.get(url, timeout=TIMEOUT)
            if resp.status_code == 200:
                cache.write_text(resp.text, encoding="utf-8")
                return resp.text
            log.warning(f"HTTP {resp.status_code} for {url} (attempt {attempt})")
            last_err = f"HTTP {resp.status_code}"
        except requests.RequestException as e:
            log.warning(f"Request error for {url}: {e} (attempt {attempt})")
            last_err = str(e)
        time.sleep(BACKOFF_BASE * (2 ** (attempt - 1)) + random.uniform(0, 1))

    raise RuntimeError(f"Failed to fetch {url}: {last_err}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def clean(text) -> str:
    if text is None:
        return ""
    if hasattr(text, "get_text"):
        text = text.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", str(text)).strip()


def parse_rupees(s: str):
    """'Rs 3,64,20,864 ~3 Crore+' -> 36420864 (int) or None."""
    if not s:
        return None
    s = s.replace("Rs", "").replace("~", "")
    s = re.split(r"\bCrore|Lacs|Lakhs|Thou|Thousand\b", s, maxsplit=1)[0]
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


def candidate_id_from_href(href: str):
    qs = parse_qs(urlparse(href).query)
    return qs.get("candidate_id", [None])[0]


def constituency_id_from_href(href: str):
    qs = parse_qs(urlparse(href).query)
    return qs.get("constituency_id", [None])[0]


# ---------------------------------------------------------------------------
# Stage 1: enumerate constituencies from the main TN2026 landing page
# ---------------------------------------------------------------------------
def enumerate_constituencies():
    """
    Returns list of dicts: {district, constituency, constituency_id, url}.
    The landing page lists every constituency under each district heading.
    """
    html = fetch(BASE_URL)
    soup = BeautifulSoup(html, "lxml")

    rows = []
    # The main content area lists districts as text followed by anchor links.
    # Each candidate-list link has action=show_candidates&constituency_id=N.
    main = soup.find("body")
    seen = set()

    # Walk all anchors; figure out the most recent district label by scanning
    # the visible text up to that point.
    text_blob = main.get_text("\n", strip=True)
    # Quicker approach: iterate descendants, track the last all-caps line.
    current_district = None
    for el in main.descendants:
        if getattr(el, "name", None) is None:
            # Bare string node -- might be a district label
            txt = clean(el)
            if txt and txt.isupper() and len(txt) <= 40 and not txt.startswith("HTTP"):
                # Heuristic: TN district names are uppercase short strings.
                # Skip obvious non-districts.
                if txt not in {"DONATE NOW", "ADR", "MYNETA", "ALL CONSTITUENCIES",
                               "HIGHLIGHTS OF CANDIDATES", "TAMILNADU 2026",
                               "DOWNLOAD APP", "FOLLOW US ON"}:
                    current_district = txt
            continue
        if el.name == "a":
            href = el.get("href", "")
            if "show_candidates" in href and "constituency_id=" in href:
                cid = constituency_id_from_href(href)
                name = clean(el)
                if cid and cid not in seen and name and name != "ALL CONSTITUENCIES":
                    seen.add(cid)
                    rows.append({
                        "district": current_district or "",
                        "constituency": name,
                        "constituency_id": cid,
                        "url": urljoin(BASE_URL, href),
                    })
    log.info(f"Found {len(rows)} constituencies")
    return rows


# ---------------------------------------------------------------------------
# Stage 2: list candidates within a constituency
# ---------------------------------------------------------------------------
def parse_candidate_list(html: str, constituency: dict):
    soup = BeautifulSoup(html, "lxml")
    out = []
    # The candidate list is inside a table whose header has SNo|Candidate|Party|...
    for table in soup.find_all("table"):
        headers = [clean(th) for th in table.find_all("th")]
        if not headers:
            # Maybe headers are in first row
            first = table.find("tr")
            if first:
                headers = [clean(td) for td in first.find_all(["td", "th"])]
        if any("Candidate" in h for h in headers) and any("Party" in h for h in headers):
            for tr in table.find_all("tr")[1:]:
                tds = tr.find_all("td")
                if len(tds) < 6:
                    continue
                a = tds[1].find("a")
                if not a:
                    continue
                href = a.get("href", "")
                cand_id = candidate_id_from_href(href)
                row = {
                    "candidate_id": cand_id,
                    "candidate_name": clean(a),
                    "candidate_url": urljoin(BASE_URL, href),
                    "party": clean(tds[2]) if len(tds) > 2 else "",
                    "criminal_cases": clean(tds[3]) if len(tds) > 3 else "",
                    "education": clean(tds[4]) if len(tds) > 4 else "",
                    "age": clean(tds[5]) if len(tds) > 5 else "",
                    "total_assets": clean(tds[6]) if len(tds) > 6 else "",
                    "liabilities": clean(tds[7]) if len(tds) > 7 else "",
                    "constituency": constituency["constituency"],
                    "constituency_id": constituency["constituency_id"],
                    "district": constituency["district"],
                }
                row["total_assets_inr"] = parse_rupees(row["total_assets"])
                row["liabilities_inr"] = parse_rupees(row["liabilities"])
                row["age_int"] = int(row["age"]) if row["age"].isdigit() else None
                row["criminal_cases_int"] = int(row["criminal_cases"]) if row["criminal_cases"].isdigit() else 0
                out.append(row)
            break
    return out


# ---------------------------------------------------------------------------
# Stage 3: parse a candidate's detail page
# ---------------------------------------------------------------------------
def parse_candidate_detail(html: str, cand: dict):
    """
    Returns a dict of structured data extracted from one candidate page.
    Keys: profile, criminal_cases (list), movable (list), immovable (list),
          liabilities (list), itr (list).
    """
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=False)

    profile = {
        "candidate_id": cand["candidate_id"],
        "candidate_name": cand["candidate_name"],
        "constituency": cand["constituency"],
        "district": cand["district"],
        "party": cand["party"],
    }

    # --- Profile fields scraped from the header block ---
    def grab(label, src=text):
        # Match "Label: value" up to next double-newline or known label
        m = re.search(
            rf"{re.escape(label)}\s*[:\-]?\s*(.+?)(?:\n\s*\n|\Z|"
            rf"(?:S/o\|D/o\|W/o:|Age:|Name Enrolled|Self Profession:|Spouse Profession:|Party:))",
            src, flags=re.I | re.S,
        )
        return clean(m.group(1)) if m else ""

    profile["s_o_d_o_w_o"] = grab("S/o|D/o|W/o:")
    profile["age_detail"] = grab("Age:")
    profile["voter_enrolled"] = grab("Name Enrolled as Voter in:")
    profile["self_profession"] = grab("Self Profession:")
    profile["spouse_profession"] = grab("Spouse Profession:")

    # Education
    edu_m = re.search(r"Educational Details.*?Category:\s*(.+?)(?:Details of PAN|\n\n)",
                      text, flags=re.S | re.I)
    profile["education_full"] = clean(edu_m.group(1)) if edu_m else ""

    # Top-line totals
    a_m = re.search(r"Assets:\s*(?:\|\s*)?\*?\*?Rs\s*([\d,]+)", text)
    l_m = re.search(r"Liabilities:\s*(?:\|\s*)?\*?\*?Rs\s*([\d,]+)", text)
    profile["assets_total_inr"] = int(a_m.group(1).replace(",", "")) if a_m else None
    profile["liabilities_total_inr"] = int(l_m.group(1).replace(",", "")) if l_m else None

    # Criminal-case count
    c_m = re.search(r"Number of Criminal Cases:\s*(\d+)", text)
    profile["num_criminal_cases"] = int(c_m.group(1)) if c_m else 0

    # --- Now parse each table on the page by header signature ---
    criminal_cases = []
    movable = []
    immovable = []
    liabilities = []
    itr = []

    for table in soup.find_all("table"):
        headers = [clean(th) for th in table.find_all(["th"])]
        if not headers:
            first = table.find("tr")
            if first:
                headers = [clean(td) for td in first.find_all(["td", "th"])]
        if not headers:
            continue
        hdr_blob = " | ".join(headers).lower()

        # ITR table: "Relation Type | PAN Given | Financial Year | Total Income"
        if "relation type" in hdr_blob and "pan given" in hdr_blob:
            for tr in table.find_all("tr")[1:]:
                tds = [clean(td) for td in tr.find_all("td")]
                if len(tds) >= 4:
                    itr.append({
                        "candidate_id": cand["candidate_id"],
                        "relation_type": tds[0],
                        "pan_given": tds[1],
                        "financial_year": tds[2],
                        "income_text": tds[3],
                    })
            continue

        # Criminal cases (pending / convicted): col 0 = SNo, contains "FIR" or "Case No"
        if "fir no" in hdr_blob or "case no" in hdr_blob or "ipc/bns sections" in hdr_blob:
            ctype = "convicted" if "punishment imposed" in hdr_blob else "pending"
            for tr in table.find_all("tr")[1:]:
                tds = [clean(td) for td in tr.find_all("td")]
                if len(tds) < 3:
                    continue
                if "no cases" in " ".join(tds).lower():
                    continue
                row = {
                    "candidate_id": cand["candidate_id"],
                    "case_type": ctype,
                    "serial_no": tds[0] if len(tds) > 0 else "",
                    "fir_no": tds[1] if len(tds) > 1 and ctype == "pending" else "",
                    "case_no": (tds[2] if ctype == "pending" else tds[1]) if len(tds) > 2 else "",
                    "court": (tds[3] if ctype == "pending" else tds[2]) if len(tds) > 3 else "",
                    "law_type": (tds[4] if ctype == "pending" else tds[3]) if len(tds) > 4 else "",
                    "sections": (tds[5] if ctype == "pending" else tds[4]) if len(tds) > 5 else "",
                    "other_acts": (tds[6] if ctype == "pending" else tds[5]) if len(tds) > 6 else "",
                    "charges_framed_or_punishment": (tds[7] if ctype == "pending" else tds[6]) if len(tds) > 7 else "",
                    "date_charged_or_convicted": (tds[8] if ctype == "pending" else tds[7]) if len(tds) > 8 else "",
                    "appeal_filed": (tds[9] if ctype == "pending" else tds[8]) if len(tds) > 9 else "",
                    "appeal_status": (tds[10] if ctype == "pending" else tds[9]) if len(tds) > 10 else "",
                }
                criminal_cases.append(row)
            continue

        # Asset / liability tables share the shape: Sr No | Description | self | spouse | huf | dependent1 | dependent2 | dependent3 | total
        if ("self" in hdr_blob and "spouse" in hdr_blob and "huf" in hdr_blob
                and ("description" in hdr_blob or "sr no" in hdr_blob)):
            # Figure out section by surrounding text
            prev = table.find_previous(string=re.compile(
                r"Movable Assets|Immovable Assets|Liabilities", re.I))
            section = clean(prev) if prev else ""
            section_lc = section.lower()
            target = (movable if "movable" in section_lc and "immovable" not in section_lc
                      else immovable if "immovable" in section_lc
                      else liabilities if "liabilit" in section_lc
                      else None)
            if target is None:
                continue
            for tr in table.find_all("tr")[1:]:
                tds = [clean(td) for td in tr.find_all("td")]
                if len(tds) < 3:
                    continue
                # Skip total rows
                desc = tds[1] if len(tds) > 1 else ""
                if re.search(r"^total|^gross total|^grand total", desc, re.I):
                    continue
                row = {
                    "candidate_id": cand["candidate_id"],
                    "section": section,
                    "sr_no": tds[0] if len(tds) > 0 else "",
                    "description": desc,
                    "self": tds[2] if len(tds) > 2 else "",
                    "spouse": tds[3] if len(tds) > 3 else "",
                    "huf": tds[4] if len(tds) > 4 else "",
                    "dependent1": tds[5] if len(tds) > 5 else "",
                    "dependent2": tds[6] if len(tds) > 6 else "",
                    "dependent3": tds[7] if len(tds) > 7 else "",
                    "total": tds[8] if len(tds) > 8 else "",
                    "total_inr": parse_rupees(tds[8] if len(tds) > 8 else ""),
                }
                target.append(row)
            continue

    return {
        "profile": profile,
        "criminal_cases": criminal_cases,
        "movable": movable,
        "immovable": immovable,
        "liabilities": liabilities,
        "itr": itr,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main():
    log.info("=" * 60)
    log.info("Tamil Nadu 2026 myneta.info scraper starting")
    log.info("=" * 60)

    # Stage 1: constituencies
    constituencies = enumerate_constituencies()
    pd.DataFrame(constituencies).to_csv(OUTPUT_DIR / "constituencies.csv", index=False)

    # Stage 2: candidate lists per constituency
    all_candidates = []
    for c in tqdm(constituencies, desc="Constituencies"):
        try:
            html = fetch(c["url"])
            cands = parse_candidate_list(html, c)
            all_candidates.extend(cands)
        except Exception as e:
            log.error(f"Constituency {c['constituency']} ({c['constituency_id']}): {e}")

    log.info(f"Collected {len(all_candidates)} candidates across "
             f"{len(constituencies)} constituencies")
    pd.DataFrame(all_candidates).to_csv(OUTPUT_DIR / "candidates_list.csv", index=False)

    # Stage 3: per-candidate detail
    profiles, criminal, movable, immovable, liabilities, itr = [], [], [], [], [], []
    fail_count = 0

    for cand in tqdm(all_candidates, desc="Candidates"):
        try:
            html = fetch(cand["candidate_url"])
            data = parse_candidate_detail(html, cand)
            # Merge summary list-page columns into the profile
            data["profile"].update({
                "education_summary": cand.get("education", ""),
                "age_summary": cand.get("age", ""),
                "criminal_cases_summary": cand.get("criminal_cases", ""),
                "total_assets_summary": cand.get("total_assets", ""),
                "liabilities_summary": cand.get("liabilities", ""),
                "candidate_url": cand["candidate_url"],
            })
            profiles.append(data["profile"])
            criminal.extend(data["criminal_cases"])
            movable.extend(data["movable"])
            immovable.extend(data["immovable"])
            liabilities.extend(data["liabilities"])
            itr.extend(data["itr"])
        except Exception as e:
            fail_count += 1
            log.error(f"Candidate {cand.get('candidate_id')} "
                      f"({cand.get('candidate_name')}): {e}")

    log.info(f"Parsed {len(profiles)} candidates ({fail_count} failures)")

    # ---------- Write outputs ----------
    df_profile = pd.DataFrame(profiles)
    df_crim    = pd.DataFrame(criminal)
    df_mov     = pd.DataFrame(movable)
    df_imm     = pd.DataFrame(immovable)
    df_liab    = pd.DataFrame(liabilities)
    df_itr     = pd.DataFrame(itr)

    df_profile.to_csv(OUTPUT_DIR / "candidates_summary.csv", index=False)
    df_crim.to_csv(OUTPUT_DIR / "criminal_cases.csv", index=False)
    df_mov.to_csv(OUTPUT_DIR / "movable_assets.csv", index=False)
    df_imm.to_csv(OUTPUT_DIR / "immovable_assets.csv", index=False)
    df_liab.to_csv(OUTPUT_DIR / "liabilities.csv", index=False)
    df_itr.to_csv(OUTPUT_DIR / "itr_income.csv", index=False)

    xlsx_path = OUTPUT_DIR / "tn2026_full.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as xl:
        df_profile.to_excel(xl, sheet_name="Candidates", index=False)
        df_crim.to_excel(xl, sheet_name="Criminal Cases", index=False)
        df_mov.to_excel(xl, sheet_name="Movable Assets", index=False)
        df_imm.to_excel(xl, sheet_name="Immovable Assets", index=False)
        df_liab.to_excel(xl, sheet_name="Liabilities", index=False)
        df_itr.to_excel(xl, sheet_name="ITR Income", index=False)

    log.info(f"Wrote outputs to {OUTPUT_DIR.resolve()}")
    log.info(f"  - candidates_summary.csv  ({len(df_profile)} rows)")
    log.info(f"  - criminal_cases.csv      ({len(df_crim)} rows)")
    log.info(f"  - movable_assets.csv      ({len(df_mov)} rows)")
    log.info(f"  - immovable_assets.csv    ({len(df_imm)} rows)")
    log.info(f"  - liabilities.csv         ({len(df_liab)} rows)")
    log.info(f"  - itr_income.csv          ({len(df_itr)} rows)")
    log.info(f"  - tn2026_full.xlsx        (all sheets)")


if __name__ == "__main__":
    main()