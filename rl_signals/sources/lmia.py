"""Employers approved to hire foreign workers (positive LMIA list), quarterly XLSX/CSV from ESDC."""
from __future__ import annotations

import re
from datetime import date, timedelta

import pandas as pd

from ..common import (OPEN_CANADA_API, ckan_resources, download, find_col, is_excluded, make_signal,
                      norm_province, parse_amount, parse_date, resource_date)

PACKAGE = "90fed587-1364-4f33-a9ee-208181dc0b97"
SOURCE = "lmia"


def _load(path) -> pd.DataFrame:
    """The files carry title rows above the header. Find the row that holds 'Employer'."""
    if str(path).lower().endswith(".csv"):
        raw = pd.read_csv(path, header=None, encoding="latin-1", low_memory=False)
    else:
        raw = pd.read_excel(path, header=None)
    for i in range(min(15, len(raw))):
        cells = [str(v).lower() for v in raw.iloc[i].tolist()]
        if any(c.strip().startswith("employer") for c in cells) and any("occupation" in c for c in cells):
            df = raw.iloc[i + 1:].copy()
            df.columns = [str(v).strip() for v in raw.iloc[i].tolist()]
            return df.dropna(how="all")
    raise RuntimeError("Could not find the header row (Employer + Occupation) in the LMIA file")


def quarter_end(text: str) -> date:
    m = re.search(r"(20\d\d)\s*q([1-4])", text.lower())
    if not m:
        return date.min
    y, q = int(m.group(1)), int(m.group(2))
    return date(y, q * 3, 28)


def parse_frame(df, cfg: dict, excl: list[str], when: date) -> list[dict]:
    c_emp = find_col(df.columns, "employer")
    c_prov = find_col(df.columns, ("province",), required=False)
    c_addr = find_col(df.columns, "address", required=False)
    c_occ = find_col(df.columns, "occupation")
    c_pos = find_col(df.columns, ("approved", "position"), required=False)
    prefixes = tuple(cfg["noc_prefixes"])
    out = []
    for row in df.to_dict("records"):
        name = row.get(c_emp)
        occ = str(row.get(c_occ) or "")
        if not isinstance(name, str) or is_excluded(name, excl) or not occ.strip()[:5].startswith(prefixes):
            continue
        addr = str(row.get(c_addr) or "") if c_addr else ""
        city = addr.split(",")[0] if "," in addr else ""
        prov = norm_province(row.get(c_prov)) if c_prov else ""
        if not prov and addr:
            m = re.search(r"\b(QC|ON|BC|AB|SK|MB|NB|NS|PE|NL)\b", addr)
            prov = m.group(1) if m else ""
        positions = int(parse_amount(row.get(c_pos))) if c_pos else 0
        out.append(make_signal(
            source=SOURCE, signal_type="lmia_hiring", company=name, province=prov, city=city, when=when,
            amount=positions, points=cfg["points"],
            detail=f"Approved to hire foreign workers: {occ[:80]} ({positions or '?'} positions)",
            ref=f"{name}|{occ[:5]}",
        ))
    return out


def fetch(cfg: dict, excl: list[str], days: int) -> list[dict]:
    # quarterly list, published about 4 months after the quarter; repeats are removed by signal id
    since = date.today() - timedelta(days=max(days, 120))
    files = [r for r in ckan_resources(OPEN_CANADA_API, PACKAGE)
             if (r.get("format") or "").upper() in ("XLSX", "XLS", "CSV")
             and "positive" in (r.get("name") or "").lower() and "en" in (r.get("language") or ["en"])]
    if not files:
        raise RuntimeError("No positive LMIA list found in the catalogue")
    res = max(files, key=lambda r: quarter_end(r.get("name") or ""))
    when = parse_date(resource_date(res)) or date.today()  # when the list came out
    if when < since:
        print(f"[lmia] newest list ({res.get('name', '')[:6]}) came out {when}; nothing new")
        return []
    path = download(res["url"], "lmia_" + res["url"].split("/")[-1])
    return parse_frame(_load(path), cfg, excl, when)
