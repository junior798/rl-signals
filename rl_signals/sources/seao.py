"""Quebec public contract awards (SEAO), weekly OCDS JSON files on Données Québec."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from ..common import (DONNEES_QUEBEC_API, ckan_resources, download, is_excluded, make_signal, norm_province,
                      parse_amount, parse_date, strip_accents)

PACKAGE = "systeme-electronique-dappel-doffres-seao"
SOURCE = "seao"


def _on_topic(title: str, codes: list[str], cfg: dict) -> bool:
    t = strip_accents(title or "").lower()
    if any(strip_accents(k).lower() in t for k in cfg.get("exclude_keywords", [])):
        return False
    if any(strip_accents(k).lower() in t for k in cfg["keywords"]):
        return True
    return any(str(c).startswith(tuple(cfg["unspsc_prefixes"])) for c in codes)


def parse_package(data, cfg: dict, excl: list[str], since: date) -> list[dict]:
    releases = data.get("releases", []) if isinstance(data, dict) else data
    out = []
    for rel in releases:
        tender = rel.get("tender") or {}
        title = tender.get("title") or rel.get("title") or ""
        codes = []
        for item in tender.get("items") or []:
            cl = item.get("classification") or {}
            if cl.get("id"):
                codes.append(str(cl["id"]))
        if not _on_topic(title, codes, cfg):
            continue
        parties = {p.get("id"): p for p in rel.get("parties") or []}
        buyer = (rel.get("buyer") or {}).get("name", "")
        for award in rel.get("awards") or []:
            when = parse_date(award.get("date") or rel.get("date"))
            if when and when < since:
                continue
            amount = parse_amount((award.get("value") or {}).get("amount"))
            if amount < cfg.get("floor_amount", 0):
                continue
            for sup in award.get("suppliers") or []:
                party = parties.get(sup.get("id"), {})
                name = sup.get("name") or party.get("name") or ""
                if not name or is_excluded(name, excl):
                    continue
                addr = party.get("address") or {}
                if (addr.get("countryName") or "CAN").upper() not in ("CAN", "CA", "CANADA"):
                    continue
                prov = norm_province(addr.get("region")) or "QC"
                pts = cfg["points_large"] if amount >= cfg["min_amount"] else cfg["points_small"]
                amt_txt = f"${amount:,.0f}" if amount else "amount not listed"
                out.append(make_signal(
                    source=SOURCE, signal_type="contract_award", company=name, province=prov,
                    city=addr.get("locality", ""), when=when, amount=amount, points=pts,
                    detail=f"Quebec public contract: {title[:120]} ({amt_txt}) for {buyer}".strip(),
                    ref=f"{rel.get('ocid')}|{award.get('id')}|{sup.get('id') or name}",
                ))
    return out


def fetch(cfg: dict, excl: list[str], days: int) -> list[dict]:
    since = date.today() - timedelta(days=days)
    resources = ckan_resources(DONNEES_QUEBEC_API, PACKAGE)
    files = []
    for r in resources:  # weekly files are named hebdo_YYYYMMDD_YYYYMMDD.json
        m = re.match(r"hebdo_(\d{8})_(\d{8})", r.get("name") or "")
        if m and m.group(2) >= since.strftime("%Y%m%d"):
            files.append((m.group(1), r))
    signals: list[dict] = []
    for _, res in sorted(files, key=lambda t: t[0]):
        path = download(res["url"], f"seao_{res['id']}.json")
        with open(path, encoding="utf-8") as f:
            signals += parse_package(json.load(f), cfg, excl, since)
    return signals
