#!/usr/bin/env python3
"""Robustheitspruefung des SOFR-Gold-Befunds.

Der Rohbefund (Gold +1,6% ueber 20 Tage nach Aufschlag >=5bp, t=3,4) hat zwei
Schwaechen, die ihn wertlos machen koennten:

1. STRESSTAGE CLUSTERN. Liegen fast alle Signale in einer einzigen Phase
   (z.B. Maerz 2020), misst man ein Ereignis, nicht einen Zusammenhang.
2. UEBERLAPPENDE FENSTER. 196 Signaltage mit je 20 Tagen Vorwaertsrendite
   sind keine 196 unabhaengigen Beobachtungen — der t-Wert ist zu gross.

Deshalb hier: Verteilung ueber die Jahre, nicht-ueberlappende Ereignisse,
und Weglassen einzelner Jahre.
"""
import json, warnings
import urllib.request
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
UA = "Mozilla/5.0"
API = "https://markets.newyorkfed.org/api/rates"
SCHWELLE = 5
TAGE = 20


def reihe(pfad):
    u = ("%s/%s/search.json?startDate=2018-04-01&endDate=2026-08-01"
         % (API, pfad))
    d = json.loads(urllib.request.urlopen(
        urllib.request.Request(u, headers={"User-Agent": UA}),
        timeout=120).read())
    return pd.Series({pd.Timestamp(x["effectiveDate"]): x["percentRate"]
                      for x in d["refRates"]
                      if x.get("percentRate") is not None}).sort_index()


def main():
    spread = ((reihe("secured/sofr") - reihe("unsecured/effr")) * 100).dropna()
    gld = yf.download("GLD", start="2018-04-01", end="2026-08-01",
                      auto_adjust=True, progress=False)["Close"]
    if isinstance(gld, pd.DataFrame):
        gld = gld.iloc[:, 0]
    vr = (gld.shift(-TAGE) / gld - 1).dropna()

    sig = spread[spread >= SCHWELLE].index
    print("Signaltage (Aufschlag >= %d bp): %d\n" % (SCHWELLE, len(sig)))

    print("1) VERTEILUNG UEBER DIE JAHRE — clustert alles in einer Phase?")
    j = pd.Series(1, index=sig).groupby(sig.year).sum()
    for jahr, n in j.items():
        tref = vr.index.intersection(sig[sig.year == jahr])
        m = vr.loc[tref].mean() * 100 if len(tref) else float("nan")
        print("   %d: %3d Signaltage   Gold danach %+6.2f%%" % (jahr, n, m))

    print("\n2) NICHT-UEBERLAPPENDE EREIGNISSE (min. %d Tage Abstand)" % TAGE)
    ereignisse, letzter = [], None
    for d in sig:
        if letzter is None or (d - letzter).days > TAGE * 1.5:
            ereignisse.append(d)
            letzter = d
    tref = vr.index.intersection(pd.DatetimeIndex(ereignisse))
    a = vr.loc[tref]
    b = vr.loc[vr.index.difference(sig)]
    diff = a.mean() - b.mean()
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    print("   %d unabhaengige Ereignisse statt %d Signaltage"
          % (len(a), len(sig)))
    print("   Gold danach %+.2f%% vs sonst %+.2f%% = %+.2f%% (t=%+.2f)"
          % (a.mean() * 100, b.mean() * 100, diff * 100,
             diff / se if se else 0))
    print("   davon positiv: %d von %d" % ((a > 0).sum(), len(a)))

    print("\n3) EINZELNE JAHRE WEGLASSEN (haelt es ohne das staerkste Jahr?)")
    for weg in sorted(set(sig.year)):
        s2 = sig[sig.year != weg]
        tref = vr.index.intersection(s2)
        if len(tref) < 20:
            continue
        a2 = vr.loc[tref]
        b2 = vr.loc[vr.index.difference(s2)]
        d2 = a2.mean() - b2.mean()
        se2 = np.sqrt(a2.var(ddof=1) / len(a2) + b2.var(ddof=1) / len(b2))
        print("   ohne %d: %+.2f%%  (t=%+.2f, n=%d)"
              % (weg, d2 * 100, d2 / se2 if se2 else 0, len(a2)))


main()
