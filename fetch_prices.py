#!/usr/bin/env python3
"""Fetch BSE prices for every code in holdings.json and write prices.json.
Runs in GitHub Actions (server-side) so there is no CORS/proxy involved.
Only finite, positive prices are written, so bad data never reaches the page."""
import json, math, datetime

import yfinance as yf

with open("holdings.json", encoding="utf-8") as f:
    holdings = json.load(f)

codes = sorted({str(h["code"]) for h in holdings
                if str(h["code"]).isdigit() and len(str(h["code"])) >= 5})
tickers = [c + ".BO" for c in codes]

def last_close(df):
    try:
        s = df["Close"].dropna()
        if len(s):
            v = float(s.iloc[-1])
            if math.isfinite(v) and v > 0:
                return round(v, 2)
    except Exception:
        pass
    return None

prices = {}
CHUNK = 40
for i in range(0, len(tickers), CHUNK):
    chunk = tickers[i:i + CHUNK]
    try:
        data = yf.download(chunk, period="5d", interval="1d",
                           group_by="ticker", threads=True,
                           progress=False, auto_adjust=False)
    except Exception as e:
        print("chunk failed:", e)
        continue
    for t in chunk:
        code = t[:-3]
        try:
            sub = data[t] if len(chunk) > 1 else data
            v = last_close(sub)
            if v is not None:
                prices[code] = {"price": v}
        except Exception:
            pass

result = {
    "lastUpdated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "count": len(prices),
    "total": len(codes),
    "prices": prices,
}
with open("prices.json", "w", encoding="utf-8") as f:
    json.dump(result, f, separators=(",", ":"))

print(f"priced {len(prices)} of {len(codes)} codes")
