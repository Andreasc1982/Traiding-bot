# Sitzungsberichte

Datierte Zusammenfassung jeder Sitzung, in der etwas erarbeitet oder verändert wurde.
Neueste zuerst. Gepflegt auf dem Pi, nachts per GitHub-Backup gesichert.

---

## 25.08.2026 (mittags) — Blocker widerlegt, Patches A1 + A3 eingespielt

Fortsetzung des Vormittags. Andreas: „mach alle Punkte."

### Was gemacht wurde

**1. Der Rollout-Blocker vom 22.08. hält nicht — beide Gründe nachgemessen.**
Die „28 Tage Historie" gehören nicht `hl_collect.py` (gebaut in der Nacht zum 22.08.,
also 3 Tage), sondern `dydx_collect.py`, der seit dem 25.07. 19:31 läuft — 852.286 Zeilen.
Am 22.08. war daran *eine* Anpassung: `MARKETS` 5 → 20. Und Funding fehlte nie in der
Hürden-Rechnung: `hl_collect.py` Zeile 128 rechnet
`2*slip180 + TAKER_BP + max(f_h,0)*HALTE_H` — Funding steckt seit dem ersten Tag drin.
Gemessen über 995 Runden je Coin: Roundtrip inkl. Funding zwischen **12,6 bp** (SOL/BTC)
und **23,0 bp** (UNI), p90 überall unter 48 bp, gegen 67 bp Break-even. Die Alarmzahl
„AAVE 74,7 bp" aus der Momentaufnahme vom 21.08. steht real bei **22,3 bp** — Faktor 3.
Zweiter Nachtrag in `DEPLOY_NEUDENKEN.md` geschrieben.

**2. `dydx_collect.py` zurück auf 5 Märkte** (war 20). Über 211.560 Zeilen seit dem 22.08.
sind die Mediane eindeutig: BTC 3,7 · ETH 7,0 · SOL 10,6 · XRP 21,0 bp brauchbar, danach
DOGE 41 bis TRUMP 517 bp. Der Edge des Bots sitzt in den Alts — dort ist dYdX nicht
handelbar. Frage beantwortet, 20 Märkte kosteten ~270 MB im Monat für nichts.
Session neu gestartet, läuft mit 0 Fehlern.

**3. `venue/funding_logger.py` wird nicht ausgerollt.** Kein Cron gesetzt, Prüfung 22
entfällt. Es gab nichts zusammenzulegen: Hyperliquid deckt `hl_collect.py` inkl. Funding
ab, dYdX ist erledigt, übrig bliebe Kraken Futures als Vergleichswert. Das Skript bleibt
als Referenz liegen.

**4. Patch A1 — `entry_ts` + `einsatz_usd`, alle vier Depots.**
`super_bot.py` (1 Kaufpfad + Verkauf), `crypto/crypto_bot.py` (3 Kaufpfade: normal,
Spike, Whale + Verkauf), `insider_paper.py`, `fundament_bot.py`. Rein additiv — der Diff
ändert keine bestehende Zeile. Alt-Positionen ohne `entry_ts` ergeben `None` statt eines
rückgerechneten Schätzwerts.
Bei den Papierdepots bin ich vom Patch-Text abgewichen, weil er dort nicht passt:
- `insider_paper.py`: Ein Titel, der eine Rückführung überlebt, **behält seinen
  ursprünglichen `entry_ts`** — sonst wäre jede Rückführung ein neuer Einstieg und die
  Haltedauer systematisch zu kurz. Dazu neu: `verkauft_detail` je verkauftem Titel
  (Haltedauer, Einsatz, Erlös). Ohne das gäbe es hier nur Ticker-Listen und eine
  Auswertung könnte das Depot nicht wie die Handels-Bots behandeln.
  `verkauft`/`gekauft` blieben unverändert — das Dashboard liest sie.
- `fundament_bot.py`: **nur `entry_ts`**, kein `einsatz_usd`, keine `haltedauer_h`.
  Das Depot hält SPY/SHY/GLD/DBC dauerhaft und führt nur Gewichte zurück. Es gibt keinen
  Ein- und Ausstieg, also keine Haltedauer. Die Felder trotzdem zu setzen wäre eine
  erfundene Zahl.
Getestet gegen Kopien mit umgebogenen Ausgabepfaden (echte Eingabedaten, Schreiben nur
nach /tmp): Haltedauer 72,01 h bei gesetzten 72 h, `entry_ts` korrekt übernommen.
`super_bot` und `crypto_bot` einzeln neu gestartet, Positionen erhalten (1 bzw. 7),
keine Tracebacks.

**5. Patch A3 — Clone `F_maker`.** Limit-Order statt Market beim Entry: 0,16 % Maker-Fee
gegen das Risiko verpasster Fills. Exits bleiben Taker 0,26 % — ein Stop, der auf einen
Maker-Fill wartet, wäre eine Lüge im Risikomodell. Vollständig in `crypto/clone.py`
gebaut, `crypto_bot.py` wurde dafür **nicht** noch einmal angefasst: `trade()` umschließt
den vorhandenen Dispatcher, wandelt jede frisch angelegte Position in eine offene
Limit-Order um (Einsatz zurück in die Balance), und `_check_pending()` füllt im 1s-Tick
zum Limit oder verwirft nach 120 s als `MISSED_FILL`. Zähler persistiert in
`F_maker_maker.json`, Quote im Dashboard-JSON.

Drei Dinge kamen dabei unerwartet dazu:
- **Der Patch-Text nennt Port 8098 als frei — ist er nicht** (Fundament-Dashboard;
  8097 Insider, 8099 Hyperliquid). Variante liegt jetzt auf **8103**.
- **`gateway.py` war mit abgeschaltet.** `clone.py` liest *alle* Marktdaten aus
  `/dev/shm/crypto_gw`; ohne Gateway sieht ein Clone nichts. Musste mit gestartet werden.
  Kein WS-Konflikt: `alpaca_gw_api_key` ist gesetzt, das Gateway läuft auf einem eigenen
  Paper-Konto. Der Live-Crypto-Bot meldet durchgehend `WS✓`.
- **Altfehler gefunden:** `CloneBot.send()` kannte das Argument `roh` nicht, das
  `crypto_bot.run()` mitgibt. **Jeder Clone wäre beim Start abgestürzt** — unbemerkt, weil
  die Clones seit dem 26.07. aus sind. Signatur korrigiert.

**`B_nospikes` läuft mit**, weil das Entscheidungskriterium „F schlägt B" lautet. Beide
starteten gleichzeitig bei 5.000 $ mit identischen Signalen und Universum; nur die
Ausführung unterscheidet sich. Ein erster Fehlstart (vor dem Fix) wurde archiviert,
nicht gelöscht (`*.fehlstart_20260825-122359`).

**6. `.gitignore`**: `*.bak_*`, `*.bak2_*`, `*.fehlstart_*` ergänzt. Die 49 bereits
versionierten `.bak`-Dateien wurden **nicht** ausgetragen — das wäre eine Löschung im Repo.

### Warum

Die Portierungsfrage des Crypto-Bots hing an einem Blocker, der auf zwei Fehlzuordnungen
beruhte. Beide ließen sich in Minuten mit Daten prüfen, die längst auf dem Pi liegen —
das war billiger, als vier Wochen auf einen zweiten Funding-Sammler zu warten. Der Grund
für beide Fehler ist derselbe wie bei den dYdX-Alt-Spreads: **eine Momentaufnahme in einer
dünnen Stunde ist keine Messung.** Deshalb ist die Konsequenz nicht „Frage beantwortet",
sondern „weiter messen, wo es zählt" — `hl_collect.py` bleibt unangetastet.

A3 misst genau das, was am 26.07. als Ursache der Clone-Verluste diagnostiziert wurde
(Kostenproblem, nicht Strategieproblem). Es ist kein Rückfall in die eingestellten Clones,
sondern der Test jener Diagnose.

### Was jetzt läuft

- `dydx` — 5 Märkte statt 20, 15 s Takt
- `gateway` — Market-Data-Gateway auf eigenem Alpaca-Paper-Konto, publiziert nach
  `/dev/shm/crypto_gw`
- `clone_B_nospikes`, `clone_F_maker` — je 5.000 $ Papier, Telegram aus, keine echten Orders
- `clones_dash` — **http://trading2025.fritz.box:8103** (`maker_dashboard.html`),
  Whitelist geprüft: `config.py` → 403.
  **Nachtrag:** die Seite war zunächst nur auf dem Pi erreichbar — bei der Abschaltung
  am 26.07. war die ufw-Regel des alten Clone-Ports (8090) entfernt worden, für 8103 gab
  es nie eine. Nachgetragen für LAN (192.168.188.0/24) und VPN (10.8.0.0/24), Muster wie
  8097/8098/8099. **Merke: ein neues Dashboard braucht immer beide Schritte — Session
  starten UND ufw-Regel setzen.** Sonst antwortet der Server auf dem Pi mit 200 und von
  außen gar nicht, was wie ein kaputtes Dashboard aussieht.
- Alle vier neu in **`start_all.sh` UND `agents/monitor_agent.py` BOTS**, maschinell
  gegeneinander verglichen (die `for`-Schleife im start_all wurde durch zwei explizite
  Blöcke ersetzt, damit sich beide Stellen zeilenweise vergleichen lassen).
  `monitor` neu gestartet, meldet alle 17 Sessions grün.
- Unverändert: `hl_collect.py` (1003 Runden, 0 Fehler), `super_bot`, `crypto_bot`

### Was offen ist

- **Erste F-vs-B-Zahlen sind bedeutungslos.** Nach 10 Minuten: B 4.996 $ / 6 Positionen,
  F 4.999 $ / 3 Positionen, MISSED_FILL-Quote 80 % (3 gefüllt, 12 verpasst). Das
  Kriterium lautet ≥ 60 Tage und Quote < 25 %. Falls die Quote sich bei 80 % einpendelt,
  ist die Antwort „Maker-Ausführung verpasst den Markt" — auch das wäre ein Ergebnis.
- **Das 120-s-Fenster ist gesetzt, nicht hergeleitet.** Kommt aus dem Patch-Text. Ob es
  die richtige Größe ist, zeigt erst die Quote über Wochen.
- **Regimeabhängigkeit des Funding** bleibt das größte offene Risiko der Hyperliquid-
  Rechnung. Drei Tage sind ein ruhiges Regime; bei DOGE mit +0,034 %/h wären es 94 bp
  je Position statt 3,5.
- **49 `.bak`-Dateien** sind weiterhin im Repo versioniert.
- Bewusst nicht gemacht: kein Cron für `funding_logger.py`, keine Prüfung 22, keine
  Umstellung auf echtes Geld, keine Änderung an Kapital oder Positionsgrößen.

## 25.08.2026 — Cloud-Ergebnisse auf den Pi übertragen (nur Dateien, kein Rollout)

### Was gemacht wurde

Der Sitzungsstart meldete 4 driftende Dateien und 7 Dateien, die es nur auf dem Mac gab —
die Arbeitsergebnisse der Cloud-Sitzung vom 22.08. Vor dem Übertragen geprüft:
bei allen vier Drift-Dateien war der **Mac** neuer, die Pi-Stände waren die kürzeren
Fassungen von 12:58; die Mac-Fassungen von 13:03 enthalten zusätzlich den Nachtrag.
Die Zeilen, die nur auf dem Pi standen (Prüfung „19" statt 22, alte Logger-Statuszeile),
sind genau die, die der Nachtrag korrigiert — also keine eigenständige Pi-Arbeit,
die verloren gehen konnte.

Übertragen mit `pi_sync.sh push` (11 Dateien, je mit Pi-Sicherung `*.bak_20260825-112404`):
`DEPLOY_NEUDENKEN.md`, `TODO_NEUDENKEN.md`, `ABGLEICH_CLOUD_PI.md`, `ANTWORT_CLOUD_20260822.md`,
`PATCHES_A1_A3.md`, `studien/event_studie.py`, `studien/momentum_backtest.py`,
`studien/momentum_backtest_ergebnis.md`, `venue/venue_check.py`, `venue/funding_logger.py`,
`venue/venue_check_ergebnis.md`.
Zusätzlich per `scp`: `venue/funding_log.csv` und `venue/venue_check_ergebnis.csv` —
`pi_sync.sh` erfasst nur `.py/.sh/.html/.md`, die Messreihen fielen sonst durchs Raster.
`pi_sync.sh check` meldet danach: deckungsgleich.

### Warum

Übertragen wurden **nur Dateien**. Schritt 3 des Rollout-Plans (stündlicher Cron für
`funding_logger.py`) wurde bewusst **nicht** ausgeführt: laut Nachtrag in `DEPLOY_NEUDENKEN.md`
ist der Rollout blockiert, bis der Logger mit `hl_collect.py` zusammengelegt ist — sonst
liefen zwei Funding-Sammler parallel und die 28-Tage-Historie von `hl_collect.py` bekäme
eine zweite, konkurrierende Quelle. Ohne Cron liegen die neuen Skripte auf dem Pi und tun
nichts; geprüft: kein Cron und kein Watchdog-Eintrag verweist auf `venue/` oder `studien/`.

### Was jetzt läuft

Unverändert — es wurde kein Prozess gestartet, gestoppt oder neu geladen.
Neu auf dem Pi liegen die Ordnerinhalte `venue/` (5 Dateien) und `studien/` (4 Dateien).
`.gitignore` erfasst beide Ordner nicht, das nächtliche GitHub-Backup nimmt sie also mit —
inklusive `funding_log.csv`, wie im Deploy-Plan gewünscht.

### Was offen ist

- **Zusammenlegung `funding_logger.py` + `hl_collect.py`** — Voraussetzung für den Cron
  und damit für den Carry-Entscheid (C2). Nicht begonnen.
- **Patches A1 + A3** aus `PATCHES_A1_A3.md` — nicht angewendet.
- **Prüfung 22** in `agents/funktionspruefung.py` — nicht ergänzt.
- **`*.bak_*` landet im Git-Repo**: 49 Sicherungsdateien sind versioniert, 55 liegen im
  Verzeichnis. Kein neues Problem, aber Rauschen im nächtlichen Backup. Ein Muster in
  `.gitignore` würde nur künftige stoppen; die 49 bestehenden auszutragen wäre eine
  Löschung im Repo — deshalb nicht von mir entschieden.

## 22.08.2026 (früh) — Die 60-MB-Datei ausgewertet: vier Befunde, einer korrigiert mich

636.664 Zeilen, 5 Märkte, 28 Tage. Die Imbalance-Frage war beantwortet (Signal zu klein) — in der
Datei stecken aber Spread- und Tiefendaten, die nie ausgewertet wurden. Auf dem Mac gerechnet;
auf dem Pi lief die Auswertung in den Timeout.

### 1. Der Spread ist über den Tag stabil — die „dünne Stunde" war NICHT die Erklärung

| Markt | Median | günstigste Stunde | teuerste Stunde | Faktor |
|---|---|---|---|---|
| BTC | 0,62 bp | 07 Uhr: 0,46 | 14 Uhr: 1,23 | 2,66 |
| ETH | 2,14 bp | 08 Uhr: 2,09 | 14 Uhr: 2,69 | 1,29 |
| SOL | 2,74 bp | 05 Uhr: 2,72 | 11 Uhr: 3,93 | 1,45 |
| XRP | 18,01 bp | 04 Uhr: 16,03 | 11 Uhr: 19,94 | 1,24 |
| DOGE | 34,34 bp | 09 Uhr: 27,11 | 22 Uhr: 38,28 | 1,41 |

DOGE liegt rund um die Uhr bei 27–38 bp. Mein Vorbehalt „gemessen zur dünnsten Stunde" trägt also
nicht — die Tageszeit erklärt höchstens Faktor 1,2 bis 2,7.

### 2. …aber der Spread schwankt von Messung zu Messung extrem — DAS korrigiert mich

| Markt | Median | 75 % | 95 % | Maximum | Anteil über 2× Median |
|---|---|---|---|---|---|
| BTC | 0,62 | 1,86 | 6,75 | **274,3** | 37,1 % |
| SOL | 2,74 | 9,23 | 18,33 | 83,3 | 36,5 % |
| DOGE | 34,34 | 45,77 | 72,12 | **1009,7** | 6,1 % |

**Bei BTC liegen 37 % aller Messungen über dem Doppelten des Medians.** Meine Momentaufnahme von
4,8 bp war damit kein Ausreißer, sondern ein normaler Zug aus einer schiefen Verteilung.

**Folge: Die dYdX-Alt-Zahlen (LINK 1,78 %, AVAX 2,32 %) sind sehr wahrscheinlich überzeichnet** —
Einzelziehungen aus derselben Verteilung. Das Urteil „dYdX: Alts unbezahlbar" steht damit **unter
Vorbehalt**, bis der 20-Markt-Sammler Mediane liefert. Nicht die Tageszeit war das Problem, sondern
dass eine einzelne Messung nichts über den Median sagt.

### 3. Die Buchtiefe ist bei unserer Größe nie das Problem

| Markt | Median Tiefe (Top 10) | schwächster je gemessener Moment |
|---|---|---|
| DOGE | 4.111.278 $ | 408 $ |
| SOL | 4.088.899 $ | 12.983 $ |
| BTC | 460.699 $ | 675 $ |

Selbst im dünnsten je gemessenen Moment übersteigt die Tiefe unsere 180-$-Order. **Die Kosten sind
vollständig Spread, nicht Größe** — Skalierung auf 500 oder 1.000 $ ändert daran nichts.

### 4. Das Ungleichgewicht wird bei engem Spread NICHT besser

Getestet nach Spread-Dritteln (Horizont 15 min): BTC 2,74 / 0,95 / 2,14 bp — kein Muster.
**ETH ist bei engem Spread sogar negativ (−2,33 bp).** In drei von fünf Märkten ist das Signal
*größer, wenn der Spread weiter ist* — also genau dort, wo es sich nicht ernten lässt.
Damit ist auch die letzte Hoffnung für diese Signalklasse erledigt.

### Was praktisch bleibt

Aus Befund 2 folgt etwas Verwertbares: BTCs 25-%-Quantil liegt bei **0,16 bp** gegen 0,62 im Median.
Wer vor dem Überqueren des Spreads auf einen engen Moment wartet, spart rund 0,5 bp je Seite —
**kostenlos, unabhängig vom Handelsplatz**. Bei ~1,3 Trades/Tag ist das kein Spielentscheider,
aber es ist das einzige, was diese Datei für die Ausführung hergibt.

**Bilanz der Sammlung:** Die Imbalance-Frage ist abschließend beantwortet (nein, in jeder Variante).
Der eigentliche Ertrag sind die Spread- und Tiefenverteilungen — und die Erkenntnis, dass
Einzelmessungen von Spreads systematisch in die Irre führen. Genau deshalb misst der
Hyperliquid-Sammler jetzt fortlaufend statt einmalig.

---

## 22.08.2026 (nachts, 3) — Hyperliquid-Kostensammler + Dashboard gebaut

Die Hyperliquid-Zahlen stammten aus **einer** Momentaufnahme. Jetzt wird laufend gemessen.

### Was gebaut wurde

- **`hl_collect.py`** — Session `hl`. Misst alle 5 Minuten für alle 20 Coins: Spread, Slippage bei
  180/500/1000 $ aus dem echten Orderbuch, Funding-Rate, und rechnet daraus den Roundtrip.
  Read-only, kein Konto, kein Handel.
- **`hl/hl_dashboard.html`** auf **Port 8099** — Balkendiagramm aller Coins gegen die
  Break-even-Linie von 67 bp, Kacheln, vollständige Tabelle. Aktualisiert sich jede Minute.

### Welche Lehren bewusst eingebaut sind

| Lehre aus | Umsetzung |
|---|---|
| Risk-Agent-Fehlalarm (halb geschriebene JSON) | jede JSON atomar über `tmp + os.replace` |
| insider_paper (Import startete alles) | `if __name__ == "__main__"`-Schutz |
| bz_watch (stiller Ausfall unsichtbar) | Heartbeat bei **jedem** Zyklus, auch ohne Befund |
| /tmp-Logs als Cron-Nachweis | Funktionsprüfung nutzt `hl/heartbeat.json`, nicht das Log |
| Mehrfach-Instanzen (WS-406) | `health.acquire_singleton("hl_collect")` — **getestet** |
| stale Mac-Kopie (22.07., Bots wiederbelebt) | Eintrag in `start_all.sh` **und** `monitor_agent.BOTS`, |
| | Whitelist beider Stellen vor dem Deploy verglichen |
| feedparser-Hänger | harte Timeouts auf allen Netzaufrufen |
| stille Ausnahmen | Fehler werden gezählt und im Heartbeat ausgewiesen |
| dydx-Log (260 MB/Monat bei 20 Märkten) | **5-Minuten-Takt statt 15 s** + Monatsdateien |
| neue Dashboards ohne ufw-Regel | Port 8099 für LAN + VPN freigegeben |

**Zur Taktfrage:** Für Kostenmediane reicht ein 5-Minuten-Takt. Nicht feiner sammeln, als die Frage
es verlangt — sonst entsteht wieder eine 60-MB-Datei, die niemand auswertet.

### Getestet, nicht nur gebaut

- Erster Durchlauf: 20 Märkte, 0 Fehler, 9 Sekunden
- Doppelstart-Sperre greift (zweite Instanz beendet sich)
- Dashboard liefert HTTP 200, `config.py` bleibt **403**
- **Absturztest:** Session abgeschossen → Watchdog erkannte es nach **10 s**, Telegram-Alarm,
  Neustart, Sammler arbeitet weiter
- Funktionsprüfung: **21 Prüfungen, 0 Abweichungen** (Dashboard 8099 + Heartbeat-Frische ergänzt)

### Erste Messung

18 von 20 Coins liegen unter der Break-even-Schwelle. Günstigste: BTC 12,6 bp, DOT 14,4 bp,
TRUMP 15,7 bp. **Belastbar wird das erst in einigen Tagen** — ein Median über wenige Runden sagt
über das Funding-Regime nichts.

**Erreichbar:** http://trading2025.fritz.box:8099

---

## 22.08.2026 (nachts, 2) — Hyperliquid vermessen: der erste Handelsplatz, der passt

Gleiches Verfahren wie bei Jupiter und dYdX. Ergebnis: **Hyperliquid erfüllt beide Bedingungen.**

### Abdeckung und Kosten

**Alle 20 Coins handelbar** (232 Perp-Märkte). Die Micro-Preis-Memes laufen als 1000er-Kontrakte —
kSHIB, kPEPE, kBONK — was das Rundungsproblem bei 0,00000319 $ elegant löst.

Gebühren Basisstufe: **0,045 % Taker / 0,015 % Maker** je Seite. Slippage einer 180-$-Order, am
Orderbuch gemessen — und der Unterschied zu dYdX ist dramatisch:

| Coin | Hyperliquid | dYdX | Faktor |
|---|---|---|---|
| LINK | 0,008 % | 1,782 % | 220× |
| AVAX | 0,004 % | 2,322 % | 580× |
| ADA | 0,013 % | 1,088 % | 84× |
| POL | 0,048 % | 0,512 % | 11× |
| RENDER | 0,055 % | 0,263 % | 5× |

Schlechtester Wert überhaupt: WIF 0,060 %. Auf dYdX war das der **beste** Alt-Wert.

### Funding — die eigentliche Kostenart bei Perpetuals

Nicht geschätzt, sondern aus der Historie geholt (`fundingHistory`, 500 Stunden je Coin über den
Handelszeitraum). Befund: Funding lag fast durchgehend am **Bodensatz** von +0,00125 %/h (dem reinen
Zinsanteil) = **0,035 % je 28-Stunden-Position**. Vernachlässigbar.

**Aber Vorsicht — das ist regimeabhängig.** Die Momentaufnahme von heute Nacht zeigt deutlich höhere
Sätze: DOGE +0,034 %/h = **0,94 % je Position**, AAVE 0,65 %, LINK 0,43 %. In einem heißen Markt
zahlen Longs kräftig. Ein Long-only-Bot auf Perpetuals hat damit einen strukturellen Gegenwind,
den Spot-Handel nicht kennt.

### Das Ergebnis der 271 Trades

| Handelsplatz / Annahme | Ergebnis | t |
|---|---|---|
| vor Kosten | +378,14 $ | — |
| **Hyperliquid, Taker + echtes Funding** | **+301,82 $** | **2,83 ✓** |
| Hyperliquid, Maker + echtes Funding | +335,13 $ | 3,14 ✓ |
| Hyperliquid, Taker ohne Funding | +313,42 $ | 2,94 ✓ |
| Hyperliquid bei heutigem (hohem) Funding | +199,85 $ | 1,85 |
| Jupiter Perps (nur 3 Coins) | +226,32 $ | 2,11 |
| **wie gehandelt (Kraken 0,62 %)** | **+33,91 $** | 0,25 |
| dYdX (Momentaufnahme) | −219,56 $ | −1,85 |

**Zum ersten Mal überlebt der Edge die Ausführung statistisch belegt** — und zwar mit dem vollen
Universum, nicht nur auf drei Majors. Gesamtkosten je Roundtrip: rund **0,13–0,24 %** gegen eine
Break-even-Schwelle von 0,67 %.

### Vorbehalte, ausdrücklich

1. **Slippage aus einer Momentaufnahme** (00:40, dünne Stunde) — wie bei dYdX. Hier wirkt der Fehler
   allerdings zu unseren Ungunsten, die echten Kosten dürften eher niedriger sein. Trotzdem: über
   Zeit messen, bevor darauf etwas gebaut wird.
2. **Funding war im Messzeitraum am Boden.** Bei anziehendem Markt kehrt sich das um (siehe oben).
   Das ist das größte offene Risiko dieser Rechnung.
3. **Kostentausch auf denselben Daten**, aus denen die Parameter stammen. Kein Vorwärtstest.
4. **Perpetuals sind kein Spot:** Liquidationsrisiko, und der Bot ist long-only.
5. Zugang, Steuerrecht und Gegenparteirisiko einer Offshore-DEX sind **nicht** geprüft — das ist
   keine technische Frage und gehört Andreas.

### Stand der Venue-Suche

| Platz | Coins | Kosten Roundtrip | Ergebnis | Urteil |
|---|---|---|---|---|
| Kraken/Alpaca (heute) | 20/20 | 62 bp | +34 $ | genau auf Break-even |
| Jupiter Perps | 3/20 | 26 bp | +226 $ | zu wenig Coins |
| dYdX | 20/20 | 11–366 bp | −220 $ | Alts unbezahlbar (vorläufig) |
| **Hyperliquid** | **20/20** | **13–24 bp** | **+302 $** | **erfüllt beide Bedingungen** |

---

## 22.08.2026 (nachts) — dYdX geprüft: richtiges Universum, falscher Spread

Beide offenen Fragen aus der Kostenrechnung durchgerechnet.

### Frage 1: Sagt Orderbuch-Ungleichgewicht die nächsten Minuten voraus?

Grundlage: 636.376 Messpunkte aus 28 Tagen (`dydx/imbalance_log.csv`), 5 Märkte, 3 Buchtiefen,
3 Horizonte = 45 Einzelmessungen.

**Die Richtung stimmt ausnahmslos** — alle 45 Spannen zwischen hoher und niedriger Ungleichgewichts-
Gruppe sind positiv. Das ist bemerkenswert konsistent und kein Zufall.

**Die Größe reicht bei weitem nicht.** Spanne hoch-minus-niedrig, bester Fall je Markt (Buchtiefe 1,
Horizont 15 min): DOGE 3,74 bp · XRP 3,79 bp · BTC 2,40 bp · SOL 2,11 bp · ETH 1,37 bp.
**Kosten: 10 bp Taker-Roundtrip.** Der beste Wert ist also 2,6-mal zu klein.

Zusätzlich der Widerspruch, der es endgültig erledigt: Am stärksten ist das Signal in den **dünnsten**
Märkten (DOGE, XRP) — und genau dort ist der Spread mit 34 bp bzw. 18 bp um ein Vielfaches größer
als das Signal selbst. Man müsste 34 bp zahlen, um 3,7 bp zu ernten.

**Urteil: als eigenständiges Signal tot.** Eine Buchtiefe von 1 ist stärker als 5 oder 10 (wie
theoretisch erwartet), was für die Messung spricht — nur eben nicht für den Handel. *Kostenlos
nutzbar bliebe es als Feinsteuerung des Zeitpunkts innerhalb eines ohnehin beschlossenen Trades.*

### Frage 2: Sind die Alt-Coins auf dYdX liquide genug?

**Das Universum stimmt: alle 20 Coins des Bots sind handelbar** (Jupiter hatte 3). Aber die Umsätze
brechen nach den Majors ab: BTC 47,4 Mio. $, ETH 34,9 Mio. — dann SOL 787k, LINK 101k, DOT 32k,
ARB 6,8k, RENDER 4,4k, **WIF 0**.

Slippage einer 180-$-Kauforder, direkt am Orderbuch gemessen: BTC 0,024 % · ETH 0,047 % ·
SOL 0,075 % · XRP 0,088 % — hervorragend. Dagegen LINK 1,78 % · ADA 1,09 % · **AVAX 2,32 %**.

Mit echten Kosten je Coin auf die 271 Trades angewandt:

| Auswahl | Trades | vor Kosten | auf dYdX | t |
|---|---|---|---|---|
| alle 20 Coins | 271 | +370,43 $ | **−219,56 $** | −1,85 |
| nur Coins unter 67 bp | 98 | +99,98 $ | +55,46 $ | 0,99 |
| nur BTC/ETH/SOL/XRP | 78 | +91,17 $ | +62,77 $ | 1,23 |
| die übrigen 16 | 193 | +279,26 $ | **−282,33 $** | **−2,66** |

**Auf dYdX wäre das Ergebnis schlechter als heute.** Dieselbe Sackgasse wie bei Jupiter, nur aus
dem umgekehrten Grund: Dort fehlten die Coins, hier sind sie da, aber unbezahlbar.

### Der Vorbehalt, der das Urteil noch kippen kann

**15 der 20 Spreads stammen aus EINER Momentaufnahme um 00:30** — der dünnsten Stunde. Die Gegenprobe
zeigt, wie stark das verzerrt: Für BTC maß die Momentaufnahme 4,8 bp, der 28-Tage-Median liegt bei
**0,6 bp** — Faktor 8. Wären die Alt-Spreads ähnlich überzeichnet, läge LINK bei 44 statt 356 bp und
damit unter der Break-even-Schwelle. **Das Urteil steht also unter Vorbehalt.**

**Deshalb umgesetzt:** `dydx_collect.py` von 5 auf **alle 20 Märkte** erweitert (Takt bleibt 15 s),
alte Datei als `dydx/imbalance_log_5maerkte_20260822.csv` gesichert. In wenigen Tagen liegen echte
Mediane für die Alts vor, dann lässt sich die Tabelle oben mit belastbaren Zahlen neu rechnen.

### Zwischenstand der Venue-Suche

| Handelsplatz | Coins | Kosten | Urteil |
|---|---|---|---|
| Kraken/Alpaca (heute) | alle | 62 bp | genau auf Break-even → Nullergebnis |
| Jupiter Perps | 3 von 20 | 26 bp | zu wenig Coins, Edge nicht dabei |
| dYdX | **20 von 20** | 11–366 bp | Majors top, Alts (vorläufig) unbezahlbar |

Gesucht bleibt: **unter 67 bp Roundtrip bei den Alt-Coins.** Nächster Kandidat wäre Hyperliquid.

---

## 22.08.2026 — Kostenmodell Jupiter Perps durchgerechnet: der Bot HAT einen Vorteil

### Das Ergebnis, das eine frühere Aussage korrigiert

In der Depot-Analyse vom 21.08. stand: „Beim Crypto-Bot lässt sich ein Vorteil ausschließen."
**Das war zu grob.** Richtig ist: kein Vorteil **nach diesen Kosten**. Rechnet man die simulierten
Kosten (0,26 % Gebühr + 0,05 % Slippage je Seite = 0,62 % Roundtrip) je Trade zurück:

| Betrachtung | Summe | t-Wert | Urteil |
|---|---|---|---|
| wie gehandelt (0,62 %) | +26,77 $ | 0,25 | nichts |
| **vor Kosten** | **+370,43 $** | **3,49** | **belegt** |
| bei Jupiter-Kosten (0,26 %) | +226,32 $ | 2,11 | knapp belegt |

**Das Einstiegssignal trägt also.** Die Kosten fressen es vollständig auf. Break-even liegt bei rund
**0,67 % Roundtrip** — die aktuellen 0,62 % liegen exakt darauf, deshalb das Nullergebnis.

### Methodik

Einsatz je Trade aus `profit/pct` rekonstruiert (254 von 271 Trades), sonst aus der Sizing-Regel
(6 % bzw. 3 % Kapital × `size_mult` aus `esnap`). Median-Einsatz 179 $. **Haltedauer 28 h**, zweifach
hergeleitet: Little's Gesetz (8 Plätze × 43,7 Tage / 271 Trades = 31 h) und das Alter der 8 offenen
Positionen (Mittel 13,9 h ≈ halbe Gesamtdauer bei laufenden Positionen). Trade-Datensätze speichern
**keine Einstiegszeit** — das ist eine Lücke, die für künftige Auswertungen zu schließen wäre.

Jupiter-Parameter recherchiert, nicht geschätzt: **0,06 % je Seite** Basisgebühr, dazu stündliche
Leihgebühr statt Funding: `Auslastung × 0,01 %/h × Positionsgröße` (max. 0,01 %/h ≈ 88 % p. a.).

### Warum es trotzdem nicht funktioniert

**Der Jupiter-Liquiditätspool enthält nur SOL, ETH, wBTC und Stablecoins.** Von den 20 Coins des Bots
sind **3 handelbar — 55 von 271 Trades (20 %)**. Und genau dort sitzt der Vorteil nicht:

| Gruppe | vor Kosten | t | auf Jupiter | t |
|---|---|---|---|---|
| SOL/ETH/BTC (handelbar) | +76,60 $ | 1,75 | +46,64 $ | 1,06 |
| die übrigen 17 Coins | +293,84 $ | **3,03** | +179,68 $ | 1,84 |

**Der Vorteil steckt in den kleineren Alts — die Jupiter Perps nicht anbietet.**

### Und alles hängt an der Slippage

Das Jupiter-Modell rechnet nur Gebühren. Mit realistischer On-Chain-Slippage:

| Slippage je Seite | Auslastung 30 % | 50 % | 80 % | 100 % |
|---|---|---|---|---|
| 0,00 % | +257 $ ✓ | +226 $ ✓ | +180 $ | +149 $ |
| 0,10 % | +146 $ | +115 $ | +69 $ | +38 $ |
| **0,20 %** | **+36 $** | **+5 $** | −42 $ | −73 $ |
| 0,50 % | −297 $ | −328 $ | −375 $ | −406 $ |

Ab **0,2 % Slippage je Seite ist der Vorteil weg**. Genau daran ist der DEX-Zweig schon einmal
gescheitert — und Alt-Coins on-chain haben mehr Slippage, nicht weniger.

### Fazit und was daraus folgt

Jupiter Perps ist **nicht** die Antwort: falsches Handelsuniversum. Die gesuchte Eigenschaft ist
jetzt aber präzise benannt — **ein Handelsplatz mit unter 0,67 % Roundtrip UND den Alt-Coins**.
Damit rücken die beiden anderen Einträge aus [[project-execution-leads]] in den Vordergrund:
**dYdX** (Maker-Gebühren, steht seit dem 02.08. ungeprüft auf der Liste) und Hyperliquid.

**Vorbehalte, ausdrücklich:** Die Kosten wurden auf denselben Daten getauscht, aus denen die
Parameter stammen — kein Vorwärtstest. 44 Tage. Der t-Wert von 2,11 für Jupiter ist knapp. Und
Perps sind kein Spot: Leihgebühr läuft richtungsunabhängig, dazu Liquidationsrisiko bei Hebel.

### Ausbeute der letzten Folgen: null

Rückwirkend alle 21 gespeicherten Transkripte gegen die Themenfilter geprüft:

- **#092 (21.08.)**: 2 Treffer, beide im Kontext **Fehltreffer** — „tokenisiert" steht in einer
  Passage über ein Trump-Treffen mit Krypto-Vertretern, „liquidation" in einem allgemeinen
  Marktüberblick. Nichts Verwertbares.
- **#091 (14.08.)**: **0 Treffer.**
- **#089**: nur „benchmark" (Fed als Zinsvergleich) und „stichtag" (Bewertungstermine) — beides
  aus der schwachen Wortliste, kein Mechanismus.

**Bilanz über den Gesamtbestand:** 21 Folgen, 13 mit hartem Treffer. Die verwertbaren stammen aber
alle aus **früheren** Folgen: #050/051/053/054 (SOFR, Repo), #060 (Liquiditätsspritze, Rebalancing),
#085 (Quartalsende, Russell), #086 (Crack Spread), #087 (Repo, tokenisiert). Diese Liste steht seit
02.08. unbearbeitet in [[project-execution-leads]] — **die Quelle liefert derzeit nichts Neues, und
das Alte ist ungeprüft.** Der Wächter läuft weiter (Kosten: ein Abruf täglich).

### Neue Quelle: Blockzocker

**`blockzocker.de` gibt es nicht** — die DENIC führt die Domain als *frei*. Gemeint war
**blockzocker.com**: „Krypto-Trading lernen mit Hermann dem Banker", Herausgeber **Paul Brandenburg
LLC** — also derselbe Verlag wie Nacktes Geld. Wöchentliche Folgen, dienstags.

**Was geprüft wurde, bevor etwas gebaut wurde:**
- Nicht auf derselben PeerTube-Instanz wie Nacktes Geld (Suche: 0 Treffer) — der Untertitel-Weg
  von `ng_watch.py` funktioniert hier also nicht.
- Die Seite ist **zugangsbeschränkt** (`/login`, `/register`, Ticket). Im öffentlichen Quelltext
  einer Folgenseite stehen **weder Untertitel noch Videoquelle**.
- Öffentlich sind: 9 kostenlose Folgen (S01E01–E09) und die **Trailer-Seiten** aller übrigen, die
  Folgennummer, Titel und Datum im Seitentitel tragen.

**Daraus `bz_watch.py`** — meldet neue Folgen per Telegram, liest **ausschließlich öffentliche
Seiten**, meldet sich an keinem Konto an und holt keine Inhalte hinter der Bezahlschranke.
Der Nutzen ist entsprechend begrenzt und wird in der Meldung auch so benannt: man erfährt, *dass*
eine Folge da ist und wie sie heißt — nicht, ob sie etwas taugt.

**Umgesetzt:** Bestand 25 Folgen erfasst (S01E01–E26). Zwei Wege nötig, weil freie Folgen unter
`/watch/<id>` liegen und kostenpflichtige nur einen Trailer unter `/watch/<id>/trailer` haben —
ohne den zweiten Weg fehlten im ersten Anlauf genau die neun freien Folgen. **S01E10 fehlt
tatsächlich**: ID 37 liefert auf beiden Wegen 302, der Betreiber hat sie nicht veröffentlicht.
Cron täglich 08:25, Zeitstempel wird bei **jedem** Lauf geschrieben (sonst wäre die Zustandsdatei
zwischen zwei Folgen sechs Tage alt und ein stiller Ausfall nicht von „diese Woche kam nichts"
unterscheidbar). In `funktionspruefung.py` eingetragen → jetzt **18 Prüfungen**, 0 Abweichungen.

### Nebenbefund

Das Datum von S01E06 lautet auf der Seite **„31.02.2026"** — ein Tag, den es nicht gibt. Fehler des
Betreibers; wird als Text übernommen, nicht als Datum geparst, stört also nichts.

---

## 21.08.2026 (nachmittags) — Voll-Analyse aller vier Depots

**Bericht:** https://claude.ai/code/artifact/8787aed0-ffda-4496-a202-6305f127ade2

### Datenlage

27 Tage seit dem Reset (Super/Crypto 25.07., Insider/Fundament 26.07.). 656 Kursmesspunkte,
283 abgeschlossene Trades, Vergleichskurse über yfinance für denselben Zeitraum.

### Die Stände

| Depot | Stand | seit Start | Rückgang max | Schwankung p.a. |
|---|---|---|---|---|
| Insider | 10.785,43 $ | +7,85 % | −2,43 % | 22,4 % |
| Fundament | 10.391,62 $ | +3,92 % | −1,00 % | 8,9 % |
| Crypto | 5.052,86 $ | +1,06 % | −3,50 % | 15,0 % |
| Super | 5.019,82 $ | +0,40 % | −0,12 % | 0,9 % |

Vergleich im selben Zeitraum: S&P 500 +3,18 %, **Bitcoin +20,19 %**, Nebenwerte +1,63 %, Gold +10,85 %.

### Der zentrale Befund: der Crypto-Bot hat keinen Vorteil

**269 Trades ergaben zusammen +0,63 $.** Der sichtbare Depotgewinn (+52,86 $) ist fast vollständig
der Buchwert von 7 offenen Positionen (+58,89 $) — also das, was auch ohne jeden Handel entstanden
wäre. Bitcoin stieg im selben Zeitraum um 20 %.

Statistisch: Ergebnis je Trade +0,002 $ bei Streuung 6,43 $ → **t = 0,01**. Für einen Nachweis
wären ~30 Mio. Trades nötig. Das Verfahren ist damit nicht „noch nicht belegt", sondern in dieser
Form **nicht belegbar**. Trefferquote 46,5 %, Chance-Risiko 1,15, Gewinnfaktor 1,00.

Teilbefunde: Stop-Loss-Ausstiege kosten −492 $ und fressen auf, was Trailing (+371 $) und PSAR
(+171 $) verdienen — das Problem liegt am **Einstieg, nicht am Ausstieg**. Blitz-Käufe verlieren
trotz der Juni-Drosselung weiter: 42 Trades, −30,80 $, nur 28,6 % Treffer. Ohne sie stünde der
Bot bei +31 $.

### Die anderen drei

- **Super-Bot:** 14 Trades in 27 Tagen, +0,40 % gegen +3,18 % beim S&P. Lehnt fast alles mit
  „Stimmung zu schwach" ab. Für einen Nachweis wären ~116 Trades nötig ≈ 8 Monate beim aktuellen Tempo.
- **Insider:** +7,85 % gegen +3,18 % (S&P) bzw. +1,63 % (IWM). **Der Vorsprung ist zu groß, um echt
  zu sein**: der Backtest verspricht 11 pp p.a., auf 18 Handelstage wären das ~0,8 pp — gemessen
  wurden 6,2 pp, also das Achtfache. Top 5 von 30 Titeln tragen 64 % des Ergebnisses. Median
  allerdings +8,35 % bei 21/30 Gewinnern, also nicht nur zwei Glückstreffer. Urteil bleibt offen
  bis zum Ende des 3-Monats-Vorwärtstests (Tag 25 von 90).
- **Fundament:** einziges Depot mit einem *belegbaren* Ergebnis, weil es Bauart-Treue misst statt
  Vorhersage. −0,49 pp gegen die reine Mischung, vollständig zerlegt: −0,025 Handelskosten,
  −0,46 Rückführung, **kein unerklärter Rest**.

### Betrieb

Seit dem Reset **kein einziger Risiko-Halt** — kein Tagesverlust-Stopp, kein Drawdown-Stopp, keine
Eskalation. Größter Rückgang des kombinierten Depots 1,67 % bei einer Bremse, die erst bei 15 % greift.

### Fazit

Der Betrieb ist gelöst, die Strategiefrage ist offen. Drei Depots stehen im Plus, weil die Märkte
gestiegen sind — nicht nachweisbar wegen der Verfahren. Beim Crypto-Bot lässt sich ein Vorteil
inzwischen sogar ausschließen.

### Nachtrag: Insider gegen echte Börsenkurse zurückgerechnet — BUG GEFUNDEN

Auf Andreas' Einwand („wieso kann Insider nicht stimmen? kann man das nicht zurückrechnen?") alle
30 Positionen gegen die tatsächlichen Tageskurse geprüft. Zwei getrennte Ergebnisse:

**1. Die Bewertung ist korrekt.** Aktuelle Kurse stimmen auf **0,000 %** mit yfinance überein,
Depotwert exakt nachgerechnet.

**2. Die Einstiegskurse sind falsch — echter Bug.** Sie stammen vom **23.07.**, eingetragen als
Kauf vom **27.07.** Belege: bei 29 von 30 Titeln passt der Einstieg auf <0,05 % zum Schlusskurs
des 23.07.; bei **18 von 30 liegt er außerhalb der Handelsspanne des 27.07.** (14× billiger als
das Tagestief, 4× teurer als das Hoch) — so nicht handelbar.

**Ursache:** `prices()` in `insider_paper.py` gab nur `cl[-1]` zurück und **verwarf das Datum des
Kursbalkens**. Der Aufrufer konnte einen veralteten Kurs nicht erkennen. Exakt die Fehlerklasse
aus [[project-known-gotchas]] („Freshness-Phantom": Entry aus alter Quelle, Bewertung live) —
dritter Fall nach Contrarian-Clone und DEX-Papierhandel.

**Wirkung:** ~1,6 Prozentpunkte Scheingewinn. Ehrlich gerechnet +6,22 % statt +7,85 % (Stand 20.08.).

**Behoben:** `prices()` liefert `stand` (Balkendatum) mit; neue `kurse_pruefen()` blockiert eine
Umschichtung, wenn die Daten älter als 3 Kalendertage sind (Montag mit Freitagsschluss bleibt
erlaubt, der 4-Tage-Fall vom 27.07. wird geblockt) und meldet das per Telegram. Getestet mit fünf
Fällen. **Nebenbei behoben:** die Datei hatte keinen `__main__`-Schutz — ein bloßes
`import insider_paper` startete den kompletten Depotlauf (beim Testen selbst ausgelöst).

### Und die Korrektur meiner eigenen Argumentation

Meine Begründung „der Vorsprung ist 8× so groß wie die Backtest-Erwartung, also Rauschen" war
**falsch geschlossen**. Dass eine Kurzfrist-Rendite die annualisierte Erwartung übersteigt, ist
normal — Rauschen wächst mit √t, der Erwartungswert mit t. Richtig gerechnet (Fenster 27.07.–21.08.,
ehrliche Einstiege):

| Prüfung | Wert |
|---|---|
| Depot | +7,50 % |
| IWM | +2,03 % |
| Vorsprung | +5,47 pp |
| Zufallsspanne 19 Tage (1σ) | ± 3,53 pp → Vorsprung = 1,5σ |
| t über Tagesrenditen | 1,50 (nicht belegt) |
| t über die 30 Einzeltitel | 2,08 (knapp belegt) |
| Titel besser als IWM | 19 von 30 |

**Richtiges Urteil: offen.** Ein Zufallsergebnis dieser Größe tritt in etwa 1 von 15 Fällen auf —
zu häufig für einen Beleg, zu selten zum Abtun. Der eigentliche Grund, warum die Messung nichts
entscheidet: die **Messunsicherheit (±3,5 pp) übersteigt das erwartete Signal (0,8 pp) um das
Vierfache**. Nicht „die Zahl ist zu gut".

### Offen zur Entscheidung

Die 30 bestehenden Positionen behalten ihre zu günstigen Einstiegskurse. Optionen: so lassen und
den Versatz bei jeder Auswertung mitdenken, oder Einstiege auf den Schlusskurs des 27.07. korrigieren
(Depot fiele rechnerisch um ~1,6 pp), oder das Depot neu aufsetzen. **Andreas' Entscheidung** —
Kapitalstände zu ändern fällt nicht unter Betrieb und Reparatur.

---

## 21.08.2026 — Monitor-Meldungen geprüft, Systemupdates, Desktop abgeschaltet

### Was geprüft wurde — und was dabei herauskam

**Es gab keine Überlastung.** Die Annahme ließ sich nicht bestätigen, im Gegenteil:
`vcgencmd get_throttled` = **0x0** (seit dem Hochfahren nie gedrosselt, weder thermisch noch wegen
Spannung), Temperatur 44,8 °C, RAM 26 %, Swap 0 MB, keine OOM-Einträge, CPU im Monitor-Log
durchgehend 0–3 % mit einer einzelnen Spitze auf 31 %.

**Die Meldungsflut kam von woanders:** 58 der Ereignisse in 14 Tagen waren `NO_TRADES`.
Nachgerechnet an 30 Tagen / 172 Trades: Handelspausen über 8 Stunden sind der **Normalfall**
(Nächte, Wochenenden, ruhige Märkte) — Median 2,3 h, aber 29 Pausen über 8 h. Der Alarm feuerte
ab 8 h und dann alle 2 h erneut → ~104 Meldungen je 30 Tage, praktisch alle unbegründet.

**Schwelle datengestützt gesetzt** (`agents/monitor_agent.py`): `NO_TRADES_HOURS` 8 → **24**,
`NO_TRADES_COOLDOWN` 2 h → **12 h**. Bei 24 h bleiben 2 Fälle in 30 Tagen übrig, also ~3 Meldungen
statt 104. Der Gesundheitszustand hängt nicht an dieser Meldung: ein hängender Bot fällt vorher über
`check_stale()` (15 min) und den Watchdog im Bot auf — `NO_TRADES` ist der langsame Rückfall.

**Die 3 „Abstürze" im Protokoll waren meine eigenen Session-Neustarts** vom 12./13.08. Der Monitor hat
sie korrekt erkannt und neu gestartet, die Doppelstart-Sperre hat gegriffen. Kein echter Ausfall.

### Der eigentliche Fund

Der Pi fuhr einen **vollständigen Grafik-Desktop** hoch, den niemand sieht: beide HDMI-Anschlüsse
`disconnected`, VNC inaktiv und auf keinem Port lauschend. Kosten: ~310 MB RAM für labwc, wf-panel,
pcmanfm und drei xdg-portal-Prozesse — und 25 der 29 offenen Updates waren Chromium, Firefox, Mesa
und Kamera-Treiber, die für den Handel keine Rolle spielen.

Nach Rücksprache auf **Konsolenbetrieb** umgestellt (`systemctl set-default multi-user.target`).
Ein Befehl, jederzeit umkehrbar über `graphical.target`.

### Updates

**0 Sicherheitsupdates waren offen** — `unattended-upgrades` erledigt die täglich und nachweislich
(Einträge 15., 19., 20.08.). Die 29 offenen Pakete waren reine Desktop-Software. Alle eingespielt
(`apt-get upgrade` mit `--force-confold`), danach `autoremove --purge`: drei alte Kernel entfernt.

**Ergebnis nach Neustart:** RAM 26 % → **16 %** (599 statt 1.038 MB belegt), Platte 22 % → **18 %**
(48 GB frei). Alle 12 Sessions kamen über systemd/`start_all.sh` von selbst hoch, Positionen aus den
Zustandsdateien wiederhergestellt (Super 3, Crypto 8), Funktionsprüfung **17/17 ohne Abweichung**.

### Nachtrag am selben Tag — Einwand von Andreas: „es gab öfter Alarm wegen Prozessorüberlastung"

**Der Einwand war berechtigt, meine Analyse war es nicht.** Zwei Mängel:
1. Ich hatte vom Monitor-Log nur die **letzten 20 Zeilen** gelesen — Spitzen weiter oben wären
   unsichtbar geblieben.
2. `throttled=0x0` belegt nur, dass der Pi nie *gedrosselt* hat (Hitze/Spannung). Ein Prozessor kann
   dauerhaft bei 100 % laufen, ohne zu drosseln. Das war nie ein Gegenbeweis.

**Warum die Alarme nirgends auffindbar waren — der eigentliche Befund:** `system_health()` schickt bei
Überschreitung ausschließlich ein `tg(...)` und schreibt **nichts** ins `health_log.csv`.
`/tmp/monitor.log` wird bei jedem Monitor-Neustart überschrieben und beim Reboot gelöscht, das
systemd-Journal enthält nur den laufenden Start. **Der Telegram-Verlauf war das einzige Archiv.**

**Behoben, zweistufig:**
- `SYS_ALERT` wird jetzt ins `health_log.csv` geschrieben — **mit den drei größten Verbrauchern**
  (`top_prozesse()`, nur im Alarmfall aufgerufen). Der nächste Alarm sagt also, *womit* es eng wurde.
- Neu `agents/system_verlauf.csv`: alle 5 Minuten CPU/RAM/Platte **plus die Lastdurchschnitte des
  Kernels** (1/5/15 min), ab 50 % CPU jede Minute. Begründung: `cpu_percent()` misst nur 0,5 s je
  Minute — eine zweiminütige Spitze kann komplett durchrutschen. Die Lastdurchschnitte sind kumulativ
  und können das nicht. Beide Dateien werden nachts nach GitHub gesichert.

**Selbst verursachter Fehler, gefunden und behoben:** die Desktop-Abschaltung ließ
`rpi-connect-wayvnc` in eine Neustartschleife laufen — **689 Fehlversuche in einer Stunde**.
Gestoppt und maskiert. Ehrliche Einordnung: der Leerlauf lag dabei bei 97 %, die Schleife flutete das
Journal, nicht den Prozessor — als Erklärung für die alten Alarme taugt sie nicht.

**Korrektur einer Aussage, auf der eine Entscheidung beruhte:** ich hatte gemeldet „VNC ist aus, kein
Port offen". Unvollständig — **Raspberry Pi Connect war angemeldet, Bildschirmfreigabe erlaubt**; die
läuft getunnelt, nicht über Port 5900, deshalb hat mein Test sie nicht gesehen. Der Konsolenbetrieb
hat diese Möglichkeit entfernt (der Kommandozeilen-Fernzugriff über Pi Connect läuft weiter).

**Neu `bildschirm.sh` (an|aus|status):** startet Desktop + Freigabe bei Bedarf und beendet sie wieder.
Ändert bewusst **nicht** das Startziel — nach einem Neustart ist der Pi wieder in der Konsole, das
Ausschalten kann man also nicht vergessen. Nutzt gezielt `systemctl start/stop lightdm` statt
`systemctl isolate`, damit die Bot-Sitzungen garantiert unberührt bleiben. In beide Richtungen
getestet: Freigabe wird aktiv, keine Fehlversuche, durchgehend 12 Bot-Sitzungen.

**Ursache der alten Alarme: weiterhin offen.** Die Beweise existieren nur in Andreas' Telegram, ein
Zeitmuster war nicht mehr erinnerlich. Ab jetzt beantwortet sich die Frage beim nächsten Auftreten
von selbst. Verdächtige nach Zeitfenster: 22:30 SEC-Abruf und 23:15 Insider-Papierdepot (verarbeiten
10-MB-CSVs), Sonntag 00:00 Optimierungs-Agent (Walk-Forward über Jahre von Kursdaten).

### Was offen ist

- **EEPROM-Firmware**: `rpi-eeprom-update` meldet weiterhin *UPDATE AVAILABLE*. Das apt-Paket ist
  aktuell, aber der Bootloader selbst wurde nicht geflasht (`rpi-eeprom-update -a` + Neustart).
  **Bewusst nicht gemacht**: eine Bootloader-Aktualisierung aus der Ferne über VPN, ohne physischen
  Zugriff, ist das eine Update, bei dem ein Fehlschlag nicht per SSH zu reparieren wäre. Sinnvoll,
  wenn Andreas zu Hause am Gerät ist.
- *(geprüft, kein Mangel)* Der Monitor meldet „alle 11 laufen", während 12 Screens existieren. Die
  zwölfte ist der **Monitor selbst** — er steht bewusst nicht in seiner eigenen BOTS-Liste, weil er
  sich nicht selbst neu starten kann. Dafür ist der Eintrag in `start_all.sh` plus der systemd-Start
  zuständig.

---

## 14.08.2026 — Crypto-Bot auf denselben Telegram-Stil, gemeinsames Textmodul

### Was gemacht wurde

**Neu: `tg_texte.py` im Repo-Wurzelverzeichnis** — ein Modul für beide Bots. Vorher hatte jeder Bot
eigene Übersetzungstabellen (`GRUND_DE` im Super-Bot, `_de_reason` im Crypto-Bot): zwei Kopien
derselben Idee. Ein neuer Exit-Grund hätte in einem Bot Klartext ergeben und im anderen ein Kürzel.
Enthält Tabellen (Gründe, Marktlage, Drawdown-Zonen, Schwankung, Sektoren, Börsen), Zahlenformate
und den gemeinsamen Verkaufs-Text.

**Zwei Zahlenformate, die sich der Größenordnung anpassen** — beide Bots kaufen Bruchstücke, und
Krypto-Kurse spannen von 0,00000563 $ (BONK) bis 118.000 $ (BTC):
- `preis()`: 0 bis 8 Nachkommastellen je nach Höhe. Feste 2 Stellen machen aus einem Meme-Coin 0,00 $.
- `menge()`: bei 1.234.567 Stück keine Nachkommastellen, bei 0,0412 BTC vier.

**Dabei einen Fehler von gestern gefunden und behoben:** meine Kauf-Nachricht im Super-Bot rundete die
Stückzahl auf 0 Nachkommastellen — bei deiner GLD-Position (0,3652 Stück) hätte dort **„0 Stück"**
gestanden. Ist jetzt korrekt.

**Crypto-Bot umgestellt:** Kauf, Blitz-Kauf, Verkauf, Drawdown-Zonen, Tagesverlust, Risikobremse,
Start, BTC-Absturz, Wal-Zufluss/-Abfluss und die drei On-Chain-Meldungen. Der Verkaufs-Text kommt
jetzt aus `tg_texte.verkauf()` — bei beiden Bots buchstäblich derselbe Code. Außerdem, wie beim
Super-Bot: die doppelte Zeit-Exit-Meldung entfernt (kam zweimal für denselben Vorgang) und die
`<b>`-Tags darin, die ohne `parse_mode` wörtlich im Chat standen.

**Alarme sagen jetzt, was sie bedeuten.** Aus „🚨 ONCHAIN INSIDER SIGNAL — LINK / 50.000 Token
verlassen Exchange (3×)" wurde: „Großer Abfluss · LINK — wer Coins von der Börse holt, will sie
halten, nicht verkaufen. Der Bot wertet das als Kaufargument. *Hinweis, keine Order.*" Der Zusatz
ist wichtig: diese Meldungen lösen **keinen** Kauf aus, das war vorher nicht erkennbar.

### Zwei Fallen beim Umbau

- Beim Einfügen der neuen Methode rutschte ein bestehendes `@staticmethod` vor `_titel(self, …)` —
  das hätte `self` verschluckt. Vor dem Aufspielen bemerkt.
- `WILD_MEME` ist eine **lokale** Variable in `trade()`, keine Modulkonstante. Der erste Entwurf von
  `_titel` griff darauf zu und wäre bei jeder Kauf-Nachricht mit `NameError` gescheitert. Aufgefallen
  ist es nur, weil die Texte vor dem Aufspielen gerendert wurden — genau dafür stecken sie in
  eigenen Methoden.

### Was jetzt läuft

- `tg_texte.py`, `super_bot.py`, `crypto/crypto_bot.py` aufgespielt (Pi-Sicherungen `*.bak_20260814-004251`)
- Crypto neu gestartet 00:43 — **8/8 Positionen** wiederhergestellt, 3.569,83 $, WebSocket verbunden
- Super neu gestartet 00:44 — 5 Positionen wiederhergestellt
- Je genau eine Instanz, keine Doppelstart-Konflikte, keine Telegram-Fehler
- Zwei Beispiel-Nachrichten zur Ansicht verschickt

### Was offen ist

- `_de_reason()` und `_de_regime()` im Crypto-Bot sind jetzt tote Übersetzungstabellen (durch
  `tg_texte` ersetzt), stehen aber noch im Code. Bewusst nicht entfernt: nachts um eins an einem
  laufenden Bot ohne Not löschen ist die schlechtere Wahl. Beim nächsten Anfassen mit weg.
- Der Insider- und der Fundament-Bot melden weiter im alten Stil; beide schreiben aber selten.

---

## 13.08.2026 (abends) — Telegram-Feed des Super-Bots lesbar gemacht

### Was gemacht wurde

**Ein echter Fehler zuerst:** die Zeit-Exit-Nachricht enthielt `<b>`-Tags, aber `send()` setzte kein
`parse_mode` — die Tags standen wörtlich im Chat. Außerdem kamen bei einem Zeit-Exit **zwei**
Nachrichten für denselben Vorgang (eigene Meldung + die aus `close_position`). Beides behoben:
`send()` schickt jetzt HTML, die doppelte Meldung ist raus.

**Neuer Aufbau der Nachrichten** (`super_bot.py`): Kernaussage zuerst, deutsche Zahlen (4.231,80 statt
4231.8), echtes Minuszeichen, Klartext statt Indikator-Kürzeln. Konkret:
- **Kauf**: Symbol mit deutschem Sektornamen, Stückzahl/Preis/Einsatz, Risiko in $ **und** in % vom
  Konto, Marktlage („starker Trend, nicht überkauft"), Signal mit der nötigen Schwelle daneben,
  Kontostand. Der Wall aus ~20 Kennzahlen bleibt vollständig in der Konsole und im Dashboard.
- **Verkauf**: 🟢/🔴 sofort erkennbar, Ergebnis in $ und %, **Grund in Klartext**
  (`WS-TRAIL-STOP` → „Gewinn gesichert (Rücksetzer vom Hoch)"), Haltedauer, Kontostand.
- Drawdown-Zonen, Tageslimit, Risikobremse, Earnings-Hinweis, Start/Stopp ebenfalls umformuliert —
  jede sagt jetzt, **was das für dich bedeutet** („Der Bot kauft heute nichts mehr").

**Testbar gemacht:** der Nachrichtenaufbau steckt in zwei eigenen Methoden `_tg_kauf()` / `_tg_verkauf()`
statt mitten im Handelscode. Damit ließ sich der Text vor dem Aufspielen mit echten Werten rendern —
inklusive Randfälle (unbekannter Verkaufsgrund → Rohtext, fehlende Haltedauer → Zeile entfällt,
Break-Even → +0 $).

### Warum

Der Feed war die Konsolen-Logzeile, 1:1 nach Telegram durchgereicht. Für die Fehlersuche am Rechner
richtig, auf dem Handy unbrauchbar: bei „CLOSE WS-TRAIL-STOP XLE: -2.9% | $-127" muss man wissen, was
ein Trailing-Stop ist, um zu erkennen, ob das gut oder schlecht war. Übersetzungstabellen (`GRUND_DE`,
`SEKTOR_DE`, `LAGE_DE`, `ZONE_DE`, `VIX_DE`) sind bewusst Klassenkonstanten — neue Exit-Gründe fallen
sichtbar auf den Rohtext zurück, statt still falsch übersetzt zu werden.

### Was jetzt läuft

- `super_bot.py` aufgespielt (Pi-Sicherung `super_bot.py.bak_20260813-224929`), Session `trading`
  neu gestartet 22:49. Alle **5 offenen Positionen** (XLE, GLD, XLK, ITA, PAVE) wiederhergestellt,
  Guthaben 4.533,54 $, WebSocket verbunden.
- Beim Neustart lief ein zweiter, gleichzeitiger Startversuch in die Doppelstart-Sperre
  (`[SINGLETON] laeuft bereits`) — genau ihr Zweck. Es läuft **genau eine** Instanz (PID 61057).
- Zwei Beispiel-Nachrichten zur Ansicht nach Telegram geschickt (als Vorschau markiert).

### Was offen ist

- Der **Crypto-Bot** verschickt weiter im alten Stil. Die Übersetzungstabellen ließen sich übernehmen;
  bewusst nicht angefasst, weil nur der Super-Bot gefragt war.
- Die ML-Zeile („Trefferchance laut Modell") erscheint erst, wenn das Modell aktiv ist — aktuell
  8 von 30 nötigen Trades mit Merkmalen.

---

## 13.08.2026 — Mac und Pi angeglichen, Drift dauerhaft verhindert

### Was gemacht wurde

**1. Ausmaß gemessen.** Vollständiger Prüfsummen-Vergleich aller 97 Code-Dateien (`.py .sh .html .md`,
ohne Archive, Sicherungen, Caches): **16 Dateien drifteten, 15 gab es nur auf dem Pi, 5 nur auf dem Mac.**

**2. Richtung geprüft, bevor überschrieben wurde.** Bei allen 16 driftenden Dateien war der **Pi neuer** —
keine Mac-Arbeit ging verloren. Der Mac hatte teils kaputte Stände: `tg_sol_check.py` enthielt dort
`"$%,.0f"`, eine in Python ungültige Formatanweisung, auf dem Pi längst repariert.

**3. Angeglichen.** Mac-Vollsicherung als `~/trading_bot_mac_backup_20260813-211545.tgz`, dann 29 Dateien
per rsync vom Pi geholt. Die 5 Mac-Only-Dateien (2 Stop-Skripte, 3 DEX-Dashboards) sind Überbleibsel
beendeter Zweige — auf dem Pi liegen sie im Archiv; auf dem Mac nach `_mac_archiv_20260813/`
verschoben, **nicht gelöscht**. Ergebnis: **95 Dateien identisch, 0 Drift.**
Bewusste Ausnahmen: `config.py` (API-Schlüssel, bleibt nur auf dem Pi, per `.gitignore` ausgeschlossen)
und die erzeugte `wochenbericht.html`.

**4. Neu: `~/bin/pi_sync.sh`** (auf dem Mac, außerhalb des Repos):
- `check` — zeigt Drift und welche Seite neuer ist
- `pull` — holt den Pi-Stand, sichert den Mac vorher als `.tgz`
- `push DATEI…` — überträgt zum Pi, **bricht ab wenn die Pi-Version neuer ist**, prüft `bash -n`
  bzw. `py_compile` und legt auf dem Pi eine Sicherung `.bak_<Zeitstempel>` an

**5. Neu: SessionStart-Hook** in `~/.claude/settings.json` — führt bei jedem Sitzungsstart
`pi_sync.sh check --kurz` aus. Der Drift-Stand steht damit von der ersten Sekunde an fest,
statt dass er vor einem Edit erst erfragt werden müsste.

### Warum

Der Abgleich hing bisher daran, dass jemand vor dem Editieren daran denkt. Genau das ist im Juli
schiefgegangen: eine stale Mac-Kopie überschrieb den Pi-Stand, der Monitor weckte vier gestoppte Bots
wieder auf, drei Tage Telegram-Spam. Eine Regel, an die man sich erinnern muss, ist keine Sperre.
`push` prüft jetzt selbst und verweigert den gefährlichen Fall.

Wichtig war die Unterscheidung: dass die eigene bearbeitete Datei driftet, ist der **Normalfall** und
darf nicht blockieren. Gefährlich ist allein, wenn die **Pi-Version neuer** ist — nur dann bricht `push` ab.
Eine erste, gröbere Fassung blockierte jeden Push und wäre in der Praxis sofort umgangen worden.

### Was jetzt läuft

- Mac und Pi deckungsgleich (95 Dateien), `pi_sync.sh check` als Nachweis
- Beide Richtungen getestet: Drift erkannt, `push` bei neuerem Pi-Stand abgebrochen, `pull` stellt her
- Mac-Sicherungen: `~/trading_bot_mac_backup_*.tgz` (legt `pull` künftig automatisch an)

### Was offen ist

- Der Hook greift erst ab der **nächsten** Sitzung (Hooks werden beim Start gelesen). Falls er nicht
  erscheint: einmal `/hooks` öffnen, das lädt die Konfiguration neu.
- Der Mac committet weiterhin nicht nach GitHub — gesichert wird der Pi-Stand um 02:00. Das ist
  Absicht, solange der Pi die Wahrheit ist.

---

## 12.08.2026 — Funktionsprüfung nach Umzug, Handlungsrahmen, tägliche/wöchentliche Automatik

### Was gemacht wurde

**1. Funktionsprüfung nach dem Umstecken des Pi.** Alles in Ordnung: beide Adressen unverändert
(`eth0 192.168.188.130`, `wlan0 192.168.188.62`, `wg0 10.8.0.1`), alle Sessions nach dem Neustart
um 12:21 wieder oben, alle vier Dashboards über HTTP erreichbar, Daten frisch, kein Risk-Halt aktiv.

**2. Handlungsrahmen schriftlich festgelegt** in `~/.claude/CLAUDE.md` (Mac, wird jede Sitzung geladen).
Betrieb und Reparatur laufen ohne Rückfrage; Geld, Kapital, Strategie und Löschungen bleiben bei Andreas.
Dazu die Pi-Pflichtregeln: md5-Abgleich Mac↔Pi vor jedem Edit geteilter Dateien, `bash -n`,
Sicherung vor Überschreiben, Reihenfolge beim Abschalten von Bots.

**3. Neu: `agents/funktionspruefung.py`** — 17 Prüfungen, täglich 09:00 per Cron.
Screen-Sessions (Liste kommt aus `monitor_agent.BOTS`, kann also nicht auseinanderlaufen),
vier Dashboards über HTTP, Frische der Live-Dateien, ob die Nacht-Crons tatsächlich gelaufen sind,
Platte/RAM/Netz/Internet. Telegram **nur bei Abweichung**, plus einmalig bei Erholung.
Ergebnis in `agents/funktionspruefung.json` + Verlauf in `agents/funktionspruefung_log.csv`.

**4. Neu: `agents/wochenbericht.py`** — sonntags 18:00. Baut `wochenbericht.html`
(ausgeliefert auf :8080) mit Depotständen aller vier Depots, Wochenveränderung, Trades,
Störungen aus `health_log.csv` und der Prüfhistorie; schickt eine Kurzfassung mit Link per Telegram.

**5. Whitelist erweitert:** `wochenbericht.html` in den `dash_server`-Aufruf für :8080 — an **beiden**
Stellen (`start_all.sh` und `monitor_agent.py` BOTS), sonst hätte der nächste Monitor-Neustart
die Änderung stillschweigend zurückgesetzt.

### Warum

Der Monitor bewacht Prozesse, aber nicht Ergebnisse: ein Cron kann still ausfallen und niemand merkt es,
weil die Session ja läuft. Die Funktionsprüfung schließt genau diese Lücke und prüft Wirkung statt Existenz.
Nachweis eines Cron-Laufs bewusst über **dauerhafte Ausgabedateien** (`sec/live_state.json`,
`tg/watch_state.json`, `ng/ng_state.json`), nicht über `/tmp`-Logs — die sind nach jedem Neustart weg
und hätten bei jedem Reboot Fehlalarm ausgelöst (im ersten Testlauf genau so passiert und korrigiert).

### Was jetzt läuft

- Cron `0 9 * * *` → Funktionsprüfung, Cron `0 18 * * 0` → Wochenbericht (Sicherung: `crontab_backup_20260812-131602.txt`)
- Neue Seite: http://trading2025.fritz.box:8080/wochenbericht.html
- Sessions `dashboard` und `monitor` mit neuer Whitelist neu gestartet; `config.py` liefert weiterhin 403

### Was offen ist

- Die **Mac-Kopie des Repos driftet** (`super_bot.py`, `crypto_bot.py`, `risk_agent.py` u. a. weichen ab).
  Deshalb wird vom Mac nicht gepusht; gesichert wird ausschließlich der Pi-Stand um 02:00.
  Ein sauberer Abgleich Mac↔Pi steht noch aus.
- Der Wochenbericht ist bewusst eine Seite auf dem Pi, keine Cloud-Seite: ein Cron auf dem Pi kann
  nichts veröffentlichen, und der Pi ist von außen nur über VPN erreichbar.


## 2026-08-25 — Diagnose: Verkauf-Rückkauf-Karussell im Krypto-Bot

**Was gemacht wurde**
Telegram-Feed (letzte 1500 Nachrichten, 20.07.–25.08.) über die Telethon-User-Session
abgezogen (/tmp/feed_dump.py) und Kauf-/Verkaufsnachrichten zu Ketten je Asset verknüpft.
Auslöser: Andreas' Beobachtung, dass Positionen mit kleinem Gewinn verkauft und
2–3 Minuten später im selben Asset zurückgekauft werden.

**Befund**
- 127 Verkauf→Rückkauf-Paare gesamt; **48 davon (38 %) innerhalb von 5 Minuten**,
  45 sogar innerhalb von 3 Minuten. Betroffen fast ausschließlich crypto_bot.py
  (2-Min-Zyklus), Super-Bot nur in einem Fall (GLD).
- Rückkaufpreis im Schnitt **−0,04 %** gegenüber dem Verkaufspreis — der Exit hat also
  faktisch nichts geschützt, 27 von 46 Rückkäufen waren sogar teurer.
- Kosten je Round-Trip 0,62 % (0,26 % Fee + 0,05 % Slippage je Seite, sim_fee/sim_slip).
  Bei Ø 227 $ Einsatz: **−59 $ netto in 11 Tagen** allein durch diese Doppelrunden —
  gegenüber 168 $ realisiertem Gewinn aller 145 Verkäufe im Feed.

**Warum das passiert**
Exit und Entry sind entkoppelt. Der Ausstieg kommt aus _exit_trigger()
(PSAR-Stop auf 1h-Bars ab ≥+1,5 %, Trailing, Breakeven), der Wiedereinstieg aus dem
Score-Modell, das alle 2 Minuten neu rechnet. Eine Sperre gibt es nur nach hartem
Stop-Loss (_sl_cooldown, 1,5 h) und nach Spikes (2 h) — **nicht nach Gewinn-Exits**.
Score und PSAR ändern sich in 2 Minuten nicht, also feuert der Kauf sofort wieder.

**Was offen ist**
Fix noch nicht eingebaut — Handelsverhalten ist Strategie, wartet auf Andreas' Entscheidung.
Vorschlag: Re-Entry im selben Symbol nur, wenn der Preis mindestens 0,7 % (= Kostenhürde)
vom Exit-Preis abweicht, plus 30-Min-Mindestpause. Rein kostensparend, da die Position
in diesen Fällen ohnehin wieder aufgebaut wurde.

### Nachtrag 25.08. — Entscheidung Andreas: Ausstieg statt Wiedereinstieg

Andreas hat die Re-Entry-Sperre verworfen ("könnte nach hinten losgehen") und die
Exit-Seite gewählt. Daraufhin gebaut und gerechnet:

**Werkzeuge (neu, alle in `crypto/`)**
- `get_bars.py` — lädt 1-Min-/1h-Bars von Alpaca nach `exit_sim_data*/` (im .gitignore).
- `exit_sim.py` — Retro-Simulation der Ausstiegsregeln, `_exit_trigger` wortgleich
  nachgebaut, PSAR-Code aus dem Bot übernommen.
- `vergleich.py` — Kalibrierung gegen die real ausgeführten Trades.
- `preischeck.py` — Kaufpreis im Feed gegen Marktkurs derselben Minute.
- `exit_sim_gross.py` — dieselben Regeln auf 2.300 künstlichen Einstiegen.
- `robust.py` — Bootstrap und Aufteilung nach Zeitraum/Symbol.

**Drei Irrwege, die erst die Kalibrierung sichtbar gemacht hat**
1. Ausführung am Minutentief statt am Stop-Niveau → Simulation rechnete sich um
   0,7 % je Trade zu schlecht. Korrigiert: Füllung am Stop-Niveau, auf die Bar-Spanne begrenzt.
2. Fehl-Prints in den Alpaca-Minutenbars → ein einziger SOL-Bar erzeugte −207 $
   Scheinverlust. Dochte werden jetzt bei 8 % gegen den Vorschlusskurs gekappt.
3. Auf den 133 echten Einstiegen (12 Tage) sah "Exit nur zum Minutenschluss prüfen"
   nach +67 $ aus. Auf 2.300 Einstiegen über 45 Tage ist dieselbe Änderung
   **signifikant schlechter** (−0,10 % je Trade). Die kleine Stichprobe hätte in die
   falsche Richtung geführt.

**Ergebnis auf 2.300 Einstiegen (12.07.–20.08.), Δ je Trade gegen heute**
| Änderung | Δ % | Bootstrap 5–95 % | Drittel 1 / 2 / 3 |
|---|---|---|---|
| Trailing 1,5 → 2,5 % | +0,11 | +0,07 … +0,16 | −0,04 / −0,00 / +0,38 |
| Trailing 1,5 → 3,5 % | +0,27 | +0,20 … +0,34 | −0,10 / −0,01 / +0,92 |
| Break-even-Exit raus | +0,07 | +0,03 … +0,11 | +0,12 / −0,02 / +0,11 |
| PSAR erst ab +3 % | −0,01 | −0,04 … +0,02 | — |
| PSAR ganz aus | −0,04 | −0,08 … −0,00 | — |
| nur halten (Referenz) | +3,47 | +3,06 … +3,89 | −1,02 / −0,44 / +11,71 |

**Umgesetzt in `crypto/crypto_bot.py` (`_exit_trigger`)**
- Trailing-Stop 1,5 % → **2,5 %**.
- **Break-even-Ausstieg entfernt.** Er schloss Positionen, die einmal +2 % gesehen
  hatten, bei exakt 0 % — garantierte 0,62 % Kosten, ohne etwas zu schützen.
  Positionen unter +4 % Bestwert hängen jetzt am harten Stop.
- PSAR unverändert — die Simulation entlastet ihn.

**Warum nicht mehr**
Trailing 3,5 % und erst recht "nur halten" verdienen ihren Vorsprung ausschließlich
im letzten Drittel (Rallye ab 08.08.); im ersten Drittel liegt "nur halten" 1 % je
Trade hinten. Das ist eine Wette auf Trendmärkte, kein Beleg. Der Break-even-Ausstieg
ist die einzige Änderung, die in allen drei Teilzeiträumen trägt.

**Was jetzt läuft**
Crypto-Bot 17:25 neu gestartet (Session `crypto`, 8 Positionen und Kontostand 3.551 $
übernommen). Backups: `crypto_bot.py.bak_20260825-172421`, `crypto_state.json.bak_…`.

**Nebenbefund, offen**
Die Kaufmeldung für SOL am 13.08. 22:44 nannte 187,44 $, Markt war 76,29 $ (Faktor 2,5).
Der Handel selbst lief korrekt (Trade schloss mit −1,7 %), nur die Telegram-Nachricht
war falsch. Einzelfall unter 134 geprüften Käufen, Ursache noch nicht gesucht.

**Was offen bleibt**
- Der eigentliche Befund ist unbequem: Der Median-Trade liegt bei −0,62 % — genau die
  Round-Trip-Kosten. Vor Kosten verdient der Bot im Median nichts; der Ertrag hängt an
  wenigen Ausreißern. Das ist ein Entry-Problem, kein Exit-Problem, und die
  Exit-Änderung verschiebt es nur um 0,1–0,2 % je Trade.
- Vorwärtstest nötig: ob Trailing 2,5 % hält, zeigt sich frühestens in einigen Wochen.
  Messgrösse: Anteil der Verkäufe mit Rückkauf binnen 5 Minuten (heute 38 %).

### Nachtrag 2 — SOL-Fehlmeldung geklärt, nicht weiterverfolgt

Nachgeprüft: Zwischen dem Kauf am 13.08. 22:44 und dem Ausstieg am 15.08. 11:26 gab es
keinen weiteren SOL-Kauf, der Trade gehört also zu diesem Einstieg. Er schloss mit
−1,7 % — mit einem Einstand von 187,44 $ wären es bei einem SOL-Kurs von ~77 $ am
Ausstiegstag −59 % gewesen. **Gebucht war der richtige Kurs, falsch war nur die
Telegram-Nachricht.** Kontostand und P&L stimmen.

Andreas' Entscheidung: nicht weiterverfolgen, solange es ein Einzelfall bleibt.
Prüfwerkzeug liegt bereit — `python3 crypto/preischeck.py` vergleicht jeden gemeldeten
Kaufpreis mit dem Marktkurs derselben Minute (aktuell: 1 Ausreisser unter 134 Käufen,
alle anderen unter 5 %). Bei Wiederholung dort ansetzen.

## 2026-08-27 — Wirkung der Exit-Änderung, Bot-Kennung im Feed, Depotwert-Fehler

**1. Wirkung der Exit-Änderung (25.08. 17:25) — nach 1,8 Tagen**

| | vorher (2 Tage) | nachher (1,8 Tage) |
|---|---|---|
| Verkäufe je Tag | 19,3 | 13,3 |
| „auf Einstand geschlossen" | 8 | 0 |
| „Gewinn gesichert (Rücksetzer)" | 5 | 1 |
| Stop-Loss | 14 | 13 |
| Ergebnis | −61 $ | −75 $ |

Mechanisch wirkt die Änderung genau wie gebaut: Break-even-Ausstiege sind weg,
Trailing-Ausstiege selten, die Handelsfrequenz fiel um 31 %. **Am Ergebnis lässt
sich nichts ablesen** — bei 24 Trades liegt die erwartete Wirkung (+0,18 % je Trade
≈ +11 $) weit unter der Streuung. Die Verluste stammen aus zwei kurzen Einbrüchen
(25.08. 23:0x, 26.08. 17:0x) mit 13 Stop-Loss; der harte Stop ist von der Änderung
nicht berührt. Marktkontext: BTC −0,2 %, ETH +0,8 %, SOL +5,8 % im Nachher-Fenster —
der Markt war also nicht schlechter, der Bot verliert an Schwankung, nicht an Richtung.
Belastbar frühestens in einigen Wochen.

**2. Bot-Kennung im Telegram-Feed** (Wunsch Andreas)

Neu in `tg_texte.py`: `BOT_NAMEN`, `BOT_ALIASSE`, `absender(text, bot)`. Die Kennung
hängt an der **ersten** Zeile, weil die Push-Vorschau am Handy nur diese zeigt:

    🟢 KAUF · SOL · Krypto-Bot
    🟢 KAUF · XLE (Energie) · Super-Bot

`crypto_bot.send()` und `super_bot.send()` rufen sie für Nachrichten mit eigener
Kopfzeile auf; die Präfixe der übrigen Meldungen heißen jetzt einheitlich
„Krypto-Bot" / „Super-Bot" statt „CRYPTO" / „SUPER". `BOT_ALIASSE` verhindert
Doppelungen wie „Krypto-Bot gestartet · Krypto-Bot".

**3. Dabei gefunden: Tagesbilanz wurde am Bargeld gemessen — Bot sperrte sich selbst**

`_get_drawdown_mult()` rechnete in beiden Bots `(balance − start_balance) / start_balance`,
wobei `balance` **reines Bargeld** ist. Ein Kauf verschiebt Geld nur von Bargeld in
eine Position — die Rechnung hielt also jeden Kauf für einen Verlust. Stand heute
13:55 beim Super-Bot: gemeldet „🚨 Gefahrenzone · −9,5 % heute", **keine Käufe mehr**;
tatsächlicher Depotwert 5.015 $ gegen Tagesbasis 4.733 $, also +6 %. Zwei Käufe à
225 $ genügten, um den Bot für den Rest des Tages stillzulegen.

Behoben in `super_bot.py` und `crypto/crypto_bot.py`: neue Methode `_depotwert()`
(Bargeld + Marktwert der Positionen, Fallback auf den Einstand, wenn ein Kurs fehlt),
Tagesbilanz rechnet dagegen. Die Tagesbasis heißt im State jetzt `day_start_equity`;
alte `day_start_balance`-Werte werden bewusst verworfen und beim Start aus dem
Depotwert neu gesetzt (sonst verglichen sich Depotwert und Bargeld). Beide Bots
14:05 neu gestartet, Tagesbasis Krypto 4.959 $, Super 5.014 $, keine DANGER-Zone mehr.

**4. Nebenbei repariert:** `~/bin/pi_sync.sh` fand den Pi von unterwegs nicht
(`trading2025.fritz.box` löst nur im Heimnetz auf). Es versucht jetzt nacheinander
`trading`, `trading-wg` (192.168.188.62 über WireGuard) und `trading-extern`.
Neuer SSH-Alias `trading-wg` in `~/.ssh/config`.

**Offen**
- Eine Verkaufsmeldung vom 25.08. 22:14 (UNI, „auf Einstand geschlossen", Kontostand
  4.903 $) steht in **keiner** Trade-Historie und in keinem Log. Einzelfall unter 24
  geprüften Verkäufen. Mit der neuen Bot-Kennung wäre so etwas sofort zuzuordnen.
- Der Kernbefund vom 25.08. bleibt: Median-Trade −0,62 % = die Kosten. Entry-Problem.

**Nachtrag zu Punkt 3 — zweite Fundstelle, erst nach dem Deploy aufgefallen**

Der erste Fix (`_get_drawdown_mult`) griff zu kurz: `check_day_loss()` rechnete in
beiden Bots dieselbe Bargeld-Formel und schlug direkt nach dem Neustart zu, weil die
frische Depotwert-Tagesbasis gegen den Bargeldstand verglichen wurde:

- Krypto-Bot: „🛑 Tagesverlust −10 % erreicht" gemeldet, Tagesbasis auf den Bargeldstand
  zurückgesetzt — damit war der eben korrigierte Wert wieder kaputt.
- Super-Bot: „🛑 Tageslimit erreicht" gemeldet und `self.running = False` — der Bot
  hätte für den Rest des Tages nichts mehr gekauft.

Beide Telegram-Warnungen sind bei Andreas angekommen und waren falsch. Behoben:
`check_day_loss()` misst jetzt ebenfalls am Depotwert. Die verbogene Krypto-Tagesbasis
wurde einmalig aus dem State entfernt und beim Start neu gesetzt (4.959,72 $ Depotwert).
Nach dem letzten Neustart (14:12 bzw. 14:14): keine DANGER-Zone, keine Tagesverlust-Meldung,
Super-Bot 6 Positionen / Basis 5.014 $, Krypto-Bot 8 Positionen / Basis 4.960 $.

Lehre für den nächsten Umbau dieser Art: `grep -n "start_balance" datei.py` **vor** dem
Deploy — die Kennzahl wurde an zwei Stellen unabhängig gerechnet.
