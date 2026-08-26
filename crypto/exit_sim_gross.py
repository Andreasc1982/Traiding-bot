#!/usr/bin/env python3
"""Grosse Stichprobe fuer die Exit-Varianten.

Die Auswertung auf den 133 echten Einstiegen (12 Tage) war nicht belastbar:
der Vorteil hing an drei Trades und drehte in der zweiten Haelfte. Hier werden
die Einstiege deshalb kuenstlich erzeugt — alle vier Stunden in jedem Coin,
gefiltert auf ein grob bot-aehnliches Umfeld (Kurs ueber der 20-Stunden-Linie,
also Aufwaertstendenz). Die Entry-Qualitaet ist damit eine andere als beim Bot,
aber fuer den Vergleich der AUSSTIEGS-Regeln reicht das: alle Varianten sehen
exakt dieselben Einstiege.

Aufruf:  SIM_DATA_MIN=exit_sim_data45 python3 exit_sim_gross.py [stunden_abstand]
"""
import os, sys, random, statistics
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exit_sim import (lade_bars, lade_stunden, stunden_bars, psar_serie,
                      atr_serie, simuliere, VARIANTEN, KOSTEN, FENSTER_H)

SYMS = ["BTC/USD","ETH/USD","SOL/USD","XRP/USD","AVAX/USD","LINK/USD","LTC/USD",
        "ADA/USD","DOT/USD","UNI/USD","AAVE/USD","ARB/USD","POL/USD","RENDER/USD",
        "DOGE/USD","SHIB/USD","PEPE/USD","WIF/USD","BONK/USD","TRUMP/USD"]
ABSTAND = int(sys.argv[1]) if len(sys.argv) > 1 else 4
EINSATZ = 250.0
random.seed(42)

def sma(hbars, n=20):
    out, w = {}, []
    for b in hbars:
        w.append(b["c"])
        out[b["t"]] = sum(w[-n:]) / min(len(w), n) if len(w) >= n else None
    return out

cache, entries = {}, []
for s in SYMS:
    mb = lade_bars(s)
    hb = lade_stunden(s)
    if not mb or not hb:
        print("%-12s keine Daten" % s); continue
    cache[s] = (mb, psar_serie(hb), atr_serie(hb))
    linie = sma(hb)
    erste, letzte = mb[0]["t"], mb[-1]["t"]
    for i, b in enumerate(hb):
        if b["t"].hour % ABSTAND: continue
        if b["t"] < erste + timedelta(hours=24) or b["t"] > letzte - timedelta(hours=FENSTER_H):
            continue
        l = linie.get(b["t"])
        if not l or b["c"] <= l:      # nur Aufwaertstendenz — der Bot kauft auch nicht in den Abwaertstrend
            continue
        entries.append({"sym": s, "zeit": b["t"], "preis": b["c"],
                        "einsatz": EINSATZ, "spike": False})

print("Einstiege: %d in %d Coins  (%s → %s)" % (
    len(entries), len(cache), min(e["zeit"] for e in entries).strftime("%d.%m"),
    max(e["zeit"] for e in entries).strftime("%d.%m")))
print("Kosten je Runde %.2f %%, Fenster %d h\n" % (KOSTEN * 100, FENSTER_H))

def lauf(v):
    return [simuliere(e, *cache[e["sym"]], v) for e in entries]

basis = lauf({"modus": "intra"})
zeiten = sorted(e["zeit"] for e in entries)
d1, d2 = zeiten[len(zeiten)//3], zeiten[2*len(zeiten)//3]
mitte = d1

def bootstrap(d, n=3000):
    m = []
    for _ in range(n):
        p = [random.choice(d) for _ in range(len(d))]
        m.append(sum(p) / len(p))
    m.sort()
    return m[int(n * .05)], m[int(n * .95)]

b_pct = [r[0] for r in basis if r]
print("Drittel: bis %s | bis %s | danach\n" % (d1.strftime("%d.%m."), d2.strftime("%d.%m.")))
print("%-28s %9s %8s %8s %7s %7s %s" % ("Variante","Summe$","Ø%","Median%","Treffer","Ø Std.","Δ zu V0 (5–95 %)  Drittel 1/2/3"))
print("%-28s %9.0f %8.2f %8.2f %6.0f%% %7.1f" % (
    "V0 heute (Tick/intrabar)", sum(p / 100 * EINSATZ for p in b_pct),
    sum(b_pct)/len(b_pct), statistics.median(b_pct),
    sum(1 for p in b_pct if p > 0)/len(b_pct)*100,
    sum(r[2] for r in basis if r)/len(b_pct)))

for name, v in VARIANTEN:
    if name.startswith("V0"): continue
    if v.get("halten"):
        res = []
        for e in entries:
            mb = cache[e["sym"]][0]
            nach = [b for b in mb if e["zeit"] < b["t"] <= e["zeit"] + timedelta(hours=FENSTER_H)]
            res.append(((nach[-1]["c"]-e["preis"])/e["preis"]*100 - KOSTEN*100, "HALTEN",
                        FENSTER_H, False) if nach else None)
    else:
        res = lauf(v)
    pcts = [r[0] for r in res if r]
    diffs = [r[0]-b[0] for r, b in zip(res, basis) if r and b]
    lo, hi = bootstrap(diffs)
    t = lambda a, b_: [r[0]-bb[0] for e, r, bb in zip(entries, res, basis)
                       if r and bb and a <= e["zeit"] < b_]
    from datetime import datetime as _dt
    h1 = t(_dt.min, d1); h2 = t(d1, d2); h3 = t(d2, _dt.max)
    print("%-28s %9.0f %8.2f %8.2f %6.0f%% %7.1f   %+.2f [%+.2f %+.2f]  %+.2f/%+.2f/%+.2f" % (
        name, sum(p/100*EINSATZ for p in pcts), sum(pcts)/len(pcts), statistics.median(pcts),
        sum(1 for p in pcts if p > 0)/len(pcts)*100,
        sum(r[2] for r in res if r)/len(pcts),
        sum(diffs)/len(diffs), lo, hi,
        sum(h1)/len(h1) if h1 else 0, sum(h2)/len(h2) if h2 else 0, sum(h3)/len(h3) if h3 else 0))
