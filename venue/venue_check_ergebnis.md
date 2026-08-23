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
