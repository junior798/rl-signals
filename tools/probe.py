"""One-off probe: prints the shape of each source file so loaders can be written against real columns."""
import io, json, re, sys, zipfile, datetime as dt
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"}


def get(u, **kw):
    try:
        r = requests.get(u, headers=UA, timeout=120, **kw)
        print(f"\n### {r.status_code} {len(r.content)} bytes  {u}")
        return r
    except Exception as e:
        print(f"\n### ERROR {u}: {e}")
        return None


def js(u, n=1500):
    r = get(u)
    if r is not None:
        print(r.text[:n])
    return r


today = dt.date.today()
since = (today - dt.timedelta(days=10)).isoformat()

js(f"https://data.calgary.ca/resource/c2es-76ed.json?$limit=2&$where=issueddate>='{since}'")
js("https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets/issued-building-permits/records?limit=1&order_by=issuedate%20desc")
js("https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets/business-licences/records?limit=1&order_by=issueddate%20desc")
js("https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets?where=search(%22bid%22)&limit=10&select=dataset_id", 3000)
js("https://data.edmonton.ca/api/catalog/v1?q=business%20licences&limit=5", 2500)
js("https://data.edmonton.ca/resource/qhi4-bdpu.json?$limit=1")
js("https://data.edmonton.ca/resource/24uj-dj8v.json?$limit=1")
js("https://data.novascotia.ca/resource/m6ps-8j6u.json?$limit=1&$order=awarded_date%20DESC")
T = "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action"
for q in ["dinesafe", "tobids-awarded-contracts"]:
    r = get(f"{T}/package_show?id={q}")
    if r is not None and r.ok:
        for res in r.json()["result"]["resources"]:
            print(res["name"], res["format"], res.get("datastore_active"), res["id"], res.get("url"))
r = get(f"{T}/package_search?q=awarded%20contracts&rows=5")
if r is not None and r.ok:
    for p in r.json()["result"]["results"]:
        print("PKG", p["name"], [x["name"] for x in p["resources"]][:6])
r = get("https://data.ontario.ca/api/3/action/package_search?q=licensed%20child%20care&rows=5")
if r is not None and r.ok:
    for p in r.json()["result"]["results"]:
        print("PKG", p["name"], [(x["name"], x["format"], x.get("url")) for x in p["resources"]][:8])
M = "https://ws.lioservices.lrc.gov.on.ca/arcgis2/rest/services/Access_Environment/Access_Environment_Map/MapServer"
js(f"{M}/1/query?where=APPROVAL_DATE%20%3E%3D%20DATE%20%27{since}%27&outFields=*&returnGeometry=false&f=json&resultRecordCount=1", 2500)
r = get("https://ero.ontario.ca/search?f%5B0%5D=type%3Ainstrument&page=0")
if r is not None:
    h = r.text
    blk = h.split("views-row")[1] if "views-row" in h else h[:3000]
    print(re.sub(r"\s+", " ", re.sub("<[^>]+>", " | ", blk))[:2500])
d = (today - dt.timedelta(days=2)).strftime("%m%d")
r = get(f"https://static.aer.ca/prd/data/well-lic/WELLS{d}.TXT")
if r is not None:
    print(r.text[:3000])
r = get("https://www.aer.ca/node/797")
if r is not None:
    print(sorted(set(re.findall(r'href="([^"]*(?:spud|SPUD)[^"]*)"', r.text)))[-8:])
for name in ["SPUDMon", "SPUDTue", "SPUDWed"]:
    r = get(f"https://static.aer.ca/data/wells/{name}.txt")
    if r is not None and r.ok:
        lines = r.text.splitlines()
        print("\n".join(lines[:40]))
        break
r = get("https://wwwapps.tc.gc.ca/Saf-Sec-Sur/2/CCARCS-RIACC/download/ccarcsdb.zip")
if r is not None and r.ok:
    z = zipfile.ZipFile(io.BytesIO(r.content))
    print(z.namelist())
    for n in z.namelist():
        if n.lower() in ("carscurr.txt", "carsownr.txt"):
            t = z.read(n).decode("latin1").splitlines()
            print(n, len(t))
            for l in t[:3]:
                print(repr(l[:700]))
r = get("https://www.jobbank.gc.ca/jobsearch/jobsearch?searchstring=welder&fprov=ON&sort=D&page=1")
if r is not None:
    h = r.text
    print("articles", h.count("<article"))
    if "<article" in h:
        print(h.split("<article")[1][:2500])
