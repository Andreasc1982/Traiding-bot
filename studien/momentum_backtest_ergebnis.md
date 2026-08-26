# Momentum-Backtest — Ergebnis (B1)

Zeitraum: 2007-03-31 bis 2026-08-31 (234 Monate). Regeln siehe Skriptkopf — vorab festgelegt, keine Parameter-Suche. Kosten 5 bp/Seite auf Umschlag (Ø Umschlag 0.53/Monat, Ø Kandidaten 17.5).

| | CAGR | Vola p.a. | max. Rückgang | Sharpe |
|---|---|---|---|---|
| **Momentum Top 5 (netto)** | 10.3 % | 14.6 % | -26.5 % | 0.75 |
| SPY Buy&Hold | 11.1 % | 15.4 % | -50.8 % | 0.76 |
| Universum gleichgewichtet | 8.5 % | 12.5 % | -39.4 % | 0.72 |

Monats-Differenz Strategie − SPY: Ø -7 bp, **t = -0.28** (n = 234).

<details><summary>Jahresrenditen</summary>

| Jahr | Strategie | SPY |
|---|---|---|
| 2007 | +12.0 % | +5.7 % |
| 2008 | -10.0 % | -36.8 % |
| 2009 | +10.1 % | +26.4 % |
| 2010 | +15.7 % | +15.1 % |
| 2011 | -8.6 % | +1.9 % |
| 2012 | +2.3 % | +16.0 % |
| 2013 | +39.3 % | +32.3 % |
| 2014 | +9.0 % | +13.5 % |
| 2015 | -6.9 % | +1.2 % |
| 2016 | +9.9 % | +12.0 % |
| 2017 | +23.1 % | +21.7 % |
| 2018 | -2.7 % | -4.6 % |
| 2019 | +14.3 % | +31.2 % |
| 2020 | +21.3 % | +18.3 % |
| 2021 | +20.5 % | +28.7 % |
| 2022 | +9.6 % | -18.2 % |
| 2023 | -2.5 % | +26.2 % |
| 2024 | +17.4 % | +24.9 % |
| 2025 | +41.5 % | +17.7 % |
| 2026 | +2.0 % | +12.9 % |

</details>

## Ehrliche Einordnung

Backtest, kein Nachweis: Aufnahme in Stufe 2 erst nach 3 Monaten unverzerrtem Vorwärtstest (Portfolio-Architektur-Regel). ETF-Universum vermeidet Survivorship-Bias, deckelt aber die Auflösung — Einzelaktien erst im Vorwärtstest über den Funnel. Spätere ETF-Auflagen (XLRE, XLC, PAVE) steigen erst ab Datenbeginn ein — das ist korrekt, kein Leck. Der Drawdown zeigt, was auszuhalten wäre; der Trendfilter senkt ihn, kostet aber in V-Erholungen Rendite.

---

## NACHTRAG 22.08. — „kein Alpha" war die falsche Messlatte

Einwand der lokalen Session, sachlich richtig: Die Aussage „t = −0,28, kein Alpha"
vergleicht rohe Monatsrenditen und ignoriert, dass die Strategie zeitweise nur
teilweise investiert ist (Ø 0,53 Umschlag, Cash wenn < 5 Kandidaten den Trendfilter
bestehen). Wer SPYs Rückgang auf das Strategieniveau drücken will, muss Aktienquote
abgeben — und verliert dabei Rendite.

**Nachgerechnet auf derselben Datenbasis** (233 Monate, Ziel: max. Rückgang ≤ 26,5 %):

| Vergleich | CAGR | max. Rückgang |
|---|---|---|
| **Momentum Top 5 (netto)** | **10,3 %** | −26,5 % |
| SPY, auf gleichen Rückgang gemischt (Cash zu 0 %) | 5,1 % (44,5 % SPY) | −26,3 % |
| SPY, auf gleichen Rückgang gemischt (Cash = T-Bills/BIL) | 6,1 % (46,5 % SPY) | −26,4 % |
| SPY voll investiert | 11,1 % | −50,8 % |

Die lokale Schätzung (52 % SPY → 5,8 %) lag in der Richtung richtig und im Betrag
etwas zu günstig für SPY — real sind nur 44–47 % SPY tragbar, weil sich Rückgänge
nicht linear mit der Quote skalieren. **Der Abstand ist also größer als dort
angenommen: 10,3 % gegen 5,1–6,1 % bei gleichem Schmerz.**

**Ehrliche Gegenrede zur Gegenrede** — beides gehört ins Urteil:
- Auf **Volatilität** normiert ist es ein Gleichstand (Sharpe 0,75 vs. 0,76). Nur auf
  **maximalen Rückgang** normiert dominiert die Strategie klar.
- Der maximale Rückgang ist eine Einzelbeobachtung aus genau einem Pfad (2008/09) und
  damit die unsicherste aller Kennzahlen — Sharpe ist statistisch belastbarer.
- Beide Größen stammen aus demselben Rückblick; ein Vorwärtstest ersetzt das nicht.

**Fazit, präziser als vorher:** Nicht „kein Alpha", sondern **„kein Renditevorsprung,
aber ein erheblicher Vorsprung je Einheit Rückgang".** Für ein Depot, dessen Besitzer
den Rückgang aussitzen muss, ist das die relevantere Größe — und damit ein besseres
Argument für den Umbau, als der Backtest zunächst hergab.
