#!/usr/bin/env python3
"""Holt 1-Minuten-Bars der gehandelten Coins von Alpaca und legt sie als CSV ab.
Grundlage fuer exit_sim.py — die Retro-Simulation der Ausstiegsregeln."""
import os, sys, json, time
import requests
from datetime import datetime, timezone, timedelta

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
from config import config

OUT = os.path.join(BASE, "crypto", "exit_sim_data")
os.makedirs(OUT, exist_ok=True)

SYMS = ["BTC/USD","ETH/USD","SOL/USD","XRP/USD","AVAX/USD","LINK/USD","LTC/USD",
        "ADA/USD","DOT/USD","UNI/USD","AAVE/USD","ARB/USD","POL/USD","RENDER/USD",
        "DOGE/USD","SHIB/USD","PEPE/USD","WIF/USD","BONK/USD","TRUMP/USD"]

TAGE = int(sys.argv[1]) if len(sys.argv) > 1 else 14
TF   = sys.argv[2] if len(sys.argv) > 2 else "1Min"
URL  = "https://data.alpaca.markets/v1beta3/crypto/us/bars"
start = (datetime.now(timezone.utc) - timedelta(days=TAGE)).strftime("%Y-%m-%dT00:00:00Z")

for sym in SYMS:
    ziel = os.path.join(OUT, sym.replace("/", "") + "_" + TF + ".json")
    if os.path.exists(ziel) and os.path.getsize(ziel) > 1000:
        print("%-12s vorhanden" % sym); continue
    bars, token, seiten = [], None, 0
    while True:
        p = {"symbols": sym, "timeframe": TF, "start": start, "limit": 10000}
        if token: p["page_token"] = token
        try:
            r = requests.get(URL, params=p, timeout=30)
            if r.status_code != 200:
                print("%-12s HTTP %s %s" % (sym, r.status_code, r.text[:100])); break
            j = r.json()
            bars += j.get("bars", {}).get(sym, [])
            token = j.get("next_page_token"); seiten += 1
            if not token: break
        except Exception as e:
            print("%-12s Fehler %s" % (sym, str(e)[:80])); break
        time.sleep(0.3)
    if bars:
        with open(ziel + ".tmp", "w") as f: json.dump(bars, f)
        os.replace(ziel + ".tmp", ziel)
    print("%-12s %6d Bars (%d Seiten)  %s → %s" % (
        sym, len(bars), seiten, bars[0]["t"][:16] if bars else "-", bars[-1]["t"][:16] if bars else "-"))
