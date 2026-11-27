import io, requests, pandas as pd
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
      "Accept": "*/*", "Accept-Language": "en-CA,en;q=0.9"}
r = requests.get("https://ckan0.cf.opendata.inter.prod-toronto.ca/datastore/dump/6d0229af-bc54-46de-9c2b-26759b01dd05", headers=UA, timeout=300)
t = pd.read_csv(io.StringIO(r.text), dtype=str)
print("max issued", t.ISSUED_DATE.max(), "rows>=2026-11-06", (t.ISSUED_DATE.fillna("") >= "2026-11-06").sum())
x = t[t.ISSUED_DATE.fillna("") >= "2026-10-01"]
print(x[["PERMIT_TYPE","WORK","EST_CONST_COST","INDUSTRIAL","MERCANTILE","BUSINESS_AND_PERSONAL_SERVICES","BUILDER_NAME"]].sample(15, random_state=1).to_string())
print(x.EST_CONST_COST.value_counts().head(8))
print("builder notna", x.BUILDER_NAME.notna().sum(), len(x))
r = requests.get("https://grants.dataservices.alberta.ca/GrantsDataService.svc/file.exportcsv", headers=UA, timeout=600)
g = pd.read_csv(io.BytesIO(r.content), dtype=str, encoding_errors="replace")
g["d"] = pd.to_datetime(g.PaymentDate, errors="coerce", format="mixed")
print("grants rows", len(g), "max", g.d.max(), "min", g.d.min(), "null", g.d.isna().sum())
print(g.PaymentDate.head(3).tolist())
print(g[g.Recipient.str.contains(r"\bLTD\b|\bINC\b", na=False)].sort_values("d").tail(5).to_string()[:1500])
for i in range(3):
    try:
        r = requests.get("https://www2.gov.bc.ca/assets/gov/employment-business-and-economic-development/business-management/liquor-regulation-licensing/reports/all_liquor_licensed_establishments_in_bc.xlsx", headers=UA, timeout=120)
        print("BC", r.status_code, len(r.content)); break
    except Exception as e: print("BC err", e)
