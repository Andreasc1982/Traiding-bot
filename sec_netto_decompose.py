#!/usr/bin/env python3
"""Sitzt der Insider-Effekt auf der Kauf- oder auf der Verkaufsseite?

ins_netto_90 (Kauf-USD minus Verkauf-USD, am Tagesumsatz skaliert) ist die
einzige Kennzahl, die ueber alle Horizonte haelt — die reinen Kauf-Kennzahlen
nicht. Verdacht: die Information steckt im VERKAUF, nicht im Kauf.

Das ist praktisch entscheidend: unsere Bots sind long-only. Ein Edge auf der
Short-Seite waere nur als VETO nutzbar ("kauf das nicht"), nicht als Einstieg.

Zerlegt die Dezil-Spanne in ihre beiden Haelften, jeweils gegen den
Marktdurchschnitt desselben Tages.

    python3 sec_netto_decompose.py [panel.pkl]
"""
import sys, csv, math, pickle, collections
import statistics as st

BASE = "/home/trading2025/trading_bot"
PANEL = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].endswith(".pkl") \
    else BASE + "/agents/panel_ins_2500x8y.pkl"
INS = BASE + "/sec/insider_daily.csv"
W = 90
HORIZONS = [1, 5, 20]


def main():
    panel = pickle.load(open(PANEL, "rb"))
    ins = collections.defaultdict(dict)
    for r in csv.DictReader(open(INS, encoding="utf-8")):
        try:
            ins[r["ticker"]][r["filing_date"]] = (float(r["kauf_usd"]),
                                                  float(r["verkauf_usd"]))
        except Exception:
            continue
    syms = [s for s in panel if s in ins]
    print("%d Titel mit Insider-Daten, Fenster %d Tage\n" % (len(syms), W), flush=True)

    sig, closes, dates_of = {}, {}, {}
    for s in syms:
        b = panel[s]
        d, cl, vo = b["dates"], b["closes"], b["volumes"]
        n = len(d)
        bu = [0.0] * n
        se = [0.0] * n
        for i, dt in enumerate(d):
            v = ins[s].get(dt)
            if v:
                bu[i], se[i] = v

        def pref(a):
            o = [0.0] * (n + 1)
            for i, x in enumerate(a):
                o[i + 1] = o[i] + x
            return o
        pb, ps, pdv = pref(bu), pref(se), pref([cl[i] * vo[i] for i in range(n)])
        v = [None] * n
        for i in range(n):
            if i < max(W, 60):
                continue
            base = (pdv[i + 1] - pdv[i - 59]) / 60.0 or 1.0
            v[i] = ((pb[i + 1] - pb[i - W + 1]) - (ps[i + 1] - ps[i - W + 1])) / base
        sig[s], closes[s], dates_of[s] = v, cl, d

    by_date = collections.defaultdict(list)
    for s in syms:
        for i, d in enumerate(dates_of[s]):
            by_date[d].append((s, i))
    dates = sorted(d for d in by_date if len(by_date[d]) >= 30)

    print("%-8s %8s %16s %16s %14s" % ("Horizont", "Tage", "Top-Dezil vs Markt",
                                       "Flop-Dezil vs Markt", "Spanne"))
    for h in HORIZONS:
        top, bot, spr = [], [], []
        for d in dates[::h]:
            xs, ys = [], []
            for s, i in by_date[d]:
                val = sig[s][i]
                cl = closes[s]
                if val is None or i + h >= len(cl) or cl[i] <= 0:
                    continue
                xs.append(val)
                ys.append((cl[i + h] / cl[i] - 1) * 100)
            if len(xs) < 30 or len(set(xs)) < 5:
                continue
            mkt = st.mean(ys)
            order = sorted(range(len(xs)), key=lambda j: xs[j])
            k = max(len(order) // 10, 3)
            t_ = st.mean([ys[j] for j in order[-k:]]) - mkt
            b_ = st.mean([ys[j] for j in order[:k]]) - mkt
            top.append(t_)
            bot.append(b_)
            spr.append(t_ - b_)
        if len(spr) < 15:
            continue

        def fmt(xs):
            m, sd = st.mean(xs), st.pstdev(xs)
            t = m / (sd / math.sqrt(len(xs))) if sd else 0
            return "%+7.4f%% (t%+5.2f)" % (m, t)
        print("%-8s %8d %16s %16s %14s"
              % ("+%dT" % h, len(spr), fmt(top), fmt(bot), fmt(spr)))
    print("\nTop-Dezil  = staerkste Netto-KAEUFE  -> nutzbar als Einstiegssignal")
    print("Flop-Dezil = staerkste Netto-VERKAEUFE -> nur als Veto nutzbar (long-only)")


main()
