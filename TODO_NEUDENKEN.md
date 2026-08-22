# TODO Neudenken — Arbeitsliste

Stand 22.08.2026. Abgeleitet aus STRATEGIE_NEUDENKEN_20260821.md (inkl. Nachtrag).
Reihenfolge ist Absicht: erst messen, dann bauen, dann entscheiden.

## Vorab: der Nicht-EU-Punkt

**Entscheidung (Andreas, 22.08.): die Krypto-Venue-Wahl zielt bewusst auf Plattformen
außerhalb der MiCA-Regulierung** (DEX wie Hyperliquid, dYdX). Verboten ist daran nichts —
MiCA reguliert Anbieter, nicht private Nutzer; die Plattformen sind ohne KYC nutzbar.
Die Absicherung dafür ist die Disziplin, die von Anfang an zum Projekt gehört: **lückenloses
eigenes Tracking aller Trades.** Genau deshalb steht A1 (Einstiegszeit) ganz oben — es ist
die letzte Lücke darin. Denn die deutsche Steuerpflicht gilt unabhängig vom Handelsplatz
(Weltprinzip), und ein DEX liefert keinen Steuerreport — unser eigenes Logging *ist* die
sichere Seite, auf der wir stehen. Bewusst in Kauf genommen wird die Kehrseite: außerhalb
der Regulierung gibt es keine Aufsicht und keine Einlagensicherung; Oracle-, Bridge- und
Smart-Contract-Risiko liegen komplett bei uns. Das bleibt als Risikoposten (nicht als
Blocker) in der Go/No-Go-Rechnung, bevor echtes Kapital fließt.

## Block A — Sofort, ohne offene Entscheidung (je ~1 Sitzung)

- [ ] **A1. Einstiegszeit + Einsatz in Trade-Records** (beide Bots + Papierdepots): `entry_ts`
      und `einsatz_usd` beim Kauf speichern, beim Close mitschreiben. Beides sind Messlücken
      (die 22.08.-Sitzung musste den Einsatz aus profit/pct rückrechnen); Voraussetzung für
      jede Haltedauer-/Funding-/Slippage-Rechnung. Zuerst erledigen.
- [ ] **A2. Funding-Rate-Logger** (nur Daten, kein Handel): stündlich Funding-Raten Kraken
      Futures + Hyperliquid + dYdX für BTC/ETH/SOL + unsere Alts nach CSV, Cron auf dem Pi,
      in `funktionspruefung.py` eintragen. Dient Carry-Rechnung UND Venue-Wahl gleichzeitig.
- [ ] **A3. Maker-Experiment im Paper**: Clone mit Kraken-Maker-Kostenmodell (2 × 0,16 %)
      plus Fill-Simulation (Limit am Quote, nicht jede Order füllt — verpasste Entries zählen
      als Kosten). Misst den einzigen Kostenhebel, der ohne Börsenwechsel wirkt.
- [ ] **A4. Venue-Check gegen die 0,67-%-Hürde** (read-only, APIs): Listing unserer 20 Coins
      auf Hyperliquid + dYdX, Orderbuchtiefe/Spread je Coin, Gebührenstufe, Auszahlungsweg.
      Ergebnis: eine Tabelle. *Zur Einsatzhöhe:* die ~180 $ sind **nicht bestätigt**, sondern
      der in der 22.08.-Sitzung rekonstruierte Median (179 $, aus profit/pct bei 254 von
      271 Trades hergeleitet — der Einsatz wird in den Trade-Records nicht direkt gespeichert).
      Real streut er mit der Sizing-Regel (6 %/3 % × Multiplikatoren auf 5.000 $ ≈ 90–300 $).
      Deshalb misst A4 die Tiefe nicht an einem Punkt, sondern an einer Leiter:
      **100 / 200 / 300 / 500 $** — damit die Tabelle auch bei anderem Kapital gültig bleibt.
      Bestätigen lässt sich der Ist-Median nur auf dem Pi (die Mac-Kopie der Crypto-Trades
      ist vom Stand vor dem 25.07.-Reset) — Einzeiler, bei der nächsten Pi-Sitzung machen.

## Block B — Kurzfristig, 2–4 Wochen

- [ ] **B1. Super-Bot-Umbau backtesten**: 12-1-Monats-Momentum + 200-Tage-Filter,
      Alpaca-Universum über den Funnel (Stufe 1 Screen → Stufe 2 Ranking), fee-aware,
      Walk-Forward. Erst wenn der Backtest steht → neues Paper-Depot nach Stufe-2-Regel
      (3 Monate Vorwärtstest, Backtests qualifizieren nicht).
- [ ] **B2. IBKR-Paper-Konto anbinden** (Juli-Entscheidung, Herausforderer-Clone):
      öffnet global Universum, Optionen-Tür, Cash-Zins-Vergleichslinie.
- [ ] **B3. Leads-Event-Studien** statt neuer Quellen: Russell-Rebalancing + Quartalsende
      auf historischen Daten (yfinance reicht); NY-Fed-SOFR/Repo als Beobachtungsgröße
      in den Wochenbericht.
- [ ] **B4. Wallet-Setup für DEX-Messung**: eigene Wallet, kleiner Test-Transfer
      (USDC → Arbitrum → Hyperliquid und zurück), Kosten und Dauer protokollieren.
      Nur Infrastruktur — kein Handelskapital.

## Block C — Gated: wartet auf Daten oder Datum

- [ ] **C1. Insider-Vorwärtstest**: nichts anfassen bis Ende Oktober, dann Entscheid nach
      dem vorab festgelegten Kriterium.
- [ ] **C2. Carry-Papierdepot**: erst wenn A2 vier Wochen Daten hat UND die Netto-Rechnung
      (Funding − Gebühren − Slippage − Rate-Flip-Risiko) positiv ausfällt.
- [ ] **C3. Signal-Portierung Billig-Venue**: erst nach A1 + A4. Dann Paper-Clone mit
      venue-echtem Kostenmodell (Gebühr + gemessene Slippage + Funding/Leihkosten),
      4–8 Wochen Vorwärtstest. Läuft als paralleler Herausforderer — der Maßstab
      (bestehende Messumgebung) wird nie mitten im Test gewechselt.
- [ ] **C4. On-Chain/Whale-Event-Studie**: nach 90 Tagen Log-Daten (Rendite t+1h/t+24h
      nach Signal, nach Kosten). Ergebnis entscheidet Gewicht oder Rauswurf.
- [ ] **C5. Covered-Call-Kandidat** (Volatilitätsprämie auf Fundament-Positionen):
      erst nach B2 und nach Entscheid der laufenden Tests. Notiert, damit es nicht verloren geht.

## Entscheidungen, die nur Andreas treffen kann

1. **Crypto-Bot v1 einfrieren** (Positionen auslaufen lassen, Sessions abbauen) — ja/nein.
2. **Insider-Depot Alt-Einstiege** (die 30 Positionen mit zu günstigen Einstiegskursen vom
   23.07.): so lassen und Versatz mitdenken / auf 27.07.-Schluss korrigieren (−1,6 pp) /
   neu aufsetzen. Steht seit dem 21.08. offen.
3. **BTC-Beimischung im Fundament** aktivieren (Ein-Drittel-Regel) — ja/nein, und ob mit
   Blick auf die Haltefrist als „kaufen und liegen lassen" geführt.
4. **Priorität bei knapper Zeit**: A-Block ist so geschnitten, dass jede Sitzung eines
   davon abschließt; Reihenfolge A1 → A2 → A4 → A3 empfohlen.

## Läuft unverändert weiter

Fundament-Depot, Podcast-Wächter (ng/bz, ohne neue Meinungsquellen), Wochenbericht,
Funktionsprüfung, Monitor/Risk-Agent, nächtliches GitHub-Backup.
