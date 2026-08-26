#!/usr/bin/env python3
"""Belastbarkeit der Exit-Varianten: paarweise Differenz je Trade gegen die
heutige Regel, Bootstrap-Bandbreite, Aufteilung nach Zeitraum und Symbol.
12 Tage sind wenig — diese Auswertung sagt, wie viel davon Rauschen ist."""
import sys, random, statistics as st
sys.path.insert(0, "/home/trading2025/trading_bot/crypto")
from exit_sim import (lade_entries, lade_bars, lade_stunden, stunden_bars,
                      psar_serie, atr_serie, simuliere, filter_fehlpreise, VARIANTEN, KOSTEN)

random.seed(42)
entries = lade_entries()
cache = {}
for e in entries:
    s = e["sym"]
    if s not in cache:
        b = lade_bars(s)
        h = lade_stunden(s) or (stunden_bars(b) if b else None)
        cache[s] = (b, psar_serie(h), atr_serie(h)) if b else None
entries = filter_fehlpreise([e for e in entries if cache.get(e["sym"])], cache)

def lauf(v):
    return [simuliere(e, *cache[e["sym"]], v) for e in entries]

basis = lauf({"modus": "intra"})

def bootstrap(diffs, n=5000):
    s = []
    for _ in range(n):
        p = [random.choice(diffs) for _ in diffs]
        s.append(sum(p) / len(p))
    s.sort()
    return s[int(n * 0.05)], s[int(n * 0.95)]

print("Trades: %d   Vergleich jeweils gegen V0 (heutige Regel)\n" % len(entries))
print("%-28s %8s %8s %9s %9s %s" % ("Variante", "Δ$ ges", "Δ%/Trade", "5%-Band", "95%-Band", "besser/schlechter/gleich"))
for name, v in VARIANTEN:
    if v.get("halten") or name.startswith("V0"): continue
    res = lauf(v)
    diffs, dollar = [], 0.0
    b = g = s_ = 0
    for e, r0, r1 in zip(entries, basis, res):
        if not (r0 and r1): continue
        d = r1[0] - r0[0]
        diffs.append(d); dollar += d / 100 * e["einsatz"]
        if abs(d) < 0.01: g += 1
        elif d > 0: b += 1
        else: s_ += 1
    lo, hi = bootstrap(diffs)
    print("%-28s %8.0f %8.2f %9.2f %9.2f   %d / %d / %d" % (
        name, dollar, sum(diffs) / len(diffs), lo, hi, b, s_, g))

print("\n── V6 gegen V0, aufgeteilt ──")
res6 = lauf(dict(VARIANTEN[6][1]))
paare = [(e, r0[0], r6[0]) for e, r0, r6 in zip(entries, basis, res6) if r0 and r6]
haelfte = paare[len(paare)//2][0]["zeit"]
for label, sel in (("14.–20.08.", [p for p in paare if p[0]["zeit"] < haelfte]),
                   ("20.–25.08.", [p for p in paare if p[0]["zeit"] >= haelfte])):
    d = sum((p[2] - p[1]) / 100 * p[0]["einsatz"] for p in sel)
    print("%-12s n=%3d   Δ$ %6.0f   Δ%%/Trade %5.2f" % (
        label, len(sel), d, sum(p[2] - p[1] for p in sel) / len(sel)))

print("\nnach Symbol (Δ$ V6−V0):")
sym = {}
for p in paare:
    s = p[0]["sym"]; sym[s] = sym.get(s, 0) + (p[2] - p[1]) / 100 * p[0]["einsatz"]
for s, d in sorted(sym.items(), key=lambda x: -abs(x[1])):
    print("   %-10s %6.0f" % (s, d))

d_all = sorted((p[2] - p[1]) / 100 * p[0]["einsatz"] for p in paare)
print("\ngrösste Einzelbeiträge V6−V0: %s" % ", ".join("%.0f$" % x for x in d_all[-5:]))
print("ohne die 3 grössten:  Δ$ %.0f von %.0f" % (sum(d_all[:-3]), sum(d_all)))
