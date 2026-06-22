#!/usr/bin/env python3
"""Fetch prices for every holding in holdings.json and write prices.json.
Runs in GitHub Actions (server-side): no CORS, no proxy.

Per stock, in order, first hit that returns a valid price wins:
  1. BSE by scrip code         -> <code>.BO
  2. explicit NSE override map  -> <ticker>.NS   (for names that aren't clean symbols)
  3. NSE by sheet symbol        -> <sym>.NS
Only finite, positive prices are written, so bad data never reaches the page.
"""
import json, math, datetime, time, logging

import yfinance as yf
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# --- explicit NSE tickers for holdings whose sheet name is a truncated description ---
NSE_OVERRIDE = {
  "500002":"ABB", "506235":"ALEMBICLTD", "508869":"APOLLOHOSP", "532454":"BHARTIARTL",
  "531344":"CONCOR", "500092":"CRISIL", "532488":"DIVISLAB", "532322":"ELDERPHARM",
  "500940":"FINPIPE", "540798":"FSC", "506109":"GENESYS", "500160":"GTLINFRA",
  "509079":"GUFICBIO", "500670":"GNFC", "500180":"HDFCBANK", "532347":"HELIOSMATH",
  "524735":"HIKAL", "500183":"HIMATSEIDE", "500440":"HINDALCO", "500185":"HCC",
  "532662":"HTMEDIA", "532174":"ICICIBANK", "500265":"MAHSEAMLES", "543223":"MAXIND",
  "500288":"MOREPENLAB", "504112":"NELCO", "500314":"ORIENTHOT", "514304":"SKUMARSYNF",
  "543123":"SAHASRA", "526521":"SANGHIIND", "540653":"SPTL", "461591":"SPUNWEB",
  "500113":"SAIL", "524715":"SUNPHARMA", "500403":"SUNDRMFAST", "509930":"SUPREMEIND",
  "532667":"SUZLON", "500770":"TATACHEM", "500408":"TATAELXSI", "500400":"TATAPOWER",
  "532371":"TTML", "500411":"THERMAX", "500251":"TRENT", "507880":"VIPIND",
  "505412":"WENDT", "590073":"WHEELS", "532648":"YESBANK", "539844":"EQUITASBNK",
  "534184":"NAGAOIL",
}

with open("holdings.json", encoding="utf-8") as f:
    holdings = json.load(f)

sym_of = {}
for h in holdings:
    c = str(h["code"])
    if c.isdigit() and len(c) >= 5:
        sym_of[c] = (h.get("sym") or "").strip()
codes = sorted(sym_of)
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

# ---- pass 1: batch BSE by code ----
tickers = [c + ".BO" for c in codes]
CHUNK = 20
for i in range(0, len(tickers), CHUNK):
    chunk = tickers[i:i + CHUNK]
    try:
        data = yf.download(chunk, period="5d", interval="1d", group_by="ticker",
                           threads=False, progress=False, auto_adjust=False)
    except Exception as e:
        print("batch failed:", e); data = None
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

# ---- pass 2: misses -> try a chain of ticker candidates, first valid wins ----
missing = [c for c in codes if c not in prices]
print(f"after BSE batch: {len(prices)} priced, retrying {len(missing)}")
for code in missing:
    ov = NSE_OVERRIDE.get(code)
    sym = sym_of.get(code, "")
    candidates = [(code + ".BO", "BO")]
    for base in (ov, sym):
        if base:
            candidates += [(base + ".NS", "NS"), (base + "-SM.NS", "NS")]  # NSE + NSE-SME
    for ticker, src in candidates:
        v = fetch_one(ticker)
        if v is not None:
            prices[code] = {"price": v, "src": src}
            break
    time.sleep(0.2)

still_missing = sorted(c for c in codes if c not in prices)
n_ns = sum(1 for c in prices if prices[c]["src"] == "NS")
result = {
    "lastUpdated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "count": len(prices), "total": len(codes), "viaNSE": n_ns,
    "missing": still_missing, "prices": prices,
}
with open("prices.json", "w", encoding="utf-8") as f:
    json.dump(result, f, separators=(",", ":"))

print(f"priced {len(prices)} of {len(codes)} ({n_ns} via NSE); still missing {len(still_missing)}")
if still_missing:
    print("missing:", ", ".join(still_missing))
