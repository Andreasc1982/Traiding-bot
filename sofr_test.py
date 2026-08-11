#!/usr/bin/env python3
"""Prueft die SOFR-These aus "Nacktes Geld" #51.

BEHAUPTUNG: Liegt die Secured Overnight Funding Rate ueber dem Fed-Korridor,
fehlt Liquiditaet im System — der Sprecher (Ex-Treasurer) sah am Tag einer
Zinssenkung 30 Basispunkte Aufschlag bei gleichzeitig 125 Mrd $ Injektion und
las das als Stresssignal.

PRUEFBARE FORM: Als Aufschlag nehmen wir **SOFR minus EFFR** (besichert minus
unbesichert, beide NY Fed). Steigt der besicherte Satz ueber den unbesicherten,
ist Sicherheitenfinanzierung knapp — das ist der uebliche Stressmassstab.

Getestet wird, ob hohe Aufschlaege den Renditen von Aktien/Gold/Bitcoin
VORAUSLAUFEN. Nur dann waere es ein nutzbarer Indikator und nicht bloss eine
Beschreibung des schon Geschehenen.

Wichtig: Quartalsenden verzerren — dort springt der Aufschlag mechanisch
(Bilanzstichtage der Banken). Deshalb wird zusaetzlich ohne die letzten und
ersten drei Tage eines Quartals gerechnet.
"""
import json, warnings
import urllib.request
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
UA = "Mozilla/5.0"
API = "https://markets.newyorkfed.org/api/rates"


def hole_reihe(pfad, name):
    # last/n ist bei grossen n ein 400 — der search-Endpunkt liefert die
    # volle Historie am Stueck.
    url = ("%s/%s/search.json?startDate=2018-04-01&endDate=2026-08-01"
           % (API, pfad))
    r = urllib.request.Request(url, headers={"User-Agent": UA})
    d = json.loads(urllib.request.urlopen(r, timeout=120).read())
    s = pd.Series({pd.Timestamp(x["effectiveDate"]): x["percentRate"]
                   for x in d["refRates"] if x.get("percentRate") is not None})
    s = s.sort_index()
    print("  %-6s %d Werte, %s bis %s"
          % (name, len(s), s.index[0].date(), s.index[-1].date()))
    return s


def vorwaerts(kurse, tage):
    return kurse.shift(-tage) / kurse - 1


def main():
    print("Lade Zinssaetze (NY Fed) ...")
    sofr = hole_reihe("secured/sofr", "SOFR")
    effr = hole_reihe("unsecured/effr", "EFFR")

    spread = ((sofr - effr) * 100).dropna()      # in Basispunkten
    print("\nAufschlag SOFR-EFFR: n=%d, Median %+.1f bp, "
          "90%%-Perzentil %+.1f bp, Maximum %+.1f bp"
          % (len(spread), spread.median(), spread.quantile(0.9), spread.max()))

    # Quartalsend-Effekt zeigen (bekanntes Bilanzstichtags-Muster)
    qe = spread[(spread.index.day >= 28) | (spread.index.day <= 3)]
    rest = spread[~spread.index.isin(qe.index)]
    print("  um Monatswechsel: Median %+.1f bp | sonst: %+.1f bp"
          % (qe.median(), rest.median()))

    print("\nLade Kurse ...")
    kurse = yf.download(["SPY", "GLD", "BTC-USD"], start="2018-04-01",
                        end="2026-08-01", auto_adjust=True,
                        progress=False)["Close"]

    for nur_ruhig in (False, True):
        sp = spread
        if nur_ruhig:
            sp = spread[(spread.index.day > 3) & (spread.index.day < 28)]
            print("\n" + "=" * 66)
            print("OHNE Monatswechsel (Bilanzstichtage herausgerechnet)")
        else:
            print("\n" + "=" * 66)
            print("ALLE Tage")
        print("=" * 66)

        for schwelle in (5, 10, 20):
            hoch = sp[sp >= schwelle].index
            if len(hoch) < 10:
                print("\n  Aufschlag >= %d bp: nur %d Tage — zu wenig"
                      % (schwelle, len(hoch)))
                continue
            print("\n  Aufschlag >= %d bp an %d von %d Tagen (%.1f%%)"
                  % (schwelle, len(hoch), len(sp), 100.0 * len(hoch) / len(sp)))
            print("    Titel    Horizont   nach Signal    sonst      Differenz")
            for sym in ("SPY", "GLD", "BTC-USD"):
                if sym not in kurse:
                    continue
                k = kurse[sym].dropna()
                for tage in (5, 20):
                    vr = vorwaerts(k, tage).dropna()
                    tref = vr.index.intersection(hoch)
                    rest_idx = vr.index.difference(hoch)
                    if len(tref) < 10:
                        continue
                    a, b = vr.loc[tref], vr.loc[rest_idx]
                    diff = a.mean() - b.mean()
                    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
                    t = diff / se if se else 0
                    print("    %-8s %2d Tage   %+7.2f%%   %+7.2f%%   "
                          "%+7.2f%%  (t=%+.2f, n=%d)"
                          % (sym, tage, a.mean() * 100, b.mean() * 100,
                             diff * 100, t, len(tref)))


main()
