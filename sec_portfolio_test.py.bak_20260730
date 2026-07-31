#!/usr/bin/env python3
"""Portfolio-Backtest des Insider-Signals ins_netto_90 — mit echten Kosten.

Statt Dezil-Spannen: ein tatsaechlich handelbares Portfolio. Alle REBAL Tage
werden die N Titel mit dem hoechsten Netto-Insiderkauf (skaliert am Tagesumsatz)
gleichgewichtet gehalten. Kosten fallen auf den UMSCHLAG an, nicht pauschal.

Die entscheidende Groesse ist die **Break-Even-Kostenschwelle**: bis zu welchen
Roundtrip-Kosten schlaegt die Strategie ihre Vergleichsbasis? Denn 4 Basispunkte
gelten fuer liquide ETFs — bei kleinen Werten ist der Spread ein Vielfaches.

Vergleichsbasis ist bewusst das gleichgewichtete Universum (nicht der S&P),
damit nur die AUSWAHL gemessen wird und nicht der Marktverlauf.

    python3 sec_portfolio_test.py [panel.pkl] [anzahl_positionen] [rebal_tage]
"""
import sys, csv, math, pickle, collections
import statistics as st

BASE = "/home/trading2025/trading_bot"
PANEL = BASE + "/agents/panel_ins_2500x8y.pkl"
for a in sys.argv[1:]:
    if a.endswith(".pkl"):
        PANEL = a
_n = [int(a) for a in sys.argv[1:] if a.isdigit()]
NPOS = _n[0] if _n else 20
REBAL = _n[1] if len(_n) > 1 else 20
INS = BASE + "/sec/insider_daily.csv"
W = 90
COSTS_BPS = [4, 20, 50, 100, 200]      # Roundtrip in Basispunkten
LIQ_TIERS = [("alle", 0), ("ab $1M/Tag", 1e6), ("ab $5M/Tag", 5e6)]


def kennzahlen(equity, per_period):
    if len(equity) < 3:
        return None
    total = equity[-1] / equity[0] - 1
    years = len(per_period) * REBAL / 252.0
    cagr = (equity[-1] / equity[0]) ** (1 / years) - 1 if years > 0 else 0
    sd = st.pstdev(per_period) if len(per_period) > 2 else 0
    ann_sd = sd * math.sqrt(252.0 / REBAL)
    sharpe = (cagr / ann_sd) if ann_sd else 0
    peak, mdd = equity[0], 0.0
    for e in equity:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1)
    return {"total": total * 100, "cagr": cagr * 100, "vol": ann_sd * 100,
            "sharpe": sharpe, "mdd": mdd * 100}


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
    print("Universum: %d Titel mit Insider-Daten | %d Positionen | "
          "Umschichtung alle %d Handelstage\n" % (len(syms), NPOS, REBAL), flush=True)

    sig, closes, dates_of, adv = {}, {}, {}, {}
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
        pb, ps = pref(bu), pref(se)
        dv = [cl[i] * vo[i] for i in range(n)]
        pdv = pref(dv)
        v = [None] * n
        av = [None] * n
        for i in range(n):
            if i < max(W, 60):
                continue
            base = (pdv[i + 1] - pdv[i - 59]) / 60.0
            av[i] = base
            if base <= 0:
                continue
            v[i] = ((pb[i + 1] - pb[i - W + 1]) - (ps[i + 1] - ps[i - W + 1])) / base
        sig[s], closes[s], dates_of[s], adv[s] = v, cl, d, av

    idx = collections.defaultdict(dict)
    for s in syms:
        for i, d in enumerate(dates_of[s]):
            idx[d][s] = i
    dates = sorted(d for d in idx if len(idx[d]) >= 50)
    rebal_dates = dates[::REBAL]
    print("Zeitraum %s .. %s | %d Umschichtungen\n"
          % (dates[0], dates[-1], len(rebal_dates) - 1), flush=True)

    for tier_name, min_adv in LIQ_TIERS:
        # Perioden-Renditen von Strategie und Vergleichsbasis + Umschlag
        strat_r, bench_r, turns, sizes, pdates = [], [], [], [], []
        prev = set()
        for p in range(len(rebal_dates) - 1):
            d0, d1 = rebal_dates[p], rebal_dates[p + 1]
            cand = []
            allr = []
            for s, i in idx[d0].items():
                j = idx[d1].get(s)
                v = sig[s][i]
                a = adv[s][i]
                if j is None or v is None or a is None or a < min_adv:
                    continue
                c0, c1 = closes[s][i], closes[s][j]
                if c0 <= 0 or c1 <= 0:
                    continue
                r = c1 / c0 - 1
                allr.append(r)
                cand.append((v, s, r))
            if len(cand) < NPOS * 3:
                continue
            cand.sort(reverse=True)
            picks = cand[:NPOS]
            held = set(s for _, s, _ in picks)
            strat_r.append(st.mean([r for _, _, r in picks]))
            bench_r.append(st.mean(allr))
            turns.append(len(held - prev) / float(NPOS) if prev else 1.0)
            sizes.append(len(allr))
            pdates.append(d1)
            prev = held
        if len(strat_r) < 10:
            print("%-12s zu wenige Perioden\n" % tier_name)
            continue

        avg_turn = st.mean(turns)
        b_eq = [1.0]
        for r in bench_r:
            b_eq.append(b_eq[-1] * (1 + r))
        bench = kennzahlen(b_eq, bench_r)
        print("=== Liquiditaet: %s === (im Schnitt %d waehlbare Titel je Periode, "
              "Umschlag %.0f%%)" % (tier_name, st.mean(sizes), avg_turn * 100))
        print("  %-18s %9s %9s %8s %8s %9s" % ("Variante", "Gesamt", "p.a.",
                                               "Vola", "Sharpe", "max DD"))
        print("  %-18s %8.1f%% %8.2f%% %7.1f%% %8.2f %8.1f%%"
              % ("Vergleichsbasis", bench["total"], bench["cagr"], bench["vol"],
                 bench["sharpe"], bench["mdd"]))
        for bps in COSTS_BPS:
            eq = [1.0]
            nets = []
            for r, tu in zip(strat_r, turns):
                net = r - tu * (bps / 10000.0)
                nets.append(net)
                eq.append(eq[-1] * (1 + net))
            k = kennzahlen(eq, nets)
            diff = k["cagr"] - bench["cagr"]
            mark = "  <<<" if diff > 0 else ""
            print("  %-18s %8.1f%% %8.2f%% %7.1f%% %8.2f %8.1f%%   (%+.2f%% p.a.)%s"
                  % ("Strategie @%dbp" % bps, k["total"], k["cagr"], k["vol"],
                     k["sharpe"], k["mdd"], diff, mark))
        # Break-Even-Kosten grob bestimmen
        base_diff = st.mean(strat_r) - st.mean(bench_r)
        be_bps = (base_diff / avg_turn) * 10000 if avg_turn > 0 else 0
        exc = [a - b for a, b in zip(strat_r, bench_r)]
        m, sd = st.mean(exc), st.pstdev(exc)
        tv = m / (sd / math.sqrt(len(exc))) if sd else 0.0
        print("  -> Ueberschuss je Periode %+0.3f%% | t=%+0.2f (n=%d) | "
              "Break-Even ca. %.0f bp" % (m * 100, tv, len(exc), be_bps))
        jahr = collections.defaultdict(list)
        for d, e in zip(pdates, exc):
            jahr[d[:4]].append(e * 100)
        js = sorted(jahr)
        print("  -> Ueberschuss je Jahr: " + "  ".join(
            "%s %+.1f%%" % (y, sum(jahr[y])) for y in js))
        pos_j = sum(1 for y in js if sum(jahr[y]) > 0)
        print("     (%d von %d Jahren positiv)\n" % (pos_j, len(js)))
    print("<<< = schlaegt die Vergleichsbasis nach Kosten.")
    print("Vergleichsbasis = gleichgewichtetes Universum, gleich umgeschichtet —")
    print("misst also reine Auswahlguete, nicht den Marktverlauf.")


main()
