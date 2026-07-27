#!/usr/bin/env python3
"""Sind Crypto und Aktien wirklich verschiedene Anlagen — oder dasselbe Risiko?

Die Frage laesst sich messen statt meinen. Geprueft wird:
 1) Korrelation von BTC/ETH zu Aktien (breit und Tech) ueber 8 Jahre
 2) rollierende 1-Jahres-Korrelation — hat sie sich veraendert?
 3) effektiv unabhaengige Einheiten verschiedener Mischungen
    (Sektoren allein vs. echte Anlageklassen vs. mit Crypto)
 4) Volatilitaet und groesster Rueckgang je Anlage

Bezug: die 10 Sektor-ETFs ergaben nur 2,8 unabhaengige Einheiten. Wenn Crypto
mit Aktien hoch korreliert, ist es kein Diversifikator, sondern Aktienrisiko
mit Hebel — und gehoert dann NICHT in den defensiven Kern.

    python3 asset_klassen_check.py
"""
import math
import statistics as st
import warnings
warnings.filterwarnings("ignore")

GRUPPEN = {
    "Aktien breit":  "SPY",
    "Tech":          "XLK",
    "Anleihen lang": "TLT",
    "Anleihen kurz": "SHY",
    "Gold":          "GLD",
    "Rohstoffe":     "DBC",
    "Bitcoin":       "BTC-USD",
    "Ethereum":      "ETH-USD",
}
MISCHUNGEN = {
    "nur 10 Sektor-ETFs": ["XLE", "XOP", "XLI", "SLX", "ITA", "XLF", "XLK",
                           "GLD", "PAVE", "IBIT"],
    "echte Anlageklassen": ["SPY", "TLT", "GLD", "DBC"],
    "Anlageklassen + BTC": ["SPY", "TLT", "GLD", "DBC", "BTC-USD"],
    "Aktien + BTC":        ["SPY", "BTC-USD"],
}


def hole(syms, jahre=8):
    import yfinance as yf
    df = yf.download(sorted(set(syms)), period="%dy" % jahre, interval="1d",
                     progress=False, auto_adjust=True)["Close"]
    out = {}
    for s in sorted(set(syms)):
        try:
            ser = df[s].dropna()
        except Exception:
            continue
        d = {}
        prev = None
        for idx, v in ser.items():
            v = float(v)
            if not math.isfinite(v) or v <= 0:
                continue
            tag = idx.strftime("%Y-%m-%d")
            if prev is not None:
                d[tag] = v / prev - 1
            prev = v
        if len(d) > 200:
            out[s] = d
    return out


def gemeinsam(rets, syms):
    tage = None
    for s in syms:
        if s not in rets:
            return [], {}
        k = set(rets[s])
        tage = k if tage is None else (tage & k)
    tage = sorted(tage or [])
    return tage, {s: [rets[s][t] for t in tage] for s in syms}


def korr(a, b):
    ma, mb = st.mean(a), st.mean(b)
    n = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return n / (da * db) if da and db else 0.0


def keff(k, rbar):
    d = 1 + (k - 1) * rbar
    return k / d if d > 0 else float("inf")


def main():
    alle = set(GRUPPEN.values())
    for v in MISCHUNGEN.values():
        alle |= set(v)
    rets = hole(alle)
    print("Daten fuer %d von %d Symbolen\n" % (len(rets), len(alle)))

    print("=== 1) Korrelation zu Aktien (gemeinsame Handelstage, 8 Jahre) ===")
    print("%-16s %14s %14s %12s %12s" % ("Anlage", "zu SPY", "zu Tech(XLK)",
                                         "Vola p.a.", "max Rueckg."))
    for name, sym in GRUPPEN.items():
        tage, r = gemeinsam(rets, [sym, "SPY", "XLK"])
        if not tage:
            print("%-16s (keine Daten)" % name)
            continue
        cs, ck = korr(r[sym], r["SPY"]), korr(r[sym], r["XLK"])
        vol = st.pstdev(r[sym]) * math.sqrt(252) * 100
        eq, peak, mdd = 1.0, 1.0, 0.0
        for x in r[sym]:
            eq *= (1 + x)
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
        print("%-16s %13.3f %14.3f %11.1f%% %11.1f%%"
              % (name, cs, ck, vol, mdd * 100))

    print("\n=== 2) Rollierende 1-Jahres-Korrelation BTC zu SPY ===")
    tage, r = gemeinsam(rets, ["BTC-USD", "SPY"])
    if tage:
        W = 252
        punkte = []
        for i in range(W, len(tage), 63):
            c = korr(r["BTC-USD"][i - W:i], r["SPY"][i - W:i])
            punkte.append((tage[i][:7], c))
        for t, c in punkte:
            balken = "#" * max(int(abs(c) * 40), 0)
            print("  %s  %+0.3f  %s" % (t, c, balken))
        erste = st.mean([c for _, c in punkte[:len(punkte) // 3]])
        letzte = st.mean([c for _, c in punkte[-len(punkte) // 3:]])
        print("  frueheres Drittel %+0.3f  ->  letztes Drittel %+0.3f" % (erste, letzte))

    print("\n=== 3) Wie viel Diversifikation bringt welche Mischung? ===")
    print("%-24s %6s %14s %16s" % ("Mischung", "Teile", "mittl. Korr.",
                                   "effektiv unabh."))
    for name, syms in MISCHUNGEN.items():
        tage, r = gemeinsam(rets, syms)
        if not tage or len(syms) < 2:
            print("%-24s (keine gemeinsamen Daten)" % name)
            continue
        ps = [korr(r[syms[i]], r[syms[j]])
              for i in range(len(syms)) for j in range(i + 1, len(syms))]
        rb = st.mean(ps)
        print("%-24s %6d %14.3f %16.1f" % (name, len(syms), rb, keff(len(syms), rb)))

    print("\nLesart: mittlere Korrelation nahe 0 = echte Streuung.")
    print("Korreliert BTC hoch mit Aktien, ist es Aktienrisiko mit Hebel und")
    print("gehoert nicht in den defensiven Kern, sondern ins Risikobudget.")


main()
