#!/usr/bin/env python3
"""Wacht ueber neue Blockzocker-Folgen und meldet sie per Telegram.

Blockzocker (blockzocker.com, "Krypto-Trading lernen mit Hermann dem Banker")
kommt vom selben Verlag wie Nacktes Geld — Paul Brandenburg LLC. Neue Folgen
erscheinen woechentlich dienstags.

WAS DIESES SKRIPT TUT — und was bewusst nicht:
  Es liest ausschliesslich die **oeffentlichen Trailer-Seiten**
  (/watch/<id>/trailer). Die tragen Folgennummer, Titel und Datum im
  Seitentitel und sind ohne Anmeldung erreichbar.

  Es holt KEINE Inhalte hinter der Bezahlschranke und meldet sich an keinem
  Konto an. Die eigentlichen Folgen brauchen ein Ticket; ein Transkript wie
  bei Nacktes Geld gibt es hier deshalb nicht — die Seite liefert im
  oeffentlichen Quelltext weder Untertitel noch Videoquelle.

  Nutzen ist damit begrenzt und ehrlich benannt: Man erfaehrt, DASS eine neue
  Folge da ist und wie sie heisst. Ob der Inhalt etwas taugt, entscheidet das
  Anhoeren — nicht dieses Skript.

Aufruf:
    python3 bz_watch.py           # nach neuen Folgen sehen und melden
    python3 bz_watch.py --init    # Bestand erfassen OHNE zu melden
    python3 bz_watch.py --dry     # pruefen, aber nichts senden
    python3 bz_watch.py --liste    # bekannten Bestand anzeigen
"""
import os
import re
import sys
import json
import time
import urllib.request

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
try:
    from config import config
except Exception:
    config = {}

SEITE = "https://blockzocker.com"
DIR = os.path.join(BASE, "bz")
STATE = os.path.join(DIR, "bz_state.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")

INIT = "--init" in sys.argv
DRY = "--dry" in sys.argv
LISTE = "--liste" in sys.argv

# Seitentitel sieht so aus:
#   "Trailer · S01E26 — Aggressiv ohne Daytrade (18.08.2026) — Blockzocker"
TITEL_RX = re.compile(
    r"<title>\s*(?:Trailer\s*·\s*)?(S\d{2}E\d{2})\s*[—–-]\s*(.+?)\s*"
    r"\((\d{2}\.\d{2}\.\d{2,4})\)", re.I | re.S)

# Wie weit ueber den bekannten Stand hinaus gesucht wird. Drei reicht: die
# Folgen erscheinen woechentlich, geprueft wird taeglich. Mehr Anfragen waeren
# nur unnoetige Last auf einer fremden Seite.
VORSCHAU = 3


def tg(text):
    tok = config.get("telegram_bot_token", "")
    chat = config.get("telegram_chat_id", "")
    if not (tok and chat) or DRY:
        return
    try:
        daten = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(
            "https://api.telegram.org/bot" + tok + "/sendMessage",
            data=daten, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        print("[TG] " + str(e))


def hole(pfad, versuche=2):
    """Oeffentliche Seite abrufen. None, wenn es sie (noch) nicht gibt."""
    for n in range(versuche):
        try:
            req = urllib.request.Request(SEITE + pfad, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                if r.status != 200:
                    return None
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code in (302, 404, 403):
                return None          # gibt es noch nicht / nicht oeffentlich
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return None


def folge_lesen(vid):
    """Nummer, Titel und Datum einer Folge aus den oeffentlichen Seiten.

    Zwei Wege, weil die Seite zwei Arten von Folgen kennt:
      kostenpflichtig -> /watch/<id>/trailer  (Trailer ist oeffentlich)
      kostenlos       -> /watch/<id>          (ganze Folge ist oeffentlich,
                                               es gibt gar keinen Trailer)
    Ohne den zweiten Weg fehlten beim Bestandsaufbau genau die neun freien
    Folgen S01E01–E09.
    """
    for pfad, frei in (("/watch/%d/trailer" % vid, False), ("/watch/%d" % vid, True)):
        html = hole(pfad)
        if not html:
            continue
        m = TITEL_RX.search(html)
        if not m:
            continue
        return {"id": vid, "folge": m.group(1).upper(),
                "titel": m.group(2).strip(), "datum": m.group(3),
                "frei": frei, "link": SEITE + pfad}
    return None


def state_laden():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {"hoechste_id": 0, "folgen": []}


def state_sichern(s):
    os.makedirs(DIR, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=1, ensure_ascii=False)
    os.replace(tmp, STATE)           # atomar — paralleler Leser sieht nie halb


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main():
    s = state_laden()
    bekannt = {f["id"] for f in s["folgen"]}

    if LISTE:
        print("Bekannte Folgen (%d):" % len(s["folgen"]))
        for f in s["folgen"][-15:]:
            print("  %-7s %s  (%s)" % (f["folge"], f["titel"], f["datum"]))
        return

    # Erstlauf: Bestand von unten aufrollen. Danach nur noch nach vorn schauen.
    start = 1 if (INIT and not s["folgen"]) else max(s["hoechste_id"], 0) + 1
    ende = (80 if INIT and not s["folgen"] else s["hoechste_id"] + VORSCHAU)

    neu = []
    luecken = 0
    for vid in range(start, ende + 1):
        if vid in bekannt:
            continue
        f = folge_lesen(vid)
        if f:
            neu.append(f)
            luecken = 0
        else:
            luecken += 1
            # Beim Bestandsaufbau nach fuenf leeren Nummern abbrechen —
            # danach kommt erfahrungsgemaess nichts mehr.
            if INIT and luecken >= 5 and neu:
                break
        time.sleep(0.4)              # freundlich zur fremden Seite

    if neu:
        s["folgen"] = sorted(s["folgen"] + neu, key=lambda f: f["id"])
        s["hoechste_id"] = max(f["id"] for f in s["folgen"])
    # Zeitstempel IMMER schreiben, auch ohne neue Folge. Sonst waere die
    # Zustandsdatei sechs Tage lang unveraendert und die taegliche
    # Funktionspruefung koennte einen stillen Ausfall nicht von "diese Woche
    # kam eben nichts" unterscheiden.
    s["letzter_lauf"] = time.strftime("%Y-%m-%d %H:%M")
    state_sichern(s)

    if not neu:
        print("Keine neue Folge. Stand: %s (%d bekannt)"
              % (s["folgen"][-1]["folge"] if s["folgen"] else "—", len(s["folgen"])))
        return

    print("%d neue Folge(n):" % len(neu))
    for f in neu:
        print("  %-7s %s  (%s)" % (f["folge"], f["titel"], f["datum"]))

    if INIT:
        print("(--init: nichts gemeldet, nur erfasst)")
        return

    for f in neu:
        tg("🎬 <b>Blockzocker · " + esc(f["folge"]) + "</b>"
           "\n\n" + esc(f["titel"]) +
           "\nVeröffentlicht: " + esc(f["datum"]) +
           "\n\n" + f["link"] +
           "\n\n<i>Nur die Ankündigung — der Inhalt liegt hinter dem Ticket "
           "und wird nicht ausgewertet.</i>")


if __name__ == "__main__":
    main()
