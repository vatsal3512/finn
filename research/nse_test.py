import requests, json
s = requests.Session()
h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
     "Accept": "application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"}
r0 = s.get("https://www.nseindia.com", headers=h, timeout=20)
print("home", r0.status_code, len(s.cookies))
r = s.get("https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=HDFCBANK&from_date=01-10-2026&to_date=27-10-2026", headers=h, timeout=20)
print("ann", r.status_code, r.headers.get("content-type"))
try:
    d = r.json(); print(type(d), len(d))
    for x in d[:8]: print(x.get("an_dt"), "|", x.get("desc"), "|", (x.get("attchmntText") or "")[:120])
except Exception as e: print("err", e, r.text[:300])
