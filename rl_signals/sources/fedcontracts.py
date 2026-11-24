"""Federal contracts over $10,000 (proactive disclosure). Covers every department, all provinces.

Construction and repair or maintenance work -> contract_award (borrower side).
Vehicles, boats and equipment sold to government -> sold_equipment_to_gov (vendor side).
Posted weeks or months after signing, so the window is always at least 6 months; repeats are skipped by id.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import pandas as pd

from ..common import (OPEN_CANADA_API, ckan_resources, download, is_excluded, latest, make_signal, parse_amount,
                      parse_date)

PACKAGE = "d8f85d91-7dec-4fd1-8055-483b77225d8b"
SOURCE = "fedcontracts"
COLS = ["reference_number", "vendor_name", "vendor_postal_code", "buyer_name", "contract_date", "description_en",
        "contract_value", "commodity_type", "country_of_vendor", "owner_org_title"]
POSTAL = {"A": "NL", "B": "NS", "C": "PE", "E": "NB", "G": "QC", "H": "QC", "J": "QC", "K": "ON", "L": "ON",
          "M": "ON", "N": "ON", "P": "ON", "R": "MB", "S": "SK", "T": "AB", "V": "BC", "X": "NT", "Y": "YT"}


def province_from_postal(code) -> str:
    s = str(code or "").strip().upper()
    return POSTAL.get(s[:1], "") if s and s.lower() != "nan" else ""


def _match(text: str, words: list[str]) -> bool:
    t = text.lower()
    return any(w.lower() in t for w in words)


def parse_frame(df, cfg: dict, excl: list[str], since: date) -> list[dict]:
    out = []
    for row in df.to_dict("records"):
        if str(row.get("country_of_vendor") or "CA").strip().upper() not in ("CA", "", "NAN"):
            continue
        name = row.get("vendor_name")
        if not isinstance(name, str) or not name.strip() or is_excluded(name, excl):
            continue
        when = parse_date(row.get("contract_date"))
        if not when or when < since or when > date.today():
            continue
        amount = parse_amount(row.get("contract_value"))
        if amount < cfg["min_amount"]:
            continue
        desc = str(row.get("description_en") or "")
        if _match(desc, cfg["exclude_keywords"]):
            continue
        ctype = str(row.get("commodity_type") or "").strip().upper()
        if ctype == "C" or (ctype == "S" and _match(desc, cfg["service_keywords"])):
            kind, pts, label = "contract_award", cfg["points"], "Federal contract"
        elif ctype == "G" and _match(desc, cfg["equipment_keywords"]):
            kind, pts, label = "sold_equipment_to_gov", cfg["vendor_points"], "Sold equipment to the federal government"
        else:
            continue
        buyer = str(row.get("owner_org_title") or "").split("|")[0].strip()
        out.append(make_signal(
            source=SOURCE, signal_type=kind, company=name, province=province_from_postal(row.get("vendor_postal_code")),
            city="", when=when, amount=amount, points=pts,
            detail=f"{label}: {desc[:100]} (${amount:,.0f})" + (f" for {buyer}" if buyer else ""),
            ref=f"{row.get('reference_number')}|{name}",
        ))
    return out


def fetch(cfg: dict, excl: list[str], days: int) -> list[dict]:
    since = date.today() - timedelta(days=max(days, 180))
    res = latest(ckan_resources(OPEN_CANADA_API, PACKAGE),
                 lambda r: (r.get("url") or "").lower().endswith("/contracts.csv"))
    path = download(res["url"], "fed_contracts.csv")
    out: list[dict] = []
    for chunk in pd.read_csv(path, usecols=lambda c: c in COLS, dtype=str, chunksize=200_000,
                             encoding="utf-8", encoding_errors="replace"):
        chunk = chunk[chunk["contract_date"].fillna("") >= since.isoformat()]
        out += parse_frame(chunk, cfg, excl, since)
    return list({s["signal_id"]: s for s in out}.values())
