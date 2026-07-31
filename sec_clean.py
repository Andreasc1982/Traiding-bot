#!/usr/bin/env python3
"""Ausreisser-Filter fuer Form-4-Transaktionen — gemeinsam fuer beide Fetcher.

Die SEC uebernimmt Form-4-Angaben ungeprueft. Ein Melder, der sich im
Preisfeld vertippt, produziert Werte, die jede Auswertung dominieren:
insider_daily.csv enthielt 412 Ticker-Tage ueber $100 Mio und 123 ueber
$1 Mrd — bei einem Median von $169.873. Spitzenwert $3,2 Billiarden.

Das ist fuer ins_netto_90 (Netto-Kauf skaliert am Tagesumsatz) besonders
schaedlich: ein einziger Tippfehler hebt einen Titel im $5-10M-ADV-Band
garantiert ins Top-Dezil — genau das Band, in dem der Effekt gemessen wurde.

Zwei Tests, bewusst konservativ, damit echte Grosskaeufe durchkommen
(Berkshire/OXY lag bei ~$400 Mio je Transaktion):
"""

# Preis gilt als Tippfehler, wenn er den Median des Filings um mehr als
# diesen Faktor uebersteigt. NMM 2026-07-27: Preise 77,64 / 79,02 / 748119
# in EINER Meldung fuer dieselbe Common Unit -> Median 79,02, Grenze 1580.
MEDIAN_FAKTOR = 20

# Ab 3 Transaktionen ist der Median belastbar; bei 2 waere er einer der
# beiden Werte und der Test wuerde raten.
MIN_FUER_MEDIAN = 3

# Absolute Schranke fuer Einzeltransaktionen ohne Median-Kontext.
MAX_TRANSAKTION_USD = 1e9


def filter_ausreisser(trans):
    """trans: [(code, shares, preis), ...] EINES Filings -> gefilterte Liste.

    Gibt zusaetzlich zurueck, wie viele Transaktionen verworfen wurden,
    damit der Aufrufer es protokollieren kann statt still zu schlucken.
    """
    n_vorher = len(trans)
    if n_vorher >= MIN_FUER_MEDIAN:
        preise = sorted(t[2] for t in trans)
        median = preise[len(preise) // 2]
        if median > 0:
            grenze = MEDIAN_FAKTOR * median
            trans = [t for t in trans if t[2] <= grenze]
    trans = [t for t in trans if t[1] * t[2] <= MAX_TRANSAKTION_USD]
    return trans, n_vorher - len(trans)


# Platzhalter, die manche Filer statt eines Handelssymbols eintragen.
# Ohne diesen Test landen alle symbollosen Emittenten im Sammel-Ticker "NONE".
PLATZHALTER = ("NONE", "NA", "N", "NULL", "NOTAP")


def ticker_gueltig(tic):
    """Form-4-Symbole sind rein alphabetisch und hoechstens 5 Zeichen."""
    tic = (tic or "").strip().upper()
    if not tic or not tic.isalpha() or len(tic) > 5:
        return None
    if tic in PLATZHALTER:
        return None
    return tic
