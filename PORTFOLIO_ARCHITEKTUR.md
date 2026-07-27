# Portfolio-Architektur — zwei Achsen, drei Stufen

Stand 2026-07-26. Grundlage sind ausschliesslich eigene Messungen.

## Der Denkfehler, der hier korrigiert wird

Eine erste Fassung legte Anlageklasse und Risikostufe auf **eine** Achse
(„Aktien = sicherer Kern, Crypto = aggressiv"). Das ist falsch. Es sind zwei
**unabhaengige** Achsen:

- **Achse A — Risikostufe:** wie viel Kapital, welcher Horizont, welcher Schutz.
- **Achse B — Anlageklasse:** welche Datenquellen, welche Auswahllogik, welche
  Kostenschwelle.

Eine Crypto-Position kann als kleiner Beimischer im Fundament stehen *oder* als
Wette im aggressiven Teil. Aber die **Strategie**, die sie auswaehlt, muss mit
crypto-eigenen Daten und Kosten gebaut werden — sie laesst sich nicht aus der
Aktienwelt uebertragen.

## Achse B — warum Aktien und Crypto getrennt gebaut werden muessen

| | Aktien | Crypto |
|---|---|---|
| Kosten Roundtrip | **4 bp** (Alpaca, kommissionsfrei) | **62 bp** (Kraken Spot) |
| Fundamentaldaten | Form 4, Earnings, Indexmechanik | existiert nicht |
| Handelszeit | Boersenzeiten | 24/7 |
| gemessener Edge bei uns | 1 Kandidat (`ins_netto_90`, im Test) | keiner |

Der Kostenunterschied allein entscheidet ueber Machbarkeit: dieselbe
Umschlagshaeufigkeit ist in einer Welt tragbar und in der anderen ruinoes. Die
Crypto-Clones waren bei dYdX-Kosten neutral und bei Kraken **signifikant
negativ** — der Verlust war ein Kosten-, kein Strategieergebnis.

**Was sich sehr wohl uebertragen laesst, ist die Methode**, nicht das Signal:
Kostenschwelle vor Signalsuche, ueberlappungsfreie Pruefung, Querschnitt statt
gepoolt, Vorwaerts- statt Rueckwaertstest, Survivorship-Bias mitdenken.

## Achse A — Risiko, gemessen statt vermutet

8 Jahre Tagesdaten, gemeinsame Handelstage:

| Anlage | Korr. zu Aktien | Vola p. a. | max Rueckgang |
|---|---|---|---|
| Aktien breit (SPY) | 1,00 | 19,4 % | −33,7 % |
| Tech (XLK) | 0,93 | 26,9 % | −33,6 % |
| Anleihen **lang** (TLT) | −0,14 | 15,7 % | **−48,4 %** |
| Anleihen **kurz** (SHY) | −0,03 | **1,7 %** | **−5,7 %** |
| Gold (GLD) | 0,12 | 17,2 % | −26,4 % |
| Rohstoffe (DBC) | 0,31 | 18,8 % | −41,7 % |
| Bitcoin | **0,33** | **56,1 %** | **−76,5 %** |
| Ethereum | 0,35 | 72,9 % | −81,9 % |

Zwei Ergebnisse widersprechen der Intuition:

1. **Crypto ist kein Diversifikator.** Korrelation zu Aktien 0,33 — und
   **steigend**: frueheres Drittel +0,22, letztes Drittel +0,33, Hoechststand
   +0,55 in 2022/23. Es ist dieselbe Risikoklasse mit dreifacher Amplitude, kein
   Gegengewicht. Im Crash faellt es **mit** Aktien, nur tiefer.
2. **Lange Anleihen sind nicht der defensive Baustein.** TLT hatte mit −48,4 %
   einen groesseren Rueckgang als Aktien (Zinsschock 2022). Defensiv sind
   **kurze** Laufzeiten.

### Diversifikation verschiedener Mischungen

| Mischung | Teile | mittl. Korr. | effektiv unabhaengig |
|---|---|---|---|
| nur 10 Sektor-ETFs | 10 | 0,42 | **2,1** |
| echte Anlageklassen (SPY/TLT/GLD/DBC) | 4 | 0,11 | **3,0** |
| Anlageklassen + BTC | 5 | 0,12 | 3,4 |
| Aktien + BTC | 2 | 0,33 | 1,5 |

Vier echte Anlageklassen streuen besser als zehn Aktiensektoren. Bitcoin fuegt
etwas hinzu — bezahlt mit 56 % Volatilitaet.

### Konsequenz fuer die Positionsgroesse
Risiko skaliert mit Volatilitaet. Bei 56 % gegen 19 % traegt **1 $ Crypto rund
das Dreifache** an Risiko wie 1 $ Aktien. Wer gleiches Risiko will, gewichtet
Crypto auf **ein Drittel** der Aktienposition. „Gleich viel Geld" ist nicht
gleich viel Risiko.

## Die drei Stufen (Achse A)

### Stufe 1 — Fundament (~65 %)
Marktrendite einsammeln, kein Timing, keine Stops. Streuung ueber **Anlageklassen**,
defensiver Teil in **kurzen** Laufzeiten. Feste Zielgewichte, Rueckfuehrung bei
Abweichung. Ehrliche Erwartung: 6–9 % p. a. **mit** zwischenzeitlichen Rueckgaengen
von 30 %+. „Langfristig" heisst nicht risikolos, sondern Rueckgaenge aussitzen
statt handeln.

### Stufe 2 — Systematisch (~28 %, startet bei 0 %)
**Aufnahmeregel: mindestens 3 Monate unverzerrter Vorwaertstest.** Backtests
qualifizieren nicht. Derzeit **leer**; einziger Kandidat `ins_netto_90` im
Papierdepot (Dashboard Port 8097). Solange leer, liegt das Geld in Stufe 1.

### Stufe 3 — Aggressiv (max. 7 %, harte Grenze)
Verbrauchbares Budget. Statt „soll break-even sein" (loest keine Entscheidung
aus): **Frist + Abschaltkriterium**. House-Money-Regel: bei Verdopplung Einsatz
entnehmen und nach Stufe 1 ueberfuehren.

## Wo unser Aufwand heute steckt — und warum das umgekehrt ist

| Bereich | Screen-Sessions | Kosten | gemessener Edge |
|---|---|---|---|
| Crypto (Bot, Gateway, 4 Clones, Dashboard) | ~7 | 62 bp | keiner |
| DEX (Monitor, Paper, Bundle, Dashboard) | ~4 | ~1000 bp | **negativ bei 0 % Kosten** |
| Aktien (Super-Bot, Dashboard) | ~2 | 4 bp | 1 Kandidat im Test |

**Der Aufwand ist fast exakt invers zur Evidenz verteilt.** Das ist der
wichtigste praktische Befund dieses Dokuments.

## Naechste Schritte

1. **DEX beenden** — Abschaltkriterium erfuellt (verliert auch bei 0 % Slippage
   signifikant). Kein Feintuning mehr.
2. **Stufe 1 bauen** — braucht keinen Edge, sofort umsetzbar, ist die Renditequelle.
3. **Insider-Vorwaertstest laufen lassen**, Entscheidung fruehestens Ende Oktober 2026.
4. **Crypto nicht ausbauen**, bevor es (a) eine tragbare Kostenbasis und (b) eine
   eigene Datenschicht gibt. Die dYdX-Kostenarbeit ist Voraussetzung, keine Strategie.
