#!/usr/bin/env python3
"""
venue_check.py — A4 aus TODO_NEUDENKEN.md

Prüft für das 20-Coin-Universum des Crypto-Bots, ob Hyperliquid und dYdX
die 0,67-%-Roundtrip-Hürde schlagen (Kostenrechnung 22.08.2026).

Read-only, keine Keys, keine Orders. Nur stdlib + requests.

Gemessen wird je Coin und Venue:
  - gelistet ja/nein (inkl. k-Präfix-Varianten auf Hyperliquid: kPEPE, kSHIB, kBONK)
  - Spread am Top of Book (bp)
  - simulierte Market-Order-Slippage (Orderbuch-Walk) für die Einsatz-Leiter
    100 / 200 / 300 / 500 $ — Kauf- und Verkaufsseite getrennt
  - Roundtrip-Gesamtkosten = 2 x Taker-Gebühr + Kauf-Impact + Verkaufs-Impact
    (Impact enthält den halben Spread bereits, da gegen Mid gerechnet)

Gebühren-Annahmen (Basis-Stufe, im Output ausgewiesen):
  Hyperliquid Taker 0,045 %/Seite  (Maker 0,015 %)
  dYdX        Taker 0,050 %/Seite  (Basis-Stufe; konkrete Stufe im Portfolio ablesen)

Aufruf:  python3 venue_check.py [--csv pfad.csv] [--md pfad.md]
"""
import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone

import requests

HL_API = "https://api.hyperliquid.xyz/info"
DYDX_API = "https://indexer.dydx.trade/v4"

# Universum aus crypto/crypto_bot.py (CRYPTO_MAIN + CRYPTO_MEME), Stand 22.08.2026
COINS_MAIN = ["BTC", "ETH", "SOL", "XRP", "AVAX", "LINK", "LTC",
              "ADA", "DOT", "UNI", "AAVE", "ARB", "POL", "RENDER"]
COINS_MEME = ["DOGE", "SHIB", "PEPE", "WIF", "BONK", "TRUMP"]
COINS = COINS_MAIN + COINS_MEME

LADDER = [100, 200, 300, 500]          # $ Notional je Seite
FEE_TAKER = {"hyperliquid": 0.045, "dydx": 0.050}   # % je Seite, Basis-Stufe
HURDLE_BP = 67.0                        # Break-even aus der 22.08.-Rechnung
KRAKEN_REF_BP = 62.0                    # Ist-Zustand als Referenz

TIMEOUT = 15
SLEEP = 0.25                            # Rate-Limit-Höflichkeit


def hl_universe():
    r = requests.post(HL_API, json={"type": "meta"}, timeout=TIMEOUT)
    r.raise_for_status()
    return {a["name"]: a for a in r.json()["universe"]}


def hl_book(coin):
    r = requests.post(HL_API, json={"type": "l2Book", "coin": coin}, timeout=TIMEOUT)
    r.raise_for_status()
    lv = r.json()["levels"]
    bids = [(float(x["px"]), float(x["sz"])) for x in lv[0]]
    asks = [(float(x["px"]), float(x["sz"])) for x in lv[1]]
    return bids, asks


def dydx_markets():
    r = requests.get(f"{DYDX_API}/perpetualMarkets", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["markets"]


def dydx_book(ticker):
    r = requests.get(f"{DYDX_API}/orderbooks/perpetualMarket/{ticker}", timeout=TIMEOUT)
    r.raise_for_status()
    j = r.json()
    bids = [(float(x["price"]), float(x["size"])) for x in j["bids"]]
    asks = [(float(x["price"]), float(x["size"])) for x in j["asks"]]
    return bids, asks


def walk(levels, notional):
    """Simulierter Market-Fill über das Buch. Liefert Durchschnittspreis oder None."""
    remaining = notional
    cost_qty = 0.0
    qty = 0.0
    for px, sz in levels:
        take_notional = min(remaining, px * sz)
        take_qty = take_notional / px
        qty += take_qty
        cost_qty += take_notional
        remaining -= take_notional
        if remaining <= 1e-9:
            break
    if remaining > 1e-9 or qty == 0:
        return None
    return cost_qty / qty


def measure(bids, asks):
    """Spread + Impact je Leitersprosse (bp gegen Mid, inkl. halbem Spread)."""
    if not bids or not asks:
        return None
    best_bid, best_ask = bids[0][0], asks[0][0]
    mid = (best_bid + best_ask) / 2
    spread_bp = (best_ask - best_bid) / mid * 1e4
    out = {"mid": mid, "spread_bp": spread_bp, "buy": {}, "sell": {}}
    for n in LADDER:
        fb = walk(asks, n)
        fs = walk(bids, n)
        out["buy"][n] = None if fb is None else (fb - mid) / mid * 1e4
        out["sell"][n] = None if fs is None else (mid - fs) / mid * 1e4
    return out


def fmt(x, nd=1):
    return "—" if x is None else f"{x:.{nd}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="venue_check_ergebnis.csv")
    ap.add_argument("--md", default="venue_check_ergebnis.md")
    args = ap.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[VENUE-CHECK] {ts} — {len(COINS)} Coins, Leiter {LADDER} $")

    hl_uni = hl_universe()
    dy_mkts = dydx_markets()

    rows = []
    for coin in COINS:
        row = {"coin": coin, "meme": coin in COINS_MEME}

        # --- Hyperliquid (k-Präfix für Micro-Preis-Coins) ---
        hl_name = None
        for cand in (coin, "k" + coin):
            if cand in hl_uni:
                hl_name = cand
                break
        row["hl_name"] = hl_name
        row["hl"] = None
        if hl_name:
            try:
                row["hl"] = measure(*hl_book(hl_name))
            except Exception as e:
                print(f"  [WARN] HL {hl_name}: {e}")
            time.sleep(SLEEP)

        # --- dYdX ---
        dy_name = None
        for cand in (f"{coin}-USD", f"k{coin}-USD", f"1000{coin}-USD"):
            if cand in dy_mkts:
                dy_name = cand
                break
        row["dy_name"] = dy_name
        row["dy"] = None
        if dy_name:
            try:
                row["dy"] = measure(*dydx_book(dy_name))
            except Exception as e:
                print(f"  [WARN] dYdX {dy_name}: {e}")
            time.sleep(SLEEP)

        rows.append(row)
        print(f"  {coin:7s} HL={hl_name or '—':8s} dYdX={dy_name or '—'}")

    # ---------- Auswertung ----------
    def roundtrip_bp(m, venue, n):
        if m is None or m["buy"].get(n) is None or m["sell"].get(n) is None:
            return None
        fee = FEE_TAKER[venue] * 100 * 2   # % -> bp, zwei Seiten
        return fee + m["buy"][n] + m["sell"][n]

    # CSV
    with open(args.csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "coin", "meme", "venue", "symbol", "mid", "spread_bp"]
                   + [f"impact_buy_{n}" for n in LADDER]
                   + [f"impact_sell_{n}" for n in LADDER]
                   + [f"roundtrip_bp_{n}" for n in LADDER])
        for r in rows:
            for venue, key in (("hyperliquid", "hl"), ("dydx", "dy")):
                m = r[key]
                if m is None:
                    w.writerow([ts, r["coin"], r["meme"], venue, r[f"{key}_name"] or "", "", ""]
                               + [""] * (3 * len(LADDER)))
                else:
                    w.writerow([ts, r["coin"], r["meme"], venue, r[f"{key}_name"], f"{m['mid']:.8g}",
                                f"{m['spread_bp']:.2f}"]
                               + [fmt(m["buy"][n], 2) for n in LADDER]
                               + [fmt(m["sell"][n], 2) for n in LADDER]
                               + [fmt(roundtrip_bp(m, venue, n), 2) for n in LADDER])

    # Markdown-Bericht
    lines = []
    lines.append("# Venue-Check — Ergebnis (A4)\n")
    lines.append(f"Messzeitpunkt: {ts}. Simulierte Market-Order-Roundtrips (Taker beide Seiten)\n"
                 f"gegen Mid, Orderbuch-Walk, Leiter {'/'.join(str(n) for n in LADDER)} $.\n"
                 f"Gebühren-Annahme Basis-Stufe: Hyperliquid 0,045 %/Seite, dYdX 0,050 %/Seite.\n"
                 f"Referenz: Kraken-Ist ~{KRAKEN_REF_BP:.0f} bp, Break-even-Hürde {HURDLE_BP:.0f} bp.\n")
    for venue, key in (("Hyperliquid", "hl"), ("dYdX", "dy")):
        vkey = "hyperliquid" if key == "hl" else "dydx"
        lines.append(f"\n## {venue}\n")
        lines.append("| Coin | Symbol | Spread bp | RT 100$ | RT 200$ | RT 300$ | RT 500$ | vs. 67 bp |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in rows:
            m = r[key]
            name = r[f"{key}_name"]
            if name is None:
                lines.append(f"| {r['coin']} | **nicht gelistet** | — | — | — | — | — | — |")
                continue
            if m is None:
                lines.append(f"| {r['coin']} | {name} | Fehler | — | — | — | — | — |")
                continue
            rts = [roundtrip_bp(m, vkey, n) for n in LADDER]
            worst = max([x for x in rts if x is not None], default=None)
            verdict = "—" if worst is None else ("✅" if worst < HURDLE_BP else "❌")
            lines.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
                r["coin"], name, fmt(m["spread_bp"]),
                *[fmt(x) for x in rts], verdict))
    lines.append("\n*Hinweis: Punktmessung eines Zeitpunkts — Tiefe schwankt mit der Tageszeit; "
                 "vor einem Go mehrfach zu unterschiedlichen Zeiten messen (der Funding-Logger "
                 "kann das stündlich miterledigen). Impact enthält den halben Spread; "
                 "Funding-/Leihkosten der Haltedauer kommen separat dazu (A2).*\n")
    with open(args.md, "w") as f:
        f.write("\n".join(lines))

    print(f"[VENUE-CHECK] geschrieben: {args.csv}, {args.md}")


if __name__ == "__main__":
    sys.exit(main())
