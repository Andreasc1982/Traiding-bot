# Deploy Neudenken — was neu ist, was es ergab, was auf dem Pi zu tun bleibt

Stand 22.08.2026, gebaut und getestet in der Cloud-Session (Cowork). **Alles parallel:
kein einziger laufender Prozess und keine bestehende Datei wurde angefasst** —
nur neue Dateien in `venue/` und `studien/` plus diese Doku.

## Neue Dateien

| Datei | Zweck | Status |
|---|---|---|
| `venue/venue_check.py` | A4: Orderbuch-/Kosten-Messung HL + dYdX, Leiter 100–500 $ | ✅ ausgeführt, Ergebnis liegt bei |
| `venue/venue_check_ergebnis.md` / `.csv` | Messergebnis 21.08. 23:06 UTC | ✅ |
| `venue/funding_logger.py` | A2: stündlicher Funding-/OI-/Spread-Logger (HL, dYdX, Kraken Fut.), nur Daten | ✅ getestet (44 Zeilen/Zyklus), Pi-Cron ausstehend |
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
4. `agents/funktionspruefung.py`: Prüfung 19 ergänzen — `venue/funding_heartbeat.json`
   jünger als 2 h (Muster wie bei `ng_state.json`).
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
