"""Federal grants and contributions (proactive disclosure). One large CSV, read in chunks."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..common import (OPEN_CANADA_API, ckan_resources, download, find_col, is_excluded, latest, make_signal,
                      norm_province, parse_amount, parse_date)

PACKAGE = "432527ab-7aac-45b5-81d6-7597107a7013"
SOURCE = "grants"
NEEDED = {"ref_number", "recipient_type", "recipient_legal_name", "recipient_operating_name", "recipient_province",
          "recipient_city", "prog_name_en", "owner_org_title", "agreement_value", "agreement_start_date"}


def program_points(text: str, cfg: dict) -> int:
    t = (text or "").lower()
    for p in cfg["programs"]:
        if p["match"].lower() in t:
            return p["points"]
    return 0


def parse_frame(df, cfg: dict, excl: list[str], since: date) -> list[dict]:
    cols = df.columns
    c_legal = find_col(cols, "recipient_legal_name", ("recipient", "legal"))
    c_oper = find_col(cols, "recipient_operating_name", ("recipient", "operating"), required=False)
    c_type = find_col(cols, "recipient_type", required=False)
    c_prov = find_col(cols, "recipient_province", ("recipient", "province"), required=False)
    c_city = find_col(cols, "recipient_city", ("recipient", "city"), required=False)
    c_prog = find_col(cols, "prog_name_en", ("prog", "name"), ("program", "name"))
    c_org = find_col(cols, "owner_org_title", required=False)
    c_value = find_col(cols, "agreement_value", ("agreement", "value"))
    c_start = find_col(cols, "agreement_start_date", ("start", "date"))
    c_ref = find_col(cols, "ref_number", required=False)

    out = []
    for row in df.to_dict("records"):
        if c_type and str(row.get(c_type) or "").strip().upper() not in ("F", ""):
            continue  # F = for-profit; skips universities, non-profits, governments, individuals
        when = parse_date(row.get(c_start))
        if not when or when < since:
            continue
        prog = str(row.get(c_prog) or "")
        pts = program_points(f"{prog} {row.get(c_org) or ''}", cfg)
        if pts <= 0:
            continue
        amount = parse_amount(row.get(c_value))
        if amount < cfg["min_amount"]:
            continue
        name = row.get(c_oper) if c_oper and isinstance(row.get(c_oper), str) and row.get(c_oper).strip() else row.get(c_legal)
        if not isinstance(name, str) or is_excluded(name, excl):
            continue
        out.append(make_signal(
            source=SOURCE, signal_type="grant", company=name, province=norm_province(row.get(c_prov)),
            city=row.get(c_city) if c_city else "", when=when, amount=amount, points=pts,
            detail=f"Federal funding: {prog[:90]} (${amount:,.0f})",
            ref=f"{row.get(c_ref) if c_ref else ''}|{name}",
        ))
    return out


def fetch(cfg: dict, excl: list[str], days: int) -> list[dict]:
    # departments disclose grants weeks or months after the start date, so always look back 6 months;
    # grants already in the sheet are skipped by signal id
    since = date.today() - timedelta(days=max(days, 180))
    res = latest(ckan_resources(OPEN_CANADA_API, PACKAGE),
                 lambda r: (r.get("format") or "").upper() == "CSV" and (r.get("url") or "").lower().endswith("/grants.csv"))
    path = download(res["url"], "grants.csv")
    out = []
    header = pd.read_csv(path, nrows=0).columns
    keep = [c for c in header if c in NEEDED]
    for chunk in pd.read_csv(path, usecols=keep or None, chunksize=200_000, low_memory=False, dtype=str,
                             encoding="utf-8", encoding_errors="replace"):
        out += parse_frame(chunk, cfg, excl, since)
    # amendments repeat the same agreement; keep one signal per id
    return list({s["signal_id"]: s for s in out}.values())
