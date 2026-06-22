#!/usr/bin/env python3
"""Fetch prices for every holding in holdings.json and write prices.json.
Runs in GitHub Actions (server-side): no CORS, no proxy.

NSE FIRST (live, liquid -> the price you actually see), BSE only as last resort,
because Yahoo's BSE feed is often a stale/thin last-traded print for mid-caps.

Per stock, first candidate that returns a valid price wins:
  1. <override-or-sheet-symbol>.NS         (NSE main board)
  2. <symbol>-SM.NS                          (NSE SME board)
  3. <the other symbol>.NS / -SM.NS
  4. <code>.BO                               (BSE, fallback for BSE-only names)
Only finite, positive prices are written, so bad data never reaches the page.
"""
import json, math, datetime, time, logging

import yfinance as yf
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# Verified NSE tickers for holdings whose sheet name is a truncated description.
NSE_OVERRIDE = {
  "500002":"ABB", "506235":"ALEMBICLTD", "508869":"APOLLOHOSP", "532454":"BHARTIARTL",
  "531344":"CONCOR", "500092":"CRISIL", "532488":"DIVISLAB",
  "500940":"FINPIPE", "506109":"GENESYS", "500160":"GTLINFRA",
  "509079":"GUFICBIO", "500670":"GNFC", "500180":"HDFCBANK",
  "524735":"HIKAL", "500183":"HIMATSEIDE", "500440":"HINDALCO", "500185":"HCC",
  "532662":"HTMEDIA", "532174":"ICICIBANK", "500265":"MAHSEAMLES",
  "500288":"MOREPENLAB", "504112":"NELCO", "500314":"ORIENTHOT",
  "526521":"SANGHIIND",
  "500113":"SAIL", "524715":"SUNPHARMA", "500403":"SUNDRMFAST", "509930":"SUPREMEIND",
  "532667":"SUZLON", "500770":"TATACHEM", "500408":"TATAELXSI", "500400":"TATAPOWER",
  "532371":"TTML", "500411":"THERMAX", "500251":"TRENT", "507880":"VIPIND",
  "505412":"WENDT", "590073":"WHEELS", "532648":"YESBANK", "539844":"EQUITASBNK",
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

def candidates(code):
    """Ordered ticker candidates: NSE first, BSE last."""
    ov = NSE_OVERRIDE.get(code)
    sym = sym_of.get(code, "")
    syms = []
    for s in (ov, sym):
        if s and s not in syms:
            syms.append(s)
    out = []
    for s in syms:
        out += [(s + ".NS", "NS"), (s + "-SM.NS", "NS")]
    out.append((code + ".BO", "BO"))   # BSE fallback
    return out

# ---- pass 1: batch the primary NSE ticker per code (fast) ----
primary = {}
for code in codes:
    primary[code] = candidates(code)[0][0]   # first candidate (usually <sym>.NS)
uniq = sorted(set(primary.values()))
CHUNK = 20
batch = {}
for i in range(0, len(uniq), CHUNK):
    chunk = uniq[i:i + CHUNK]
    try:
        data = yf.download(chunk, period="5d", interval="1d", group_by="ticker",
                           threads=False, progress=False, auto_adjust=False)
    except Exception as e:
        print("batch failed:", e); data = None
    if data is not None:
        for t in chunk:
            try:
                sub = data[t] if len(chunk) > 1 else data
                v = last_close(sub)
                if v is not None:
                    batch[t] = v
            except Exception:
                pass
    time.sleep(1.0)
for code in codes:
    t = primary[code]
    if t in batch:
        prices[code] = {"price": batch[t], "src": "NS" if t.endswith(".NS") else "BO"}

# ---- pass 2: walk remaining candidates individually for misses ----
missing = [c for c in codes if c not in prices]
print(f"after NSE batch: {len(prices)} priced, retrying {len(missing)}")
for code in missing:
    for ticker, src in candidates(code):
        if ticker == primary[code]:
            continue
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
