"""Job Bank monthly postings. A company posting 3+ equipment-heavy jobs in a month is a hiring signal."""
from __future__ import annotations

import re
from datetime import date, timedelta

from ..common import (OPEN_CANADA_API, ColumnError, ckan_resources, download, find_col, is_excluded, latest,
                      make_signal, norm_province, parse_date, read_text_table, resource_date)

PACKAGE = "ea639e28-c0fc-48bf-b5dd-b8899bd43072"
SOURCE = "jobbank"


def parse_frame(df, cfg: dict, excl: list[str], when: date) -> list[dict]:
    try:
        c_emp = find_col(df.columns, ("employer", "name"), "employer", ("business", "name"), ("company",))
    except ColumnError as e:
        print(f"[jobbank] this file has no employer column, so it cannot produce company signals. {e}")
        return []
    c_noc = find_col(df.columns, ("noc", "21"), ("noc",))
    c_prov = find_col(df.columns, ("province",), required=False)
    c_city = find_col(df.columns, ("city",), ("location",), required=False)
    c_title = find_col(df.columns, ("job", "title"), ("title",), required=False)
    c_date = find_col(df.columns, ("posting", "date"), ("date", "posted"), required=False)
    prefixes = tuple(cfg["noc_prefixes"])

    groups: dict[tuple, dict] = {}
    for row in df.to_dict("records"):
        name = row.get(c_emp)
        noc = re.sub(r"\D", "", str(row.get(c_noc) or ""))[:5]
        if not isinstance(name, str) or name.strip() in ("", "NA") or not noc.startswith(prefixes):
            continue
        if is_excluded(name, excl):
            continue
        prov = norm_province(row.get(c_prov)) if c_prov else ""
        g = groups.setdefault((name.strip(), prov), {"n": 0, "titles": set(), "city": "", "date": None})
        g["n"] += 1
        if c_title and isinstance(row.get(c_title), str):
            g["titles"].add(row[c_title].strip())
        if c_city and not g["city"]:
            g["city"] = str(row.get(c_city) or "")
        d = parse_date(row.get(c_date)) if c_date else None
        if d and (g["date"] is None or d > g["date"]):
            g["date"] = d

    out = []
    for (name, prov), g in groups.items():
        if g["n"] < cfg["min_postings"]:
            continue
        titles = ", ".join(sorted(g["titles"])[:3])
        out.append(make_signal(
            source=SOURCE, signal_type="hiring", company=name, province=prov, city=g["city"],
            when=g["date"] or when, amount=g["n"], points=cfg["points"],
            detail=f"{g['n']} equipment-related job posts on Job Bank ({titles})",
            ref=f"{name}|{when:%Y-%m}",
        ))
    return out


def fetch(cfg: dict, excl: list[str], days: int) -> list[dict]:
    since = date.today() - timedelta(days=days)
    res = latest(ckan_resources(OPEN_CANADA_API, PACKAGE),
                 lambda r: (r.get("format") or "").upper() == "CSV" and "-en-" in (r.get("url") or "").lower())
    when = (parse_date(resource_date(res)) or date.today())
    if when < since:
        return []
    path = download(res["url"], "jobbank_" + res["url"].split("/")[-1])
    return parse_frame(read_text_table(path), cfg, excl, when)
