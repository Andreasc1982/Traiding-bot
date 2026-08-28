#!/usr/bin/env python3
"""Gemeinsame Textbausteine fuer die Telegram-Nachrichten beider Bots.

Warum ein eigenes Modul: super_bot und crypto_bot hatten je eigene
Uebersetzungstabellen (`_de_reason` hier, `GRUND_DE` dort) — zwei Kopien
derselben Idee, die zwangslaeufig auseinanderlaufen. Ein neuer Exit-Grund
haette sonst in einem Bot Klartext und im anderen ein Kuerzel ergeben.

Gestaltungsregeln (von Andreas abgenommen, 13.08.2026):
  - Kernaussage zuerst, kompakt, 3-6 Zeilen
  - deutsche Zahlen (4.231,80), echtes Minuszeichen
  - Farbe sagt sofort Gewinn/Verlust
  - keine Indikator-Kuerzel, sondern Klartext
  - jede Warnung sagt, was sie fuer den Leser bedeutet

Die vollstaendigen Kennzahlen bleiben in Konsole und Dashboard — Telegram
ist die Zusammenfassung, nicht das Logbuch.

Unbekannte Schluessel fallen ABSICHTLICH auf den Rohwert zurueck: ein neuer
Exit-Grund faellt dann im Chat auf und wird nachgetragen, statt still falsch
uebersetzt zu werden.
"""
from datetime import datetime

# ── Verkaufsgruende ──────────────────────────────────────────────────────
# "WS-TRAIL-STOP" sagt einem Menschen nichts. Der Text sagt zusaetzlich,
# ob das Ergebnis gewollt war (Gewinn gesichert) oder nicht (Stop gerissen).
GRUND_DE = {
    "WS-STOP-LOSS":    "Stop-Loss gerissen",
    "STOP-LOSS":       "Stop-Loss gerissen",
    "WS-TRAIL-STOP":   "Gewinn gesichert (Rücksetzer vom Hoch)",
    "TRAIL-STOP":      "Gewinn gesichert (Rücksetzer vom Hoch)",
    "WS-PROFIT-LOCK":  "Gewinn gesichert (Kursrückgang nach Hoch)",
    "PROFIT-LOCK":     "Gewinn gesichert (Kursrückgang nach Hoch)",
    "WS-BREAKEVEN":    "auf Einstand geschlossen (kein Verlust)",
    "BREAKEVEN":       "auf Einstand geschlossen (kein Verlust)",
    "WS-PSAR-STOP":    "Trend gedreht (nachgezogener Stop)",
    "PSAR-STOP":       "Trend gedreht (nachgezogener Stop)",
    "TAKE-PROFIT":     "Kursziel erreicht",
    "WS-TAKE-PROFIT":  "Kursziel erreicht",
    "TIME-EXIT":       "lief zu lange nicht an",
    "TIME-EXIT-MAX":   "zu lange gehalten",
    "TIME-EXIT-STUCK": "lief zu lange nicht an",
    "RISK-CLOSE-ALL":  "Risikobremse hat alles geschlossen",
}

LAGE_DE = {
    "TRENDING":     "starker Trend",
    "TRANSITIONAL": "Trend im Aufbau",
    "RANGING":      "seitwärts",
}

# Drawdown-Zonen (wie tief das Depot im Minus steht)
ZONE_DE = {
    "HEALTHY": "Depot unauffällig",       "CAUTION": "Depot im Minus",
    "WARNING": "Depot deutlich im Minus", "DANGER":  "Depot stark im Minus",
}

# Schwankungsbreite: VIX (Aktien) bzw. realisierte Volatilitaet (Crypto)
VIX_DE = {
    "LOW":     "ruhiger Markt",      "NORMAL":  "normale Schwankung",
    "ELEVATED": "nervöser Markt",    "HIGH":    "unruhiger Markt",
    "EXTREME": "sehr unruhiger Markt",
}

SEKTOR_DE = {
    "energy": "Energie", "oil": "Öl", "industry": "Industrie", "steel": "Stahl",
    "defense": "Rüstung", "finance": "Finanzen", "tech": "Technologie",
    "gold": "Gold", "infra": "Infrastruktur", "crypto": "Krypto",
}

# Handelsplatz-Namen fuer die Startmeldung
BOERSE_DE = {"alpaca": "Alpaca (Papierhandel)", "kraken": "Kraken"}

# ── Absender ─────────────────────────────────────────────────────────────
# Im Chat laufen die Meldungen mehrerer Bots zusammen. Ohne Kennung ist am
# Handy nicht zu erkennen, wer gekauft hat — die Kuerzel im Titel helfen nicht
# (UNI ist Krypto, GLD ist der Super-Bot, beide heissen nur nach ihrem Papier).
BOT_NAMEN = {
    "crypto":    "Krypto-Bot",
    "super":     "Super-Bot",
    "fundament": "Fundament-Bot",
}

# Schreibweisen, die bereits als Absender durchgehen. Ohne diese Liste haengt
# absender() an "Krypto-Bot gestartet" noch ein "· Krypto-Bot" an.
BOT_ALIASSE = {
    "crypto":    ("Krypto-Bot", "Crypto-Bot", "CRYPTO"),
    "super":     ("Super-Bot", "SUPER"),
    "fundament": ("Fundament-Bot", "Fundament"),
}


def absender(text, bot):
    """Haengt die Bot-Kennung an die ERSTE Zeile.

    Bewusst die erste Zeile: die Push-Vorschau auf dem Handy zeigt nur diese.
    Eine eigene Zeile am Ende waere unsichtbar, solange die Nachricht zu ist.
    Mehrfaches Anwenden aendert nichts (die Kennung wird erkannt).
    """
    name = BOT_NAMEN.get(bot, str(bot))
    if not text:
        return text
    zeilen = text.split("\n")
    if any(a in zeilen[0] for a in BOT_ALIASSE.get(bot, (name,))):
        return text
    zeilen[0] = zeilen[0].rstrip() + " · " + name
    return "\n".join(zeilen)


def esc(text):
    """HTML-Sonderzeichen entschaerfen — sonst verwirft Telegram die Nachricht."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def de(zahl, stellen=0):
    """Deutsche Schreibweise: 4.231,80 statt 4231.8"""
    try:
        s = "{:,.{}f}".format(float(zahl), stellen)
    except (TypeError, ValueError):
        return esc(zahl)
    return s.replace(",", "#").replace(".", ",").replace("#", ".")


def vz(zahl, stellen=0):
    """Mit echtem Minuszeichen — das kurze - geht auf dem Handy unter."""
    try:
        z = float(zahl)
    except (TypeError, ValueError):
        return esc(zahl)
    return ("+" if z >= 0 else "−") + de(abs(z), stellen)


def preis(p):
    """Kurse spannen von 0,00000563 (BONK) bis 118.000 (BTC).

    Feste Nachkommastellen scheitern an beiden Enden: 2 Stellen machen aus
    einem Meme-Coin 0,00 $, 8 Stellen machen aus Bitcoin eine Zahlenwueste.
    """
    try:
        p = float(p)
    except (TypeError, ValueError):
        return esc(p)
    if p >= 1000:
        return de(p, 0)
    if p >= 1:
        return de(p, 2)
    if p >= 0.01:
        return de(p, 4)
    return de(p, 8)


def menge(x):
    """Stueckzahlen — beide Bots kaufen Bruchstuecke (0,3652 GLD; 0,04 BTC).

    Auf 0 Stellen gerundet stuende dort "0 Stück".
    """
    try:
        x = float(x)
    except (TypeError, ValueError):
        return esc(x)
    if x >= 100:
        return de(x, 0)
    if x >= 10:
        return de(x, 1)
    if x >= 1:
        return de(x, 2)
    return de(x, 4)


def dauer(seit_str):
    """'3 Tage' / '5 Std.' — wie lange die Position lief. None wenn unbekannt."""
    if not seit_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            seit = datetime.strptime(str(seit_str).strip(), fmt)
            break
        except ValueError:
            continue
    else:
        return None
    st = (datetime.now() - seit).total_seconds() / 3600.0
    if st < 0:
        return None
    if st < 1:
        return "%d Min." % max(1, int(st * 60))
    if st < 48:
        return "%d Std." % int(st)
    return "%d Tage" % int(st / 24)


def grund(reason):
    return GRUND_DE.get(reason, esc(reason))


def lage(regime):
    return LAGE_DE.get(regime, str(regime).lower())


def verkauf(titel, profit, pnl_pct, reason, gehalten_seit, kontostand):
    """Verkaufs-Nachricht — fuer beide Bots identisch aufgebaut."""
    zeilen = [
        ("🟢" if profit >= 0 else "🔴") + " <b>VERKAUF · " + titel + "</b>",
        "",
        "Ergebnis: <b>" + vz(profit) + " $</b>  (" + vz(pnl_pct, 1) + " %)",
        "Grund: " + grund(reason),
    ]
    d = dauer(gehalten_seit)
    if d:
        zeilen.append("Gehalten: " + d)
    zeilen += ["", "Kontostand: " + de(kontostand) + " $"]
    return "\n".join(zeilen)
