"""One-off probe, round 5: bids&tenders."""
import re, requests, json
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"}
s = requests.Session(); s.headers.update(UA)
h = s.get("https://hamilton.bidsandtenders.ca/Module/Tenders/en", timeout=60).text
for m in re.finditer(r"<script[^>]*>(.*?)</script>", h, re.S):
    t = m.group(1)
    if "Tender" in t or "ajax" in t.lower() or "url" in t.lower():
        print("---SCRIPT---"); print(re.sub(r"\s+", " ", t)[:2500])
print(sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', h))))
for js in re.findall(r'src="(/Module/Tenders/[^"]+\.js[^"]*)"', h):
    if "min" in js and ("jquery" in js.lower() or "bootstrap" in js.lower() or "fuelux" in js.lower()): continue
    t = s.get("https://hamilton.bidsandtenders.ca" + js, timeout=60).text
    hits = sorted(set(re.findall(r'["\'](/Module/Tenders/[^"\']*(?:Search|Award|Tender)[^"\']*)["\']', t)))
    if hits: print("JS", js, hits[:30])
