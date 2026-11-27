"""Weekly loaders for the sources that were first loaded by hand on Nov 25, 2026.

Each loader copies the rules used in that first load (the signals chat's build_ledger.py), so new rows get
the same signal names, campaigns, details and dedupe keys as the old ones. Every row already carries its
final trigger_type, so Supabase stores it as is (ingest_signals, "direct" rows).

One broken source never stops the others: each runs in its own try block and reports to runs.csv.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import html
import io
import json
import re
import time
import traceback
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
      "Accept": "*/*", "Accept-Language": "en-CA,en;q=0.9"}

SIGN = {
    1: ("Contractor on a Calgary commercial, industrial or institutional permit", "Expansion"),
    15: ("Nova Scotia public tender winner (province, universities, health)", "Funding event"),
    16: ("City of Toronto awarded contract", "Funding event"),
    43: ("Small or mid producer spudding wells", "Expansion"),
    59: ("Commercial aircraft 25+ years old", "Asset turnover"),
    67: ("Hiring CFO / controller / finance manager", "New finance leader"),
    77: ("Farm supervisor / greenhouse manager hiring", "Expansion"),
    80: ("Auto / diesel technician hiring", "Expansion"),
    82: ("Aircraft transferred to a company", "Asset turnover"),
    83: ("Air operator adding aircraft", "Expansion"),
    88: ("Helicopter or charter operator hiring pilots/AMEs", "Expansion"),
    89: ("Commercial fit-out permit (Calgary)", "Expansion"),
    90: ("Commercial permit with applicant/contractor (Vancouver)", "Funding event"),
    91: ("Warehouse racking permit", "Expansion"),
    93: ("Commercial permits other cities", "Expansion"),
    99: ("Child care operator adding a centre", "Expansion"),
    101: ("New pit or quarry licence or expansion", "Expansion"),
    107: ("Permit to take water for construction dewatering", "Compliance-driven spend"),
    118: ("Small producer licensing new wells (service work coming)", "Expansion"),
    121: ("Ontario mining work permit", "Expansion"),
    124: ("Logging / heavy equipment operator hiring", "Expansion"),
    134: ("Hiring CNC machinists / programmers", "Expansion"),
    135: ("Hiring welders / fabricators", "Expansion"),
    136: ("Hiring millwrights / maintenance", "Expansion"),
    137: ("Hiring machine operators (moulding, extrusion, printing)", "Expansion"),
    138: ("Hiring heavy equipment / crane operators", "Expansion"),
    139: ("Hiring estimators / site supers", "Expansion"),
    140: ("Hiring forklift / warehouse leads", "Expansion"),
    141: ("Hiring industrial electricians / HVAC techs", "Expansion"),
    170: ("Medical clinic fit-out permit", "Expansion"),
    175: ("Dental hiring for a new clinic", "Expansion"),
    181: ("Imaging tech hiring at a private clinic", "Expansion"),
    199: ("Calgary, Edmonton, Vancouver contract won", "Funding event"),
    209: ("Restaurant fit-out permit", "Expansion"),
    212: ("New food premises (Toronto DineSafe)", "Expansion"),
    218: ("Kitchen manager hiring for a new location", "Expansion"),
    220: ("Commercial bakery or catering hiring", "Expansion"),
    224: ("Hiring AZ drivers (capped)", "Expansion"),
    301: ("Ontario air approval (new or changed process equipment)", "Expansion"),
    302: ("Ontario sewage works approval (site servicing, developers, plants)", "Compliance-driven spend"),
    304: ("Edmonton: business licensed 2y+ opens another location", "Expansion"),
    305: ("Vancouver: existing licensed business at a new address", "Expansion"),
    307: ("Ontario waste hauler registers its trucks (EASR waste transportation)", "Compliance-driven spend"),
    308: ("Ontario construction dewatering registration (EASR)", "Compliance-driven spend"),
    309: ("Ontario auto body shop registers a paint booth (EASR refinishing)", "Asset turnover"),
    310: ("Ontario industrial sewage approval (plant process water)", "Compliance-driven spend"),
    311: ("Ontario waste site or processing approval", "Compliance-driven spend"),
    312: ("Ontario end-of-life vehicle site registration", "Asset turnover"),
    313: ("Building permit to install equipment (booth, racking, crane, kitchen, lab, cold storage)", "Expansion"),
    2: ("Builder on Calgary apartment or townhouse permits", "Expansion"),
    3: ("Contractor named on Toronto building permits", "Expansion"),
    92: ("Industrial new building or addition permit", "Expansion"),
    196: ("Big contract won 3-5 years ago (equipment now paid down)", "Asset turnover"),
    129: ("Alberta grant payment", "Funding event"),
    210: ("Existing restaurant adding area (AGCO)", "Expansion"),
    211: ("New licensed spot by an existing operator (AGCO)", "Expansion"),
    213: ("New BC brewery, winery, distillery or restaurant licence", "Expansion"),
    169: ("Licensed surgical / diagnostic imaging centre", "Expansion"),
    171: ("Imaging centre new licence or added service", "Expansion"),
    173: ("New or relocated surgical / cosmetic clinic (Ontario)", "Expansion"),
    61: ("First-time Alberta Certificate of Recognition (diff of daily file)", "Expansion"),
}

STATE = __import__("pathlib").Path("data/state")


def load_state(name: str) -> pd.DataFrame | None:
    f = STATE / f"{name}.csv"
    return pd.read_csv(f, dtype=str).fillna("") if f.exists() else None


def save_state(name: str, df: pd.DataFrame):
    STATE.mkdir(parents=True, exist_ok=True)
    df.to_csv(STATE / f"{name}.csv", index=False)

PUBLIC = re.compile(r"\b(city of|town of|township|municipality|county of|region(al)? (municipality|district)|district of|village of|university|college|hospital|health (authority|network|services)|school board|board of education|government|ministry|minister|her majesty|his majesty|corporation of the|first nation|band council|conservation authority|public works|crown)\b", re.I)
SUFFIX = re.compile(r"\b(incorporated|inc|ltd|limited|ltee|corp|corporation|co|company|ulc|llp|lp|llc|plc)\b\.?", re.I)
EQUIP = ["spray booth", "paint booth", "racking", "crane", "dust collector", "commercial kitchen", "walk-in cooler",
         "walk-in freezer", "cold storage", "mezzanine", "hood", "generator", "boiler", "chiller", "tank", "mri", "lab"]


def key(name: str) -> str:
    n = html.unescape(str(name)).lower()
    n = re.sub(r"\(.*?\)", " ", n)
    n = SUFFIX.sub(" ", n)
    n = re.sub(r"^the\s+", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


def get(url: str, timeout: int = 180, tries: int = 4, **kw) -> requests.Response:
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=timeout, **kw)
            r.raise_for_status()
            return r
        except Exception as e:  # network hiccups
            last = e
            time.sleep(5 + 15 * i)
    raise RuntimeError(f"download failed: {url}: {last}")


class Out:
    """Collects rows the same way the first load's add() did."""

    def __init__(self):
        self.rows: list[dict] = []

    def add(self, company, sig, source, date, value=None, city=None, prov=None, detail=None, ttype=None, campaign=None):
        if company is None or str(company).strip() in ("", "nan", "None", "NaN"):
            return
        company = html.unescape(str(company)).strip()
        if PUBLIC.search(company) or "REDACTED" in company.upper():
            return
        if prov and str(prov).strip().upper() in ("QC", "QUEBEC", "QUÉBEC"):
            return
        k = key(company)
        if len(k) < 3:
            return
        name, camp = SIGN.get(sig, ("", "Unmapped"))
        c = campaign or camp
        t = (ttype or f"s{sig}: {name}")[:200]
        d = None
        try:
            if date is not None and str(date) not in ("", "nan", "NaT", "None"):
                d = str(pd.to_datetime(date).date())
        except Exception:
            d = None
        try:
            v = float(str(value).replace(",", "")) if value not in (None, "") and str(value) not in ("nan", "None") else None
        except Exception:
            v = None
        det = None if detail is None or str(detail) in ("nan", "None") else str(detail)[:300]
        self.rows.append(dict(
            company=company, key=k, signal_no=sig, trigger_type=t, campaign=c, source_name=source, date=d or "",
            amount="" if v is None else v,
            city="" if city is None or str(city) == "nan" else str(city)[:80],
            province="" if prov is None or str(prov) == "nan" else str(prov)[:40],
            detail=det or "",
            dedupe_key=hashlib.sha1(f"{source}|{k}|{t}|{d}|{det}".encode()).hexdigest(),
        ))


def since(days: int) -> dt.date:
    return dt.date.today() - dt.timedelta(days=days)


# ---------------------------------------------------------------- Calgary permits (s1, s89, s91, s170, s209, s313)
def calgary(o: Out, days: int):
    s = since(days).isoformat()
    r = get(f"https://data.calgary.ca/resource/c2es-76ed.csv?$limit=50000&$where=issueddate>='{s}'")
    cal = pd.read_csv(io.StringIO(r.text), dtype=str)
    for _, x in cal.iterrows():
        pc = str(x.get("permitclassgroup")); desc = str(x.get("description"))
        d = x.get("issueddate"); cost = x.get("estprojectcost")
        if "Residential" in pc or "Residential" in str(x.get("permitclassmapped")):
            if re.search(r"multi|apartment|townhouse|row house|rowhouse", f"{x.get('permitclassmapped')} {x.get('permitclass')} {desc}", re.I) \
                    and re.search(r"new", str(x.get("workclassgroup")), re.I):
                o.add(x.get("contractorname"), 2, "Calgary building permits", d, cost, "Calgary", "AB", desc[:200])
            continue
        if re.search(r"industr|warehouse|manufactur", f"{pc} {x.get('permitclassmapped')} {x.get('permitclass')}", re.I) \
                and re.search(r"new|addition", str(x.get("workclassgroup")), re.I):
            o.add(x.get("applicantname"), 92, "Calgary building permits", d, cost, "Calgary", "AB", desc[:200])
        o.add(x.get("contractorname"), 1, "Calgary building permits", d, cost, "Calgary", "AB", desc[:200])
        if re.search(r"restaurant|food|kitchen|cafe|bar ", desc, re.I):
            o.add(x.get("applicantname"), 209, "Calgary building permits", d, cost, "Calgary", "AB", desc[:200])
        elif re.search(r"clinic|dental|medical|physio|veterinar", desc, re.I):
            o.add(x.get("applicantname"), 170, "Calgary building permits", d, cost, "Calgary", "AB", desc[:200])
        elif re.search(r"rack", desc, re.I):
            o.add(x.get("applicantname"), 91, "Calgary building permits", d, cost, "Calgary", "AB", desc[:200])
        elif re.search(r"tenant|improvement|fit|interior", desc, re.I):
            o.add(x.get("applicantname"), 89, "Calgary building permits", d, cost, "Calgary", "AB", desc[:200])
        hits = [w for w in EQUIP if re.search(rf"\b{re.escape(w)}\b", desc, re.I)]
        if hits:
            o.add(x.get("applicantname"), 313, "Calgary building permits", d, cost, "Calgary", "AB", f"{', '.join(hits)}: {desc[:200]}")


# ---------------------------------------------------------------- Vancouver permits (s90, s93, s313)
def _van_all(dataset: str, where: str, select: str = "") -> pd.DataFrame:
    u = f"https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets/{dataset}/exports/csv?delimiter=%2C&where={requests.utils.quote(where)}"
    if select:
        u += f"&select={requests.utils.quote(select)}"
    r = get(u, timeout=300)
    return pd.read_csv(io.StringIO(r.content.decode("utf-8-sig")), dtype=str)


def vancouver_permits(o: Out, days: int):
    v = _van_all("issued-building-permits", f"issuedate >= date'{since(days).isoformat()}'")
    v["d"] = v.issuedate
    com = v[v.permitcategory.fillna("").str.contains("Commercial|Industrial|Mixed", case=False)]
    for _, x in com.iterrows():
        a = re.sub(r"^.*DBA:\s*", "", str(x.get("applicant") or ""))
        desc = str(x.get("projectdescription") or "")
        o.add(a, 90, "Vancouver building permits", x.d, x.get("projectvalue"), "Vancouver", "BC", f"{x.get('permitcategory')}: {desc[:200]}")
        hits = [w for w in EQUIP if re.search(rf"\b{re.escape(w)}\b", desc, re.I)]
        if hits:
            o.add(x.get("applicant"), 313, "Vancouver building permits", x.d, x.get("projectvalue"), "Vancouver", "BC", f"{', '.join(hits)}: {desc[:200]}")
    ind = v[v.permitcategory.fillna("").str.contains("Industrial", case=False)
            & v.typeofwork.fillna("").str.contains("New Building|Addition", case=False)]
    for _, x in ind.iterrows():
        o.add(re.sub(r"^.*DBA:\s*", "", str(x.get("applicant") or "")), 92, "Vancouver building permits", x.d, x.get("projectvalue"),
              "Vancouver", "BC", f"{x.get('typeofwork')}: {str(x.get('projectdescription') or '')[:200]}")
    bc = v[v.buildingcontractor.notna()]
    for _, x in bc.iterrows():
        o.add(x.buildingcontractor, 93, "Vancouver building permits", x.d, x.get("projectvalue"), "Vancouver", "BC", None)


# ---------------------------------------------------------------- Vancouver business licences (s305)
def vancouver_licences(o: Out, days: int):
    y = dt.date.today().year % 100
    v = _van_all("business-licences", f"issueddate >= date'{dt.date.today().year - 2}-01-01'",
                 "folderyear,businessname,businesstradename,businesstype,status,issueddate,house,street")
    v = v[~v.businessname.fillna("(").str.startswith("(")]
    v = v[~v.businesstype.fillna("").str.contains("Legal|Real Estate|Consulting|Health Care Professionals|Rental|Association")]
    k = lambda s: re.sub(r"(inc|ltd|limited|corp|corporation|co)$", "", re.sub(r"[^a-z0-9]", "", str(s).lower()))
    v["k"] = v.businessname.map(k); v["d"] = v.issueddate.str[:10]
    v["loc"] = v.k + "|" + v.house.fillna("") + v.street.fillna("")
    cur = v[(v.d >= since(days).isoformat()) & (v.status == "Issued")]
    prev = v[v.folderyear.astype(str).isin([f"{y - 2:02d}", f"{y - 1:02d}"])]
    nl = cur[cur.k.isin(set(prev.k)) & cur.street.notna() & ~cur["loc"].isin(set(prev["loc"]))]
    for _, x in nl.iterrows():
        o.add(x.businessname, 305, "Vancouver business licences", x.d, None, "Vancouver", "BC", x.businesstype)


# ---------------------------------------------------------------- Vancouver awarded contracts (s199)
def vancouver_awards(o: Out, days: int):
    v = _van_all("awarded-contracts", f"award_date >= date'{since(days).isoformat()}' and awarded = 'Yes'")
    for _, x in v.iterrows():
        o.add(x.vendor_name, 199, "Vancouver bid awards", x.award_date, x.get("bid_amount"), "Vancouver", "BC", x.bid_description)


# ---------------------------------------------------------------- Edmonton business licences (s304)
def edmonton_licences(o: Out, days: int):
    r = get("https://data.edmonton.ca/resource/qhi4-bdpu.csv?$limit=200000&$select=business_name,business_licence_category,business_address,originalissuedate,most_recent_issue_date", timeout=300)
    e = pd.read_csv(io.StringIO(r.text), dtype=str)
    e["k"] = e.business_name.map(key)
    e["orig"] = pd.to_datetime(e.originalissuedate, errors="coerce")
    two = pd.Timestamp(dt.date.today() - dt.timedelta(days=730))
    old = set(e[e.orig < two].k)
    new = e[(e.orig >= pd.Timestamp(since(days))) & e.k.isin(old) & ~e.business_address.fillna("").str.contains("Home Based")]
    for _, x in new.iterrows():
        o.add(x.business_name, 304, "Edmonton business licences", x.orig, None, "Edmonton", "AB", x.business_licence_category)


# ---------------------------------------------------------------- Nova Scotia awarded tenders (s15)
def nova_scotia(o: Out, days: int):
    r = get(f"https://data.novascotia.ca/resource/m6ps-8j6u.csv?$limit=50000&$where=awarded_date>='{since(days).isoformat()}'")
    ns = pd.read_csv(io.StringIO(r.text), dtype=str)
    for _, x in ns.iterrows():
        o.add(x.vendor, 15, "Nova Scotia awarded public tenders", x.awarded_date, x.get("awarded_amount"), None, "NS",
              f"{x.entity}: {str(x.tender_description)[:180]}")


# ---------------------------------------------------------------- Toronto awarded contracts (s16)
def toronto_awards(o: Out, days: int):
    r = get("https://ckan0.cf.opendata.inter.prod-toronto.ca/datastore/dump/e211f003-5909-4bea-bd96-d75899d8e612", timeout=300)
    t = pd.read_csv(io.StringIO(r.text), dtype=str)
    cut = since(days).isoformat()
    for _, x in t.iterrows():
        try:
            awards = json.loads(json.loads(x["Award"])) if str(x["Award"]).startswith('"') else json.loads(x["Award"])
        except Exception:
            continue
        for a in awards or []:
            d = a.get("Date_Awarded") or a.get("AwardedDate") or ""
            if str(d)[:10] < cut:
                continue
            o.add(a.get("Successful_Bidder"), 16, "Toronto awarded contracts", d, a.get("Award_Amount"), "Toronto", "ON",
                  f"{x['High Level Category']}: {str(x['Solicitation Document Description'])[:150]}")


# ---------------------------------------------------------------- Toronto DineSafe (s212)
def dinesafe(o: Out, days: int):
    r = get("https://ckan0.cf.opendata.inter.prod-toronto.ca/datastore/dump/75dbb3ff-8281-4f03-9de2-bd1214761302", timeout=300)
    d = pd.read_csv(io.StringIO(r.text), dtype=str, usecols=["estId", "estName", "address", "inspectionDate"])
    f = d.groupby("estId").agg(Company=("estName", "first"), Address=("address", "first"), first=("inspectionDate", "min")).reset_index(drop=True)
    for _, x in f[f["first"] >= since(days).isoformat()].iterrows():
        o.add(x.Company, 212, "Toronto DineSafe", x["first"], None, "Toronto", "ON", x.Address)


# ---------------------------------------------------------------- Ontario child care (s99)
def child_care(o: Out, days: int):
    meta = get("https://data.ontario.ca/api/3/action/package_show?id=licensed-child-care-facilities-in-ontario").json()
    res = [x for x in meta["result"]["resources"] if str(x.get("url", "")).endswith(".xlsx") and "open_data" in x.get("url", "")]
    res.sort(key=lambda x: x.get("last_modified") or x.get("created") or "")
    b = pd.read_excel(io.BytesIO(get(res[-1]["url"]).content))
    b["iss"] = pd.to_datetime(b["Original Issue Date"], errors="coerce")
    cut = pd.Timestamp(since(max(days, 75)))  # the file only updates once a month
    x = b[b.iss >= cut]
    prior = set(b[b.iss < cut]["Licensee Name"])
    for _, r in x[x["Licensee Name"].isin(prior)].iterrows():
        o.add(r["Licensee Name"], 99, "Ontario child care file", r.iss, None, r.City, "ON", r["Child Care Site Name"])


# ---------------------------------------------------------------- Ontario Access Environment (s301, s302, s107, s307-s312)
def access_environment(o: Out, days: int):
    M = "https://ws.lioservices.lrc.gov.on.ca/arcgis2/rest/services/Access_Environment/Access_Environment_Map/MapServer"

    def ae_sig(layer, t):
        t = str(t)
        if layer == 1:
            if "AIR" in t: return 301
            if "INDUSTRIAL" in t: return 310
            if "WASTE" in t: return 311
            if "SEWAGE" in t: return 302
        if layer == 3:
            if "Air Emissions" in t: return 301
            if "Waste Transportation" in t: return 307
            if "Dewatering" in t or "Pumping" in t: return 308
            if "Refinishing" in t: return 309
            if "End-of-Life" in t: return 312
            if "Storm" in t: return 302
        if layer == 5: return 107
        return None

    for lyr in (1, 3, 5):
        off = 0
        while True:
            q = {"where": f"APPROVAL_DATE >= DATE '{since(days).isoformat()}'",
                 "outFields": "APPROVAL_NUMBER,BUSINESS_NAME,MUNICIPALITY,APPROVAL_DATE,APPROVAL_TYPE",
                 "returnGeometry": "false", "f": "json", "resultOffset": off, "resultRecordCount": 2000, "orderByFields": "OBJECTID"}
            d = get(f"{M}/{lyr}/query?" + requests.compat.urlencode(q)).json()
            feats = d.get("features", [])
            for f in feats:
                a = f["attributes"]
                s = ae_sig(lyr, a.get("APPROVAL_TYPE"))
                if s and a.get("APPROVAL_DATE"):
                    when = dt.datetime.utcfromtimestamp(a["APPROVAL_DATE"] / 1000)
                    o.add(a.get("BUSINESS_NAME"), s, "Ontario Access Environment", when, None, a.get("MUNICIPALITY"), "ON",
                          f"{a.get('APPROVAL_TYPE')} {a.get('APPROVAL_NUMBER')}")
            if len(feats) < 2000 and not d.get("exceededTransferLimit"):
                break
            off += len(feats)


# ---------------------------------------------------------------- Ontario Environmental Registry (s301, s302, s310, s311, s107, s121, s101)
def ero(o: Out, days: int):
    def ero_sig(t):
        t = str(t).lower()
        if "air" in t: return 301
        if "industrial" in t and "sewage" in t: return 310
        if "sewage" in t: return 302
        if "waste" in t: return 311
        if "take water" in t: return 107
        if "mineral" in t or "minerals" in t: return 121
        if "pit" in t or "quarry" in t or "aggregate" in t: return 101
        return None

    cut = since(days)
    for p in range(0, 60):
        h = get(f"https://ero.ontario.ca/search?f%5B0%5D=type%3Ainstrument&page={p}", timeout=90).text
        blocks = h.split("views-row")[1:]
        if not blocks:
            break
        oldest = None
        for blk in blocks:
            t = re.sub(r"\s+", " ", re.sub("<[^>]+>", " | ", blk))
            name = re.search(r"^[\s|\">]*([^|]+?)\s*\|\s*-\s", t)
            itype = re.search(r"Instrument type:\s*([^|]+)", t)
            num = re.search(r"ERO \| number \| \| ([\d-]+)", t)
            stage = re.search(r"Notice stage \| \| \| ([^|]+)", t)
            dm = re.search(r"(?:Proposal posted|Decision posted|Bulletin posted) \| \| \| ([A-Z][a-z]+ \d{1,2}, \d{4})", t)
            if not (name and itype and dm):
                continue
            when = dt.datetime.strptime(dm.group(1), "%B %d, %Y").date()
            oldest = when if oldest is None or when < oldest else oldest
            if when < cut:
                continue
            s = ero_sig(itype.group(1))
            if s:
                o.add(name.group(1).strip(), s, "Ontario Environmental Registry", when, None, None, "ON",
                      f"{itype.group(1).strip()} ({stage.group(1).strip() if stage else ''}) ERO {num.group(1) if num else ''}")
        if oldest and oldest < cut:
            break


# ---------------------------------------------------------------- AER well licences (s118)
def aer_licences(o: Out, days: int):
    cnt, last = {}, {}
    for i in range(0, 30):
        day = dt.date.today() - dt.timedelta(days=i)
        try:
            t = get(f"https://static.aer.ca/prd/data/well-lic/WELLS{day.strftime('%m%d')}.TXT", tries=1, timeout=60).text
        except Exception:
            continue
        m = re.search(r"DATE:\s+(\d{1,2} \w+ \d{4})", t)
        fdate = dt.datetime.strptime(m.group(1), "%d %B %Y").date() if m else day
        if fdate < day - dt.timedelta(days=300):  # last year's file with the same name
            continue
        blocks = re.split(r"\n\s*\n", t.split("-----\n", 2)[-1])
        for b in blocks:
            lines = [l for l in b.splitlines() if l.strip()]
            if len(lines) >= 5 and re.search(r"\d{7}", lines[0]):
                lic = lines[4][:68].strip()
                if lic:
                    cnt[lic] = cnt.get(lic, 0) + 1
                    last[lic] = max(last.get(lic, fdate), fdate)
    for lic, n in cnt.items():
        o.add(lic, 118, "AER daily well licences", last[lic], None, None, "AB", f"{n} licences in 30 days")


# ---------------------------------------------------------------- AER ST49 spud list (s43)
def aer_spud(o: Out, days: int):
    pat = re.compile(r"\s(\d{7})\s+(\S{4})\s+(.+?)\s{2,}(\S+)\s+(\d\d \w{3} \d{4}) [\d:]+ (?:AM|PM)\s+(.+?)\s{2,}(\S{4})\s+(.+?)(?:\s{2,}|$)")
    texts = []
    page = get("https://www.aer.ca/node/797").text
    zips = sorted(set(re.findall(r'href="(/prd/data/wells/spud20\d\d-\d\d\.zip|/20\d\d-\d\d/spud20\d\d-\d\d\.zip)"', page)))
    for z in zips[-2:]:
        try:
            zz = zipfile.ZipFile(io.BytesIO(get("https://static.aer.ca" + z if z.startswith("/prd") else "https://www.aer.ca/sites/default/files" + z).content))
            texts += [zz.read(n).decode("latin1") for n in zz.namelist() if n.lower().endswith(".txt")]
        except Exception:
            traceback.print_exc()
    for dname in re.findall(r'href="(/data/wells/SPUD\w+\.txt)"', page):
        for host in ("https://static.aer.ca/prd", "https://www.aer.ca", "https://static.aer.ca"):
            try:
                texts.append(get(host + dname, tries=1, timeout=60).text)
                break
            except Exception:
                pass
    cut = pd.Timestamp(since(max(days, 75)))
    for t in texts:
        for l in t.splitlines():
            m = pat.search(l)
            if not m:
                continue
            contractor, when, licensee = m.group(3).strip(), pd.to_datetime(m.group(5), errors="coerce"), m.group(8).strip()
            if pd.isna(when) or when < cut or re.search(r"\d{7}", contractor):
                continue
            o.add(licensee, 43, "AER ST49 daily spud list", when, None, None, "AB", f"Spudded well with {contractor}")
            if not re.search("Precision|Ensign|Akita", contractor):
                o.add(contractor, 43, "AER ST49 daily spud list", when, None, None, "AB", f"Rig active for {licensee}",
                      ttype="s43: Drilling contractor rig active (spud)")


# ---------------------------------------------------------------- Transport Canada aircraft register (s82, s83, s59)
def aircraft(o: Out, days: int):
    z = zipfile.ZipFile(io.BytesIO(get("https://wwwapps.tc.gc.ca/Saf-Sec-Sur/2/CCARCS-RIACC/download/ccarcsdb.zip").content))
    names = {n.lower(): n for n in z.namelist()}
    lay = z.read(names["carslayout.txt"]).decode("latin1").splitlines()
    cur_fields, file_ = [], None
    for l in lay:
        m = re.match(r"\s*\d+\s+(\S+)\s+\S+\s+(\S+)", l)
        if not m:
            continue
        if m.group(2) == "FILE":
            file_ = m.group(1).upper()
            continue
        if file_ == "CARSCURR.TXT":
            cur_fields.append(m.group(1).upper())
    print("aircraft fields:", cur_fields)
    idx = lambda pat, default: next((i for i, f in enumerate(cur_fields) if re.search(pat, f)), default)
    i_make, i_model = idx(r"^COMMON_NAME$", 3), idx(r"^MODEL_NAME$", 4)
    i_purpose = idx(r"^PURPOSE.*_E$", 24)
    i_built = idx(r"MANUFACTUR.*DATE|DATE.*MANUFACTUR", 31)
    i_reg = idx(r"^(REGISTRATION_EFFECTIVE_DATE|CERTIFICATE_ISSUE_DATE|ISSUE_DATE|EFFECTIVE_DATE)$", 21)
    print("aircraft columns used:", i_make, i_model, i_purpose, i_built, i_reg)
    cc = pd.read_csv(io.BytesIO(z.read(names["carscurr.txt"])), header=None, dtype=str, encoding="latin1",
                     quoting=csv.QUOTE_ALL, on_bad_lines="skip")
    cc = cc.iloc[:, [0, i_make, i_model, i_purpose, i_built, i_reg]]
    cc.columns = ["mark", "make", "model", "purpose", "built", "reg"]
    cc["mark"] = cc.mark.str.strip()
    ow = pd.read_csv(io.BytesIO(z.read(names["carsownr.txt"])), header=None, dtype=str, encoding="latin1", on_bad_lines="skip").iloc[:, [0, 1, 5, 6, 11]]
    ow.columns = ["mark", "name", "city", "prov", "otype"]
    ow["mark"] = ow.mark.str.strip()
    m = cc.merge(ow[ow.otype.str.contains("Entity", na=False)], on="mark")
    m = m[m.prov != "Quebec"]
    m["regd"] = pd.to_datetime(m.reg, errors="coerce")
    new = m[m.regd >= pd.Timestamp(since(days))]
    for _, r in new.iterrows():
        sig = 83 if str(r.purpose).strip() == "Commercial" else 82
        o.add(r["name"], sig, "Transport Canada aircraft register", r.regd, None, str(r.city).strip(), r.prov, f"{r.make} {r.model}")
    old = m[(m.purpose.str.strip() == "Commercial") & (m.built.fillna("9999").str[:4] <= str(dt.date.today().year - 25))]
    for _, r in old.iterrows():
        o.add(r["name"], 59, "Transport Canada aircraft register", None, None, str(r.city).strip(), r.prov,
              f"{r.make} {r.model} built {str(r.built)[:4]}", campaign="Asset turnover")


# ---------------------------------------------------------------- Job Bank hiring (s77 ... s224, s67)
JB_KW = {
    134: ["CNC machinist", "CNC programmer"], 135: ["welder", "fabricator"], 136: ["millwright", "industrial mechanic"],
    137: ["machine operator"], 138: ["heavy equipment operator", "crane operator"], 139: ["estimator", "construction superintendent"],
    140: ["forklift"], 141: ["industrial electrician", "HVAC technician"], 77: ["farm supervisor", "greenhouse"],
    80: ["automotive service technician", "heavy duty mechanic"], 88: ["pilot", "aircraft maintenance engineer"],
    124: ["logging", "feller buncher"], 181: ["MRI technologist", "sonographer"], 218: ["kitchen manager"], 220: ["baker"],
    224: ["AZ driver", "long haul truck driver"], 175: ["dental assistant"], 67: ["controller", "chief financial officer", "finance manager"],
}
# A posting only counts if its title really is that job. Job Bank search also returns loosely related postings.
JB_TITLE = {  # keep identical to the Supabase table jobbank_title_rules; the Monday quality check compares against it
    134: r"\bcnc\b", 135: r"weld|fabricat",
    136: r"millwright|industrial mechanic|maintenance mechanic|production machinery|rig mechanic|mechanic, (production|knitting|industrial)|machinery mechanic",
    137: r"machine operator|machine tender|moulding|molding|extrusion|press operator|press brake|printing press|machine tool operator|machining|lathe|process operator|bindery|cutter operator|sign maker|operator, machine",
    138: r"heavy equipment|heavy.duty equipment|equipment operator, heavy|crane|excavator|bulldozer|dozer|loader operator|grader operator|backhoe|bobcat|concrete (pump|spreader)|snow removal equipment|crusher",
    139: r"estimator|superintendent|site super", 140: r"forklift|warehouse (lead|supervisor|team lead)",
    141: r"electrician|hvac|refrigeration|heating|gas fitter|air conditioning",
    77: r"farm (supervisor|manager|operation supervisor|workers? supervisor)|greenhouse",
    80: r"automotive service tech|heavy.duty (mechanic|tech)|diesel|truck mechanic|automotive tech|motor vehicle mechanic|mechanic, (truck|heavy)",
    88: r"pilot|aircraft maintenance|\bame\b", 124: r"logging|feller|harvester operator|forestry|skidder|log loader",
    181: r"\bmri\b|sonograph|radiolog|x-ray|imaging|ultrasound", 218: r"kitchen manager|kitchen supervisor",
    220: r"baker|bakery", 224: r"truck driver|driver, truck|\baz\b|long.haul|class 1|tractor.trailer|transport driver",
    175: r"dental", 67: r"controller|chief financial|finance manager|\bcfo\b",
}
JB_PROV = ["ON", "BC", "AB", "SK", "MB", "NS", "NB", "NL", "PE"]


def _jb_parse(h: str) -> list[dict]:
    out = []
    for a in h.split("<article")[1:]:
        t = re.sub(r"\s+", " ", re.sub("<[^>]+>", " | ", a))
        m = re.search(r"\| ([A-Z][a-z]+ \d{1,2}, 20\d\d) \|", t)
        d = dt.datetime.strptime(m.group(1), "%B %d, %Y").date() if m else None
        biz = re.search(r'class="business"[^>]*>([^<]+)', a)
        loc = re.search(r"Location \|[ |]*([^|]+)\|", t)
        title = re.search(r'class="noctitle"[^>]*>\s*([^<]+)', a)
        jid = re.search(r"article-(\d+)", a)
        out.append(dict(id=jid.group(1) if jid else None, date=d, employer=(biz.group(1).strip() if biz else ""),
                        loc=(loc.group(1).strip() if loc else ""), title=(title.group(1).strip() if title else "")))
    return out


def _jb_run(sig, kw, prov, cut):
    rows = []
    for page in range(1, 41):
        q = requests.compat.urlencode({"searchstring": kw, "fprov": prov, "sort": "D", "page": page})
        try:
            h = get(f"https://www.jobbank.gc.ca/jobsearch/jobsearch?{q}", timeout=60).text
        except Exception:
            break
        got = _jb_parse(h)
        if not got:
            break
        for g in got:
            g.update(signal=sig, prov=prov)
        rows += [g for g in got if g["date"] and g["date"] >= cut]
        if all(g["date"] and g["date"] < cut for g in got):
            break
        time.sleep(0.5)
    return rows


def jobbank(o: Out, days: int):
    cut = since(min(days, 30))
    jobs = [(s, k, p) for s, ks in JB_KW.items() for k in ks for p in JB_PROV]
    allr = []
    with ThreadPoolExecutor(6) as ex:
        for res in ex.map(lambda a: _jb_run(*a, cut), jobs):
            allr += res
    seen = set()
    for r in allr:
        if (r["id"], r["signal"]) in seen:
            continue
        seen.add((r["id"], r["signal"]))
        if not re.search(JB_TITLE[r["signal"]], r["title"], re.I):
            continue
        if r["signal"] == 67 and re.search(r"traffic|air|pest|quality|inventory|production|access|flight", r["title"], re.I):
            continue
        city = re.sub(r"\s*\([A-Z]{2}\)\s*$", "", r["loc"])
        o.add(r["employer"], r["signal"], "Job Bank", r["date"], None, city, r["prov"], r["title"])


# ---------------------------------------------------------------- Toronto building permits (s3, s92)
# Not in LOADERS: since 2026 Toronto's open data leaves the builder off commercial permits (0 of 101 in a 3-week test),
# so there is no company to contact. Kept here in case the city adds the field back.
def toronto_permits(o: Out, days: int):
    r = get("https://ckan0.cf.opendata.inter.prod-toronto.ca/datastore/dump/6d0229af-bc54-46de-9c2b-26759b01dd05", timeout=300)
    t = pd.read_csv(io.StringIO(r.text), dtype=str)
    t = t[t.ISSUED_DATE.fillna("") >= since(days).isoformat()]
    num = lambda c: pd.to_numeric(t[c], errors="coerce").fillna(0)
    use = (t.CURRENT_USE.fillna("") + " " + t.PROPOSED_USE.fillna("")).str.lower()
    resi = use.str.contains(r"sfd|semi|townhouse|duplex|triplex|residential|apartment|dwelling|house|condo|multiple unit|res\b", regex=True)
    nonres = ((num("INDUSTRIAL") + num("MERCANTILE") + num("BUSINESS_AND_PERSONAL_SERVICES") + num("ASSEMBLY") + num("INSTITUTIONAL")) > 0) | \
             t.PERMIT_TYPE.fillna("").str.contains("Non-Residential", case=False) | \
             (t.PERMIT_TYPE.fillna("").isin(["Building Additions/Alterations", "New Building"]) & ~resi & (use.str.strip() != ""))
    cost = pd.to_numeric(t.EST_CONST_COST.fillna("").str.replace(",", ""), errors="coerce").fillna(0)
    print("toronto permits:", len(t), "in window,", int(nonres.sum()), "non-residential,", int((nonres & (cost >= 100000)).sum()),
          "over $100K,", int((nonres & (cost >= 100000) & t.BUILDER_NAME.notna()).sum()), "with a builder named", flush=True)
    for _, x in t[nonres & (cost >= 100000)].iterrows():
        desc = str(x.DESCRIPTION or "")
        o.add(x.BUILDER_NAME, 3, "Toronto building permits", x.ISSUED_DATE, x.EST_CONST_COST, "Toronto", "ON", f"{x.WORK}: {desc[:180]}")
    ind = ((num("INDUSTRIAL") > 0) | use.str.contains("industrial|warehouse|manufactur")) & t.WORK.fillna("").str.contains("New Building|Addition", case=False)
    for _, x in t[ind].iterrows():
        o.add(x.BUILDER_NAME, 92, "Toronto building permits", x.ISSUED_DATE, x.EST_CONST_COST, "Toronto", "ON", f"{x.WORK}: {str(x.DESCRIPTION or '')[:180]}")


# ---------------------------------------------------------------- Big federal contract 3 to 5 years ago (s196)
def old_contracts(o: Out, days: int):
    meta = get("https://open.canada.ca/data/api/action/package_show?id=d8f85d91-7dec-4fd1-8055-483b77225d8b").json()
    url = next(x["url"] for x in meta["result"]["resources"] if (x.get("url") or "").lower().endswith("/contracts.csv"))
    path = "/tmp/fed_contracts_all.csv"
    with requests.get(url, headers=UA, timeout=600, stream=True) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    today = dt.date.today()
    lo, hi = today.replace(year=today.year - 5).isoformat(), today.replace(year=today.year - 3).isoformat()
    cols = ["vendor_name", "vendor_postal_code", "contract_date", "description_en", "contract_value", "commodity_type", "country_of_vendor"]
    post = {"A": "NL", "B": "NS", "C": "PE", "E": "NB", "K": "ON", "L": "ON", "M": "ON", "N": "ON", "P": "ON", "R": "MB", "S": "SK", "T": "AB", "V": "BC"}
    work = re.compile(r"construct|repair|renovat|road|paving|excavat|demolition|dredg|marine|snow|haul|landscap|roof|mechanical|electrical|building|infrastructure|bridge|airfield|grounds", re.I)
    for ch in pd.read_csv(path, usecols=lambda c: c in cols, dtype=str, chunksize=200_000, encoding_errors="replace"):
        ch = ch[(ch.contract_date.fillna("") >= lo) & (ch.contract_date.fillna("") <= hi)]
        ch = ch[ch.country_of_vendor.fillna("CA").str.upper().isin(["CA", ""])]
        ch["v"] = pd.to_numeric(ch.contract_value, errors="coerce").fillna(0)
        ch = ch[ch.v >= 250000]
        for _, x in ch.iterrows():
            desc = str(x.description_en or "")
            if not (str(x.commodity_type).upper() == "C" or work.search(desc)):
                continue
            if re.search(r"consult|architect|engineering services|business services|design|professional|management services|research", desc, re.I) \
                    or re.search(r"architect|engineer|consult|design|planning|associates", str(x.vendor_name), re.I):
                continue  # advisors don't own the equipment
            prov = post.get(str(x.vendor_postal_code or "")[:1].upper(), "")
            if not prov:
                continue
            o.add(x.vendor_name, 196, "Federal contracts proactive disclosure", None, x.v, None, prov,
                  f"Federal contract {str(x.contract_date)[:4]}: {desc[:150]}", campaign="Asset turnover")


# ---------------------------------------------------------------- Alberta grant payments (s129)
def alberta_grants(o: Out, days: int):
    r = get("https://grants.dataservices.alberta.ca/GrantsDataService.svc/file.exportcsv", timeout=600)
    g = pd.read_csv(io.BytesIO(r.content), dtype=str, encoding_errors="replace")
    g["d"] = pd.to_datetime(g.PaymentDate, errors="coerce", format="mixed")
    g["v"] = pd.to_numeric(g.Amount, errors="coerce").fillna(0)
    g = g[(g.d >= pd.Timestamp(since(max(days, 120)))) & (g.v >= 10000)]  # Alberta posts payments about a quarter late
    corp = g.Recipient.fillna("").str.contains(r"\b(?:LTD|LIMITED|INC|CORP|CORPORATION|ULC|LLP|CO\.)\b", case=False)
    g = g[corp & ~g.Recipient.fillna("").str.contains(r"SOCIETY|ASSOCIATION|FOUNDATION|CHURCH|SCHOOL|UNIVERSITY|COLLEGE|HOSPITAL|CO-OP|COOPERATIVE|AUTHORITY|COUNTY|TOWN OF|CITY OF|FIRST NATION|METIS|CHILD|DAYCARE|DAY CARE|CARE CENTRE|HOMES? FOR|SENIOR", case=False)]
    g = g[~g.Ministry.fillna("").str.contains(r"EDUCATION|HEALTH|SENIORS|CHILDREN|SOCIAL|MENTAL|INDIGENOUS|ARTS|CULTURE|PUBLIC SAFETY|JUSTICE", case=False)]
    g = g[~g.Program.fillna("").str.contains(r"SURFACE RIGHTS|COMPENSATION|COMP\. PAY|QUAL-|WAGE TOP|CHILD|DAYCARE|SUBSIDY-CHILD", case=False)]
    agg = g.groupby(["Recipient", "Ministry", "Program"]).agg(d=("d", "max"), v=("v", "sum")).reset_index()
    for _, x in agg.iterrows():
        o.add(x.Recipient, 129, "Alberta grant payments", x.d, x.v, None, "AB", f"{x.Ministry}: {x.Program}")


# ---------------------------------------------------------------- shared: remember when each item was first seen
def first_seen(name: str, keys: list[str]) -> dict:
    """Returns {key: first_seen_date}. Keys seen on the very first run are marked 'baseline' and never sent,
    because we can't tell if they are new. Every later key keeps the date we first saw it, so a missed week
    loses nothing: items first seen in the last 30 days are sent again and Supabase skips the repeats."""
    st = load_state(name)
    today = dt.date.today().isoformat()
    known = dict(zip(st.key, st.first_seen)) if st is not None else {}
    mark = "baseline" if st is None else today
    for k in keys:
        if k and k not in known:
            known[k] = mark
    save_state(name, pd.DataFrame({"key": list(known), "first_seen": list(known.values())}))
    return known


def recent(d: str, days: int = 30) -> bool:
    return d != "baseline" and d >= since(days).isoformat()


# ---------------------------------------------------------------- AGCO liquor applications (s210, s211)
def agco(o: Out, days: int):
    r = get("https://www.agco.ca/sites/default/files/opendata/LiquorApplicationsUndergoingPublicNotice.csv")
    a = pd.read_csv(io.BytesIO(r.content), dtype=str, encoding_errors="replace").fillna("")
    a["k"] = a.premises_name.map(key)
    fs = first_seen("agco_files", list(a.file_number))
    hist = load_state("agco_names")
    hist = pd.concat([hist if hist is not None else pd.DataFrame(columns=["k", "address"]), a[["k", "address"]]]).drop_duplicates()
    save_state("agco_names", hist)
    multi = set(hist.groupby("k").address.nunique().loc[lambda s: s > 1].index)
    today = dt.date.today().isoformat()
    for _, x in a.iterrows():
        d = fs.get(x.file_number, today)
        d = today if d == "baseline" else d  # applications are only listed while their 2-3 week notice runs
        area = f"{x.application_type_en} ({x.areas})"
        if "Additions to Existing Licensed Areas" in x.application_type_en:
            o.add(x.premises_name, 210, "AGCO liquor applications", d, None, x.city.title(), "ON", area)
        elif x.application_type_en.startswith("New") and x.k in multi:
            o.add(x.premises_name, 211, "AGCO liquor applications", d, None, x.city.title(), "ON", f"{area} at {x.address}")


# ---------------------------------------------------------------- BC liquor licences (s213)
def bc_liquor(o: Out, days: int):
    u = ("https://www2.gov.bc.ca/assets/gov/employment-business-and-economic-development/business-management/"
         "liquor-regulation-licensing/reports/all_liquor_licensed_establishments_in_bc.xlsx")
    content = None
    for attempt in range(6):  # this server often drops the first connections from cloud machines
        try:
            r = requests.get(u, headers={**UA, "Connection": "close"}, timeout=120)
            r.raise_for_status()
            content = r.content
            break
        except Exception as e:
            print("bc_liquor retry", attempt, e, flush=True)
            time.sleep(20 + 20 * attempt)
    if content is None:
        raise RuntimeError("BC liquor file could not be downloaded after 6 tries")
    b = pd.read_excel(io.BytesIO(content), sheet_name=0, dtype=str).fillna("")
    b = b[b["Licence Type"].str.contains("Food Primary|Liquor Primary|Manufacturer", case=False)]
    old = load_state("bc_liquor_seen")  # earlier format: one column of licence numbers
    if old is not None and "licence" in old.columns:
        save_state("bc_liquor_seen", pd.DataFrame({"key": old.licence, "first_seen": "baseline"}))
    fs = first_seen("bc_liquor_seen", list(b["Licence Number"]))
    for _, x in b.iterrows():
        d = fs.get(x["Licence Number"], "baseline")
        if not recent(d):
            continue
        lic = x.Licensee if re.search(r"\b(ltd|inc|corp|limited|ulc)\b", x.Licensee, re.I) else re.sub(r"\s*\(\d+\)\s*$", "", x.Establishment)
        kind = x["Licence Sub Category Id"] or x["Licence Type"]
        o.add(lic, 213, "BC liquor licences", d, None, x["Establishment Address City"].title(), "BC",
              f"{kind}: {re.sub(r'\s*\(\d+\)\s*$', '', x.Establishment)}")


# ---------------------------------------------------------------- Ontario surgical and imaging centres (s169, s171, s173)
def ichsc(o: Out, days: int):
    meta = get("https://data.ontario.ca/api/3/action/package_show?id=integrated-community-health-services-centres-ichsc-locations").json()
    res = [x for x in meta["result"]["resources"] if str(x.get("url", "")).endswith(".csv") and not str(x.get("url", "")).endswith("_fr.csv")]
    res.sort(key=lambda x: x.get("last_modified") or "")
    c = pd.read_csv(io.BytesIO(get(res[-1]["url"]).content), dtype=str, encoding_errors="replace").fillna("")
    surg = re.compile(r"surg|cataract|endoscop|plastic", re.I)
    events = []  # one key per licence, per service and per address, so each change is seen once
    for lic, g in c.groupby("Licence Num"):
        x = g.iloc[0]
        svc = sorted({p.strip() for v in g.Services for p in v.split(",") if p.strip()})
        events.append((f"L|{lic}", 173 if surg.search(" ".join(svc)) else 169, x, f"New licence: {x.Facilityname} ({', '.join(svc)[:150]})"))
        for sv in svc:
            events.append((f"S|{lic}|{sv}", 171, x, f"Added service at {x.Facilityname}: {sv}"))
        events.append((f"A|{lic}|{x.Address1}", 173, x, f"Moved {x.Facilityname} to {x.Address1}"))
    fs = first_seen("ichsc_seen2", [e[0] for e in events])
    new_lic = {e[0].split("|")[1] for e in events if e[0].startswith("L|") and recent(fs[e[0]])}
    for k, sig, x, det in events:
        if not recent(fs[k]):
            continue
        lic = k.split("|")[1]
        if not k.startswith("L|") and lic in new_lic:
            continue  # a new centre's services and address are part of its "new licence" signal
        o.add(x["Licensee Name"], sig, "Ontario ICHSC list", fs[k], None, x.City, "ON", det)


# ---------------------------------------------------------------- Alberta Certificate of Recognition, first time (s61)
def alberta_cor(o: Out, days: int):
    raw = pd.read_excel(io.BytesIO(get("https://extern.labour.alberta.ca/cor-listing/ohs-employers-with-cor.xlsx").content), header=None, dtype=str)
    hdr = raw.index[raw[0].fillna("").str.strip() == "Legal Name"][0]
    c = raw.iloc[hdr + 1:].copy(); c.columns = [str(v).strip() for v in raw.iloc[hdr]]
    c = c[c["Legal Name"].notna()].fillna("")
    old = load_state("ab_cor_seen")
    if old is not None and "account" in old.columns:
        save_state("ab_cor_seen", pd.DataFrame({"key": old.account, "first_seen": "baseline"}))
    fs = first_seen("ab_cor_seen", list(c.Account))
    c["issued"] = pd.to_datetime(c["COR Number"].str[:8], format="%Y%m%d", errors="coerce")
    for _, x in c.iterrows():
        d = fs.get(x.Account, "baseline")
        if not recent(d):
            continue
        o.add(x["Legal Name"], 61, "Alberta COR list", x.issued if pd.notna(x.issued) else d, None, None, "AB",
              f"First COR, {x['Certifying Partner']}" + (f" ({x['Display/Trade Name']})" if x["Display/Trade Name"] else ""))

LOADERS = {
    "calgary": calgary, "vancouver_permits": vancouver_permits, "vancouver_licences": vancouver_licences,
    "vancouver_awards": vancouver_awards, "edmonton_licences": edmonton_licences, "nova_scotia": nova_scotia,
    "toronto_awards": toronto_awards, "dinesafe": dinesafe, "child_care": child_care,
    "access_environment": access_environment, "ero": ero, "aer_licences": aer_licences, "aer_spud": aer_spud,
    "aircraft": aircraft, "jobbank": jobbank, "old_contracts": old_contracts,
    "alberta_grants": alberta_grants, "agco": agco, "bc_liquor": bc_liquor, "ichsc": ichsc, "alberta_cor": alberta_cor,
}

COLS = ["dedupe_key", "source_name", "trigger_type", "signal_no", "campaign", "company", "city", "province", "date", "amount", "detail"]


def run_all(days: int, only: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    rows, runs = [], []
    now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    for name, fn in LOADERS.items():
        if only and name not in only:
            continue
        o = Out()
        t0 = time.time()
        try:
            fn(o, days)
            uniq = {r["dedupe_key"]: r for r in o.rows}
            rows += uniq.values()
            runs.append(dict(run_at=now, source=name, status="ok", signals_found=len(uniq), new_signals="", note=f"{int(time.time() - t0)}s"))
            print(f"[{name}] {len(uniq)} signals in {int(time.time() - t0)}s", flush=True)
        except Exception as e:
            traceback.print_exc()
            runs.append(dict(run_at=now, source=name, status="FAILED", signals_found=0, new_signals="", note=str(e)[:400]))
            print(f"[{name}] FAILED: {e}", flush=True)
    rows = list({r["dedupe_key"]: r for r in rows}.values())
    return rows, runs
