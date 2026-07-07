# Fee- & Break-Even-Analyse — Crypto-Bot (echte Daten)

**Stand:** 2026-06-28 · **Datenquelle:** `crypto/trades_history.json` — **544 echte Trades** (kein Backtest, keine Annahme).

---

## 1. Die harte Realität (gemessen, nicht geschätzt)

| Kennzahl | Wert |
|---|---|
| Trades gesamt | **544** |
| **Win-Rate** | **34,4 %** (187 Gewinner / 357 Verlierer) |
| Ø Gewinn je Gewinner | **+2,15 %** (Median +1,70 %) |
| Ø Verlust je Verlierer | **−1,36 %** (Median −1,50 %) |
| **R:R** (Ø Gewinn ÷ Ø Verlust) | **1,58** *(nicht 2,0 wie im Design angenommen)* |
| **Ø PnL pro Trade (brutto, VOR Börsen-Fee)** | **−0,15 %** |
| Netto-Ergebnis (mit simulierten Kraken-Fees) | **−$530** |

**Exit-Gründe:** 198× Stop-Loss, 114× PSAR-Stop, 69× Spike-Time-Exit, 57× Trailing, 52× Risk-Close, 41× Break-Even.
→ Der Bot wird **überwiegend ausgestoppt** — wenige saubere Take-Profits. Klassisches Zeichen für schwache Entries.

> ⚠️ **Kernbefund:** Der Bot ist mit **−0,15 %/Trade schon VOR Gebühren im Minus.** Die Fees machen einen ohnehin leicht verlierenden Ansatz nur schneller verlierend.

---

## 2. Break-Even-Win-Rate je Börse (mit echtem R:R = 1,58)

Formel: `Break-Even-Win = (Roundtrip-Fee % + 1,36) ÷ 3,51`

| Börse | Roundtrip-Fee | **Nötige Win-Rate** | Abstand zur echten 34,4 % |
|---|---|---|---|
| *(ganz ohne Fees)* | 0,00 % | 38,7 % | **−4,3 PP** (schon drunter!) |
| Futures (Bybit/MEXC) | 0,04 % | 39,9 % | −5,5 PP |
| MEXC Spot | 0,10 % | 41,6 % | −7,2 PP |
| Bybit Spot | 0,20 % | 44,4 % | −10,0 PP |
| **Kraken (aktuell)** | 0,52 % | **53,6 %** | **−19,2 PP** |

**Lies das so:** Selbst bei **gebührenfreiem** Handel bräuchte der Bot 38,7 % Trefferquote — er schafft aber nur **34,4 %**. Auf Kraken bräuchte er **53,6 %**. Der Bot ist auf **jeder** Börse aktuell unter Wasser.

---

## 3. Netto pro Trade — aktueller Zustand (Win-Rate 34,4 %)

| Börse | Netto/Trade | @ $100, 600 Trades/Monat | in % von €5000/Monat |
|---|---|---|---|
| Futures | −0,19 % | −$114 | −2,3 % |
| MEXC Spot | −0,25 % | −$150 | −3,0 % |
| Bybit Spot | −0,35 % | −$210 | −4,2 % |
| **Kraken** | **−0,67 %** | **−$402** | **−8,0 %** |

→ Alle negativ. Kraken blutet ~3,5× schneller als Futures.

---

## 4. Was, wenn die Strategie besser wird? (Netto/Trade nach Win-Rate)

*(echtes R:R 1,58 beibehalten, nur Win-Rate variiert)*

| Win-Rate | Kraken 0,52 % | Bybit 0,20 % | MEXC 0,10 % | Futures 0,04 % |
|---|---|---|---|---|
| **34,4 %** (heute) | 🔴 −0,67 % | 🔴 −0,35 % | 🔴 −0,25 % | 🔴 −0,19 % |
| **40 %** | 🔴 −0,48 % | 🔴 −0,16 % | 🔴 −0,06 % | 🟢 +0,00 % |
| **45 %** | 🔴 −0,30 % | 🟡 +0,02 % | 🟢 +0,12 % | 🟢 +0,18 % |
| **50 %** | 🔴 −0,13 % | 🟢 +0,20 % | 🟢 +0,30 % | 🟢 +0,36 % |
| **55 %** | 🟢 +0,05 % | 🟢 +0,37 % | 🟢 +0,47 % | 🟢 +0,53 % |

**Auffällig:** Auf **Kraken** ist der Bot selbst bei **50 %** Win-Rate noch im Minus (weil R:R nur 1,58). Auf MEXC reicht schon ~42 %.

---

## 5. Fazit & Hebel

**Zwei Hebel — und keiner allein reicht:**

1. **Strategie verbessern (Pflicht):** Selbst gebührenfrei braucht der Bot +4,3 PP Win-Rate (34,4 → 39 %) ODER ein besseres R:R. Ohne das verliert er auf *jeder* Börse. Die vielen Stop-Exits deuten auf **schwache Entries** (wie beim DEX-„Pump-Chasing"-Befund) — hier liegt die Wurzel.
2. **Billige Börse (großer Verstärker):** Der nötige Verbesserungssprung schrumpft dramatisch — von **+19 PP** (Kraken) auf **+7 PP** (MEXC). Kraken ist für hochfrequentes Trading die schlechteste Wahl.

**Empfehlung:**
- **Nicht live gehen**, solange die Win-Rate < Break-Even ist. Erst die Entry-Qualität fixen (weniger, überzeugtere Trades — jeder vermiedene schwache Trade spart Fee + Verlust doppelt).
- Wenn live: **MEXC/Bybit Spot statt Kraken** — halbiert bis drittelt die Fee-Hürde.
- **Frequenz runter** wirkt wie eine Fee-Senkung UND verbessert oft die Trefferquote.
- Die **Clones** (A/B/C) sind die Live-Messstrecke — dort testen, ob eine Strategie-Variante die Break-Even-Win-Rate real überspringt, BEVOR echtes Geld fließt.

---

## Annahmen & Grenzen

- Win/Verlust-% sind die **realisierten Kursbewegungen** aus den 544 Trades (Demo modelliert Slippage bereits im Fill-Preis).
- Roundtrip-Fee = 2 × Taker-Rate. Futures-Rate ~0,02 % Taker; **Funding-Rate NICHT eingerechnet** (kann Futures-Vorteil teils auffressen) + Hebel-/Liquidationsrisiko.
- „600 Trades/Monat" = 20/Tag als Beispiel; reale Frequenz schwankt mit dem Marktregime.
- $ ≈ € (Parität zur Vereinfachung).
- Belastbarer wird's nur mit **mehr Live-Daten** und getrennt nach Coin-Typ (Main vs. Meme vs. Spike) — Spikes waren historisch die Hauptverlustquelle.
