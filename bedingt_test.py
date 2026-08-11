#!/usr/bin/env python3
"""Nachtest beider Thesen in der Fassung, die der SPRECHER genannt hat.

Die ersten Tests pruefen, was ICH aus den Aussagen gemacht hatte. Beim
Nachlesen der Passagen nennt der Sprecher aber praezisere Bedingungen:

BCOM (#60): "man nimmt den Preis VORHER nach unten ... dann kommen die Fonds
und verkaufen" — der Druck entsteht durch Antizipation der Haendler, also
VOR dem Rebalancing-Fenster. Zusatzbedingung: "wenn der Preis immer noch so
hoch ist". Und ausdruecklich: "no free lunch, wenn du dich zu frueh short
positionierst, kann jemand wie die USA oder China dir alles wegkaufen".
-> Test: Vorlauf-Fenster (15.12.-07.01.) statt 08.-14.01.

SOFR (#51): der Sprecher liest den Aufschlag als Zeichen fuer BANKENSTRESS
(Eurodollar-Knappheit, Schattenbanken, Private-Credit-Abschreibungen) — nicht
als Signal fuer Gold oder Aktien.
-> Test: gegen Bankaktien (KRE Regionalbanken, KBE Banken, XLF Finanzsektor)
   statt gegen Gold/SPY.
"""
import json, warnings
import urllib.request
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
UA = "Mozilla/5.0"
API = "https://markets.newyorkfed.org/api/rates"

ROHSTOFFE = ["CL=F", "BZ=F", "NG=F", "HO=F", "RB=F", "GC=F", "SI=F", "HG=F",
             "ZC=F", "ZS=F", "ZW=F", "ZL=F", "ZM=F", "SB=F", "KC=F", "CT=F",
             "LE=F", "HE=F"]


def reihe(pfad):
    u = ("%s/%s/search.json?startDate=2018-04-01&endDate=2026-08-01"
         % (API, pfad))
    d = json.loads(urllib.request.urlopen(
        urllib.request.Request(u, headers={"User-Agent": UA}),
        timeout=120).read())
    return pd.Series({pd.Timestamp(x["effectiveDate"]): x["percentRate"]
                      for x in d["refRates"]
                      if x.get("percentRate") is not None}).sort_index()


def teil1_bcom():
    print("=" * 68)
    print("BCOM in der Fassung des Sprechers: Druck VOR dem Fenster")
    print("=" * 68)
    df = yf.download(ROHSTOFFE, start="2007-01-01", end="2026-08-01",
                     auto_adjust=True, progress=False)["Close"]
    df = df.dropna(axis=1, how="all").ffill()

    def rel(jahr):
        e = df[(df.index.year == jahr) & (df.index.month == 1)]
        if e.empty:
            return None
        vor = df.index[df.index <= e.index[0] - pd.Timedelta(days=365)]
        if len(vor) == 0:
            return None
        r = e.iloc[0] / df.loc[vor[-1]] - 1
        return r - r.mean()

    def fenster(jahr, von, bis):
        m = df[(df.index >= von % jahr) & (df.index <= bis % jahr)]
        if len(m) < 2:
            return None
        return m.iloc[-1] / m.iloc[0] - 1

    varianten = [
        ("Vorlauf 15.12.-07.01. (These des Sprechers)",
         "%d-12-15", "%d-01-07", True),
        ("Fenster 08.-14.01. (mein erster Test)", "%d-01-08", "%d-01-14", False),
        ("Danach 15.-31.01.", "%d-01-15", "%d-01-31", False),
    ]
    for name, von, bis, vorjahr in varianten:
        werte = []
        for jahr in range(2008, 2027):
            r = rel(jahr)
            if r is None:
                continue
            v = von % (jahr - 1) if vorjahr else von % jahr
            b = bis % jahr
            m = df[(df.index >= v) & (df.index <= b)]
            if len(m) < 2:
                continue
            f = m.iloc[-1] / m.iloc[0] - 1
            g = pd.concat([r.rename("r"), f.rename("f")], axis=1).dropna()
            if len(g) < 8:
                continue
            g["fr"] = g["f"] - g["f"].mean()
            n = len(g) // 3
            werte.append(g.nlargest(n, "r")["fr"].mean() -
                         g.nsmallest(n, "r")["fr"].mean())
        if not werte:
            continue
        a = np.array(werte) * 100
        t = a.mean() / (a.std(ddof=1) / np.sqrt(len(a))) if a.std(ddof=1) else 0
        print("  %-44s %+6.2f%%  t=%+.2f  (%d Jahre, %d/%d negativ)"
              % (name, a.mean(), t, len(a), (a < 0).sum(), len(a)))
    print("  (negativ = Uebergewichtete fallen zurueck, wie behauptet)")


def teil2_sofr():
    print("\n" + "=" * 68)
    print("SOFR in der Fassung des Sprechers: Zeichen fuer BANKENstress")
    print("=" * 68)
    spread = ((reihe("secured/sofr") - reihe("unsecured/effr")) * 100).dropna()
    k = yf.download(["KRE", "KBE", "XLF", "SPY"], start="2018-04-01",
                    end="2026-08-01", auto_adjust=True,
                    progress=False)["Close"].ffill()

    sig = spread[spread >= 5].index
    # unabhaengige Ereignisse, sonst blaeht Ueberlappung den t-Wert auf
    ereig, letzter = [], None
    for d in sig:
        if letzter is None or (d - letzter).days > 30:
            ereig.append(d)
            letzter = d
    ei = pd.DatetimeIndex(ereig)
    print("  %d Signaltage -> %d unabhaengige Ereignisse\n" % (len(sig), len(ei)))
    print("  Titel  Horizont   nach Stress    sonst     Differenz")
    for sym in ("KRE", "KBE", "XLF", "SPY"):
        if sym not in k:
            continue
        s = k[sym].dropna()
        for tage in (20, 60):
            vr = (s.shift(-tage) / s - 1).dropna()
            tref = vr.index.intersection(ei)
            if len(tref) < 5:
                continue
            a = vr.loc[tref]
            b = vr.loc[vr.index.difference(sig)]
            d = a.mean() - b.mean()
            se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
            print("  %-5s  %2d Tage   %+7.2f%%   %+7.2f%%   %+7.2f%%  "
                  "(t=%+.2f, n=%d, %d negativ)"
                  % (sym, tage, a.mean() * 100, b.mean() * 100, d * 100,
                     d / se if se else 0, len(a), (a < 0).sum()))


teil1_bcom()
teil2_sofr()
