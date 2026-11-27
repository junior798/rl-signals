"""One-off probe, round 4."""
import io, re
import requests, pandas as pd
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"}
def get(u, **kw):
    r = requests.get(u, headers=UA, timeout=180, **kw); print(f"\n### {r.status_code} {len(r.content)}  {u}"); return r
def show(d):
    print(d.shape, list(d.columns)); print(d.head(3).to_string()[:2000])
h = get("https://hamilton.bidsandtenders.ca/Module/Tenders/en").text
print(sorted(set(re.findall(r'["\'](/Module/[^"\']+)["\']', h)))[:40])
print(sorted(set(re.findall(r'(?i)(?:url|action)\s*[:=]\s*["\']([^"\']+)["\']', h)))[:40])
i = h.lower().find("award"); print(re.sub(r"\s+", " ", h[max(0, i-1500):i+1500]))
for u in ["https://hamilton.bidsandtenders.ca/Module/Tenders/en/Tender/Search/b8f2e1c4-3a5d-4c4e-9b5b-1f8f1c6d0000?status=Awarded",
          "https://hamilton.bidsandtenders.ca/Module/Tenders/en/Tender/Search"]:
    try:
        r = requests.post(u, headers=UA, timeout=60, data={"status": "Awarded"}); print("\n### POST", r.status_code, u, r.text[:800])
    except Exception as e: print(e)
r = get("https://open.canada.ca/data/dataset/bf00b7f4-e370-46b7-94e4-0bdedc98531b/resource/0b5a739d-b01e-43df-8757-7fc1453baec5/download/large_vessel_-_eng.csv")
x = pd.read_excel(io.BytesIO(r.content), sheet_name=None)
for k, v in x.items(): print("SHEET", k); show(v)
r = get("https://data.ontario.ca/dataset/aac6695e-a8c0-4e0b-ae47-55f3a840ec21/resource/49f55d76-5b91-4019-8a6a-e938ce2c0d0e/download/ichsc_web_page_report_october_2026.csv")
show(pd.read_csv(io.BytesIO(r.content), dtype=str, encoding_errors="ignore"))
r = get("https://www.agco.ca/sites/default/files/opendata/LiquorApplicationsUndergoingPublicNotice.csv")
d = pd.read_csv(io.BytesIO(r.content), dtype=str, encoding_errors="ignore"); show(d)
for c in d.columns:
    if d[c].nunique() < 30: print(c, d[c].value_counts().head(12).to_dict())
r = get("https://www2.gov.bc.ca/assets/gov/employment-business-and-economic-development/business-management/liquor-regulation-licensing/reports/all_liquor_licensed_establishments_in_bc.xlsx")
x = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None)
for k, v in x.items(): print("SHEET", k, v.shape); print(v.head(6).to_string()[:2000])
r = get("https://extern.labour.alberta.ca/cor-listing/ohs-employers-with-cor.xlsx")
v = pd.read_excel(io.BytesIO(r.content), header=None); print(v.iloc[3:9].to_string()[:2500])
r = get("https://ckan0.cf.opendata.inter.prod-toronto.ca/datastore/dump/6d0229af-bc54-46de-9c2b-26759b01dd05")
d = pd.read_csv(io.StringIO(r.text), dtype=str); show(d)
print(d.PERMIT_TYPE.value_counts().head(20).to_dict() if "PERMIT_TYPE" in d else "")
print(d.ISSUED_DATE.max() if "ISSUED_DATE" in d else "")
r = requests.get("https://data-donnees.az.ec.gc.ca/api/file?path=%2Fsubstances%2Fplansreports%2Freporting-facilities-pollutant-release-and-transfer-data%2Fbulk-data-files-for-all-years-releases-disposals-transfers-and-facility-locations%2FNPRI-INRP_GeolocationsGeolocalisation_1993-present.csv", headers=UA, timeout=180, stream=True)
print("\n### NPRI", r.status_code, r.headers.get("content-length")); print(next(r.iter_content(3000)).decode("latin1"))
