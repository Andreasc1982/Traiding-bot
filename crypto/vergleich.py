#!/usr/bin/env python3
"""Kalibrierung: Sim-Variante V0 (heutige Regel) gegen die real ausgefuehrten Trades."""
import sys, json, datetime as dt
sys.path.insert(0, "/home/trading2025/trading_bot/crypto")
from exit_sim import lade_entries, lade_bars, lade_stunden, stunden_bars, psar_serie, atr_serie, simuliere, filter_fehlpreise, KOSTEN

real = json.load(open("/tmp/crypto_trades.json"))
real = [t for t in real if t["time"] >= "2026-08-13 20:00"]
entries = lade_entries()

cache = {}
paare = []
for e in entries:
    s = e["sym"]
    if s not in cache:
        b = lade_bars(s)
        h = lade_stunden(s) or (stunden_bars(b) if b else None)
        cache[s] = (b, psar_serie(h), atr_serie(h)) if b else None
    if not cache[s]: continue
    # realer Trade: erster Exit desselben Symbols nach dem Einstieg
    lokal = e["zeit"] + dt.timedelta(hours=2)     # trades_history in lokaler Zeit
    kand = [t for t in real if t["symbol"] == s and
            dt.datetime.strptime(t["time"], "%Y-%m-%d %H:%M") >= lokal]
    r = simuliere(e, *cache[s], {"modus": "intra"})
    paare.append((e, r, kand[0] if kand else None))

ok = set(id(e) for e in filter_fehlpreise([p[0] for p in paare], cache))
paare = [p for p in paare if id(p[0]) in ok]
mit = [p for p in paare if p[2]]
print("Einstiege: %d, davon mit realem Gegenstueck: %d\n" % (len(paare), len(mit)))
sim_d  = sum(p[1][0] / 100 * p[0]["einsatz"] for p in mit)
real_d = sum(p[2]["profit"] for p in mit)
print("Sim V0 : $%7.0f   Ø %5.2f %%netto" % (sim_d, sum(p[1][0] for p in mit) / len(mit)))
print("Real   : $%7.0f   Ø %5.2f %%brutto (= %.2f netto)" % (
    real_d, sum(p[2]["pct"] for p in mit) / len(mit),
    sum(p[2]["pct"] for p in mit) / len(mit) - KOSTEN * 100))

def verteilung(name, gr):
    print("%-8s %s" % (name, dict(sorted(gr.items(), key=lambda x: -x[1]))))
g1, g2 = {}, {}
for p in mit:
    g1[p[1][1]] = g1.get(p[1][1], 0) + 1
    r = p[2]["reason"].replace("WS-", "")
    g2[r] = g2.get(r, 0) + 1
verteilung("Sim V0", g1); verteilung("Real", g2)

print("\nGrösste Abweichungen (Sim netto% − Real netto%):")
diff = sorted(mit, key=lambda p: p[1][0] - (p[2]["pct"] - KOSTEN * 100))
for p in diff[:8] + diff[-8:]:
    e, r, t = p
    print("  %-10s ein %s  Sim %6.2f%% (%-12s %4.1fh)  Real %6.2f%% (%-14s)  Einsatz $%.0f" % (
        e["sym"], e["zeit"].strftime("%d.%m %H:%M"), r[0], r[1], r[2],
        t["pct"] - KOSTEN * 100, t["reason"].replace("WS-", ""), e["einsatz"]))
