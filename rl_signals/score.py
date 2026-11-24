"""Turn signals into one scored row per company."""
from __future__ import annotations

from datetime import date

from .common import parse_date
from .situations import describe


# sources that describe the same kind of event; a company in both counts once when stacking
GROUP = {"fedcontracts": "canadabuys"}


def recency_mult(days_old: int, cfg: dict) -> float:
    for step in cfg["scoring"]["recency"]:
        if days_old <= step["max_days"]:
            return step["mult"]
    return 0.0


def score_companies(signals: list[dict], cfg: dict, today: date | None = None) -> list[dict]:
    today = today or date.today()
    sc = cfg["scoring"]
    prio = set(cfg["provinces_priority"])
    companies: dict[str, dict] = {}
    for s in signals:
        d = parse_date(s.get("date")) or today
        age = (today - d).days
        if age > cfg["expire_days"]:
            continue
        c = companies.setdefault(s["company_key"], {
            "company_key": s["company_key"], "company": s["company"], "city": s.get("city", ""),
            "province": s.get("province", ""), "best": {}, "signals": [], "latest": d,
        })
        if not c["city"] and s.get("city"):
            c["city"] = s["city"]
        value = float(s.get("points") or 0) * recency_mult(age, cfg)
        # one counted signal per source: the strongest
        g = GROUP.get(s["source"], s["source"])
        if value > c["best"].get(g, (0, None))[0]:
            c["best"][g] = (value, s)
        c["signals"].append(s)
        c["latest"] = max(c["latest"], d)

    rows = []
    for c in companies.values():
        if not c["best"]:
            continue
        base = sum(v for v, _ in c["best"].values())
        bonus = sc["extra_source_bonus"] * (len(c["best"]) - 1)
        bonus += sc["province_bonus"] if c["province"] in prio else 0
        score = round(base + bonus, 1)
        top = max(c["best"].values(), key=lambda t: t[0])[1]
        tier = "hot" if score >= sc["hot_threshold"] else "sequence" if score >= sc["sequence_threshold"] else "hold"
        info = describe(c["signals"], set(c["best"]))
        rows.append({**info,
            "company": c["company"], "city": c["city"], "province": c["province"], "score": score, "tier": tier,
            "sources": ", ".join(sorted(c["best"])), "signal_count": len(c["signals"]),
            "top_signal_type": top["signal_type"], "trigger_event": top["detail"],
            "latest_signal": c["latest"].isoformat(), "company_key": c["company_key"],
        })
    rows.sort(key=lambda r: (-r["score"], r["company"]))
    return rows
