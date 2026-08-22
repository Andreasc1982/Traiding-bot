# Strategie-Neudenken — Bots, Markt, Taktik

Stand 21.08.2026. Grundlage: die eigenen Messungen (CLAUDE.md, SITZUNGEN.md, PORTFOLIO_ARCHITEKTUR.md, NEUAUSRICHTUNG_SUPER_BOT.md) plus externe Recherche vom heutigen Tag. Jede Zahl aus fremder Quelle ist verlinkt.

---

## 0. Vorbemerkung zu „Gesetze und Ethik erst mal weglassen"

Ich lasse beides nicht weg — aber das ist hier gar kein Verzicht, und das ist der vielleicht wichtigste Einzelbefund der Recherche: **die illegalen Abkürzungen sind für uns keine Gewinnquelle, sondern eine Verlustquelle.** Die größte akademische Studie zu Krypto-Pump-and-Dumps ([Dhawan & Putniņš, Review of Finance](https://revfin.org/a-new-wolf-in-town-pump-and-dump-manipulation-in-cryptocurrency-markets/)) hat 355 Pumps auf Binance und Yobit seziert: Kurssprung im Schnitt +65 %, Umkehr nach ~8 Minuten, ~350 Mio. $ Volumen — und **für alle Teilnehmer außer den Organisatoren ist der Erwartungswert negativ**. Die Organisatoren selbst verdienten zusammen nur ~6 Mio. $. Wer einem Pump-Signal folgt, ist die Exit-Liquidität — dieselbe Rolle, die wir bei NAKMAK schon im Juli erkannt und vermieden haben. Echtes Insiderwissen haben wir nicht, und Front-Running braucht Colocation-Infrastruktur im Millionenbereich. Alles, was für uns tatsächlich erreichbar ist, ist ohnehin legal. Es gibt hier also keinen Zielkonflikt: der ehrliche Weg und der gewinnmaximierende Weg sind für ein Konto unserer Größe **derselbe Weg**.

---

## 1. Die Kernannahme geprüft: „Alle verdienen am Markt — nur wir nicht"

Diese Annahme ist empirisch falsch, und zwar deutlich. Eine [Zusammenstellung von 30 Studien aus 8 Ländern](https://bananafarmer.app/research/day-trading-failure-rate) über 25 Jahre kommt auf 70–97 % Verliererquote unter aktiven Kurzfrist-Tradern: Brasilien ([Chague et al. 2020](https://www.tradicted.com/research/chagu-day-2020/)) 97 % bei Tradern, die länger als 300 Tage durchhielten; Taiwan ([Barber/Odean](https://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/Day%20Trade%20040330.pdf)) ~95 % über 15 Jahre bei 360.000 Tradern; Indien (SEBI 2024) 92,8 % von 11,3 Mio.; französische CFD-Konten (AMF) 89 %.

Verlässlich verdienen am Markt vor allem: **die Infrastruktur** (Börsen, Broker, Market Maker über den Spread), **die Gebührennehmer** (Fonds, Signal- und Kursverkäufer — deshalb gibt es so viele Trading-Podcasts: der Podcast ist das Geschäftsmodell, nicht der Trade) und **die Risikoträger** (wer breit investiert bleibt, kassiert langfristig die Marktrendite). Das Bild „alle verdienen" entsteht durch Survivorship-Bias: die Verlierer posten keine Screenshots.

**Konsequenz fürs Neudenken:** nicht versuchen, besser zu raten als die anderen Rater — sondern strukturell auf die Seite derer wechseln, die verdienen: Risikoprämien einsammeln (Fundament), dokumentierte Anomalien mit Messnachweis handeln (Insider-Cluster), und Kosten behandeln wie ein Market Maker (jeder Basispunkt zählt).

---

## 2. Auftrag „rückwirkend prüfen, ob Vorhersagen funktioniert haben"

Das ist extern bereits in großem Stil gemacht worden — und wir haben es intern selbst gemacht:

| Quelle | Befund |
|---|---|
| [CXO Advisory „Guru Grades"](https://www.cxoadvisory.com/gurus/) | 68 prominente Marktpropheten, 6.582 dokumentierte Prognosen (1998–2012): **46,9 % Trefferquote** — schlechter als Münzwurf. Bester 68 %, schlechtester 21 %. ([Forbes-Zusammenfassung](https://www.forbes.com/sites/rickferri/2014/01/23/gurus-achieve-an-astounding-47-4-accuracy/)) |
| [Hulbert / AAII, Jahrzehnte Newsletter-Tracking](https://www.aaii.com/journal/article/observations-from-decades-of-tracking-investment-newsletters) | Die Mehrheit der Börsenbriefe bleibt langfristig hinter dem Markt zurück; die wenigen Ausnahmen sind vorab nicht identifizierbar. |
| Eigene Messung: Nacktes Geld | 21 Folgen transkribiert und gefiltert: verwertbare **Mechanismen** nur in alten Folgen (SOFR/Repo, Rebalancing, Crack Spread); die letzten Folgen: null Ausbeute. Mike the Pirate: kein Track Record, kein Trading-Edge (dokumentiert 25.07.). |
| Eigene Messung: Blockzocker | Bezahlschranke, kein öffentlich prüfbarer Track Record — der Wächter meldet nur, *dass* etwas erscheint, nicht ob es taugt. |

Das Urteil ist einheitlich, extern wie intern: **Personen, die Richtungen vorhersagen, sind als Signalquelle tot.** Was die Podcast-Arbeit trotzdem wertvoll macht: sie liefert gelegentlich **prüfbare Mechanismen** (Termineffekte, Marktstruktur) statt Prognosen. Die seit 02.08. unbearbeitete Leads-Liste (SOFR/Repo, Liquiditätsspritze, Quartalsende/Russell, Crack Spread, Tokenisierung) ist darum mehr wert als jede weitere neue Quelle — **abarbeiten statt sammeln.**

---

## 3. Whale Watching — was die Großen wirklich tun und was davon kopierbar ist

Die unbequeme Wahrheit zuerst: Die Großen verdienen überwiegend **nicht durch bessere Prognosen** (siehe Guru-Daten oben), sondern durch Strukturvorteile — Spread-Einnahmen aus Market Making, Latenz, Skalen- und Finanzierungsvorteile, Carry- und Basis-Geschäfte, und schlicht Gebühren auf fremdes Geld. Diese Vorteile sind nicht kopierbar. Kopierbar sind ihre **veröffentlichten Positionen** — und da ist die Evidenz gemischt:

**Aktien, brauchbar:** 13F-Cloning („Best Ideas" von Hedgefonds nachkaufen) hat echte akademische Evidenz — die Überzeugungspositionen der Manager schlugen den Markt historisch um [1,6–2,1 % pro Quartal](https://quantpedia.com/strategies/alpha-cloning-following-13f-fillings), und Kopierportfolios erreichten nach Kosten ähnliche Ergebnisse wie die Originale. Aber: 45 Tage Meldeverzug, und neuere Studien zeigen einen abschmelzenden Vorsprung. **Insider-Cluster (Form 4) bleibt der am besten belegte Retail-Edge** — die Recherche bestätigt unsere Juli-Analyse; unser Vorwärtstest (Tag 25 von 90) ist genau das richtige Instrument. Congress-Tracking ([NANC](https://www.etf.com/sections/etf-basics/nanc-vs-kruz-battle-congress-stock-trackers)) schlägt zwar den S&P seit Auflage, aber im Wesentlichen als gehebelte Tech-Wette — risikoadjustiert kein nachgewiesener Edge (deckt sich mit unserem Befund vom 25.07.).

**Krypto, ernüchternd:** On-Chain-Whale-Kopieren klingt logisch, misst sich aber schlecht: eine [90-Tage-Auswertung über drei Börsen](https://bitsgap.com/blog/why-copying-on-chain-whale-trades-usually-backfires) fand 97 % profitable „Leader" — aber nur **44 % der Kopierer** landeten im Plus. Die Gründe sind strukturell und treffen uns alle: man sieht die Position, aber nicht die Kontogröße (Sizing), nicht den geplanten Exit, nicht die Gegen-Hedges auf anderen Venues; man füllt später und schlechter; und die Leaderboards zeigen nur Überlebende. **Konsequenz:** unsere Whale-Alert- und On-Chain-Signale bleiben, was sie seit dem 14.08. sind — *Hinweis, keine Order* — und werden nach 90 Tagen als Event-Studie ausgewertet, exakt wie die Telegram-Pipeline: erst messen, nie blind handeln.

---

## 4. Was nachweislich funktioniert — sortiert nach Evidenz × Umsetzbarkeit für uns

**A. Marktrendite + Rebalancing (Fundament-Depot).** Der einzige „Edge", der keiner ist und gerade deshalb sicher existiert: die Prämie fürs Risikotragen. Langfristig schlägt der Index [~90 % der aktiven Ansätze](https://www.aaii.com/journal/article/observations-from-decades-of-tracking-investment-newsletters); unser Fundament ist zugleich das **einzige Depot mit belegbarem Ergebnis** (Bauart-Treue, kein unerklärter Rest). Das bleibt die Renditequelle. Ehrliche Erwartung: 6–9 % p. a. mit zwischenzeitlichen Rückgängen.

**B. Insider-Cluster (läuft).** Bester belegter Retail-Edge, Daten frei (EDGAR), Vorwärtstest läuft. Nichts ändern, nichts aufstocken, Entscheidung wie geplant Ende Oktober. Der Freshness-Bug ist behoben; ehrlich gerechnet +7,50 % gegen +2,03 % IWM im selben Fenster (t = 1,5) ist weiterhin „offen, vielversprechend".

**C. Zeitreihen-Momentum / Trendfolge — aber auf dem richtigen Horizont.** Die stärkste dokumentierte Anomalie überhaupt: [Moskowitz/Ooi/Pedersen](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf) über 58 Märkte und 25 Jahre, seither [breit repliziert](https://alphaarchitect.com/time-series-momentum-aka-trend-following-the-historical-evidence/), funktioniert auch auf BTC. Entscheidend: die Evidenz gilt für **Wochen- bis Monatshorizonte** — nicht für 2-Minuten-Zyklen mit acht gestapelten Vetos. Unser eigener Strenge-Backtest (17.06.) zeigte dasselbe: ETF-Momentum war auf 10 Jahren bei *jeder* Schwelle profitabel; was verliert, ist das Drumherum aus Overtrading und Kosten. **Der Super-Bot sollte zu dem werden, wofür es Evidenz gibt: ein Monats-Momentum-System** (12-1-Momentum plus 200-Tage-Filter, 10–20 Positionen, Handel einmal pro Monat). Nebeneffekt: gehandelt wird nur einmal im Monat, aber über 10–20 Titel gleichzeitig — gemessen wird dann über den Querschnitt der Positionen statt über seltene Einzeltrades, und das Ergebnis wird in Monaten statt in 8+ Monaten beurteilbar.

**D. Krypto-Carry statt Krypto-Prognose.** Wenn Krypto, dann über den einzigen strukturellen Geldstrom des Marktes: **Funding-Arbitrage / Cash-and-Carry** — Spot long, Perpetual short, die Funding-Zahlungen der gehebelten Longs einsammeln, marktneutral ([Funktionsweise und Risiken](https://www.kraken.com/learn/futures-trading-funding-rate-arbitrage)). Das ist das Geschäft, das große Player tatsächlich machen (unsere dYdX-Kostenarbeit war dafür schon die halbe Vorarbeit). Aber die Regel aus der Portfolio-Architektur gilt hart: **Kostenschwelle vor Signalsuche.** Bei 62 bp Kraken-Roundtrip und Funding-Raten, die jederzeit drehen können, entscheidet die Netto-Rechnung. Erster Schritt ist darum kein Handel, sondern ein **Funding-Rate-Logger** (Kraken + eine zweite Venue, stündlich, 4 Wochen), dann die ehrliche Rechnung gegen unsere echten Kosten.

**E. Mechanische Termineffekte (die Leads-Liste).** Index-Rebalancing (Russell), Quartalsende, Repo-/SOFR-Stress: kleine, wiederkehrende, dokumentierte Effekte mit festem Kalender — als Event-Studie mit vorhandener Infrastruktur prüfbar, ohne einen Cent zu riskieren.

**F. Was raus ist — und warum das ein Erfolg ist.** Crypto-Bot v1: 269 Trades, +0,63 $, t = 0,01 — ein Edge ist in dieser Form **ausgeschlossen, nicht nur unbewiesen**. *(Präzisierung durch die Kostenrechnung vom 22.08.: „in dieser Form" heißt „zu diesen Börsenkosten" — das Einstiegssignal selbst trägt vor Kosten. Details im Nachtrag, Abschnitt 7.)* DEX: verlor signifikant selbst bei 0 % Kosten, korrekt beendet. Beides sind keine Niederlagen, sondern das, was 97 % der Verlierer aus Abschnitt 1 nie tun: einen negativen Befund akzeptieren, bevor echtes Geld brennt.

---

## 5. Der eigentliche Befund des Neudenkens

Wir haben das Seltenste am Markt bereits gebaut: eine **ehrliche Messmaschine** — Vorwärtstests, echte Kosten in der Simulation, Freshness-Prüfungen, t-Statistiken, Adversarial-Reviews, die drei „Phantom"-Bugs gefunden haben, bevor sie Entscheidungen verfälschten. Die Verlierer-Statistik aus Abschnitt 1 besteht überwiegend aus Leuten ohne genau das. Der Engpass ist nicht Ideenmangel, sondern die schon am 26.07. erkannte Schieflage: **der Aufwand war invers zur Evidenz verteilt** (7 Sessions Krypto ohne Edge, 2 Sessions Aktien mit dem einzigen Kandidaten). Neudenken heißt: die Messmaschine auf die evidenzstärksten Hypothesen richten, Horizonte von Monaten statt Minuten, Kosten zuerst. „Groß denken wie die Broker" heißt nicht größere Wetten — es heißt **verdienen wie das Haus**: Prämien, Carry, Mechanik, Disziplin.

Zur Marktlage (21.08.2026, Stocklake-Snapshot): Regime CAUTIOUS bei VIX ~15, aber SKEW ~143 — unter der ruhigen Oberfläche wird Absicherung gegen Extremrisiken teuer bezahlt. Ausblick verhalten bullisch. Kein Umfeld für Hebel-Experimente; ein gutes für Fundament und Carry-Messung.

---

## 6. Plan für die nächsten 90 Tage

1. **Crypto-Bot v1 einfrieren** (Positionen auslaufen lassen, Sessions abbauen). Die Messung ist abgeschlossen; jeder weitere Betriebstag kostet Aufmerksamkeit ohne Erkenntnisgewinn. Das Einstiegssignal selbst bleibt als Portierungs-Kandidat im Rennen — siehe Schiene 5 und Nachtrag. *(Kapital-/Strategie-Entscheidung → liegt bei dir.)*
2. **Insider-Vorwärtstest unangetastet** bis Ende Oktober laufen lassen; dann Entscheidung nach dem vorab festgelegten Kriterium.
3. **Super-Bot zum Monats-Momentum-System umbauen**: 12-1-Momentum + 200-Tage-Filter auf dem Alpaca-Universum (Funnel-Architektur aus der Juli-Planung passt dafür), Rebalancing monatlich, Backtest fee-aware, danach 3-Monats-Vorwärtstest nach Stufe-2-Aufnahmeregel.
4. **Funding-Rate-Logger bauen** (nur Daten, kein Handel): Kraken + zweite Venue, stündlich; nach 4 Wochen Netto-Ertragsrechnung gegen echte Kosten → Go/No-Go für ein Carry-Papierdepot.
5. **Leads-Liste abarbeiten statt Meinungsquellen sammeln**: Russell-/Quartalsende-Effekt als Event-Studie auf historischen Daten; SOFR/Repo als Beobachtungsgröße. Podcast-Wächter laufen lassen (kosten fast nichts). „Keine neuen Quellen" heißt dabei präzise: keine neuen **Meinungsquellen** (Podcasts, Gurus, Signal-Kanäle) — nicht, weil alles ausgereizt wäre, sondern weil (a) die gemessene Trefferquote dieser Kategorie bei ~47 % liegt (Abschnitt 2) und (b) unsere eigene Ausbeute-Messung zeigt, dass der Engpass das *Auswerten* ist, nicht der Zufluss: die besten Leads liegen seit dem 02.08. unbearbeitet. Neue **Primärdaten-Quellen** sind dagegen ausdrücklich erwünscht, wenn sie eine prüfbare Hypothese bedienen — der Funding-Rate-Logger (Punkt 4) ist genau so eine neue Quelle. Der „entscheidende Infogeber" ist nach aller Evidenz keine Person, sondern der Datenfeed, den kaum jemand sauber auswertet: EDGAR (Form 4 / 13F), Funding-Raten, CFTC-COT-Positionsdaten der Großhändler, Rebalancing-Kalender der Indexanbieter, NY-Fed-Repo/SOFR-Daten — alles frei, alles rückwirkend prüfbar. **Aufnahmekriterium für jede künftige Quelle** (damit die Tür offen, aber bewacht bleibt): sie liefert Mechanismen oder Rohdaten statt Prognosen, ihr Track Record lässt sich rückwirkend prüfen (unsere Transkript-/Event-Studien-Pipeline kann das), und der bestehende Rückstau ist abgearbeitet.
6. **Whale-/On-Chain-Signale**: weiter nur loggen; nach 90 Tagen Event-Studie (Rendite t+1h/t+24h nach Signal, nach Kosten). Ergebnis entscheidet, ob sie Gewicht bekommen oder rausfliegen.

**Und was heißt das für Krypto insgesamt?** Einfrieren von Bot v1 heißt nicht Ausstieg aus Krypto — es heißt, die eine Sache zu beenden, deren Nicht-Funktionieren bewiesen ist (Intraday-Momentum auf 20 Coins), und Krypto auf fünf Schienen neu aufzustellen, die zur Evidenz passen:

*Schiene 1 — Besitzen statt handeln (sofort):* BTC als kleine Beimischung im Fundament, nach der Ein-Drittel-Regel aus der Portfolio-Architektur (56 % Volatilität → 1 $ BTC trägt ~3× das Risiko von 1 $ Aktien). Bitter, aber lehrreich: BTC machte im Messfenster +20 %, während 269 Crypto-Trades +0,63 $ ergaben — die Rendite lag im *Halten*, nicht im Handeln.

*Schiene 2 — Carry statt Prognose (der Hauptpfad, Punkt 4):* Funding-Arbitrage ist der einzige strukturelle Geldstrom des Krypto-Markts, marktneutral, kein Raten nötig. Erst der Logger und die Netto-Rechnung gegen unsere echten Kosten (62 bp Kraken sind hier die Hürde — die dYdX-Kostenarbeit war die Vorarbeit für genau diese Frage), dann ggf. ein Carry-Papierdepot nach Stufe-2-Regel.

*Schiene 3 — BTC-Trendfolge auf Monatshorizont (Kandidat):* Die Zeitreihen-Momentum-Evidenz (Abschnitt 4C) deckt BTC ab. Eine simple Monatsregel nur auf BTC/ETH (z. B. über/unter 200-Tage-Linie), eine Handvoll Umschichtungen pro Jahr — damit wird selbst die Kraken-Kostenbasis tragbar. Fee-aware backtesten, dann Vorwärtstest; kein neuer Dauerbetrieb vorher.

*Schiene 4 — On-Chain/Whale als Messobjekt (Punkt 6):* weiter loggen, Event-Studie nach 90 Tagen entscheidet.

*Schiene 5 — Signal-Portierung auf eine Billig-Venue (neu, aus der Kostenrechnung vom 22.08.):* Das Einstiegssignal des Bots trägt vor Kosten (+370 $, t = 3,49 über 44 Tage); die 62 bp Kraken-Roundtrip fressen es exakt auf (Break-even ~0,67 %). Der Vorteil sitzt dabei in den kleineren Alts. Ein Handelsplatz mit deutlich niedrigeren Kosten **und** diesen Alts macht aus dem eingefrorenen Bot wieder einen Kandidaten — Details, Kandidaten und Vorbehalte im Nachtrag (Abschnitt 7).

Tot bleiben: Intraday-Krypto **zu 62 bp Kosten**, Spikes, Meme-Coins, DEX-Moonshots. Nicht, weil es verboten oder unmoralisch wäre — sondern weil wir es gemessen haben.

**Erwartungsrahmen, ehrlich:** Bei unserem Kapital wären 1–3 Prozentpunkte p. a. *über* Marktrendite aus B+C+D zusammen bereits ein hervorragendes Ergebnis — die Marktrendite selbst (historisch 7–10 % p. a. vor Inflation, mit 30 %+-Rückschlägen) liefert das Fundament. „Auch nur kleine Gewinne" ist also nicht der Trostpreis, sondern exakt das realistische Ziel — und mehr, als die große Mehrheit der aktiven Marktteilnehmer je erreicht.

---

## 7. Nachtrag — Börsenwechsel und Lückencheck

### 7a. Was die Kostenrechnung vom 22.08. ändert

Die Jupiter-Perps-Analyse hat das Krypto-Urteil präzisiert: **das Einstiegssignal des Crypto-Bots trägt** — vor Kosten +370,43 $ mit t = 3,49, also statistisch belegt. Die 0,62 % Kraken-Roundtrip fressen es vollständig auf (Break-even ~0,67 %), und der Vorteil sitzt in den kleineren Alts (t = 3,03), nicht in SOL/ETH/BTC. Jupiter selbst scheidet aus (nur 3 der 20 Coins handelbar). Damit ist der geplante Börsenwechsel nicht mehr nur „mehr Auswahl, andere Kosten" — er ist **der eine Hebel, an dem hängt, ob aus dem eingefrorenen Bot wieder ein Kandidat wird.** Die Vorbehalte aus der Sitzung gelten unverändert: Kosten rückwirkend auf denselben Daten getauscht (kein Vorwärtstest), 44 Tage, und Perps sind kein Spot.

### 7b. Krypto-Venue: die Kandidaten gegen die 0,67-%-Hürde

| Venue | Kosten Roundtrip (Basis-Stufe) | Anmerkung |
|---|---|---|
| Kraken, Market-Order (Ist) | ~62 bp inkl. Slippage-Simulation | Break-even-Fall — gemessen |
| Kraken, **Maker**-Order (post-only) | ~32 bp + weniger Slippage | **Sofort-Hebel ohne Wechsel** — aber Fill-Risiko: nicht jede Limit-Order wird bedient, verpasste Entries kosten unsichtbar. Erst im Paper messen |
| [Hyperliquid Perps](https://hyperliquidguide.com/guides/fees/fees-explained) | Taker 2 × 0,045 % = **9 bp**, Maker 2 × 0,015 % = 3 bp; 1 USDC Auszahlungsgebühr | Breites Alt-Universum (gegen unsere 20er-Liste konkret zu prüfen); stündliches Funding; Perps, nicht Spot |
| [dYdX](https://help.dydx.trade/en/articles/166995-trading-fees-on-dydx) | Maker/Taker-Staffel nach 30-Tage-Volumen, Größenordnung einstellige bp | Stand 02.08. ungeprüft auf der Leads-Liste; konkrete Stufe vor dem Test ablesen |

Was zusätzlich zur Gebühr halten muss, bevor eine Portierung Kandidat wird: **(1)** die tatsächliche On-Chain-/Orderbuch-Slippage — die Sensitivitätsrechnung vom 22.08. zeigt, dass ab 0,2 % je Seite der Vorteil weg ist; **(2)** die Alt-Abdeckung der konkreten Coin-Liste; **(3)** der Strukturwechsel Spot → Perps: Funding-/Leihkosten laufen richtungsunabhängig, Liquidationsrisiko existiert selbst ohne gewollten Hebel, und der Bot ist heute long-only-Spot gebaut; **(4)** Selbstverwahrung und Bridge-Weg (USDC auf Arbitrum bei Hyperliquid) — anderes Gegenparteirisiko als eine Börse mit Konto; Oracle-Störungen auf Perp-DEXen sind real (der SPACEX-USDH-Vorfall im Mai liquidierte [405 Trader in 30 Minuten](https://bitsgap.com/blog/why-copying-on-chain-whale-trades-usually-backfires) durch einen Datenfehler). **Vorgehen deshalb wie immer:** venue-echtes Kostenmodell (Gebühr + gemessene Slippage + Funding) in einen Paper-Clone, 4–8 Wochen Vorwärtstest, erst dann die Kapitalfrage. Der Wechsel läuft als **paralleler Herausforderer**, nie als Migration des Maßstabs mitten in laufenden Tests.

### 7c. Aktien-Seite: IBKR als Herausforderer (Juli-Entscheidung bestätigt)

Für Aktien bleibt der Plan vom 25.07. richtig und wird durch das Neudenken eher stärker: [IBKR](https://brokerchooser.com/broker-reviews/interactive-brokers-review/interactive-brokers-fees) parallel als Clone (Paper zuerst), Alpaca bleibt Kontrolle und Messumgebung. Der Wechsel öffnet vier Dinge, die zur neuen Strategie passen: das **globale Universum** (Xetra, London, Asien) für das Monats-Momentum-System; **Optionen** — damit wird die Volatilitätsprämie (Covered Calls auf Fundament-Positionen) als späterer, evidenzgestützter Stufe-2-Kandidat überhaupt erst technisch möglich; **Futures** als kostengünstigster Weg für Trendfolge, falls das Kapital dafür je reicht; und **Zins auf unbeschäftigtes Guthaben** ([IBKR verzinst Cash](https://www.interactivebrokers.co.uk/de/accounts/fees/pricing-interest-rates.php), Konditionen beim Anbinden prüfen) — ein kleiner, sicherer „Haus-Ertrag", den das Alpaca-Paper-Setup gar nicht abbildet.

### 7d. Lückencheck: was bisher in keinem Dokument stand

Vier Hebel, die weder in der Portfolio-Architektur noch im bisherigen Neudenken vorkamen — alle legal, alle klein, alle real:

**Maker- statt Taker-Ausführung** (siehe Tabelle 7b): der einzige Kostenhebel, der ohne Börsenwechsel wirkt. Halbiert die Gebühr, kostet dafür Fill-Sicherheit — messbar im bestehenden Paper-Setup, bevor irgendeine Wechsel-Entscheidung fällt.

**Die deutsche Steuer-Asymmetrie.** Privat gehaltene Coins sind nach [einem Jahr Haltefrist steuerfrei](https://www.blockpit.io/de-de/steuer-guides/krypto-haltefrist) (§ 23 EStG); jeder Verkauf innerhalb des Jahres und alles Derivate-/Perps-Geschäft ist steuerpflichtig. Das ist ein struktureller Rückenwind von bis zu ~26 % Nachsteuer-Differenz für Schiene 1 (Halten) gegenüber jedem Handelsansatz — ein „Edge", den kein Backtest zeigt, weil er nach der Rendite ansetzt. Wichtig: die [Reform-Debatte läuft](https://www.btc-echo.de/news/krypto-steuer-vorerst-vom-tisch-haltefrist-fehlt-im-jahressteuergesetz-2026-234973/) (im Entwurf des Jahressteuergesetzes 2026 fehlt die Abschaffung bislang) — vor Entscheidungen, die darauf bauen, Stand prüfen; ich bin kein Steuerberater.

**Zins auf Cash.** In jeder künftigen Live-Rechnung gehört der Guthabenzins als Vergleichslinie hinein: eine Strategie muss nicht nur den Index schlagen, sondern erst einmal das, was das Kapital risikolos verdient, während es auf Signale wartet.

**Options-Prämie als späterer Kandidat.** Systematisches Verkaufen von Volatilität (Covered Calls) hat dokumentierte Prämien-Evidenz und passt zur Haus-Logik aus Abschnitt 1 — aber erst, wenn IBKR angebunden ist und die laufenden Vorwärtstests entschieden sind. Kein neues Projekt vor Abarbeitung der bestehenden; es steht hier, damit es nicht verloren geht.

Und eine Messlücke aus der 22.08.-Sitzung, die vor jeder Portierung zu schließen ist: die Trade-Datensätze speichern **keine Einstiegszeit** — für Haltedauer-, Funding- und Slippage-Rechnungen auf einer neuen Venue ist die Pflicht.

---

*Keine Anlageberatung — ich bin kein Finanzberater; Entscheidungen über echtes Kapital bleiben wie im Handlungsrahmen festgelegt bei Andreas. Recherchequellen sind oben verlinkt; interne Zahlen stammen aus SITZUNGEN.md (21.08.2026), PORTFOLIO_ARCHITEKTUR.md (26.07.2026) und NEUAUSRICHTUNG_SUPER_BOT.md (25.07.2026).*
