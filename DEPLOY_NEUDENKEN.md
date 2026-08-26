# Deploy Neudenken — was neu ist, was es ergab, was auf dem Pi zu tun bleibt

Stand 22.08.2026, gebaut und getestet in der Cloud-Session (Cowork). **Alles parallel:
kein einziger laufender Prozess und keine bestehende Datei wurde angefasst** —
nur neue Dateien in `venue/` und `studien/` plus diese Doku.

## Neue Dateien

| Datei | Zweck | Status |
|---|---|---|
| `venue/venue_check.py` | A4: Orderbuch-/Kosten-Messung HL + dYdX, Leiter 100–500 $ | ✅ ausgeführt, Ergebnis liegt bei |
| `venue/venue_check_ergebnis.md` / `.csv` | Messergebnis 21.08. 23:06 UTC | ✅ |
| `venue/funding_logger.py` | A2: stündlicher Funding-/OI-/Spread-Logger (HL, dYdX, Kraken Fut.), nur Daten | ⚠️ getestet, aber **vor Rollout mit `hl_collect.py` auf dem Pi zusammenlegen** |
| `venue/funding_log.csv` | erster Datenpunkt (aus dem Test) | wächst per Cron |
| `studien/event_studie.py` + `_ergebnis.md` | B3: Quartalsende + Russell, SPY/IWM 2005–2026 | ✅ gerechnet |
| `studien/momentum_backtest.py` + `_ergebnis.md` | B1: 12-1-Momentum + 200-Tage-Filter, fee-aware, 28 ETFs, 2007–2026 | ✅ gerechnet |
| `PATCHES_A1_A3.md` | präzise Patch-Anleitung für Live-Code (nur Pi-Sitzung) | zur Umsetzung |

## Die Ergebnisse in vier Sätzen

1. **A4 / Venue:** Hyperliquid listet **alle 20 Coins** und liegt bei **9–18 bp**
   Roundtrip über die ganze Einsatz-Leiter — weit unter der 0,67-%-Hürde und unter
   Kraken (62 bp). **dYdX fällt für die Alts durch** (Spreads 70–450 bp; nur
   BTC/ETH/SOL/XRP brauchbar). Punktmessung — der Funding-Logger misst die
   Impact-Spreads jetzt stündlich mit.
2. **A2 / Funding:** läuft; Schnappschuss 21.08.: BTC ~11 % APR, ETH ~11 %, aber
   XRP ~124 %, LTC ~158 %, ADA ~124 % — ob das trägt oder Momentaufnahme ist,
   zeigen die 4 Wochen Daten (Carry-Entscheid C2 erst danach).
3. **B3 / Events:** Russell-Rekonstitution ist real: IWM−SPY **+63 bp kumuliert in
   den 5 Tagen davor (t = 2,48)**, danach −58 bp Umkehr; Quartalsende nur schwach
   (T+1 +21 bp, t = 2,0, sonst nichts). Einmal-im-Jahr-Effekt: Erkenntnis ja,
   Renditetreiber nein.
4. **B1 / Momentum-Umbau:** netto **10,3 % CAGR bei −26,5 % max. Rückgang** gegen
   SPY 11,1 % bei **−50,8 %** — gleiche Sharpe (0,75), halber Schmerz, kein
   Alpha gegen SPY (t = −0,28). Der Umbau kauft Robustheit, keine Wunder —
   ehrliche Grundlage für den 3-Monats-Vorwärtstest.

## Rollout auf den Pi (nächste Pi-Sitzung, ~30 min)

1. `~/bin/pi_sync.sh check` — Drift-Stand ansehen (neue Dateien konfliktfrei).
2. Neue Ordner übertragen: `pi_sync.sh push venue/* studien/* PATCHES_A1_A3.md DEPLOY_NEUDENKEN.md TODO_NEUDENKEN.md STRATEGIE_NEUDENKEN_20260821.md`
   (rsync legt die Ordner an; nichts davon kollidiert mit Bestehendem).
3. Cron ergänzen (`crontab -e`, vorher `crontab -l > crontab_backup_$(date +%Y%m%d).txt`):
   `7 * * * * cd /home/trading2025/trading_bot/venue && /usr/bin/python3 funding_logger.py >> /tmp/funding.log 2>&1`
4. `agents/funktionspruefung.py`: **Prüfung 22** ergänzen — `venue/funding_heartbeat.json`
   jünger als 2 h (Muster wie bei `ng_state.json`). *(Korrigiert: die Prüfung hat
   inzwischen 21 Einträge, nicht 18 — mein Stand kam aus der Mac-Kopie.)*
5. Patches A1 + A3 nach `PATCHES_A1_A3.md` anwenden (Pflichtregeln: check, .bak,
   py_compile, Sessions einzeln neu starten).
6. GitHub-Backup nimmt `venue/` + `studien/` automatisch mit, sofern nicht
   von `.gitignore` erfasst — kurz prüfen (`funding_log.csv` SOLL versioniert
   werden: es ist die Messreihe).

## Bewusst NICHT gemacht (und warum)

- **Kein Edit an laufendem Code von hier** — Mac↔Pi-Drift seit 13.08.
  (z. B. `insider_paper.py` auf dem Pi neuer); Live-Änderungen nur in
  Pi-Sitzungen mit Sync-Check. Deshalb PATCHES statt Patch.
- **Kein Carry-Papierdepot, kein Venue-Paper-Clone** — beides ist per
  TODO gated (C2 braucht 4 Wochen Funding-Daten, C3 braucht A1 + mehr
  A4-Messpunkte). Reihenfolge ist Absicht.
- **Keine Wallet, keine Keys, kein Handel** — B4 (Test-Transfer) ist ein
  Mensch-Schritt mit echtem (Klein-)Geld → Andreas.

## Offene Entscheidungen (unverändert bei Andreas)

Crypto-Bot v1 einfrieren · Insider-Alt-Einstiege · BTC-Beimischung Fundament ·
Priorität der Pi-Sitzung (Vorschlag: Rollout-Schritte 1–4, dann Patch A1, dann A3).

---

## NACHTRAG 22.08. — nach dem Abgleich mit der lokalen Session

**Rollout ist BLOCKIERT, bis drei Dinge erledigt sind.** Drei Einwände der lokalen
Session waren berechtigt, und die Prüfung hat einen vierten Fehler zutage gefördert,
der schwerer wiegt als alle drei.

1. **Doppelte Messreihe — `funding_logger.py` vs. `hl_collect.py`.** Auf dem Pi
   existiert bereits ein Hyperliquid-Funding-Sammler mit **28 Tagen Historie**.
   Davon wusste ich nichts: meine Grundlage war die Mac-Kopie, und die ist älter.
   Genau die Drift, wegen der ich keinen Live-Code angefasst habe — sie hat mich
   trotzdem erwischt, nur an anderer Stelle. **Vor dem Rollout zusammenlegen:**
   `hl_collect.py` behält die Historie und bleibt führend für Hyperliquid; aus
   meinem Logger übernehmen, was dort fehlt (dYdX, Kraken Futures, Impact-Spreads,
   Heartbeat bei jedem Lauf). Ein Sammler, eine Datei.
2. **Funktionsprüfung**: neue Prüfung ist Nr. **22**, nicht 19 (oben korrigiert).
3. **Venue-Check ist keine unabhängige Bestätigung** — 26 Minuten Abstand, gleicher
   Marktmoment, Abweichungen bis Faktor 2,6. Quantifizierte Einordnung im Nachtrag
   von `venue/venue_check_ergebnis.md`: das Handelskosten-Urteil hält, weil bei HL
   9 der 9–18 bp feste Gebühr sind.
4. **Der Fund, der alles verschiebt: Funding fehlte in der Hürden-Rechnung.**
   Der Bot ist long-only; ein Long auf einem Perp zahlt Funding. Bei 28 h
   Haltedauer kostet das je nach Coin 3,5 bis 64 bp **zusätzlich**. Damit reißt
   AAVE die 67-bp-Hürde bereits (74,7 bp), LTC liegt mit 61 bp auf der Kante —
   und die hohen Funding-Raten sitzen ausgerechnet in den Alts, in denen der
   gemessene Vorteil steckt. **Die Portierung ist damit nicht entschieden, sondern
   offen**, und der zusammengelegte Funding-Sammler ist ihre Entscheidungsgrundlage.

**Was sich am Rollout ändert:** Schritte 1–2 (Dateien übertragen) und 5 (Patches
A1/A3) bleiben unverändert richtig. Schritt 3 (Cron) erst **nach** der Zusammenlegung.
Die Aussage „Hyperliquid ist der Kandidat" bleibt richtig für BTC/ETH/SOL und wird
für die Alts zur offenen Frage.

---

## NACHTRAG 2 — 25.08.2026: der Blocker ist gegenstandslos

Der Nachtrag vom 22.08. hat den Rollout blockiert. Nachgemessen auf dem Pi hält
keiner der beiden tragenden Gründe. **Punkt 1 des Rollouts (Cron) ist damit nicht
aufgeschoben, sondern gestrichen.**

### Die „28 Tage Historie" gehören einem anderen Sammler

`hl_collect.py` wurde in der Nacht zum 22.08. gebaut und hat entsprechend erst
3 Tage Daten (993 Runden, 20 Coins, 0 Fehler). Die 28 Tage stammen von
**`dydx_collect.py`**, der seit dem 25.07. 19:31 läuft — 852.286 Zeilen. Am 22.08.
00:24 war daran nur *eine* Anpassung: `MARKETS` von 5 auf 20 Coins, alte Datei
nach `imbalance_log_5maerkte_20260822.csv` rotiert. Die Zahl steht im Kommentar
des Skripts selbst („wo der 28-Tage-Median bei 0,6 bp liegt") und meint den
dYdX-**Spread**, nicht Funding.

### Funding steckt längst in der Hürden-Rechnung

`hl_collect.py`, Zeile 128:
`roundtrip = 2*slip180*100 + TAKER_BP + max(f_h,0) * HALTE_H * 10000`.
Der vierte Befund des ersten Nachtrags („Funding fehlte") galt für den
Venue-Check der Cloud-Sitzung — nicht für den Sammler, der in derselben Nacht
entstand und Funding von Anfang an mitrechnet.

### Gemessen statt geschätzt: kein Coin reißt die Hürde

Roundtrip inkl. Funding (28 h), Median über 995 Runden je Coin, 22.–25.08.:

| | Median | p90 | Funding je Position |
|---|---|---|---|
| bestes (SOL/BTC) | 12,6 bp | 17,5 bp | 3,5 bp |
| schlechtestes (UNI) | 23,0 bp | 46,7 bp | 12,3 bp |
| **AAVE** | **22,3 bp** | 47,9 bp | 10,5 bp |

Gegen 67 bp Break-even. Alle 20 Coins liegen darunter, auch im p90.
Die Alarmzahl des ersten Nachtrags — AAVE 74,7 bp — stammt aus der
Momentaufnahme vom 21.08. und liegt Faktor 3 daneben; dieselbe Krankheit wie
beim dYdX-Snapshot. Funding liegt bei 17 von 20 Coins am Bodensatz (3,5 bp).

**Der Vorbehalt, der bleibt:** drei Tage sind ein ruhiges Regime. Bei anziehendem
Markt kehrt sich Funding um (DOGE bei +0,034 %/h wären 94 bp je Position). Die
Portierungsfrage ist nicht beantwortet, sie ist *bisher unauffällig* — und genau
dafür läuft `hl_collect.py` weiter.

### dYdX: für die Alts endgültig erledigt

Nicht mehr per Momentaufnahme, sondern über 211.560 Zeilen seit dem 22.08.,
Median-Spread je Markt: BTC 3,7 · ETH 7,0 · SOL 10,6 · XRP 21,0 bp — brauchbar.
Danach DOGE 41 · LTC 48 · WIF 59 · BONK 72 · DOT 88 · UNI 88 · LINK 119 ·
ARB 125 · ADA 136 · AVAX 140 · RENDER 167 · POL 201 · AAVE 209 · PEPE 214 ·
SHIB 468 · TRUMP 517 bp. Der Edge des Bots sitzt in den Alts (t = 3,03) — dort
ist dYdX nicht handelbar. Urteil des Venue-Checks bestätigt, jetzt mit Medianen.

### Was daraus folgt (umgesetzt am 25.08.)

- **`venue/funding_logger.py` wird nicht ausgerollt.** Hyperliquid deckt
  `hl_collect.py` inkl. Funding ab; dYdX ist erledigt; übrig bliebe Kraken
  Futures als Vergleichswert, wofür kein eigener Cron lohnt. Es gibt nichts
  zusammenzulegen. Das Skript bleibt als Referenz liegen, ohne Cron.
- **Rollout-Schritt 3 (Cron) entfällt**, Schritt 4 (Prüfung 22 für
  `venue/funding_heartbeat.json`) entfällt mit ihm — es gibt keinen Heartbeat
  zu prüfen. Die Prüfung für `hl/heartbeat.json` existiert bereits (Zeile 64).
- **`dydx_collect.py` zurück auf die vier Majors** — 15 s × 20 Märkte schrieben
  rund 270 MB im Monat für eine Antwort, die schon dasteht.
