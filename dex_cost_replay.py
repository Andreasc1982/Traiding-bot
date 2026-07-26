#!/usr/bin/env python3
"""Sind die DEX-Paper-Verluste kostengetrieben oder strategiegetrieben?

dex_paper rechnet pauschal 5% Slippage je Seite (10% Roundtrip). Die Trades
speichern entry (= Fill INKL. 5% Aufschlag) und exit (= Rohpreis), damit laesst
sich exakt auf andere Slippage-Annahmen umrechnen:

    roher Einstieg = entry / (1 + SLIP_ALT)
    netto(s)       = exit*(1-s) / (roher Einstieg*(1+s)) - 1

Rugs (RUG-TOTAL) haben bewusst keine Exit-Slippage — der Fill ist der Absturz.

    python3 dex_cost_replay.py [v12 v11 ...]
"""
import json, glob, os, sys, math, statistics as st

BASE = "/home/trading2025/trading_bot/dex"
SLIP_OLD = 0.05
SCEN = [("5% (Ist)", 0.05), ("2%", 0.02), ("1%", 0.01), ("0,5%", 0.005), ("0%", 0.0)]
BET = 20.0


def net(entry_fill, exit_px, s, is_rug):
    raw_in = entry_fill / (1 + SLIP_OLD)
    fill_in = raw_in * (1 + s)
    fill_out = exit_px if is_rug else exit_px * (1 - s)
    if fill_in <= 0:
        return None
    return fill_out / fill_in - 1


def main():
    vers = sys.argv[1:] or ["v9", "v10", "v11", "v12"]
    for v in vers:
        path = os.path.join(BASE, "paper_trades_%s.json" % v)
        if not os.path.exists(path):
            print("%-5s (keine Datei)" % v)
            continue
        try:
            trades = json.load(open(path))
        except Exception as e:
            print("%-5s Lesefehler %s" % (v, e))
            continue
        use, skipped = [], 0
        for t in trades:
            e, x = t.get("entry"), t.get("exit")
            if not e or x is None or e <= 0:
                skipped += 1
                continue
            if t.get("scaled") or t.get("realized"):
                skipped += 1          # Scale-Out/Pyramiding -> Notional nicht eindeutig
                continue
            use.append((float(e), float(x), t.get("reason", "") == "RUG-TOTAL"))
        if len(use) < 5:
            print("\n%-5s zu wenig auswertbare Trades (%d, %d uebersprungen)"
                  % (v, len(use), skipped))
            continue
        rugs = sum(1 for _, _, r in use if r)
        print("\n=== %s ===  %d Trades (%d uebersprungen: Scale-Out) | %d Rugs (%.0f%%)"
              % (v, len(use), skipped, rugs, 100 * rugs / len(use)))
        print("  %-10s %10s %10s %9s %8s %9s" % ("Slippage", "Summe $", "Mittel %",
                                                 "Median %", "t-Wert", "Win-Rate"))
        for label, s in SCEN:
            rs = []
            for e, x, isrug in use:
                r = net(e, x, s, isrug)
                if r is not None:
                    rs.append(r * 100)
            if not rs:
                continue
            m, sd = st.mean(rs), st.pstdev(rs)
            t = m / (sd / math.sqrt(len(rs))) if sd else 0
            wins = 100 * sum(1 for r in rs if r > 0) / len(rs)
            print("  %-10s %10.2f %10.2f %9.2f %8.2f %8.1f%%"
                  % (label, sum(rs) / 100 * BET, m, st.median(rs), t, wins))
    print("\nLesart: bleibt die Summe auch bei 0%% Slippage negativ, ist die "
          "Strategie schuld,\nnicht die Ausfuehrung — dann hilft auch Jupiter "
          "mit Limit-Orders nicht.")


main()
