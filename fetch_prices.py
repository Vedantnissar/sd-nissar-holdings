#!/usr/bin/env python3
"""Fetch BSE prices for every code in holdings.json and write prices.json.
Runs in GitHub Actions (server-side): no CORS, no proxy.
Two passes: small batches first, then retry every miss individually,
because Yahoo rate-limits large batch downloads and yfinance drops them.
Only finite, positive prices are written, so bad data never reaches the page."""
import json, math, datetime, time

import yfinance as yf

with open("holdings.json", encoding="utf-8") as f:
    holdings = json.load(f)

codes = sorted({str(h["code"]) for h in holdings
                if str(h["code"]).isdigit() and len(str(h["code"])) >= 5})
tickers = [c + ".BO" for c in codes]
prices = {}

def good(v):
    try:
        v = float(v)
        return round(v, 2) if math.isfinite(v) and v > 0 else None
    except Exception:
        return None

def last_close(df):
    try:
        s = df["Close"].dropna()
        if len(s):
            return good(s.iloc[-1])
    except Exception:
        pass
    return None

# ---- pass 1: small batches, no threading, pause between ----
CHUNK = 20
for i in range(0, len(tickers), CHUNK):
    chunk = tickers[i:i + CHUNK]
    try:
        data = yf.download(chunk, period="5d", interval="1d", group_by="ticker",
                           threads=False, progress=False, auto_adjust=False)
    except Exception as e:
        print("batch failed:", e)
        data = None
    if data is not None:
        for t in chunk:
            code = t[:-3]
            if code in prices:
                continue
            try:
                sub = data[t] if len(chunk) > 1 else data
                v = last_close(sub)
                if v is not None:
                    prices[code] = v
            except Exception:
                pass
    time.sleep(1.0)

# ---- pass 2: retry each miss individually (this recovers most) ----
missing = [c for c in codes if c not in prices]
print(f"after batch: {len(prices)} priced, retrying {len(missing)} individually")
for code in missing:
    t = code + ".BO"
    for attempt in range(2):
        try:
            df = yf.Ticker(t).history(period="5d", interval="1d", auto_adjust=False)
            v = last_close(df)
            if v is not None:
                prices[code] = v
                break
        except Exception:
            pass
        time.sleep(0.5)
    time.sleep(0.25)

still_missing = sorted(c for c in codes if c not in prices)
result = {
    "lastUpdated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "count": len(prices),
    "total": len(codes),
    "missing": still_missing,
    "prices": {c: {"price": prices[c]} for c in prices},
}
with open("prices.json", "w", encoding="utf-8") as f:
    json.dump(result, f, separators=(",", ":"))

print(f"priced {len(prices)} of {len(codes)}; still missing {len(still_missing)}")
if still_missing:
    print("missing codes:", ", ".join(still_missing))
