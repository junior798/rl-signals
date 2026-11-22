"""Shared helpers: downloads, CKAN lookups, column finding, name and province cleanup."""
from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path

import requests

OPEN_CANADA_API = "https://open.canada.ca/data/api/action/package_show"
DONNEES_QUEBEC_API = "https://www.donneesquebec.ca/recherche/api/3/action/package_show"

HEADERS = {"User-Agent": "rl-signals/1.0 (weekly open data download)"}
CACHE = Path("cache")


class ColumnError(RuntimeError):
    """Raised when a file does not have a column we need. The message lists the real columns."""


def get(url: str, retries: int = 3, timeout: int = 120, stream: bool = False) -> requests.Response:
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, stream=stream)
            r.raise_for_status()
            return r
        except requests.RequestException as e:  # retry network hiccups
            last = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Download failed after {retries} tries: {url}: {last}")


def download(url: str, name: str | None = None) -> Path:
    """Download a file to cache/ (streamed, so large files are fine) and return its path."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / (name or url.rstrip("/").split("/")[-1].split("?")[0])
    with get(url, stream=True, timeout=600) as r, open(path, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    return path


def ckan_resources(api: str, package_id: str) -> list[dict]:
    data = get(f"{api}?id={package_id}").json()
    if not data.get("success"):
        raise RuntimeError(f"Catalogue lookup failed for {package_id}")
    return data["result"]["resources"]


def resource_date(res: dict) -> str:
    return res.get("last_modified") or res.get("metadata_modified") or res.get("created") or ""


def latest(resources: list[dict], test) -> dict:
    hits = [r for r in resources if test(r)]
    if not hits:
        raise RuntimeError("No matching file found in the catalogue entry")
    return max(hits, key=resource_date)


def find_col(columns, *candidates: tuple[str, ...] | str, required: bool = True) -> str | None:
    """Return the first column whose lowercased name contains every token of a candidate.

    find_col(cols, ("supplier", "name"), "vendor") matches 'supplierLegalName-nomFournisseur-eng'.
    """
    cols = list(columns)
    low = {c: str(c).lower() for c in cols}
    for cand in candidates:
        tokens = (cand,) if isinstance(cand, str) else cand
        for c in cols:
            if all(t.lower() in low[c] for t in tokens):
                return c
    if required:
        raise ColumnError(f"None of {candidates} found. Columns in file: {cols}")
    return None


_SUFFIX = re.compile(
    r"\b(inc|incorporated|ltd|ltee|limited|limitee|corp|corporation|co|company|cie|enr|senc|s e n c|llc|lp|ulc|"
    r"canada|groupe|group|the|les|le|la)\b"
)


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_name(name: str) -> str:
    s = strip_accents(str(name or "")).lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


PROVINCES = {
    "QC": ["qc", "quebec", "que", "pq"], "ON": ["on", "ontario", "ont"], "BC": ["bc", "british columbia", "colombie britannique", "c b"],
    "AB": ["ab", "alberta", "alta"], "SK": ["sk", "saskatchewan", "sask"], "MB": ["mb", "manitoba", "man"],
    "NB": ["nb", "new brunswick", "nouveau brunswick"], "NS": ["ns", "nova scotia", "nouvelle ecosse"],
    "PE": ["pe", "pei", "prince edward island", "ile du prince edouard"], "NL": ["nl", "newfoundland and labrador", "terre neuve et labrador", "newfoundland"],
    "YT": ["yt", "yukon"], "NT": ["nt", "northwest territories", "territoires du nord ouest"], "NU": ["nu", "nunavut"],
}
_PROV_LOOKUP = {alias: code for code, aliases in PROVINCES.items() for alias in aliases}


def norm_province(value) -> str:
    s = re.sub(r"[^a-z ]+", " ", strip_accents(str(value or "")).lower()).strip()
    s = re.sub(r"\s+", " ", s)
    if s in _PROV_LOOKUP:
        return _PROV_LOOKUP[s]
    for alias, code in sorted(_PROV_LOOKUP.items(), key=lambda kv: -len(kv[0])):
        if len(alias) > 3 and alias in s:
            return code
    return ""


def is_excluded(name: str, patterns: list[str]) -> bool:
    s = strip_accents(str(name or "")).lower()
    return any(re.search(strip_accents(p).lower(), s) for p in patterns)


def parse_date(value) -> date | None:
    if value is None or value != value:  # None or NaN
        return None
    s = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(value) -> float:
    if value is None or value != value:
        return 0.0
    s = re.sub(r"[^0-9.\-]", "", str(value).replace(",", ""))
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def signal_id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def make_signal(*, source, signal_type, company, province, city, when, amount, points, detail, url="", ref="") -> dict:
    return {
        "signal_id": signal_id(source, ref or company, when, amount),
        "source": source,
        "signal_type": signal_type,
        "company": str(company).strip(),
        "company_key": f"{norm_name(company)}|{province}",
        "city": str(city or "").split(",")[0].strip().title() if str(city or "").lower() != "nan" else "",
        "province": province,
        "date": when.isoformat() if when else "",
        "amount": round(amount, 2),
        "points": points,
        "detail": detail,
        "url": url,
    }


def read_text_table(path: Path, **kw):
    """Read a CSV with whatever encoding the government used this time."""
    import pandas as pd

    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False, **kw)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Could not decode {path}")

