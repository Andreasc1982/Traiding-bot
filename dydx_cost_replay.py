#!/usr/bin/env python3
"""Was waeren unsere Clones bei dYdX-Kosten wert gewesen?

Die Clone-Trades wurden mit Kraken-Annahmen simuliert (0,26% Fee + 0,05%
Slippage je Seite = 0,62% Roundtrip). dYdX kostet real 0,05% Taker (bzw. 0,01%
Maker) je Seite plus Spread. Dieses Skript rechnet die BESTEHENDE Historie auf
die neuen Kosten um — ohne neue Daten, ohne Annahme ueber die Strategie.

Rekonstruktion: aus profit (netto, $) und pct (%) laesst sich das Positions-
Notional N zurueckrechnen. Trades zu nah an der Kostenschwelle sind numerisch
instabil und werden verworfen (wird ausgewiesen).

    python3 dydx_cost_replay.py
"""
import json, glob, os, sys, statistics as st, urllib.request

BASE = "/home/trading2025/trading_bot"
FEE_OLD, SLIP_OLD = 0.0026, 0.0005          # crypto_bot sim_fee / sim_slip
COSTS = {                                    # (fee je Seite, slippage je Seite)
    "Kraken (Ist)":      (0.0026, 0.0005),
    "dYdX Taker":        (0.0005, 0.0001),   # 0,05% + ~1bp halber Spread (Majors)
    "dYdX Maker":        (0.0001, 0.0000),   # 0,01%, kein Spread (Limit gefuellt)
    "Gebuehrenfrei":     (0.0000, 0.0000),   # theoretische Obergrenze
}
MIN_DENOM = 0.004        # |Nenner| darunter -> Notional-Rekonstruktion unbrauchbar


def net_factor(p, fee, slip):
    """Netto-Ergebnis je 1$ Notional bei Kursbewegung p (als Bruch)."""
    out = (1 + p) * (1 - slip)
    return (out - 1) - out * fee - fee


def dydx_markets():
    try:
        req = urllib.request.Request("https://indexer.dydx.trade/v4/perpetualMarkets",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return set(json.loads(r.read().decode()).get("markets", {}))
    except Exception as e:
        print("(Marktliste nicht abrufbar: %s)" % str(e)[:50])
        return set()


def main():
    mk = dydx_markets()
    print("=== Welche unserer Coins gibt es auf dYdX? ===")
    files = sorted(glob.glob(os.path.join(BASE, "crypto/clones/*_trades.json")))
    universe = set()
    for f in files:
        try:
            for t in json.load(open(f)):
                universe.add(t.get("symbol", ""))
        except Exception:
            pass
    have, miss = [], []
    for s in sorted(universe):
        (have if s.replace("/USD", "-USD") in mk else miss).append(s)
    print("  vorhanden (%d): %s" % (len(have), ", ".join(have)))
    print("  fehlt     (%d): %s\n" % (len(miss), ", ".join(miss) or "-"))

    print("=== Kosten-Neurechnung je Clone ===")
    for f in files:
        name = os.path.basename(f).replace("_trades.json", "")
        try:
            trades = json.load(open(f))
        except Exception as e:
            print("%s: Lesefehler %s" % (name, e))
            continue
        notionals, usable, skipped, skipped_sym = [], [], 0, 0
        for t in trades:
            sym = t.get("symbol", "")
            if mk and sym.replace("/USD", "-USD") not in mk:
                skipped_sym += 1
                continue
            p = float(t.get("pct", 0)) / 100.0
            profit = float(t.get("profit", 0))
            d = net_factor(p, FEE_OLD, SLIP_OLD)
            if abs(d) < MIN_DENOM:
                skipped += 1
                continue
            n = profit / d
            if not (10 <= n <= 5000):        # unplausible Positionsgroesse
                skipped += 1
                continue
            notionals.append(n)
            usable.append((p, n))
        if not usable:
            print("\n%-14s keine rekonstruierbaren Trades "
                  "(%d verworfen, %d nicht auf dYdX)" % (name, skipped, skipped_sym))
            continue
        print("\n%-14s %d Trades verwertbar | %d verworfen (Kostenschwelle) | "
              "%d nicht auf dYdX" % (name, len(usable), skipped, skipped_sym))
        print("               Notional Median $%.0f (min $%.0f / max $%.0f)"
              % (st.median(notionals), min(notionals), max(notionals)))
        print("               %-16s %12s %10s %10s" % ("Kostenmodell", "Summe $",
                                                       "je Trade", "Win-Rate"))
        for label, (fee, slip) in COSTS.items():
            tot = sum(n * net_factor(p, fee, slip) for p, n in usable)
            wins = sum(1 for p, n in usable if net_factor(p, fee, slip) > 0)
            print("               %-16s %12.2f %10.3f %9.1f%%"
                  % (label, tot, tot / len(usable), 100 * wins / len(usable)))
    print("\nHinweis: identische Strategie, identische Kursbewegungen — nur die "
          "Kosten sind getauscht.\nLiquiditaet/Slippage bei groesseren Orders ist "
          "damit NICHT geprueft.")


main()
