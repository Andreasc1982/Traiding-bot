#!/usr/bin/env python3
"""Prueft die Crack-Spread-These aus "Nacktes Geld" #86.

BEHAUPTUNG (Jul 2026): Die Raffineriemarge liegt bei 60 $ statt historisch
10-17 $, weil Raffineriekapazitaet fehlt. Wer raffiniert, "macht eine
absolute Granate" — Titel MIT Raffinerie profitieren, reine Foerderer nicht.

ZWEI PRUEFBARE TEILE:
1. Stimmt die Zahl? Der 3-2-1-Crack-Spread ist aus Futures berechenbar:
   (2 x Benzin + 1 x Heizoel - 3 x Rohoel) / 3, alles in $/Barrel.
2. Ist er ein SIGNAL? Laufen Raffinerie-Aktien (VLO, MPC, PSX) besser,
   wenn der Spread hoch ist — und zwar DANACH, nicht gleichzeitig?

Teil 2 ist der eigentliche Test: dass eine hohe Marge und gute
Raffineriegewinne zusammenfallen, ist trivial. Nutzbar waere es nur, wenn
der Spread der Aktienrendite vorauslaeuft.
"""
import warnings
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# Umrechnung: RB/HO notieren in $/Gallone, CL in $/Barrel. 42 Gallonen = 1 Barrel.
GAL = 42.0


def main():
    print("Lade Futures und Raffinerie-Aktien ...")
    df = yf.download(["CL=F", "RB=F", "HO=F", "VLO", "MPC", "PSX", "XOM", "SPY"],
                     start="2010-01-01", end="2026-08-01",
                     auto_adjust=True, progress=False)["Close"].ffill()

    crack = (2 * df["RB=F"] * GAL + 1 * df["HO=F"] * GAL - 3 * df["CL=F"]) / 3
    crack = crack.dropna()

    print("\n1) STIMMT DIE ZAHL?  3-2-1-Crack-Spread in $/Barrel")
    print("   Median seit 2010: %5.1f $" % crack.median())
    for j in range(2010, 2027):
        c = crack[crack.index.year == j]
        if len(c):
            print("   %d: Median %5.1f | Hoch %5.1f | Tief %5.1f"
                  % (j, c.median(), c.max(), c.min()))
    jul = crack[(crack.index >= "2026-07-01") & (crack.index <= "2026-07-31")]
    if len(jul):
        print("   -> Juli 2026 (Aussage im Podcast: 60 $): Median %.1f $"
              % jul.median())

    print("\n2) IST ER EIN SIGNAL?  Vorwaertsrendite nach hohem Spread")
    q80 = crack.quantile(0.80)
    hoch = crack[crack >= q80].index
    print("   Schwelle = 80%%-Perzentil = %.1f $, %d von %d Tagen"
          % (q80, len(hoch), len(crack)))
    print("   Titel   Horizont   nach hohem Spread    sonst     Differenz")
    for sym in ("VLO", "MPC", "PSX", "XOM", "SPY"):
        if sym not in df:
            continue
        k = df[sym].dropna()
        for tage in (20, 60):
            vr = (k.shift(-tage) / k - 1).dropna()
            tref = vr.index.intersection(hoch)
            rest = vr.index.difference(hoch)
            if len(tref) < 30:
                continue
            a, b = vr.loc[tref], vr.loc[rest]
            d = a.mean() - b.mean()
            se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
            print("   %-5s   %2d Tage    %+7.2f%%        %+7.2f%%   %+7.2f%%"
                  "  (t=%+.2f, n=%d)"
                  % (sym, tage, a.mean() * 100, b.mean() * 100, d * 100,
                     d / se if se else 0, len(tref)))

    print("\n3) GEGENPROBE: unabhaengige Ereignisse statt ueberlappender Tage")
    for sym in ("VLO", "MPC"):
        if sym not in df:
            continue
        k = df[sym].dropna()
        vr = (k.shift(-60) / k - 1).dropna()
        ereig, letzter = [], None
        for d0 in hoch:
            if letzter is None or (d0 - letzter).days > 90:
                ereig.append(d0)
                letzter = d0
        tref = vr.index.intersection(pd.DatetimeIndex(ereig))
        if len(tref) < 5:
            continue
        a = vr.loc[tref]
        b = vr.loc[vr.index.difference(hoch)]
        d = a.mean() - b.mean()
        se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
        print("   %-5s 60 Tage: %d unabhaengige Ereignisse, %+.2f%% "
              "(t=%+.2f), davon positiv %d/%d"
              % (sym, len(a), d * 100, d / se if se else 0,
                 (a > 0).sum(), len(a)))


main()
