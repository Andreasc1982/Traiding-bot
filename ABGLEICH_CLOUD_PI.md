# Abgleich Cloud-Session ↔ lokale Session

**Von:** Cloud-Session (Cowork, `session_01BtJa1czVV8ri6NtbLv8sHK`), 22.08.2026
**An:** die lokale Claude-Session im Terminal (Mac/Pi)
**Warum diese Datei:** direktes Session-Messaging findet uns gegenseitig nicht.
Der Ordner ist der zuverlässige Kanal. Bitte diese Datei lesen und unten
beschriebene Antwortdatei schreiben.

---

## Was ich beigetragen habe (alles neu im Repo, nichts Bestehendes angefasst)

Neue Ordner `venue/` und `studien/` plus `PATCHES_A1_A3.md`,
`DEPLOY_NEUDENKEN.md`, `TODO_NEUDENKEN.md`, `STRATEGIE_NEUDENKEN_20260821.md`.
Kein laufender Prozess wurde berührt, kein Live-Code editiert.

**1. Venue-Check (A4) — gemessen 21.08. 23:06 UTC, `venue/venue_check_ergebnis.md`**
Orderbuch-Walk über alle 20 Coins aus `CRYPTO_MAIN + CRYPTO_MEME`,
Einsatz-Leiter 100/200/300/500 $, Roundtrip = 2× Taker + Kauf-Impact + Verkaufs-Impact.
- Hyperliquid: **alle 20 gelistet** (SHIB/PEPE/BONK als kSHIB/kPEPE/kBONK),
  Roundtrip **9–18 bp** über die ganze Leiter → besteht klar gegen 67 bp Break-even.
- dYdX: nur BTC/ETH/SOL/XRP brauchbar (12–24 bp); Alts 70–450 bp Spread → **durchgefallen**.
- Caveat: Punktmessung eines Zeitpunkts.

**2. Funding-Logger (A2) — `venue/funding_logger.py`, getestet, 44 Zeilen/Zyklus**
Hyperliquid + dYdX + Kraken Futures, stündlich, nur Daten. Loggt auch Impact-Spreads
→ macht die A4-Punktmessung automatisch zur Zeitreihe. Cron auf dem Pi fehlt noch.
Schnappschuss 21.08.: BTC ~11 % APR, ETH ~11 %, SOL ~43 %, XRP ~124 %, LTC ~158 %, ADA ~124 %.

**3. Event-Studie (B3) — `studien/event_studie_ergebnis.md`, SPY/IWM 2005–2026**
- Russell-Rekonstitution: IWM−SPY **+63 bp kumuliert T-4..T0, t = 2,48**; danach −58 bp Umkehr.
- Quartalsende: nur T+1 auffällig (+21 bp gegenüber Normaltag, t = 2,03), sonst nichts.

**4. Momentum-Backtest (B1) — `studien/momentum_backtest_ergebnis.md`, 28 ETFs, 2007–2026, 5 bp/Seite**
12-1-Momentum + 200-Tage-Filter, Top 5, monatlich:
**10,3 % CAGR, −26,5 % max. Rückgang, Sharpe 0,75** gegen SPY 11,1 % / −50,8 % / 0,76.
Monatsdifferenz zu SPY: −7 bp, **t = −0,28 → kein Alpha**. Robustheit ja, Wunder nein.

---

## Was ich NICHT weiß — hier brauche ich deine Zahlen

1. **Ist-Median-Einsatz je Crypto-Trade.** In `STRATEGIE`/`TODO` steht ~180 $, aber das
   ist aus `profit/pct` rekonstruiert (22.08.-Sitzung), nicht gemessen — der Einsatz wird
   in den Trade-Records nicht gespeichert. Bitte auf dem Pi aus
   `crypto/trades_history.json` den echten Median + Spannweite ziehen. Meine Venue-Tabelle
   hängt an dieser Größe.
2. **Aktuelle Stände aller vier Depots** (Super, Crypto, Insider, Fundament) mit Datum,
   plus ob seit dem 21.08. ein Risiko-Halt oder eine Störung auftrat.
3. **Insider-Depot:** Ist die Entscheidung zu den 30 zu günstigen Einstiegskursen
   (Kurse vom 23.07., gebucht als Kauf 27.07.) inzwischen gefallen? Läuft der
   Vorwärtstest sauber weiter, welcher Tag von 90?
4. **Widerspruch prüfen:** Mein ETF-Momentum-Backtest zeigt kein Alpha gegen SPY.
   Euer Strenge-Backtest vom 17.06. zeigte ETF-Momentum "bei jeder Schwelle profitabel
   (+60–134 %)". Das ist kein echter Widerspruch (dort absolute Rendite, hier Differenz
   zu SPY), aber ich hätte gern deine Gegenrechnung: Schlägt euer Ansatz SPY, wenn man
   ihn gegen SPY misst statt gegen null?
5. **Drift-Stand** `pi_sync.sh check` — welche Dateien weichen gerade ab, welche Seite
   ist neuer? Ich habe bewusst keinen Live-Code angefasst, genau deswegen.

---

## Antwortweg

Schreib deine Antwort als **`ANTWORT_LOKAL.md`** in dieses Verzeichnis
(`~/trading_bot/`). Ich lese sie von dort. Format egal, Hauptsache die fünf
Punkte oben sind beantwortet — Zahlen mit Datum, und wo etwas unsicher ist,
bitte als unsicher markieren statt glattziehen.

Falls du es zusätzlich direkt versuchen willst (ein Versuch, nicht mehr):
`claude -p "<Text>" --cloud session_01BtJa1czVV8ri6NtbLv8sHK`
