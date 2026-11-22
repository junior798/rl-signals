"""Federal contract awards from the CanadaBuys open data CSV.

Two kinds of signal come out of it:
- contract_award: construction or service work the supplier has to perform (borrower side)
- sold_equipment_to_gov: equipment the supplier sold to government, which marks them as a dealer (vendor side)
"""
from __future__ import annotations

from datetime import date, timedelta

from ..common import (download, find_col, is_excluded, make_signal, norm_province, parse_amount, parse_date,
                      read_text_table, strip_accents)

SOURCE = "canadabuys"
BASE = "https://canadabuys.canada.ca/opendata/pub/"


def fiscal_year_file(today: date) -> str:
    start = today.year if today.month >= 4 else today.year - 1
    return f"{BASE}{start}-{start + 1}-awardNotice-avisAttribution.csv"


def _has(text: str, words: list[str]) -> bool:
    t = f" {strip_accents(text).lower()} "
    return any(f" {strip_accents(w).lower()}" in t for w in words)


def parse_frame(df, cfg: dict, excl: list[str], since: date) -> list[dict]:
    c_name = find_col(df.columns, ("supplierlegalname", "eng"), ("supplier", "legal", "name"), ("supplier", "name"))
    c_value = find_col(df.columns, ("totalcontractvalue",), ("contract", "value"), ("contractamount",), ("value",), required=False)
    c_date = find_col(df.columns, ("contractawarddate",), ("award", "date"), ("publicationdate",), required=False)
    c_title = find_col(df.columns, ("title", "eng"), ("title",), required=False)
    c_cat = find_col(df.columns, ("procurementcategory",), required=False)
    c_prov = find_col(df.columns, ("supplieraddressprovince", "eng"), ("supplier", "province"), required=False)
    c_city = find_col(df.columns, ("supplieraddresscity", "eng"), ("supplier", "city"), required=False)
    c_country = find_col(df.columns, ("supplieraddresscountry", "eng"), ("supplier", "country"), required=False)
    c_ref = find_col(df.columns, ("contractnumber",), ("referencenumber",), required=False)

    out = []
    for row in df.to_dict("records"):
        name = row.get(c_name)
        if not isinstance(name, str) or not name.strip() or is_excluded(name, excl):
            continue
        country = str(row.get(c_country) or "").strip().lower() if c_country else ""
        if country and country not in ("ca", "can", "canada"):
            continue
        amount = parse_amount(row.get(c_value)) if c_value else 0.0
        if amount < cfg["min_amount"]:
            continue
        when = parse_date(row.get(c_date)) if c_date else None
        if when and (when < since or when > date.today()):
            continue
        title = str(row.get(c_title) or "") if c_title else ""
        if _has(title, cfg["exclude_keywords"]):
            continue
        category = str(row.get(c_cat) or "") if c_cat else ""
        goods_only = "GD" in category and "SRV" not in category and "CNST" not in category
        if goods_only:
            if not _has(title, cfg["equipment_keywords"]):
                continue
            kind, pts, label = "sold_equipment_to_gov", cfg["vendor_points"], "Sold equipment to the federal government"
        elif "CNST" in category or _has(title, cfg["service_keywords"]):
            kind, pts, label = "contract_award", cfg["points"], "Federal contract"
        else:
            continue
        out.append(make_signal(
            source=SOURCE, signal_type=kind, company=name, province=norm_province(row.get(c_prov)) if c_prov else "",
            city=row.get(c_city) if c_city else "", when=when, amount=amount, points=pts,
            detail=f"{label}: {title[:120]} (${amount:,.0f})",
            ref=f"{row.get(c_ref) if c_ref else ''}|{name}",
        ))
    return out


def fetch(cfg: dict, excl: list[str], days: int) -> list[dict]:
    today = date.today()
    since = today - timedelta(days=days)
    urls = [fiscal_year_file(today)]
    if since < date(today.year if today.month >= 4 else today.year - 1, 4, 1):
        urls.append(fiscal_year_file(date(today.year - 1, today.month, 1)))  # window reaches last fiscal year
    signals = []
    for url in urls:
        try:
            df = read_text_table(download(url))
        except RuntimeError as e:
            print(f"[canadabuys] skipped {url}: {e}")
            continue
        signals += parse_frame(df, cfg, excl, since)
    return signals
