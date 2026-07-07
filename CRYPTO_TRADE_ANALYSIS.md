# Crypto-Bot — Tiefen-Trade-Analyse

**Stand:** 2026-06-28 · **Daten:** 544 echte Trades (20.05.–05.07.2026), `crypto/trades_history.json`.

---

## TL;DR — die eine Erkenntnis

**Es gibt eine profitable Kern-Strategie — begraben unter Spike-Verlusten und BTC/ETH-Drag.**

| Segment | Trades | Win | EV/Trade | Σ $ | Urteil |
|---|---|---|---|---|---|
| **CORE** (normal, ohne Meme, ohne BTC/ETH) | 194 | **39,7 %** | **+0,13 %** | **+$28** | ✅ funktioniert |
| SPIKES (alle) | 308 | 32,1 % | −0,27 % | **−$432** | ❌ Hauptverlust |
| BTC + ETH (alle) | 99 | ~27 % | negativ | **−$222** | ❌ verlieren immer |
| MEME (alle) | 21 | 28,6 % | −0,74 % | −$60 | ❌ blutet |
| **GESAMT** | 544 | 34,4 % | −0,16 % | −$530 | |

---

## 1. Nach Entry-Typ

| Typ | Trades | Win | ØGewinn | ØVerlust | R:R | EV | Σ $ |
|---|---|---|---|---|---|---|---|
| MAIN (normal) | 215 | 38,1 % | +2,09 % | −1,18 % | 1,77 | **+0,07 %** | −$38 |
| MEME | 21 | 28,6 % | +2,72 % | −2,12 % | 1,28 | −0,74 % | −$60 |
| **SPIKE** | 308 | 32,1 % | +2,17 % | −1,43 % | 1,52 | **−0,27 %** | **−$432** |

→ **57 % aller Trades sind Spikes, sie verursachen 82 % des Verlusts.**

## 2. Der Spike-Befund — Spikes verlieren auf JEDER Münze

| Coin | Spike EV | Spike Σ$ | Normal EV | Normal Σ$ |
|---|---|---|---|---|
| BTC | −0,46 % | −$82 | −1,66 % | −$51 |
| ETH | −0,55 % | −$74 | −0,11 % | −$15 |
| SOL | −0,09 % | −$29 | −0,01 % | **+$32** |
| RENDER | −0,80 % | −$17 | **+2,00 %** | **+$121** |

→ Ausnahmslos: **Spike-Entry = negativer Erwartungswert.** Selbst RENDER (der Star) verliert als Spike, gewinnt normal +$121. Das ist der klarste Befund der ganzen Analyse.

## 3. BTC & ETH — die überraschenden Verlierer

Verlieren auf **beiden** Entry-Arten (BTC normal sogar 0 % Win auf 5 Trades). Die Momentum-/Spike-Logik funktioniert bei den größten, liquidesten Coins **nicht** — sie mean-reverten stärker, laufen weniger sauber im Trend. Zusammen **−$222**.

## 4. Die Gewinner (normal, Mid-Cap)

RENDER normal **+$121** (45,5 % Win, EV +2,0 %), SOL normal +$32, dazu ADA/UNI/LTC leicht positiv. **Mid-Cap-Momentum mit normalem Entry funktioniert.**

## 5. Zeit-Trend — der Bot wird BESSER

| Zeitraum | Win | R:R | EV | Σ $ |
|---|---|---|---|---|
| 1. Hälfte | 29,4 % | 1,20 | −0,50 % | −$517 |
| **2. Hälfte** | **39,3 %** | **1,92** | **+0,19 %** | −$13 |

→ Die 2. Hälfte ist **brutto positiv** (+0,19 %/Trade) und fast Netto-Break-Even. Die Spike-Drossel (10.06.) + Parameter-Fixes wirken. Der −$530-Gesamtverlust stammt größtenteils aus der frühen Phase.

---

## 6. Empfehlungen (priorisiert, umsetzbar)

1. **Spikes abschalten** (oder radikal drosseln) — mit Abstand größter Hebel (−$432, verliert auf jeder Münze). Der **B_nospikes-Clone** misst genau das live → A vs. B vergleichen, bevor man's fest verdrahtet.
2. **BTC & ETH aus dem aggressiven Universum nehmen** — verlieren auf beiden Entry-Arten (−$222). Ggf. nur für normale Entries mit strengeren Gates behalten.
3. **Blocklist erweitern:** `excluded_symbols` += SHIB (11 % Win), PEPE (0 %). DOGE ist schon raus.
4. **Kern behalten & schärfen:** normale Mid-Cap-Entries (RENDER, SOL, LINK, ADA, UNI …) — das ist der profitable Teil (+$28 CORE).
5. **Verzahnung mit der Fee-Analyse:** CORE macht **+0,13 % brutto** → auf MEXC (0,10 %) **+0,03 % netto**, auf Kraken (0,52 %) **−0,39 %**. Die Kern-Strategie ist **nur auf einer Billig-Börse** knapp profitabel. Beide Hebel (Spikes weg + MEXC statt Kraken) sind nötig.

## 7. Nächster Analyse-Schritt

- **CORE isoliert live testen** (ein Clone „nur normal, Mid-Cap, MEXC-Fees"), ob +0,13 % brutto real hält und die Fee-Hürde überspringt.
- Untersuchen, **warum RENDER/SOL normal funktionieren** (Entry-Charakteristik) und BTC/ETH nicht → gezielt die Entry-Gates pro Coin-Klasse tunen.
- **Erst wenn ein Segment die Break-Even-Win-Rate live UND nach Fees hält → echtes Geld.**
