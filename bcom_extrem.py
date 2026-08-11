#!/usr/bin/env python3
"""Nachpruefung der BCOM-These in der fairsten Form.

Der erste Test (oberes Drittel gegen unteres) fand keinen Rebalancing-Effekt.
Aber der Podcast sprach von einem EXTREM: Silber +150%, Indexgewicht von 2%
auf 9,6%. Vielleicht wirkt der Zwang erst, wenn die Abweichung gross ist.

Deshalb hier: (1) nur Rohstoffe mit relativer Vorjahresstaerke ueber einer
Schwelle, (2) der konkrete Silber-Fall Januar 2026 zur Kontrolle der
Podcast-Behauptung (82 -> 75 $).
"""
import warnings
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

ROHSTOFFE = ["CL=F", "BZ=F", "NG=F", "HO=F", "RB=F", "GC=F", "SI=F", "HG=F",
             "ZC=F", "ZS=F", "ZW=F", "ZL=F", "ZM=F", "SB=F", "KC=F", "CT=F",
             "LE=F", "HE=F"]


def lade():
    df = yf.download(ROHSTOFFE, start="2007-01-01", end="2026-08-01",
                     auto_adjust=True, progress=False)["Close"]
    return df.dropna(axis=1, how="all").ffill()


def rel_vorjahr(df, jahr, monat):
    ende = df[(df.index.year == jahr) & (df.index.month == monat)]
    if ende.empty:
        return None
    e = ende.iloc[0]
    vor = df.index[df.index <= ende.index[0] - pd.Timedelta(days=365)]
    if len(vor) == 0:
        return None
    r = e / df.loc[vor[-1]] - 1
    return r - r.mean()


def fenster(df, jahr, monat, a=8, b=14):
    m = df[(df.index.year == jahr) & (df.index.month == monat) &
           (df.index.day >= a) & (df.index.day <= b)]
    if len(m) < 2:
        return None
    return m.iloc[-1] / m.iloc[0] - 1


def extremtest(df, monat, name, schwelle):
    """Nur Rohstoffe ueber der Schwelle — marktneutral gemessen."""
    werte = []
    for jahr in range(2008, 2027):
        rel, fen = rel_vorjahr(df, jahr, monat), fenster(df, jahr, monat)
        if rel is None or fen is None:
            continue
        g = pd.concat([rel.rename("rel"), fen.rename("fen")], axis=1).dropna()
        if len(g) < 8:
            continue
        g["fr"] = g["fen"] - g["fen"].mean()
        sel = g[g["rel"] > schwelle]
        if len(sel):
            werte.append((jahr, len(sel), sel["fr"].mean() * 100))
    if not werte:
        return None
    a = np.array([w[2] for w in werte])
    t = a.mean() / (a.std(ddof=1) / np.sqrt(len(a))) if len(a) > 1 and \
        a.std(ddof=1) else 0
    print("  %-9s Schwelle >%3.0f%%: %+6.2f%%  t=%+.2f  (%d Jahre, "
          "%d Faelle, %d/%d negativ)"
          % (name, schwelle * 100, a.mean(), t, len(a),
             sum(w[1] for w in werte), (a < 0).sum(), len(a)))
    return a.mean(), t


def main():
    df = lade()
    print("Extremtest: nur stark uebergewichtete Rohstoffe\n")
    for s in (0.30, 0.50, 0.80, 1.00):
        print("  --- Schwelle %.0f%% relative Vorjahresstaerke ---" % (s * 100))
        extremtest(df, 1, "Januar", s)
        extremtest(df, 7, "Juli", s)
        print()

    print("=" * 60)
    print("KONTROLLE: der konkrete Silber-Fall Januar 2026 (Podcast: 82->75 $)")
    si = df["SI=F"]
    jan = si[(si.index >= "2026-01-02") & (si.index <= "2026-01-31")]
    for d, v in jan.items():
        print("   %s  %7.2f" % (d.date(), v))
    if len(jan):
        f = jan[(jan.index.day >= 8) & (jan.index.day <= 14)]
        if len(f) >= 2:
            print("\n   Fenster 8.-14.: %.2f -> %.2f = %+.1f%%"
                  % (f.iloc[0], f.iloc[-1], (f.iloc[-1] / f.iloc[0] - 1) * 100))
        print("   Monatshoch %.2f, Monatstief %.2f, Rueckgang %.1f%%"
              % (jan.max(), jan.min(), (jan.min() / jan.max() - 1) * 100))
        v = si[(si.index >= "2025-01-01") & (si.index <= "2026-01-08")]
        if len(v) > 1:
            print("   Silber 12 Monate vor dem Fenster: %+.0f%%"
                  % ((v.iloc[-1] / v.iloc[0] - 1) * 100))


main()
