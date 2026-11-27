"""One-off probe, round 3."""
import io, re, json
import requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"}
def get(u, **kw):
    try:
        r = requests.get(u, headers=UA, timeout=120, **kw)
        print(f"\n### {r.status_code} {len(r.content)} {r.headers.get('content-type','')[:40]}  {u}")
        return r
    except Exception as e:
        print(f"\n### ERROR {u} {e}"); return None
def links(r, pat):
    if r is not None:
        print(sorted(set(re.findall(pat, r.text)))[:30])
import pandas as pd
def head(r, kind="csv"):
    if r is None or not r.ok: return
    try:
        if kind == "xlsx":
            d = pd.read_excel(io.BytesIO(r.content))
        else:
            d = pd.read_csv(io.BytesIO(r.content), dtype=str, encoding_errors="ignore", nrows=2000)
        print(d.shape, list(d.columns)); print(d.head(3).to_string()[:1800])
    except Exception as e:
        print("parse", e); print(r.text[:800])

r = get("https://www.agco.ca/en/alcohol/status-current-liquor-sales-licence-applications"); links(r, r'href="([^"]+\.(?:csv|xlsx|json)[^"]*)"'); links(r, r'href="(https?://[^"]*(?:data|dataset)[^"]*)"')
r = get("https://www2.gov.bc.ca/gov/content/employment-business/business/liquor-regulation-licensing/liquor-licence-permits/liquor-resources-information/bc-liquor-licensed-establishment-locations"); links(r, r'href="([^"]+\.xlsx[^"]*)"')
r = get("https://grants.dataservices.alberta.ca/GrantsDataService.svc/file.exportcsv", stream=True)
if r is not None:
    chunk = next(r.iter_content(4000)); print(chunk[:1500])
r = get("https://data.ontario.ca/api/3/action/package_show?id=integrated-community-health-services-centres-ichsc-locations")
if r is not None and r.ok:
    for x in r.json()["result"]["resources"]: print(x["name"], x.get("url"), x.get("last_modified"))
r = get("https://open.canada.ca/data/dataset/bf00b7f4-e370-46b7-94e4-0bdedc98531b/resource/0b5a739d-b01e-43df-8757-7fc1453baec5/download/large_vessel_-_eng.csv"); head(r)
r = get("https://extern.labour.alberta.ca/cor-listing/ohs-employers-with-cor.xlsx"); head(r, "xlsx")
r = get("https://purchasing.alberta.ca/api/opportunity/public?status=AWARD&limit=2")
if r is not None: print(r.text[:1200])
r = get("https://purchasing.alberta.ca/search"); links(r, r'(/api/[^"\']+)')
for org in ["hamilton", "mississauga", "brampton", "london"]:
    r = get(f"https://{org}.bidsandtenders.ca/Module/Tenders/en")
    if r is not None: print(re.sub(r"\s+", " ", r.text[:1500]))
r = get("https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_show?id=building-permits-active-permits")
if r is not None and r.ok:
    for x in r.json()["result"]["resources"]: print(x["name"], x["format"], x.get("datastore_active"), x["id"])
r = get("https://open.canada.ca/data/api/action/package_show?id=40e01423-7728-429c-ac9d-2954385ccdfb")
if r is not None and r.ok:
    for x in r.json()["result"]["resources"][:15]: print(x["name"], x.get("url"))
