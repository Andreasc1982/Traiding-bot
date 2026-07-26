#!/usr/bin/env python3
"""Schreibt die Sektor-Scores des Super-Bots als Zeitreihe mit — read-only.

Zweck: die nie gestellte Frage beantwortbar machen, ob unsere Sentiment-Schicht
den Sektor-ETFs VORLAEUFT oder nur mitlaeuft (siehe Middle-East-Befund:
Meldungsdichte war koinzident, nicht vorlaufend). Ohne Zeitreihe ist das nicht
pruefbar — dashboard.json haelt nur den Momentanwert.

Greift NICHT in den Handel ein. Cron: stuendlich.

    python3 super_score_log.py [--dry]
"""
import os, sys, csv, json, urllib.request
from datetime import datetime

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
try:
    from config import config
except Exception:
    config = {}

DASH = os.path.join(BASE, "dashboard.json")
OUT = os.path.join(BASE, "agents", "score_history.csv")
DRY = "--dry" in sys.argv

# Sektor -> ETF (identisch zur Zuordnung in super_bot.py)
SECTOR_ETF = {"energy": "XLE", "oil": "XOP", "industry": "XLI", "steel": "SLX",
              "defense": "ITA", "finance": "XLF", "tech": "XLK", "gold": "GLD",
              "infra": "PAVE", "crypto": "IBIT"}
COLS = ["time", "sector", "symbol", "score", "price", "fear_greed", "put_call",
        "held", "running"]


def latest_prices(symbols):
    key, sec = config.get("alpaca_api_key"), config.get("alpaca_secret_key")
    if not key or not sec:
        return {}
    url = ("https://data.alpaca.markets/v2/stocks/trades/latest?symbols="
           + ",".join(symbols) + "&feed=iex")
    try:
        req = urllib.request.Request(url, headers={
            "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
        with urllib.request.urlopen(req, timeout=12) as r:
            d = json.loads(r.read().decode())
        return {s: v.get("p") for s, v in (d.get("trades") or {}).items()}
    except Exception as e:
        print("[PREIS] Abruf fehlgeschlagen:", str(e)[:70])
        return {}


def main():
    try:
        dash = json.load(open(DASH))
    except Exception as e:
        print("dashboard.json nicht lesbar:", str(e)[:70])
        return
    scores = dash.get("scores") or {}
    if not scores:
        print("Keine Scores im Dashboard — Bot evtl. noch im ersten Zyklus.")
        return
    held = set((dash.get("positions") or {}).keys())
    fg = (dash.get("fear_greed") or {}).get("value", "")
    pc = dash.get("put_call", "")
    if isinstance(pc, dict):
        pc = pc.get("value", "")
    running = dash.get("running", "")

    # Sektoren aus dem Dashboard, ETF-Zuordnung mit Fallback (falls Universum waechst)
    syms = [SECTOR_ETF.get(s, s.upper()) for s in scores]
    prices = latest_prices(sorted(set(syms)))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    for sector, score in scores.items():
        sym = SECTOR_ETF.get(sector, sector.upper())
        rows.append([now, sector, sym, score, prices.get(sym, ""),
                     fg, pc, int(sym in held), running])

    if DRY:
        for r in rows:
            print(r)
        print("(dry — nichts geschrieben)")
        return

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    exists = os.path.exists(OUT)
    with open(OUT, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(COLS)
        w.writerows(rows)
    print("%s — %d Sektoren geloggt (%d mit Preis)"
          % (now, len(rows), sum(1 for r in rows if r[4] != "")))


main()
