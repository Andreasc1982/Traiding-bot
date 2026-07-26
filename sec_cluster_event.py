#!/usr/bin/env python3
"""Ereignis-Studie: was passiert NACH einem Insider-Cluster-Kauf?

Der Rangfolgen-Test zeigte Spanne an den Extremen, aber Rang-Korrelation ~0.
Das ist genau das erwartete Muster, wenn nur wenige Titel ueberhaupt ein
Ereignis haben. Hier deshalb die These direkt: Titel, bei denen innerhalb von
90 Tagen mindestens N verschiedene Insider am offenen Markt gekauft haben,
gegen alle anderen Titel am selben Tag (marktbereinigt).

Marktbereinigung ist entscheidend: sonst misst man nur, ob der Markt stieg.

    python3 sec_cluster_event.py [min_kaeufer]
"""
import sys, csv, math, pickle, collections
import statistics as st

BASE = "/home/trading2025/trading_bot"
PANEL = BASE + "/agents/panel_700x8y.pkl"
for _a in sys.argv[1:]:
    if _a.endswith(".pkl"):
        PANEL = _a
INS = BASE + "/sec/insider_daily.csv"
_nums = [a for a in sys.argv[1:] if a.isdigit()]
MINB = int(_nums[0]) if _nums else 3
WINDOW = 90
HORIZONS = [1, 5, 20, 60]
COST = 0.04


def main():
    panel = pickle.load(open(PANEL, "rb"))
    ins = collections.defaultdict(dict)
    for r in csv.DictReader(open(INS, encoding="utf-8")):
        try:
            ins[r["ticker"]][r["filing_date"]] = (int(r["n_kaeufer"]),
                                                  int(r["n_verkaeufer"]))
        except Exception:
            continue

    syms = [s for s in panel if s in ins]
    print("%d Titel mit Insider-Daten | Cluster = >=%d Kaeufer in %d Tagen\n"
          % (len(syms), MINB, WINDOW))

    # Kurse und Cluster-Flags je Titel/Tag
    flags, closes, dates_of = {}, {}, {}
    for s in syms:
        b = panel[s]
        d, cl = b["dates"], b["closes"]
        n = len(d)
        nb = [0] * n
        for i, dt in enumerate(d):
            v = ins[s].get(dt)
            if v:
                nb[i] = v[0]
        pre = [0] * (n + 1)
        for i in range(n):
            pre[i + 1] = pre[i] + nb[i]
        f = [False] * n
        for i in range(WINDOW, n):
            f[i] = (pre[i + 1] - pre[i - WINDOW + 1]) >= MINB
        flags[s], closes[s], dates_of[s] = f, cl, d

    by_date = collections.defaultdict(list)
    for s in syms:
        for i, d in enumerate(dates_of[s]):
            by_date[d].append((s, i))
    dates = sorted(d for d in by_date if len(by_date[d]) >= 30)

    print("%-8s %10s %14s %14s %12s %9s" % ("Horizont", "Ereignisse",
                                            "Cluster-Rendite", "Markt-Rendite",
                                            "Ueberschuss", "t-Wert"))
    for h in HORIZONS:
        ev, excess = 0, []
        for d in dates[::h]:
            rows = by_date[d]
            rs, hit = [], []
            for s, i in rows:
                cl = closes[s]
                if i + h >= len(cl) or cl[i] <= 0:
                    continue
                r = (cl[i + h] / cl[i] - 1) * 100
                rs.append(r)
                if flags[s][i]:
                    hit.append(r)
            if len(rs) < 30 or not hit:
                continue
            mkt = st.mean(rs)
            excess.append(st.mean(hit) - mkt)
            ev += len(hit)
        if len(excess) < 15:
            print("%-8s zu wenige Tage (%d)" % ("+%dT" % h, len(excess)))
            continue
        m, sd = st.mean(excess), st.pstdev(excess)
        t = m / (sd / math.sqrt(len(excess))) if sd else 0
        # Rohwerte zur Einordnung
        print("%-8s %10d %13s %14s %11.4f%% %9.2f"
              % ("+%dT" % h, ev, "-", "-", m, t))
    print("\nUeberschuss = Rendite der Cluster-Titel minus Marktdurchschnitt")
    print("desselben Tages. Handelbar waere ein Ueberschuss klar ueber %.2f%%" % COST)
    print("mit |t| >= 2. Ereignisse zaehlen Titel-Tage, nicht eigenstaendige Faelle.")


main()
