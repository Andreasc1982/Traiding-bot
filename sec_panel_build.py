#!/usr/bin/env python3
"""Baut ein grosses, schlankes Kurs-Panel fuer den Insider-Test.

Anders als das Screening-Panel: viel mehr Titel, deutlich niedrigere
Liquiditaetsschwelle (Insider-Effekte sind laut Literatur bei kleineren Werten
am staerksten — genau die schnitt der bisherige $5M-Filter weg) und nur die
noetigen Reihen (Datum/Schluss/Volumen) statt aller OHLCV, um Speicher zu sparen.

    python3 sec_panel_build.py [anzahl] [jahre] [min_tagesumsatz_usd]
"""
import sys, os, json, time, pickle, urllib.request
import statistics as st
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, "/home/trading2025/trading_bot")
from config import config

N = int(sys.argv[1]) if len(sys.argv) > 1 else 2500
YEARS = int(sys.argv[2]) if len(sys.argv) > 2 else 8
MINDV = float(sys.argv[3]) if len(sys.argv) > 3 else 3e5
OUT = "/home/trading2025/trading_bot/agents/panel_ins_%dx%dy.pkl" % (N, YEARS)
CHUNK = 50
MIN_BARS = 400


def universe(n):
    req = urllib.request.Request(
        "https://paper-api.alpaca.markets/v2/assets?status=active&asset_class=us_equity",
        headers={"APCA-API-KEY-ID": config.get("alpaca_api_key"),
                 "APCA-API-SECRET-KEY": config.get("alpaca_secret_key")})
    with urllib.request.urlopen(req, timeout=90) as r:
        assets = json.loads(r.read().decode())
    syms = sorted(a["symbol"] for a in assets
                  if a.get("tradable") and a.get("exchange") in ("NYSE", "NASDAQ")
                  and a.get("symbol", "").isalpha() and len(a.get("symbol", "")) <= 5)
    print("%d handelbare Titel insgesamt" % len(syms), flush=True)
    if len(syms) <= n:
        return syms
    step = len(syms) / float(n)
    return [syms[int(i * step)] for i in range(n)]


def main():
    import yfinance as yf
    syms = universe(N)
    print("Lade %d Titel, %d Jahre, min. $%.0fk Tagesumsatz...\n"
          % (len(syms), YEARS, MINDV / 1000), flush=True)
    out = {}
    for i in range(0, len(syms), CHUNK):
        part = syms[i:i + CHUNK]
        try:
            df = yf.download(part, period="%dy" % YEARS, interval="1d",
                             progress=False, auto_adjust=True, threads=True,
                             group_by="ticker")
        except Exception as e:
            print("  Chunk-Fehler: %s" % str(e)[:50], flush=True)
            continue
        for s in part:
            try:
                sub = df[s].dropna()
                if len(sub) < MIN_BARS:
                    continue
                cl = [float(x) for x in sub["Close"].values]
                vo = [float(x) for x in sub["Volume"].values]
                if min(cl) <= 0:
                    continue
                if st.median([c * v for c, v in zip(cl[-120:], vo[-120:])]) < MINDV:
                    continue
                out[s] = {"dates": [d.strftime("%Y-%m-%d") for d in sub.index],
                          "closes": cl, "volumes": vo}
            except Exception:
                continue
        if (i // CHUNK) % 5 == 0 or i + CHUNK >= len(syms):
            print("  %d/%d -> %d brauchbar" % (min(i + CHUNK, len(syms)),
                                               len(syms), len(out)), flush=True)
        time.sleep(0.3)
    with open(OUT, "wb") as f:
        pickle.dump(out, f)
    print("\nPanel: %d Titel -> %s (%.0f MB)"
          % (len(out), OUT, os.path.getsize(OUT) / 1e6))


main()
