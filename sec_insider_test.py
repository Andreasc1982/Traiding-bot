#!/usr/bin/env python3
"""Haben Insider-Kaeufe (SEC Form 4) Querschnitts-Vorhersagekraft?

Verbindet sec/insider_daily.csv mit dem gecachten Kurs-Panel und testet mit
derselben Maschinerie wie super_signal_screen.py: je Handelstag alle Titel nach
Insider-Kennzahl sortieren, oberes gegen unteres Dezil, ueberlappungsfrei.

Kein Lookahead: es zaehlt das FILING-Datum, und am Tag t gehen nur Meldungen
mit filing_date <= t ein.

Kennzahlen (jeweils rollierend ueber das Fenster):
  ins_kaeufer_N   Anzahl Kauf-Meldungen (Cluster-Staerke)
  ins_netto_N     (Kauf-USD - Verkauf-USD), skaliert am Tagesumsatz
  ins_kauf_N      nur Kauf-USD, skaliert am Tagesumsatz
  ins_saldo_N     Kaeufer minus Verkaeufer (reine Koepfe)

    python3 sec_insider_test.py [panel.pkl] [fenster_tage]
"""
import sys, os, csv, math, pickle, collections
import statistics as st

BASE = "/home/trading2025/trading_bot"
PANEL = sys.argv[1] if len(sys.argv) > 1 else BASE + "/agents/panel_700x8y.pkl"
WINDOWS = [30, 90]
HORIZONS = [1, 5, 20]
INS = BASE + "/sec/insider_daily.csv"
COST_PCT = 0.04


def load_insider():
    per = collections.defaultdict(dict)      # ticker -> datum -> [nB, kaufUSD, nS, verkUSD]
    if not os.path.exists(INS):
        print("Fehlt: %s" % INS)
        return per
    for r in csv.DictReader(open(INS, encoding="utf-8")):
        try:
            per[r["ticker"]][r["filing_date"]] = [
                int(r["n_kaeufer"]), float(r["kauf_usd"]),
                int(r["n_verkaeufer"]), float(r["verkauf_usd"])]
        except Exception:
            continue
    return per


def spearman(a, b):
    def rk(x):
        o = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        for p, i in enumerate(o):
            r[i] = p
        return r
    ra, rb = rk(a), rk(b)
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return num / (da * db) if da and db else 0.0


def main():
    with open(PANEL, "rb") as f:
        panel = pickle.load(f)
    ins = load_insider()
    if not ins:
        return
    hit = [s for s in panel if s in ins]
    print("Panel %d Titel | Insider-Daten fuer %d davon | %d Ticker in SEC-Datei\n"
          % (len(panel), len(hit), len(ins)), flush=True)
    if len(hit) < 30:
        print("Zu wenig Ueberschneidung.")
        return

    sigs, closes, dates_of = {}, {}, {}
    for s in hit:
        bars = panel[s]
        dates, cl, vo = bars["dates"], bars["closes"], bars["volumes"]
        n = len(dates)
        dv = [cl[i] * vo[i] for i in range(n)]
        rec = ins[s]
        # tagesgenaue Reihen der Meldungen, auf Handelstage projiziert
        nb = [0] * n
        bu = [0.0] * n
        ns = [0] * n
        se = [0.0] * n
        for i, d in enumerate(dates):
            v = rec.get(d)
            if v:
                nb[i], bu[i], ns[i], se[i] = v[0], v[1], v[2], v[3]
        sg = {}
        for W in WINDOWS:
            kb = [None] * n
            net = [None] * n
            kauf = [None] * n
            saldo = [None] * n
            for i in range(n):
                if i < max(W, 60):
                    continue
                w0 = i - W + 1
                base = st.median(dv[i - 59:i + 1]) or 1.0
                kb[i] = float(sum(nb[w0:i + 1]))
                saldo[i] = float(sum(nb[w0:i + 1]) - sum(ns[w0:i + 1]))
                kauf[i] = sum(bu[w0:i + 1]) / base
                net[i] = (sum(bu[w0:i + 1]) - sum(se[w0:i + 1])) / base
            sg["ins_kaeufer_%d" % W] = kb
            sg["ins_saldo_%d" % W] = saldo
            sg["ins_kauf_%d" % W] = kauf
            sg["ins_netto_%d" % W] = net
        sigs[s] = sg
        closes[s] = cl
        dates_of[s] = dates

    by_date = collections.defaultdict(list)
    for s in sigs:
        for i, d in enumerate(dates_of[s]):
            by_date[d].append((s, i))
    dates = sorted(d for d in by_date if len(by_date[d]) >= 30)
    names = sorted(next(iter(sigs.values())).keys())
    print("%d Titel, %d Handelstage\n" % (len(sigs), len(dates)), flush=True)

    for h in HORIZONS:
        print("=== Horizont +%d Handelstage (ueberlappungsfrei) ===" % h)
        print("%-16s %8s %14s %9s %10s %11s" % ("Signal", "Tage", "Dezil-Spanne",
                                                "t-Wert", "positiv", "Rang-Korr."))
        rows = []
        for name in names:
            spreads, ics = [], []
            for d in dates[::h]:
                xs, ys = [], []
                for s, i in by_date[d]:
                    v = sigs[s][name][i] if i < len(sigs[s][name]) else None
                    cl = closes[s]
                    if v is None or i + h >= len(cl) or cl[i] <= 0:
                        continue
                    xs.append(v)
                    ys.append((cl[i + h] / cl[i] - 1) * 100)
                if len(xs) < 30 or len(set(xs)) < 5:
                    continue
                order = sorted(range(len(xs)), key=lambda j: xs[j])
                k = max(len(order) // 10, 3)
                spreads.append(st.mean([ys[j] for j in order[-k:]])
                               - st.mean([ys[j] for j in order[:k]]))
                ics.append(spearman(xs, ys))
            if len(spreads) < 20:
                print("%-16s zu wenige Tage (%d)" % (name, len(spreads)))
                continue
            m, sd = st.mean(spreads), st.pstdev(spreads)
            t = m / (sd / math.sqrt(len(spreads))) if sd else 0
            rows.append((abs(t), name, len(spreads), m, t,
                         100 * sum(1 for x in spreads if x > 0) / len(spreads),
                         st.mean(ics)))
        for _, name, n, m, t, pos, ic in sorted(rows, reverse=True):
            mark = "  <<<" if abs(t) >= 2 and m > COST_PCT else ""
            print("%-16s %8d %13.4f%% %9.2f %9.1f%% %11.4f%s"
                  % (name, n, m, t, pos, ic, mark))
        print()
    print("<<< = |t| >= 2 UND Spanne ueber der Kostenschwelle (%.2f%%)." % COST_PCT)
    print("Bei 8 Kennzahlen x 3 Horizonten sind ~1,2 Zufallstreffer zu erwarten.")


main()
