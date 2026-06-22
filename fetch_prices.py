#!/usr/bin/env python3
"""Fetch prices for every holding in holdings.json and write prices.json.
Runs in GitHub Actions (server-side): no CORS, no proxy.

Strategy per stock:
  1. BSE by scrip code  ->  <code>.BO   (authoritative, unambiguous)
  2. if BSE has no data  ->  NSE by symbol  ->  <sym>.NS   (recovers newer
     listings that Yahoo doesn't carry on its BSE feed)
Only finite, positive prices are written, so bad data never reaches the page.
"""
import json, math, datetime, time, logging

import yfinance as yf
logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # quiet the "delisted" spam

with open("holdings.json", encoding="utf-8") as f:
    holdings = json.load(f)

# code -> nse symbol (may be "")
sym_of = {}
for h in holdings:
    c = str(h["code"])
    if c.isdigit() and len(c) >= 5:
        sym_of[c] = (h.get("sym") or "").strip()
codes = sorted(sym_of)
prices = {}   # code -> {"price":x,"src":"BO"/"NS"}

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

def fetch_one(ticker):
    for _ in range(2):
        try:
            df = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=False)
            v = last_close(df)
            if v is not None:
                return v
        except Exception:
            pass
        time.sleep(0.4)
    return None

# ---- pass 1: batch BSE by code (fast, small chunks) ----
tickers = [c + ".BO" for c in codes]
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
            try:
                sub = data[t] if len(chunk) > 1 else data
                v = last_close(sub)
                if v is not None:
                    prices[code] = {"price": v, "src": "BO"}
            except Exception:
                pass
    time.sleep(1.0)

# ---- pass 2: for misses, retry BSE individually, then NSE by symbol ----
missing = [c for c in codes if c not in prices]
print(f"after BSE batch: {len(prices)} priced, retrying {len(missing)}")
for code in missing:
    v = fetch_one(code + ".BO")
    if v is not None:
        prices[code] = {"price": v, "src": "BO"}
    else:
        sym = sym_of.get(code, "")
        if sym:
            v = fetch_one(sym + ".NS")
            if v is not None:
                prices[code] = {"price": v, "src": "NS"}
    time.sleep(0.2)

still_missing = sorted(c for c in codes if c not in prices)
n_ns = sum(1 for c in prices if prices[c]["src"] == "NS")
result = {
    "lastUpdated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "count": len(prices),
    "total": len(codes),
    "viaNSE": n_ns,
    "missing": still_missing,
    "prices": prices,
}
with open("prices.json", "w", encoding="utf-8") as f:
    json.dump(result, f, separators=(",", ":"))

print(f"priced {len(prices)} of {len(codes)} ({n_ns} via NSE); still missing {len(still_missing)}")
if still_missing:
    print("missing:", ", ".join(still_missing))
