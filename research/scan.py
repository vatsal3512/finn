import requests, json, time, urllib.parse, collections
syms = """RELIANCE HDFCBANK ICICIBANK SBIN INFY TCS LT ITC BHARTIARTL BAJFINANCE MARUTI M&M SUNPHARMA TITAN ASIANPAINT
HINDUNILVR ADANIENT ADANIPORTS COALINDIA ETERNAL TMPV TMCV INDIGO TRENT BEL HAL NTPC TATASTEEL VEDL INDHOTEL DIXON
POLYCAB PAYTM SUZLON WAAREEENER KPITTECH PERSISTENT INDUSINDBK NYKAA OLAELEC ICICIPRULI POLICYBZR MAZDOCK CDSL IEX
KAYNES TATAPOWER DELHIVERY HFCL NAZARA EMUDHRA IRCTC JIOFIN IDEA YESBANK JSWSTEEL CIPLA""".split()
s = requests.Session()
h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
     "Accept": "application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9",
     "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"}
s.get("https://www.nseindia.com", headers=h, timeout=20)
out = {}
for sym in syms:
    url = f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={urllib.parse.quote(sym)}&from_date=27-09-2026&to_date=27-10-2026"
    for attempt in range(3):
        try:
            r = s.get(url, headers=h, timeout=20)
            if r.status_code == 200:
                d = r.json(); break
            s.get("https://www.nseindia.com", headers=h, timeout=20); time.sleep(2)
        except Exception as e:
            time.sleep(2); d = None
    else:
        d = None
    out[sym] = [{"dt": x.get("an_dt"), "desc": x.get("desc"), "text": (x.get("attchmntText") or "")[:300], "pdf": x.get("attchmntFile"), "name": x.get("sm_name")} for x in (d or [])]
    print(sym, len(out[sym]) if d is not None else "FAIL", flush=True)
    time.sleep(0.8)
json.dump(out, open("ann.json", "w"), indent=1)
