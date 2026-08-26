# Venue-Check — Ergebnis (A4)

Messzeitpunkt: 2026-08-21 23:06 UTC. Simulierte Market-Order-Roundtrips (Taker beide Seiten)
gegen Mid, Orderbuch-Walk, Leiter 100/200/300/500 $.
Gebühren-Annahme Basis-Stufe: Hyperliquid 0,045 %/Seite, dYdX 0,050 %/Seite.
Referenz: Kraken-Ist ~62 bp, Break-even-Hürde 67 bp.


## Hyperliquid

| Coin | Symbol | Spread bp | RT 100$ | RT 200$ | RT 300$ | RT 500$ | vs. 67 bp |
|---|---|---|---|---|---|---|---|
| BTC | BTC | 0.1 | 9.1 | 9.1 | 9.1 | 9.1 | ✅ |
| ETH | ETH | 0.4 | 9.4 | 9.4 | 9.4 | 9.4 | ✅ |
| SOL | SOL | 0.1 | 9.1 | 9.1 | 9.1 | 9.1 | ✅ |
| XRP | XRP | 1.4 | 10.4 | 10.4 | 10.4 | 10.4 | ✅ |
| AVAX | AVAX | 0.1 | 10.7 | 10.8 | 10.8 | 11.0 | ✅ |
| LINK | LINK | 1.6 | 10.6 | 10.6 | 10.6 | 10.6 | ✅ |
| LTC | LTC | 1.3 | 10.3 | 10.3 | 10.3 | 10.3 | ✅ |
| ADA | ADA | 0.4 | 10.2 | 10.2 | 10.3 | 10.3 | ✅ |
| DOT | DOT | 1.3 | 11.6 | 11.7 | 11.7 | 11.9 | ✅ |
| UNI | UNI | 0.2 | 9.2 | 9.2 | 9.2 | 9.2 | ✅ |
| AAVE | AAVE | 0.8 | 9.8 | 10.2 | 10.4 | 10.5 | ✅ |
| ARB | ARB | 3.0 | 12.0 | 12.0 | 12.0 | 12.0 | ✅ |
| POL | POL | 0.1 | 10.9 | 11.2 | 11.2 | 11.3 | ✅ |
| RENDER | RENDER | 3.3 | 14.0 | 14.8 | 15.0 | 15.6 | ✅ |
| DOGE | DOGE | 0.1 | 9.4 | 9.5 | 9.5 | 9.9 | ✅ |
| SHIB | kSHIB | 1.6 | 11.4 | 11.8 | 12.0 | 12.1 | ✅ |
| PEPE | kPEPE | 2.4 | 11.4 | 12.4 | 12.9 | 14.2 | ✅ |
| WIF | WIF | 4.0 | 14.9 | 16.4 | 17.1 | 17.7 | ✅ |
| BONK | kBONK | 6.4 | 15.4 | 15.4 | 15.4 | 15.4 | ✅ |
| TRUMP | TRUMP | 0.5 | 10.9 | 11.0 | 11.1 | 11.3 | ✅ |

## dYdX

| Coin | Symbol | Spread bp | RT 100$ | RT 200$ | RT 300$ | RT 500$ | vs. 67 bp |
|---|---|---|---|---|---|---|---|
| BTC | BTC-USD | 2.2 | 12.2 | 12.2 | 12.2 | 12.2 | ✅ |
| ETH | ETH-USD | 9.9 | 19.9 | 19.9 | 19.9 | 19.9 | ✅ |
| SOL | SOL-USD | 9.6 | 22.4 | 23.6 | 24.0 | 24.4 | ✅ |
| XRP | XRP-USD | 9.6 | 19.6 | 19.6 | 19.6 | 19.6 | ✅ |
| AVAX | AVAX-USD | 183.5 | 502.4 | 504.3 | 504.9 | 505.4 | ❌ |
| LINK | LINK-USD | 137.1 | 147.1 | 147.1 | 147.1 | 147.1 | ❌ |
| LTC | LTC-USD | 57.7 | 67.7 | 67.7 | 67.7 | 67.7 | ❌ |
| ADA | ADA-USD | 115.9 | 125.9 | 125.9 | 125.9 | 125.9 | ❌ |
| DOT | DOT-USD | 84.3 | 94.3 | 94.3 | 94.3 | 94.3 | ❌ |
| UNI | UNI-USD | 74.8 | 84.8 | 84.8 | 84.8 | 84.8 | ❌ |
| AAVE | AAVE-USD | 173.4 | 183.4 | 183.4 | 183.4 | 183.4 | ❌ |
| ARB | ARB-USD | 208.0 | 245.0 | 246.7 | 247.2 | 247.6 | ❌ |
| POL | POL-USD | 99.9 | 109.9 | 109.9 | 109.9 | 109.9 | ❌ |
| RENDER | RENDER-USD | 91.6 | 101.6 | 101.6 | 101.6 | 101.6 | ❌ |
| DOGE | DOGE-USD | 76.8 | 86.8 | 86.8 | 86.8 | 86.8 | ❌ |
| SHIB | SHIB-USD | 453.2 | 581.8 | 585.7 | 587.0 | 660.8 | ❌ |
| PEPE | PEPE-USD | 262.3 | 293.6 | 347.8 | 366.0 | 380.7 | ❌ |
| WIF | WIF-USD | 67.5 | 77.5 | 77.5 | 77.5 | 77.5 | ❌ |
| BONK | BONK-USD | 70.6 | 80.6 | 80.6 | 80.6 | 80.6 | ❌ |
| TRUMP | TRUMP-USD | 89.4 | 99.4 | 99.4 | 99.4 | 99.4 | ❌ |

*Hinweis: Punktmessung eines Zeitpunkts — Tiefe schwankt mit der Tageszeit; vor einem Go mehrfach zu unterschiedlichen Zeiten messen (der Funding-Logger kann das stündlich miterledigen). Impact enthält den halben Spread; Funding-/Leihkosten der Haltedauer kommen separat dazu (A2).*

---

## NACHTRAG 22.08. — zwei Korrekturen nach dem Abgleich mit der lokalen Session

### 1. Diese Messung ist KEINE unabhängige Bestätigung (Einwand der lokalen Session, berechtigt)

Beide Messungen liefen 26 Minuten auseinander — derselbe Marktmoment, also eine
Wiederholung, keine Bestätigung. Sie weichen bis Faktor 2–2,6 ab (dYdX LINK:
137 bp hier, 356 bp dort). Die lokale 28-Tage-Reihe zeigt, warum: bei BTC liegen
**37 % aller Messungen über dem Doppelten des Medians.**

**Was das für das Urteil bedeutet — quantifiziert, nicht behauptet:** Bei
Hyperliquid sind von den 9–18 bp genau **9 bp feste Gebühr** (2 × 0,045 %); der
schwankende Impact-Anteil ist nur 0–9 bp. Selbst bei **5-fachem** Impact bliebe der
schlechteste Wert (WIF, 8,7 bp Impact) bei 9 + 43,5 = **52,5 bp**, also unter der
Hürde. Die Streuung kippt das Handelskosten-Urteil also nicht — anders als bei
Kraken, wo die Gebühr allein (52 bp) das Problem ist. Trotzdem gilt: erst die
Zeitreihe entscheidet, nicht dieser Punkt.

### 2. Der eigentliche Fehler war meiner: FUNDING FEHLTE IN DER RECHNUNG

Der Venue-Check misst nur Handelskosten. Der Bot ist **long-only**, und ein Long
auf einem Perp **zahlt** Funding, solange es positiv ist. Bei 28 h mittlerer
Haltedauer (Herleitung 22.08.) und den Funding-Raten aus dem eigenen Logger-Lauf
vom selben Abend:

| Coin | Handel bp | Funding % p.a. | Funding bp/28 h | **Gesamt bp** | vs. 67 |
|---|---|---|---|---|---|
| BTC | 9,1 | 10,9 | 3,5 | **12,6** | ok |
| ETH | 9,4 | 10,9 | 3,5 | **12,9** | ok |
| SOL | 9,1 | 42,8 | 13,7 | **22,8** | ok |
| AVAX | 11,0 | 75,1 | 24,0 | **35,1** | ok |
| UNI | 9,2 | 84,9 | 27,1 | **36,4** | ok |
| DOGE | 9,9 | 106,4 | 34,0 | **43,9** | ok |
| LINK | 10,6 | 113,6 | 36,3 | **46,9** | ok |
| PEPE | 14,2 | 105,5 | 33,7 | **48,0** | ok |
| ADA / XRP | 10,3 / 10,4 | 124,3 | 39,7 | **50,0 / 50,1** | ok |
| LTC | 10,3 | 158,3 | 50,6 | **61,0** | grenzwertig |
| **AAVE** | 10,5 | 201,0 | 64,2 | **74,7** | **reißt** |

**Der Befund kehrt die Aussage teilweise um.** Nicht die Gebühr ist der Engpass,
sondern das Funding — und es ist bei genau den Alts am höchsten, in denen der
gemessene Vorteil des Bots sitzt (t = 3,03 für die 17 Nicht-BTC/ETH/SOL-Coins).
Aus „Hyperliquid schlägt die Hürde mit Faktor 4–7" wird „Hyperliquid schlägt sie
bei BTC/ETH/SOL klar, bei den Alts knapp bis gar nicht".

**Konsequenz:** Der Funding-Logger ist damit nicht Vorarbeit für das Carry-Depot,
sondern **die Entscheidungsgrundlage für die Portierung selbst**. Ohne 4 Wochen
Funding-Median je Coin ist kein Go möglich. Zwei Auswege, die die Zeitreihe prüfen
muss: (a) kürzere Haltedauer senkt Funding proportional, (b) Spot statt Perp auf
HL zahlt kein Funding — kostet aber 0,04/0,07 % Gebühr statt 0,015/0,045 %.
