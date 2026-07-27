#!/usr/bin/env python3
"""Welche Aufteilung fuer das Fundament? Kandidaten historisch vergleichen.

Kein Erraten von Gewichten. Getestet werden mehrere Mischungen ueber die
laengste gemeinsame Historie, mit monatlicher Rueckfuehrung auf die Zielgewichte
und Handelskosten auf den Umschlag.

Bezug zu den Messungen dieses Projekts:
 - Lange Anleihen (TLT) hatten −48,4 % Rueckgang, schlechter als Aktien.
   Deshalb steht ueberall SHY (kurze Laufzeit) als defensiver Teil daneben.
 - Vier echte Anlageklassen streuen besser (3,0 von 4 unabhaengig) als
   zehn Aktiensektoren (2,1 von 10).

    python3 fundament_mix.py
"""
import math
import statistics as st
import warnings
warnings.filterwarnings("ignore")

KOSTEN_BP = 5           # Roundtrip auf den umgeschichteten Anteil
MISCHUNGEN = {
    "100 % Aktien":            {"SPY": 1.00},
    "60/40 klassisch (lang)":  {"SPY": 0.60, "TLT": 0.40},
    "60/40 kurz":              {"SPY": 0.60, "SHY": 0.40},
    "4 Klassen gleich":        {"SPY": 0.25, "SHY": 0.25, "GLD": 0.25, "DBC": 0.25},
    "Wachstum":                {"SPY": 0.50, "SHY": 0.20, "GLD": 0.15, "DBC": 0.15},
    "Ausgewogen":              {"SPY": 0.40, "SHY": 0.30, "GLD": 0.20, "DBC": 0.10},
    "Defensiv":                {"SPY": 0.30, "SHY": 0.45, "GLD": 0.15, "DBC": 0.10},
    "Wachstum + 5 % BTC":      {"SPY": 0.47, "SHY": 0.20, "GLD": 0.14, "DBC": 0.14,
                                "BTC-USD": 0.05},
}


def kurse(syms, jahre=18):
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
        for idx, v in ser.items():
            v = float(v)
            if math.isfinite(v) and v > 0:
                d[idx.strftime("%Y-%m-%d")] = v
        if len(d) > 250:
            out[s] = d
    return out


def lauf(kurse_d, gew, kosten_bp):
    syms = list(gew)
    tage = None
    for s in syms:
        if s not in kurse_d:
            return None
        k = set(kurse_d[s])
        tage = k if tage is None else (tage & k)
    tage = sorted(tage)
    if len(tage) < 500:
        return None

    anteile = {s: gew[s] for s in syms}          # Wert je Klasse, Summe = 1
    equity = [1.0]
    monat = tage[0][:7]
    tagesrend = []
    for i in range(1, len(tage)):
        d0, d1 = tage[i - 1], tage[i]
        alt = sum(anteile.values())
        for s in syms:
            anteile[s] *= kurse_d[s][d1] / kurse_d[s][d0]
        neu = sum(anteile.values())
        tagesrend.append(neu / alt - 1)
        if d1[:7] != monat:                      # monatliche Rueckfuehrung
            monat = d1[:7]
            umschlag = sum(abs(anteile[s] - gew[s] * neu) for s in syms) / 2.0
            neu -= umschlag * (kosten_bp / 10000.0)
            for s in syms:
                anteile[s] = gew[s] * neu
        equity.append(neu)

    jahre = len(tage) / 252.0
    cagr = equity[-1] ** (1 / jahre) - 1
    vol = st.pstdev(tagesrend) * math.sqrt(252)
    peak, mdd = equity[0], 0.0
    for e in equity:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1)
    # Kalenderjahre
    jahres = {}
    for i, d in enumerate(tage):
        jahres.setdefault(d[:4], []).append(equity[i])
    jr = {j: v[-1] / v[0] - 1 for j, v in jahres.items() if len(v) > 100}
    return {"cagr": cagr * 100, "vol": vol * 100, "mdd": mdd * 100,
            "sharpe": cagr / vol if vol else 0, "von": tage[0], "bis": tage[-1],
            "jahre": jahre and jr, "n": len(tage)}


def main():
    alle = set()
    for g in MISCHUNGEN.values():
        alle |= set(g)
    k = kurse(alle)
    print("Kursdaten fuer %d von %d Symbolen | Kosten %d bp auf den Umschlag\n"
          % (len(k), len(alle), KOSTEN_BP))
    print("%-24s %8s %8s %9s %8s %11s %11s" % (
        "Mischung", "p.a.", "Vola", "max DD", "Sharpe", "schlecht.J", "Zeitraum"))
    erg = {}
    for name, gew in MISCHUNGEN.items():
        r = lauf(k, gew, KOSTEN_BP)
        if not r:
            print("%-24s (keine gemeinsame Historie)" % name)
            continue
        erg[name] = r
        wj = min(r["jahre"].items(), key=lambda x: x[1]) if r["jahre"] else ("-", 0)
        print("%-24s %7.2f%% %7.1f%% %8.1f%% %8.2f %6s %+5.1f%% %s..%s"
              % (name, r["cagr"], r["vol"], r["mdd"], r["sharpe"],
                 wj[0], wj[1] * 100, r["von"][:7], r["bis"][:7]))

    print("\n=== Jahresrenditen der engeren Auswahl ===")
    for name in ("100 % Aktien", "Wachstum", "Ausgewogen", "Defensiv"):
        if name not in erg:
            continue
        js = sorted(erg[name]["jahre"])
        print("%-14s " % name[:14] + "  ".join(
            "%s %+.0f%%" % (j[2:], erg[name]["jahre"][j] * 100) for j in js[-9:]))
    print("\nLesart: 'max DD' ist der groesste zwischenzeitliche Rueckgang — das ist")
    print("die Zahl, die man aushalten muss, nicht die Durchschnittsrendite.")


main()
