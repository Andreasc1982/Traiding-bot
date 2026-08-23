# Event-Studie Quartalsende + Russell (B3)

Daten: SPY/IWM adjustiert, 2005-01-01 bis 2026-08-21, 5442 Handelstage. Fenster vorab festgelegt, nicht optimiert.


## 1. Quartalsende (SPY, Tagesrendite je Offset)

| Offset | Ø Rendite bp | t | n | vs. Normaltag bp |
|---|---|---|---|---|
| T-4 | -2.5 | -0.23 | 87 | -7.0 |
| T-3 | 18.9 | 1.52 | 87 | +14.4 |
| T-2 | -6.6 | -0.60 | 87 | -11.1 |
| T-1 | -4.4 | -0.31 | 87 | -8.9 |
| T+0 | 12.2 | 1.17 | 87 | +7.7 |
| T+1 | 25.3 | 2.03 | 86 | +20.8 |
| T+2 | 5.4 | 0.48 | 86 | +0.9 |
| T+3 | 8.3 | 0.72 | 86 | +3.8 |
| Normaltage | 4.5 | 2.58 | 4749 | — |

## 2. Russell-Rekonstitution (IWM − SPY, kumulierter 5-Tage-Spread)

| Fenster | Ø kum. Spread bp | t | n Jahre |
|---|---|---|---|
| T-4..T0 (vor/inkl. Recon-Freitag) | 63 | 2.48 | 22 |
| T+1..T+5 (danach) | -58 | -1.66 | 22 |
| Referenz: beliebige 5 Tage | -2 | — | — |

<details><summary>Einzeljahre (bp)</summary>

| Jahr | vor | nach |
|---|---|---|
| 2005 | -65 | +236 |
| 2006 | +220 | -137 |
| 2007 | +26 | +42 |
| 2008 | -85 | -357 |
| 2009 | +10 | -87 |
| 2010 | +24 | -197 |
| 2011 | +236 | -39 |
| 2012 | +119 | +141 |
| 2013 | +23 | +139 |
| 2014 | +15 | -94 |
| 2015 | +19 | -107 |
| 2016 | +14 | -54 |
| 2017 | +56 | -53 |
| 2018 | -116 | +128 |
| 2019 | +137 | -149 |
| 2020 | -25 | -65 |
| 2021 | +171 | -298 |
| 2022 | -3 | +17 |
| 2023 | +135 | +117 |
| 2024 | +132 | -231 |
| 2025 | -44 | +104 |
| 2026 | +383 | -334 |

</details>

## Lesehilfe

Handelbar ist ein Effekt erst, wenn |t| ≥ 2 UND der Effekt nach Kosten (~4 bp Roundtrip Alpaca) und in einem Vorwärtstest bestehen bleibt. Alles darunter ist Beobachtung, kein Signal.
