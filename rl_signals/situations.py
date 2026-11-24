"""Turn a company's signals into: which situation it is in, a first line for outreach,
the equipment it likely needs, and a rough financing range.

The ranges are rough Quebec market estimates used to sort leads, never quoted to a prospect.
"""
from __future__ import annotations

import re

from .common import strip_accents

SNOW = r"deneige|snow|deglac|abrasif|epandage|tassement de la neige"
CIVIL = (r"excavat|pavage|asphalt|paving|terrass|nivel|route|chaussee|ponceau|pont |aqueduc|egout|granul|grading|"
         r"road|culvert|bridge|ditch|voirie")
TRANSPORT = r"transport|camionn|hauling|autobus|collecte|dechet|ordures|towing|remorqu|conteneur"
GROWTH = r"tariff|rtri|scale|regi|economic growth|strategic innovation"

SITUATIONS = {
    "1 Snow contract": ("Loaders, plow trucks, sidewalk machines, snow blowers", "Are you adding equipment for this winter?"),
    "2 Civil / road work": ("Excavators, loaders, dump trucks", "Are you buying or renting for this one?"),
    "3 Transport / hauling": ("Trucks, trailers, buses, roll-off containers", "Do you need another unit for this contract?"),
    "4 Building / maintenance": ("Vans, lifts, tools, small equipment", "Is there anything you need to buy for this job?"),
    "5 Growth funding": ("Production equipment for the funded project", "Are you buying equipment as part of the project?"),
    "6 R&D / export funding": ("Lab or production equipment, working capital", "Is equipment or cash flow the bigger need right now?"),
    "7 Hiring": ("Machines and trucks for the new hires", "Are you adding equipment along with the new hires?"),
    "8 Dealer": ("Vendor partner: financing for their buyers", "Do you want a second option for the deals your lender turns down?"),
    "9 Two or more lists": ("Depends on the signals; call first", "Are you the right person to talk to about the equipment side?"),
}

SHORT_BUYERS = [
    (r"minist.re des transports", "Transports Québec"),
    (r"soci.t. de l'assurance automobile", "the SAAQ"),
    (r"centre de services scolaire", "the school service centre"),
    (r"sant. qu.bec", "Santé Québec"),
    (r"soci.t. qu.b.coise des infrastructures|^sqi", "the SQI"),
    (r"hydro-qu.bec", "Hydro-Québec"),
]


def _low(x) -> str:
    return strip_accents(str(x or "")).lower()


def situation_of(signal: dict) -> str:
    t, d = signal.get("signal_type", ""), _low(signal.get("detail"))
    if t == "sold_equipment_to_gov":
        return "8 Dealer"
    if t == "contract_award":
        if re.search(SNOW, d):
            return "1 Snow contract"
        if re.search(CIVIL, d):
            return "2 Civil / road work"
        if re.search(TRANSPORT, d):
            return "3 Transport / hauling"
        return "4 Building / maintenance"
    if t == "grant":
        return "5 Growth funding" if re.search(GROWTH, d) else "6 R&D / export funding"
    return "7 Hiring"


def buyer_of(detail: str) -> str:
    m = re.search(r" for (.+?)\.?$", str(detail or ""))
    b = m.group(1).strip() if m else ""
    for pat, rep in SHORT_BUYERS:
        if re.search(pat, b, re.I):
            return rep
    b = re.sub(r"^(Ville de|Municipalité de|Municipalite de|City of)\s+", "the City of ", b)
    return b if len(b) <= 45 else ""


def role_of(detail: str) -> str:
    m = re.search(r"\d{5}-([^(]+)", str(detail or ""))
    r = m.group(1).strip().lower() if m else ""
    r = re.split(r",| and | \(", r)[0].strip()
    r = re.sub(r"^transport truck drivers?$", "truck driver", r)
    return r[:-1] if r.endswith("s") else r


def first_line(sit: str, detail: str) -> str:
    b = buyer_of(detail)
    w = f" with {b}" if b else ""
    return {
        "1": f"Saw you picked up snow removal work{w} this season.",
        "2": f"Saw you won road and site work{w}.",
        "3": f"Saw you won a transport contract{w}.",
        "4": f"Saw you were awarded new work{w}.",
        "5": "Saw your federal growth funding came through this year.",
        "6": "Saw you're growing with federal support this year.",
        "7": f"Saw you got approval to bring on more {role_of(detail) or 'skilled staff'}s.",
        "8": "Saw you're supplying equipment to the federal government.",
        "9": f"Saw you won new work{w} and you're adding people at the same time.",
    }[sit[0]]


def multi_line(sources: set[str], signals: list[dict]) -> str:
    contract = max((s for s in signals if s.get("signal_type") == "contract_award"),
                   key=lambda s: float(s.get("amount") or 0), default=None)
    b = buyer_of(contract.get("detail", "")) if contract else ""
    w = f" with {b}" if b else ""
    if contract and "lmia" in sources:
        return f"Saw you won new work{w} and you're adding people at the same time."
    if contract and "grants" in sources:
        return f"Saw you won new work{w} and your federal funding came through this year."
    if contract:
        return f"Saw you picked up several new contracts this year, including work{w}."
    return "Saw your federal funding came through and you're adding people at the same time."


def likely_need(sit: str, contract_total: float) -> str:
    """Rough financing range from the situation and the total value of contracts won."""
    if sit.startswith(("5", "6")):
        return "$100K-$500K"
    if sit.startswith("7"):
        return "$100K-$300K"
    if sit.startswith("8"):
        return "Vendor partner"
    v = contract_total or 0
    if v >= 5_000_000:
        return "$500K-$1.5M"
    if v >= 1_000_000:
        return "$250K-$750K"
    if v >= 250_000:
        return "$100K-$300K"
    return "$50K-$150K"


def describe(signals: list[dict], sources: set[str]) -> dict:
    """Pick the situation for a company from all its signals."""
    best = max(signals, key=lambda s: float(s.get("points") or 0))
    sit = "9 Two or more lists" if len(sources) > 1 else situation_of(best)
    contract_total = sum(float(s.get("amount") or 0) for s in signals if s.get("signal_type") == "contract_award")
    base_sit = situation_of(best)
    return {
        "situation": sit,
        "first_line": multi_line(sources, signals) if sit[0] == "9" else first_line(sit, best.get("detail", "")),
        "likely_equipment": SITUATIONS[base_sit if sit[0] == "9" else sit][0],
        "likely_need": likely_need(base_sit, contract_total),
        "ask": SITUATIONS[sit][1],
    }
