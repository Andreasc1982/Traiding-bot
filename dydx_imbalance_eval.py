#!/usr/bin/env python3
"""Sagt Orderbuch-Imbalance die naechsten Minuten voraus — oder nicht?

Liest dydx/imbalance_log.csv und misst je Markt die Vorwaertsrendite des
Mid-Preises nach +1/+5/+15 Minuten, aufgeteilt nach Imbalance-Bucket.
Wenn stark positive Imbalance NICHT ueberdurchschnittlich steigt, ist das
Signal wertlos — das soll dieser Test zeigen koennen.

    python3 dydx_imbalance_eval.py [imb5|imb1|imb10]
"""
import sys, csv, collections, statistics as st
from datetime import datetime, timedelta

LOG = "/home/trading2025/trading_bot/dydx/imbalance_log.csv"
HORIZONS = [1, 5, 15]        # Minuten
FIELD = sys.argv[1] if len(sys.argv) > 1 else "imb5"


def load():
    per = collections.defaultdict(list)
    for r in csv.DictReader(open(LOG, encoding="utf-8")):
        try:
            t = datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S")
            per[r["market"]].append((t, float(r["mid"]), float(r[FIELD]),
                                     float(r["spread_bps"])))
        except Exception:
            continue
    for m in per:
        per[m].sort()
    return per


def fwd(series, i, minutes):
    """Mid-Rendite nach 'minutes' — naechster Punkt >= Zielzeit, max 2x Toleranz."""
    t0, p0 = series[i][0], series[i][1]
    target = t0 + timedelta(minutes=minutes)
    limit = t0 + timedelta(minutes=minutes * 2)
    for j in range(i + 1, len(series)):
        if series[j][0] >= target:
            if series[j][0] > limit:
                return None
            return (series[j][1] / p0 - 1) * 10000       # in Basispunkten
    return None


def main():
    per = load()
    if not per:
        print("Keine Daten in %s" % LOG)
        return
    total = sum(len(v) for v in per.values())
    t0 = min(v[0][0] for v in per.values())
    t1 = max(v[-1][0] for v in per.values())
    print("%d Messpunkte | %s .. %s (%.1f h) | Feld: %s\n" % (
        total, t0.strftime("%m-%d %H:%M"), t1.strftime("%m-%d %H:%M"),
        (t1 - t0).total_seconds() / 3600, FIELD))

    for m, s in sorted(per.items()):
        imbs = [x[2] for x in s]
        spr = [x[3] for x in s]
        if len(s) < 20:
            print("%-10s zu wenig Daten (%d)\n" % (m, len(s)))
            continue
        lo = st.quantiles(imbs, n=5)[0]      # unterstes Quintil
        hi = st.quantiles(imbs, n=5)[3]      # oberstes Quintil
        print("=== %s ===  n=%d | Imbalance Median %+0.3f | Spread Median %.2f bp"
              % (m, len(s), st.median(imbs), st.median(spr)))
        print("  %-10s %10s %12s %12s %12s" % ("Horizont", "Gruppe", "n",
                                               "Mittel bp", "positiv %"))
        for h in HORIZONS:
            groups = {"Imb hoch": [], "Imb niedrig": [], "alle": []}
            for i in range(len(s)):
                r = fwd(s, i, h)
                if r is None:
                    continue
                groups["alle"].append(r)
                if s[i][2] >= hi:
                    groups["Imb hoch"].append(r)
                elif s[i][2] <= lo:
                    groups["Imb niedrig"].append(r)
            for g in ("alle", "Imb hoch", "Imb niedrig"):
                xs = groups[g]
                if not xs:
                    continue
                print("  %-10s %10s %12d %12.3f %11.1f%%" % (
                    "+%dmin" % h, g, len(xs), sum(xs) / len(xs),
                    100 * sum(1 for x in xs if x > 0) / len(xs)))
            hi_m = groups["Imb hoch"]
            lo_m = groups["Imb niedrig"]
            if hi_m and lo_m:
                edge = sum(hi_m) / len(hi_m) - sum(lo_m) / len(lo_m)
                print("  %-10s Spanne hoch-minus-niedrig: %+0.3f bp  "
                      "(Kosten Taker-Roundtrip: 10 bp)" % ("", edge))
        print()


main()
