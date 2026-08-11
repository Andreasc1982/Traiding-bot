#!/usr/bin/env python3
"""Prueft die BCOM-Rebalancing-These aus "Nacktes Geld" #60.

BEHAUPTUNG (Podcast, Jan 2026): Rohstofffonds folgen dem Bloomberg Commodity
Index mit festen Zielgewichten. Steigt ein Rohstoff stark, waechst sein
Indexgewicht ueber das Ziel (Silber: 2% -> 9,6%). Im jaehrlichen
Rebalancing-Fenster (im Podcast: 8.-14. Januar) muessen die Fonds
zurueckgewichten, also das Uebergewicht VERKAUFEN. Beobachtung im Podcast:
Silber fiel in 48 h von 82 auf 75 $.

PRUEFBARE FORM: Rohstoffe, die im Vorjahr relativ zum Rohstoffkorb stark
gestiegen sind (= uebergewichtet), sollten im Januar-Fenster relativ
schwaecher laufen als der Korb.

Das ist ein QUERSCHNITTS-Test: nicht "faellt Silber", sondern "faellt der
relativ Staerkste relativ zum Rest". Damit faellt der allgemeine Marktverlauf
heraus — dieselbe Logik wie beim Insider-Test.

Gegenprobe: dasselbe Fenster in Monaten OHNE Rebalancing. Findet sich der
Effekt auch dort, ist es kein Rebalancing-Effekt, sondern schlichte
Mean-Reversion.
"""
import sys, json, warnings
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# BCOM-Bestandteile, soweit als liquider Future bei yfinance verfuegbar.
# Aluminium/Zink/Nickel (LME) fehlen dort — deren Gewicht ist zusammen ~12%,
# das Ergebnis ist also auf die ~85% abgedeckten Rohstoffe zu lesen.
ROHSTOFFE = {
    "CL=F": "WTI-Rohoel", "BZ=F": "Brent", "NG=F": "Erdgas",
    "HO=F": "Heizoel", "RB=F": "Benzin",
    "GC=F": "Gold", "SI=F": "Silber", "HG=F": "Kupfer",
    "ZC=F": "Mais", "ZS=F": "Sojabohnen", "ZW=F": "Weizen",
    "ZL=F": "Sojaoel", "ZM=F": "Sojamehl",
    "SB=F": "Zucker", "KC=F": "Kaffee", "CT=F": "Baumwolle",
    "LE=F": "Lebendrind", "HE=F": "Magerschwein",
}

START, ENDE = "2007-01-01", "2026-08-01"
FENSTER = (8, 14)          # Tage im Januar, wie im Podcast genannt


def lade():
    df = yf.download(list(ROHSTOFFE), start=START, end=ENDE,
                     auto_adjust=True, progress=False)["Close"]
    df = df.dropna(axis=1, how="all").ffill()
    print("%d Rohstoffe, %s bis %s, %d Handelstage"
          % (df.shape[1], df.index[0].date(), df.index[-1].date(), len(df)))
    return df


def fenster_rendite(df, jahr, monat, tag_von, tag_bis):
    """Rendite je Rohstoff im Fenster [tag_von, tag_bis] des Monats."""
    m = df[(df.index.year == jahr) & (df.index.month == monat) &
           (df.index.day >= tag_von) & (df.index.day <= tag_bis)]
    if len(m) < 2:
        return None
    return m.iloc[-1] / m.iloc[0] - 1


def vorjahr_relativ(df, jahr, monat):
    """Relative Performance der 12 Monate VOR dem Fenster (= Uebergewicht)."""
    ende = df[(df.index.year == jahr) & (df.index.month == monat)]
    if ende.empty:
        return None
    e = ende.iloc[0]
    start_idx = df.index[df.index <= ende.index[0] - pd.Timedelta(days=365)]
    if len(start_idx) == 0:
        return None
    s = df.loc[start_idx[-1]]
    r = e / s - 1
    return r - r.mean()          # relativ zum Korb


def test(df, monat, tag_von, tag_bis, titel):
    """Querschnitt: obere vs. untere Haelfte nach Vorjahres-Relativstaerke."""
    zeilen, spreads = [], []
    for jahr in range(2008, 2027):
        rel = vorjahr_relativ(df, jahr, monat)
        fen = fenster_rendite(df, jahr, monat, tag_von, tag_bis)
        if rel is None or fen is None:
            continue
        gem = pd.concat([rel.rename("rel"), fen.rename("fen")], axis=1).dropna()
        if len(gem) < 8:
            continue
        gem["fen_rel"] = gem["fen"] - gem["fen"].mean()   # marktneutral
        n = len(gem) // 3
        oben = gem.nlargest(n, "rel")["fen_rel"].mean()   # uebergewichtet
        unten = gem.nsmallest(n, "rel")["fen_rel"].mean()  # untergewichtet
        spread = oben - unten
        spreads.append(spread)
        zeilen.append((jahr, len(gem), oben * 100, unten * 100, spread * 100))

    if not spreads:
        print("  keine Daten")
        return None
    a = np.array(spreads)
    t = a.mean() / (a.std(ddof=1) / np.sqrt(len(a))) if a.std(ddof=1) else 0
    print("\n=== %s ===" % titel)
    print("  Jahr   n   uebergew.  untergew.   Differenz")
    for j, n, o, u, s in zeilen:
        print("  %d  %2d   %+7.2f%%   %+7.2f%%   %+7.2f%%" % (j, n, o, u, s))
    print("  ---------------------------------------------")
    print("  Mittel      %+7.2f%%   (t=%+.2f, n=%d Jahre, %d/%d negativ)"
          % (a.mean() * 100, t, len(a), (a < 0).sum(), len(a)))
    return a.mean(), t, len(a)


def main():
    df = lade()
    erg = {}
    erg["januar"] = test(df, 1, FENSTER[0], FENSTER[1],
                         "REBALANCING-FENSTER: 8.-14. Januar (These)")
    # Gegenproben: gleiche Fensterlaenge, Monate ohne BCOM-Rebalancing
    for monat, name in [(4, "April"), (7, "Juli"), (10, "Oktober")]:
        erg[name] = test(df, monat, FENSTER[0], FENSTER[1],
                         "GEGENPROBE: 8.-14. %s (kein Rebalancing)" % name)
    print("\n" + "=" * 62)
    print("ZUSAMMENFASSUNG (negativ = Uebergewichtete fallen zurueck)")
    for k, v in erg.items():
        if v:
            print("  %-10s %+6.2f%%  t=%+.2f  (%d Jahre)"
                  % (k, v[0] * 100, v[1], v[2]))


main()
