#!/usr/bin/env python3
"""
funding_logger.py — A2 aus TODO_NEUDENKEN.md

Loggt stündlich Funding-Raten (und leichte Liquiditätskennzahlen) für das
20-Coin-Universum — NUR DATEN, KEIN HANDEL. Grundlage für:
  - die Carry-Netto-Rechnung (C2): lohnt Cash-and-Carry nach echten Kosten?
  - die Venue-Entscheidung (C3): was kostet Halten auf einem Perp-DEX wirklich?

Quellen (alle öffentlich, keine Keys):
  - Hyperliquid  metaAndAssetCtxs  → funding/h, Open Interest, Mark, Impact-Preise
  - dYdX v4      perpetualMarkets  → nextFundingRate/h (nur Majors — Alt-Bücher
                                     sind laut Venue-Check vom 22.08. zu dünn)
  - Kraken Fut.  tickers (PF_*)    → fundingRate (relativ = absolut/Mark, /h)

Ausgabe: append nach funding_log.csv (im Skriptverzeichnis), Heartbeat-JSON.
Kein Telegram — bewusst still (reine Datensammlung).

Betrieb (Pi): Cron  7 * * * *  /usr/bin/python3 /home/trading2025/trading_bot/venue/funding_logger.py
Test:          python3 funding_logger.py --test   (ein Zyklus, Ausgabe auf Konsole)
"""
import argparse
import csv
import fcntl
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE, "funding_log.csv")
HEARTBEAT = os.path.join(BASE, "funding_heartbeat.json")
LOCK_PATH = "/tmp/funding_logger.lock"

COINS_MAIN = ["BTC", "ETH", "SOL", "XRP", "AVAX", "LINK", "LTC",
              "ADA", "DOT", "UNI", "AAVE", "ARB", "POL", "RENDER"]
COINS_MEME = ["DOGE", "SHIB", "PEPE", "WIF", "BONK", "TRUMP"]
COINS = COINS_MAIN + COINS_MEME
DYDX_COINS = ["BTC", "ETH", "SOL", "XRP"]   # nur dort ist das Buch brauchbar

TIMEOUT = 15
HOURS_PER_YEAR = 24 * 365


def acquire_singleton():
    """flock wie in health.py — zweite Instanz beendet sich sofort."""
    fh = open(LOCK_PATH, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        return None


def rows_hyperliquid(ts):
    r = requests.post("https://api.hyperliquid.xyz/info",
                      json={"type": "metaAndAssetCtxs"}, timeout=TIMEOUT)
    r.raise_for_status()
    meta, ctxs = r.json()
    out = []
    by_name = {}
    for asset, ctx in zip(meta["universe"], ctxs):
        by_name[asset["name"]] = ctx
    for coin in COINS:
        name = coin if coin in by_name else ("k" + coin if ("k" + coin) in by_name else None)
        if name is None:
            continue
        c = by_name[name]
        try:
            fh_rate = float(c["funding"])           # dezimal je Stunde
            mark = float(c["markPx"])
            oi = float(c.get("openInterest", 0)) * mark
            imp = c.get("impactPxs") or [None, None]
            spread_bp = None
            if imp[0] and imp[1]:
                b, a = float(imp[0]), float(imp[1])
                spread_bp = (a - b) / ((a + b) / 2) * 1e4
            out.append([ts, "hyperliquid", coin, name,
                        f"{fh_rate * 100:.6f}", f"{fh_rate * HOURS_PER_YEAR * 100:.2f}",
                        f"{mark:.8g}", f"{oi:.0f}",
                        "" if spread_bp is None else f"{spread_bp:.2f}"])
        except (KeyError, TypeError, ValueError) as e:
            print(f"[WARN] HL {coin}: {e}")
    return out


def rows_dydx(ts):
    r = requests.get("https://indexer.dydx.trade/v4/perpetualMarkets", timeout=TIMEOUT)
    r.raise_for_status()
    mkts = r.json()["markets"]
    out = []
    for coin in DYDX_COINS:
        m = mkts.get(f"{coin}-USD")
        if not m:
            continue
        try:
            fh_rate = float(m["nextFundingRate"])   # dezimal je Stunde
            mark = float(m["oraclePrice"])
            oi = float(m.get("openInterest", 0)) * mark
            out.append([ts, "dydx", coin, f"{coin}-USD",
                        f"{fh_rate * 100:.6f}", f"{fh_rate * HOURS_PER_YEAR * 100:.2f}",
                        f"{mark:.8g}", f"{oi:.0f}", ""])
        except (KeyError, TypeError, ValueError) as e:
            print(f"[WARN] dYdX {coin}: {e}")
    return out


def rows_kraken(ts):
    r = requests.get("https://futures.kraken.com/derivatives/api/v3/tickers",
                     timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for t in r.json().get("tickers", []):
        sym = t.get("symbol", "")
        if not sym.startswith("PF_") or not sym.endswith("USD"):
            continue
        base = sym[3:-3]
        coin = "BTC" if base == "XBT" else base
        if coin not in COINS:
            continue
        try:
            mark = float(t["markPrice"])
            fr_abs = t.get("fundingRate")           # absolut in Quote je Kontrakt-Einheit/h
            if fr_abs is None or mark == 0:
                continue
            fh_rate = float(fr_abs) / mark          # relativ je Stunde (dokumentierte Umrechnung)
            oi = float(t.get("openInterest", 0)) * mark
            out.append([ts, "kraken_fut", coin, sym,
                        f"{fh_rate * 100:.6f}", f"{fh_rate * HOURS_PER_YEAR * 100:.2f}",
                        f"{mark:.8g}", f"{oi:.0f}", ""])
        except (KeyError, TypeError, ValueError) as e:
            print(f"[WARN] KrakenFut {sym}: {e}")
    return out


HEADER = ["ts_utc", "venue", "coin", "symbol",
          "funding_pct_1h", "funding_apr_pct", "mark_price", "open_interest_usd",
          "impact_spread_bp"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="ein Zyklus, Konsole, kein Heartbeat-Zwang")
    args = ap.parse_args()

    lock = acquire_singleton()
    if lock is None:
        print("[SINGLETON] laeuft bereits — Ende.")
        return 0

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    errors = []
    for fn in (rows_hyperliquid, rows_dydx, rows_kraken):
        try:
            rows += fn(ts)
        except Exception as e:                       # eine Quelle darf ausfallen
            errors.append(f"{fn.__name__}: {type(e).__name__} {e}")
            print(f"[ERR] {fn.__name__}: {e}")

    new_file = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(HEADER)
        w.writerows(rows)

    # Heartbeat bei JEDEM Lauf schreiben (Lehre aus bz_watch: sonst ist ein
    # stiller Ausfall nicht von "keine Daten" unterscheidbar)
    with open(HEARTBEAT, "w") as f:
        json.dump({"last_run": ts, "rows": len(rows), "errors": errors}, f)

    print(f"[FUNDING] {ts}: {len(rows)} Zeilen "
          f"({sum(1 for r in rows if r[1]=='hyperliquid')} HL, "
          f"{sum(1 for r in rows if r[1]=='dydx')} dYdX, "
          f"{sum(1 for r in rows if r[1]=='kraken_fut')} KrakenFut)"
          + (f", Fehler: {errors}" if errors else ""))

    if args.test:
        for r in rows[:8]:
            print("  ", {k: v for k, v in zip(HEADER, r)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
