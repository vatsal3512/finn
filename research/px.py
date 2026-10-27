import yfinance as yf, pandas as pd, json, numpy as np, warnings
warnings.filterwarnings("ignore")
syms = list(json.load(open("ann.json")).keys())
tick = [s + ".NS" for s in syms]
df = yf.download(tick, period="7mo", interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=True)
rows = []
for s, t in zip(syms, tick):
    try:
        d = df[t].dropna(subset=["Close"])
    except Exception:
        rows.append((s, None)); continue
    if len(d) < 30: rows.append((s, f"only {len(d)} rows")); continue
    r = d["Close"].pct_change()
    vr = d["Volume"] / d["Volume"].rolling(20).mean().shift(1)
    last = d.tail(126)
    rows.append((s, dict(n=len(d), last=d.index[-1].strftime("%d-%b"), close=round(float(d["Close"].iloc[-1]),1),
        vol_ann=round(float(r.tail(126).std()*np.sqrt(252)*100),1),
        d_gt3=int((r.tail(126).abs()>0.03).sum()), d_gt5=int((r.tail(126).abs()>0.05).sum()),
        v2x=int((vr.tail(126)>2).sum()), maxvr5=round(float(vr.tail(5).max()),1), ret1d=round(float(r.iloc[-1]*100),1),
        ret6m=round(float((d['Close'].iloc[-1]/last['Close'].iloc[0]-1)*100),1))))
for s, x in rows:
    print(s, x)
json.dump(rows, open("px.json","w"))
