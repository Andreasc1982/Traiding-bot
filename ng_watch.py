#!/usr/bin/env python3
"""Wacht ueber neue "Nacktes Geld"-Folgen und meldet Verwertbares per Telegram.

Neue Folgen erscheinen freitags ab 06:00. Die Untertitel kommen von der
PeerTube-API hinter paulbrandenburg.com — kein Download, kein Whisper, ~150 KB
je Folge, mit Zeitstempeln. Ausgewertet wird NICHT auf Meinung, sondern auf die
Themen, die sich als verwertbar erwiesen haben: Rebalancing-Termine,
Geldmarkt-Stress, Index-Umbauten, Spreads.

Zeitstempel werden mitgemeldet, damit man die Stelle direkt anhoeren kann.

    python3 ng_watch.py           # neue Folgen holen und melden
    python3 ng_watch.py --init    # Bestand erfassen OHNE zu melden
    python3 ng_watch.py --dry     # auswerten, aber nicht senden
"""
import os, sys, re, json, time
import urllib.request, urllib.parse

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
try:
    from config import config
except Exception:
    config = {}

API = "https://tube.theplattform.net/api/v1"
HOST = "https://tube.theplattform.net"
DIR = os.path.join(BASE, "ng")
STATE = os.path.join(DIR, "ng_state.json")
TEXTE = os.path.join(DIR, "texte")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
NUMMER = re.compile(r"Nacktes Geld\s*#\s?(\d{1,3})", re.I)

INIT = "--init" in sys.argv
DRY = "--dry" in sys.argv
TEXTE_MODUS = "--texte" in sys.argv   # vorhandene ng/texte/*.txt auswerten

# Nur was sich als verwertbar erwiesen hat — bewusst eng, sonst meldet es
# jede Woche denselben Makro-Kommentar. Erweitern, wenn ein neues Thema
# tatsaechlich zu einer pruefbaren Idee gefuehrt hat.
#
# Zweistufig wie in tg_watch.py: ein EINDEUTIGER Begriff genuegt fuer eine
# Meldung, ALLGEMEINE zaehlen erst ab zwei verschiedenen. Grund: "future" oder
# "leitzins" faellt in jeder zweiten Folge, "crack spread" nie ohne Anlass.
# Loeschen waere falsch — die Comex-Margin-Anhebung in #049 haengt an "future".
THEMEN = {
    "Rebalancing/Index": {
        "eindeutig": ["rebalanc", "bloomberg commodity", "bcom", "indexgewicht",
                      "zielgewicht", "neugewichtung", "rekonstitution",
                      "aus dem index", "in den index"],
        "allgemein": ["russell", "msci", "stichtag", "quartalsende", "benchmark"],
    },
    "Geldmarkt/Repo": {
        "eindeutig": ["sofr", "sofa", "repo", "reverse repo", "standing repo",
                      "liquiditaetsspritze", "liquiditätsspritze", "injiziert",
                      "diskontfenster", "eurodollar"],
        "allgemein": ["bilanzsumme", "leitzins"],
    },
    "Spread/Termin": {
        "eindeutig": ["crack spread", "backwardation", "contango", "rollverlust",
                      "terminkurve"],
        "allgemein": ["future", "basis", "verfall", "sicherheitsleistung",
                      "termingeschaeft", "termingeschäft"],
    },
    "Ausfuehrung/Boerse": {
        "eindeutig": ["margin-parameter", "orderbuch", "market maker", "xstock",
                      "dydx", "jupiter", "tokenisiert"],
        "allgemein": ["liquidation", "gegenpartei"],
    },
}

# Wortgrenzen statt Substring — "russell" traf sonst "Karussell" (Folge #053),
# genau wie "Mallorca"->orca in tg_watch.py. Praefixe wie "rebalanc" sollen
# weiter greifen (rebalancing/Rebalancierung), deshalb nur die linke Grenze.
def _rx(worte):
    return re.compile(r"(?<!\w)(?:%s)" % "|".join(re.escape(w) for w in worte),
                      re.I)

RX = {t: {"eindeutig": _rx(d["eindeutig"]), "allgemein": _rx(d["allgemein"])}
      for t, d in THEMEN.items()}
MIN_ALLGEMEIN = 2

# Treffer, die trotz Wortgrenze das Falsche meinen. "Basispunkte" faellt in
# fast jeder Folge und hat mit der Termin-Basis nichts zu tun.
NICHT = {"basis": re.compile(r"basispunkt", re.I)}


def _erster_echter(rx, satz):
    """Erster Treffer, der nicht durch NICHT disqualifiziert ist."""
    for m in rx.finditer(satz):
        w = m.group(0).lower()
        aus = NICHT.get(w)
        if aus and aus.match(satz, m.start()):
            continue
        return m
    return None


def tg_send(text):
    tok, chat = config.get("telegram_bot_token"), config.get("telegram_chat_id")
    if not tok or not chat:
        print("[TG] kein Token/Chat — kein Versand.")
        return
    for i in range(0, len(text), 3800):
        data = urllib.parse.urlencode({
            "chat_id": chat, "text": text[i:i + 3800],
            "disable_web_page_preview": "true"}).encode()
        try:
            urllib.request.urlopen(
                "https://api.telegram.org/bot%s/sendMessage" % tok, data,
                timeout=15)
        except Exception as e:
            print("[TG] Sendefehler:", str(e)[:80])


def hole(url, roh=False, versuche=3):
    letzte = None
    for i in range(versuche):
        try:
            r = urllib.request.Request(url, headers={"User-Agent": UA})
            d = urllib.request.urlopen(r, timeout=60).read()
            return d if roh else json.loads(d)
        except Exception as e:
            letzte = e
            time.sleep(3 * (i + 1))
    raise letzte


def folgen_liste():
    folgen, start = {}, 0
    while True:
        d = hole("%s/search/videos?search=Nacktes%%20Geld&count=100&start=%d"
                 "&sort=-publishedAt" % (API, start))
        daten = d.get("data") or []
        if not daten:
            break
        for v in daten:
            m = NUMMER.search(v.get("name") or "")
            if m:
                folgen[int(m.group(1))] = (v["uuid"], v.get("name"),
                                           v.get("publishedAt", "")[:10])
        start += len(daten)
        if start >= d.get("total", 0):
            break
        time.sleep(0.3)
    return folgen


def untertitel(uuid):
    """-> [(sekunden, text), ...] oder None."""
    caps = hole("%s/videos/%s/captions" % (API, uuid))
    pfad = None
    for c in caps.get("data", []):
        if (c.get("language") or {}).get("id", "").startswith("de"):
            pfad = c.get("captionPath")
            break
    if not pfad:
        return None
    vtt = hole(HOST + pfad, roh=True).decode("utf-8", "replace")
    out, zeit, vorher = [], 0.0, None
    for l in vtt.splitlines():
        l = l.strip()
        if "-->" in l:
            t = l.split("-->")[0].strip().replace(",", ".")
            teile = [float(x) for x in t.split(":")]
            zeit = sum(v * 60 ** (len(teile) - 1 - i)
                       for i, v in enumerate(teile))
        elif l and not l.startswith("WEBVTT") and not l.isdigit():
            if l != vorher:
                out.append((zeit, l))
                vorher = l
    return out


def pruefe(zeilen):
    """-> {thema: [(mm:ss, begriff, satz), ...]}

    zeilen: [(sekunde_oder_None, satz)]. Ein Thema wird nur gemeldet, wenn ein
    eindeutiger Begriff faellt ODER mindestens MIN_ALLGEMEIN verschiedene
    allgemeine. Das haelt "in jeder Folge einmal Leitzins" draussen, ohne den
    Begriff zu verlieren, wenn er zusammen mit anderen auftritt.
    """
    roh = {}
    for i, (sek, satz) in enumerate(zeilen):
        for thema, rx in RX.items():
            for art in ("eindeutig", "allgemein"):
                m = _erster_echter(rx[art], satz)
                if not m:
                    continue
                ctx = " ".join(s for _, s in zeilen[max(0, i - 1):i + 3])
                zeit = ("%d:%02d" % (int(sek // 60), int(sek % 60))
                        if sek is not None else "—")
                roh.setdefault(thema, []).append(
                    (art, zeit, m.group(0).lower(), ctx[:400]))
                break

    treffer = {}
    for thema, funde in roh.items():
        stark = [f for f in funde if f[0] == "eindeutig"]
        schwach_begriffe = {f[2] for f in funde if f[0] == "allgemein"}
        if stark or len(schwach_begriffe) >= MIN_ALLGEMEIN:
            # Eindeutige zuerst, damit das Wesentliche oben in der Meldung steht
            treffer[thema] = [(z, b, c) for _, z, b, c in
                              sorted(funde, key=lambda f: f[0] != "eindeutig")]
    return treffer


def text_zu_zeilen(text):
    """Transkript ohne Zeitmarken in Saetze zerlegen — fuer ng/texte/*.txt."""
    saetze = re.split(r"(?<=[.!?])\s+", text.replace("\n", " "))
    return [(None, s.strip()) for s in saetze if s.strip()]


def texte_auswerten():
    """Wertet die lokal liegenden Transkripte aus (Whisper-Ergebnisse).

    Noetig, weil der Online-Zweig nur Folgen anfasst, die noch nicht in
    'gesehen' stehen — durch ein frueheres --init stehen dort ALLE, also wurden
    die per Whisper erzeugten Texte nie geprueft. Ruehrt den Zeiger nicht an.
    """
    dateien = sorted(f for f in os.listdir(TEXTE) if f.endswith(".txt"))
    if not dateien:
        print("Keine Transkripte in %s." % TEXTE)
        return
    print("%d Transkripte werden geprueft." % len(dateien))
    meldungen = []
    for f in dateien:
        text = open(os.path.join(TEXTE, f), encoding="utf-8",
                    errors="ignore").read()
        tr = pruefe(text_zu_zeilen(text))
        print("  %s — %d Woerter, %d Themen" % (f, len(text.split()), len(tr)))
        if not tr:
            continue
        teile = ["📻 Folge %s (Transkript)" % f[:-4]]
        for thema, stellen in tr.items():
            gesehen_b = set()
            teile.append("\n▸ %s" % thema)
            for zeit, b, ctx in stellen:
                if b in gesehen_b:
                    continue
                gesehen_b.add(b)
                teile.append("  %s\n  %s" % (b, ctx[:260]))
        meldungen.append("\n".join(teile))
    if not meldungen:
        print("nichts Meldenswertes.")
        return
    txt = "\n\n".join(meldungen)
    print(txt)
    if not DRY:
        tg_send(txt)


def main():
    os.makedirs(TEXTE, exist_ok=True)
    if TEXTE_MODUS:
        texte_auswerten()
        return
    try:
        state = json.load(open(STATE))
    except Exception:
        state = {"gesehen": []}
    gesehen = set(state.get("gesehen", []))

    folgen = folgen_liste()
    neu = sorted(set(folgen) - gesehen)
    print("%d Folgen online, %d neu" % (len(folgen), len(neu)), flush=True)

    if INIT:
        state["gesehen"] = sorted(set(folgen))
        json.dump(state, open(STATE, "w"))
        print("Bestand erfasst (%d Folgen), nichts gemeldet." % len(folgen))
        return

    meldungen = []
    for n in neu:
        uuid, name, datum = folgen[n]
        try:
            zeilen = untertitel(uuid)
        except Exception as e:
            print("  #%d Fehler: %s" % (n, str(e)[:60]))
            continue          # Zeiger NICHT setzen -> naechster Lauf holt es
        if not zeilen:
            print("  #%d noch keine Untertitel — spaeter erneut" % n)
            continue          # Untertitel entstehen oft erst Stunden spaeter
        text = " ".join(s for _, s in zeilen)
        open(os.path.join(TEXTE, "%03d.txt" % n), "w").write(text)
        tr = pruefe(zeilen)
        gesehen.add(n)
        print("  #%d %s — %d Woerter, %d Themen"
              % (n, name, len(text.split()), len(tr)))
        if tr:
            teile = ["📻 %s (%s)" % (name, datum)]
            for thema, stellen in tr.items():
                gesehen_b = set()
                teile.append("\n▸ %s" % thema)
                for zeit, b, ctx in stellen:
                    if b in gesehen_b:
                        continue
                    gesehen_b.add(b)
                    teile.append("  [%s] %s\n  %s" % (zeit, b, ctx[:260]))
            meldungen.append("\n".join(teile))

    state["gesehen"] = sorted(gesehen)
    json.dump(state, open(STATE, "w"))

    if not meldungen:
        print("nichts Meldenswertes.")
        return
    txt = "\n\n".join(meldungen)
    print(txt)
    if not DRY:
        tg_send(txt)


main()
