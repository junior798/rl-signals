"""One-off probe, round 2."""
import io, json, re, zipfile
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"}


def get(u):
    r = requests.get(u, headers=UA, timeout=180)
    print(f"\n### {r.status_code} {len(r.content)} bytes  {u}")
    return r


r = get("https://wwwapps.tc.gc.ca/Saf-Sec-Sur/2/CCARCS-RIACC/download/ccarcsdb.zip")
z = zipfile.ZipFile(io.BytesIO(r.content))
print(z.read("carslayout.txt").decode("latin1")[:6000])

r = get("https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets/awarded-contracts/records?limit=2")
print(r.text[:1500])
r = get("https://ckan0.cf.opendata.inter.prod-toronto.ca/datastore/dump/e211f003-5909-4bea-bd96-d75899d8e612")
print("\n".join(r.text.splitlines()[:4])[:2000])
r = get("https://ckan0.cf.opendata.inter.prod-toronto.ca/datastore/dump/75dbb3ff-8281-4f03-9de2-bd1214761302")
print("\n".join(r.text.splitlines()[:3])[:1500])
r = get("https://data.ontario.ca/dataset/7efd8b4b-cc63-4337-a551-c940a346605b/resource/876d6b6a-784f-4d79-85f1-f0433e7e5e58/download/child_care_facilities_open_data_oct_2026.xlsx")
import pandas as pd
d = pd.read_excel(io.BytesIO(r.content))
print(d.shape, list(d.columns))
print(d.head(2).to_string()[:1500])
r = get("https://data.ontario.ca/api/3/action/package_show?id=licensed-child-care-facilities-in-ontario")
for x in r.json()["result"]["resources"]:
    print(x["name"], x["format"], x.get("url"), x.get("created"))
r = get("https://www.aer.ca/node/797")
print(sorted(set(re.findall(r'href="([^"]*(?:spud|SPUD)[^"]*)"', r.text))))
r = get("https://static.aer.ca/prd/data/wells/spud2026-09.zip")
z = zipfile.ZipFile(io.BytesIO(r.content))
print(z.namelist()[:5])
t = z.read(z.namelist()[-1]).decode("latin1").splitlines()
print("\n".join(t[:30]))
