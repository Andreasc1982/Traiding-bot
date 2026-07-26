#!/usr/bin/env python3
"""Laeuft unser Sektor-Score den ETFs voraus — oder nur mit?

Liest agents/score_history.csv und misst je Sektor die Vorwaertsrendite des
zugehoerigen ETF nach +1h / +4h / +1 Tag, aufgeteilt nach Score-Hoehe.
Gegenprobe zum Middle-East-Befund, nur nach innen gerichtet.

Massstab: Der Super-Bot kostet nur 4 bp Roundtrip — eine Spanne zwischen hohem
und niedrigem Score von deutlich ueber 0,04% waere also bereits handelbar.

    python3 super_score_eval.py
"""
import csv, os, math, collections, statistics as st
from datetime import datetime, timedelta

LOG = "/home/trading2025/trading_bot/agents/score_history.csv"
HORIZONS = [(1, "+1h"), (4, "+4h"), (24, "+1 Tag")]
COST_PCT = 0.04


def load():
    per = collections.defaultdict(list)
    if not os.path.exists(LOG):
        return per
    for r in csv.DictReader(open(LOG, encoding="utf-8")):
        try:
            if not r["price"]:
                continue
            t = datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S")
            per[r["sector"]].append((t, float(r["score"]), float(r["price"]),
                                     r["symbol"]))
        except Exception:
            continue
    for s in per:
        per[s].sort()
    return per


def fwd(series, i, hours):
    t0, p0 = series[i][0], series[i][2]
    target = t0 + timedelta(hours=hours)
    limit = t0 + timedelta(hours=hours * 2 + 12)
    for j in range(i + 1, len(series)):
        if series[j][0] >= target:
            if series[j][0] > limit:
                return None
            return (series[j][2] / p0 - 1) * 100
    return None


def corr(a, b):
    if len(a) < 5:
        return 0.0
    ma, mb = st.mean(a), st.mean(b)
    n = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return n / (da * db) if da and db else 0.0


def cross_section(per):
    """Der eigentliche Test: je Zeitpunkt Sektoren nach Score sortieren und
    Bestes-minus-Schlechtestes messen. Rechnet den Marktfaktor heraus (der bei
    den 10 ETFs ~28% der Schwankung ausmacht und den gepoolten Test erschlaegt)
    und testet genau das, was der Bot entscheidet: WELCHER Sektor."""
    stamps = collections.defaultdict(dict)
    for sector, s in per.items():
        for idx, (t, score, price, sym) in enumerate(s):
            stamps[t][sector] = (score, idx)
    print("=== Querschnitts-Test (Top-Score minus Flop-Score) ===")
    print("  %-8s %8s %12s %10s %10s" % ("Horizont", "n", "Spanne/Trade",
                                         "t-Wert", "positiv"))
    for h, label in HORIZONS:
        diffs = []
        for t, secs in sorted(stamps.items()):
            if len(secs) < 4:
                continue
            order = sorted(secs.items(), key=lambda x: x[1][0])
            (lo_sec, (_, lo_i)) = order[0]
            (hi_sec, (_, hi_i)) = order[-1]
            rh = fwd(per[hi_sec], hi_i, h)
            rl = fwd(per[lo_sec], lo_i, h)
            if rh is None or rl is None:
                continue
            diffs.append(rh - rl)
        if len(diffs) < 8:
            print("  %-8s zu wenig Zeitpunkte (%d)" % (label, len(diffs)))
            continue
        m, sd = st.mean(diffs), st.pstdev(diffs)
        tv = m / (sd / math.sqrt(len(diffs))) if sd else 0.0
        print("  %-8s %8d %11.3f%% %10.2f %9.1f%%"
              % (label, len(diffs), m, tv,
                 100 * sum(1 for d in diffs if d > 0) / len(diffs)))
    print("  Handelbar waere eine Spanne klar ueber %.2f%% (Kosten) mit |t| >= 2.\n"
          % COST_PCT)


def main():
    per = load()
    if not per:
        print("Noch keine Daten in %s — der Cron laeuft stuendlich." % LOG)
        return
    n_tot = sum(len(v) for v in per.values())
    t0 = min(v[0][0] for v in per.values())
    t1 = max(v[-1][0] for v in per.values())
    days = (t1 - t0).total_seconds() / 86400
    print("%d Messpunkte | %s .. %s (%.1f Tage) | Kostenschwelle %.2f%%\n"
          % (n_tot, t0.strftime("%d.%m %H:%M"), t1.strftime("%d.%m %H:%M"),
             days, COST_PCT))
    if days < 3:
        print("WARNUNG: unter 3 Tagen Daten ist jede Aussage wertlos.\n")

    all_pairs = {h: ([], []) for h, _ in HORIZONS}
    for sector, s in sorted(per.items()):
        if len(s) < 12:
            print("%-10s zu wenig Punkte (%d)" % (sector, len(s)))
            continue
        sym = s[0][3]
        print("=== %s (%s) === n=%d" % (sector, sym, len(s)))
        print("  %-8s %8s %10s %11s %11s %10s" % ("Horizont", "n", "Korr.",
                                                  "Score hoch", "Score tief", "Spanne"))
        for h, label in HORIZONS:
            xs, ys = [], []
            for i in range(len(s)):
                r = fwd(s, i, h)
                if r is None:
                    continue
                xs.append(s[i][1])
                ys.append(r)
            if len(xs) < 8:
                continue
            all_pairs[h][0].extend(xs)
            all_pairs[h][1].extend(ys)
            order = sorted(zip(xs, ys))
            k = max(len(order) // 3, 2)
            lo = st.mean([y for _, y in order[:k]])
            hi = st.mean([y for _, y in order[-k:]])
            print("  %-8s %8d %10.3f %10.3f%% %10.3f%% %9.3f%%"
                  % (label, len(xs), corr(xs, ys), hi, lo, hi - lo))
        print()

    cross_section(per)

    print("=== Alle Sektoren zusammen (gepoolt — schwacher Test) ===")
    print("  %-8s %8s %10s %12s" % ("Horizont", "n", "Korr.", "Bewertung"))
    for h, label in HORIZONS:
        xs, ys = all_pairs[h]
        if len(xs) < 20:
            continue
        c = corr(xs, ys)
        floor = 2 / math.sqrt(len(xs))
        verdict = ("ueber Rauschgrenze" if abs(c) > floor else "im Rauschen")
        print("  %-8s %8d %10.3f  %s (Grenze %.3f)" % (label, len(xs), c, verdict, floor))
    print("\nKorr. > 0 = hoher Score geht steigenden Kursen VORAUS (handelbar).")
    print("Korr. ~ 0 = der Score laeuft nur mit — dieselbe Diagnose wie beim")
    print("Middle East Spectator, dann traegt die Sentiment-Schicht nichts bei.")


main()
