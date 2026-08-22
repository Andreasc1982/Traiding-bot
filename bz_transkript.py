#!/usr/bin/env python3
"""Holt die KOSTENLOSEN Blockzocker-Folgen als Text (Ton -> Spracherkennung).

Blockzocker markiert neun Folgen ausdruecklich als "kostenlos, ohne Anmeldung
und ohne Kosten verfuegbar" (S01E01–E09). Deren Seite legt die Stream-Adresse
offen in den Quelltext — genau das, was ein Besucher im Browser auch bekommt.
Nur diese Folgen werden angefasst.

WAS DIESES SKRIPT NICHT TUT: Es meldet sich an keinem Konto an, umgeht keine
Bezahlschranke und ruft keine kostenpflichtige Folge ab. Die Sperre dafuer ist
hart verdrahtet (FREIE_IDS) und nicht per Schalter aufhebbar.

Laeuft auf dem Mac, weil die Spracherkennung dort ueber MLX rund 40x Echtzeit
schafft — auf dem Pi waere es ein Vielfaches langsamer.

    python3 bz_transkript.py            # alle freien Folgen, die noch fehlen
    python3 bz_transkript.py 28         # nur diese eine (zum Pruefen)
"""
import os
import re
import sys
import json
import time
import subprocess
import urllib.request

MAC_BASIS = os.path.expanduser("~/trading_bot")
ZIEL = os.path.join(MAC_BASIS, "bz", "texte")
TON = os.path.join(MAC_BASIS, "bz", "ton")
WHISPER = os.path.expanduser("~/whisper_env/bin/mlx_whisper")
MODELL = "mlx-community/whisper-large-v3-turbo-q4"
SEITE = "https://blockzocker.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")

# Hart begrenzt auf die neun als kostenlos ausgewiesenen Folgen.
FREIE_IDS = list(range(28, 37))          # /watch/28 .. /watch/36 = S01E01..E09

HLS_RX = re.compile(r"hlsUrl\s*=\s*'([^']+)'")
TITEL_RX = re.compile(r"<title>\s*(S\d{2}E\d{2})\s*[—–-]\s*(.+?)\s*\(", re.I)


def hole(pfad):
    req = urllib.request.Request(SEITE + pfad, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def folge_holen(vid):
    """(folge, titel, hls) der frei zugaenglichen Folge — oder None."""
    if vid not in FREIE_IDS:
        raise SystemExit("Folge %s ist nicht als kostenlos ausgewiesen — Abbruch." % vid)
    html = hole("/watch/%d" % vid)
    m_h = HLS_RX.search(html)
    m_t = TITEL_RX.search(html)
    if not m_h:
        print("  keine öffentliche Stream-Adresse in der Seite — übersprungen")
        return None
    folge = m_t.group(1) if m_t else "S01E??"
    titel = m_t.group(2).strip() if m_t else ""
    return folge, titel, m_h.group(1)


def ton_holen(hls, ziel):
    """Nur die Tonspur, 16 kHz Mono — mehr braucht die Spracherkennung nicht."""
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-headers",
         "Referer: https://blockzocker.com\r\n", "-i", hls,
         "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", ziel],
        capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        print("  ffmpeg: " + (r.stderr or "")[:200])
        return False
    return os.path.exists(ziel) and os.path.getsize(ziel) > 100000


def erkennen(wav, ziel_txt):
    r = subprocess.run(
        [WHISPER, wav, "--model", MODELL, "--language", "de",
         "--output-dir", os.path.dirname(ziel_txt), "--output-format", "txt"],
        capture_output=True, text=True, timeout=5400)
    erzeugt = os.path.join(os.path.dirname(ziel_txt),
                           os.path.basename(wav).rsplit(".", 1)[0] + ".txt")
    if os.path.exists(erzeugt):
        if erzeugt != ziel_txt:
            os.replace(erzeugt, ziel_txt)
        return True
    print("  Spracherkennung: " + (r.stderr or r.stdout or "")[-250:])
    return False


def main():
    os.makedirs(ZIEL, exist_ok=True)
    os.makedirs(TON, exist_ok=True)
    nur = [int(a) for a in sys.argv[1:] if a.isdigit()]
    ids = nur or FREIE_IDS

    for vid in ids:
        txt = os.path.join(ZIEL, "%d.txt" % vid)
        if os.path.exists(txt) and os.path.getsize(txt) > 2000:
            print("Folge %d: liegt schon vor (%d Zeichen)" % (vid, os.path.getsize(txt)))
            continue
        print("Folge %d …" % vid, flush=True)
        t0 = time.time()
        d = folge_holen(vid)
        if not d:
            continue
        folge, titel, hls = d
        print("  %s — %s" % (folge, titel), flush=True)
        wav = os.path.join(TON, "%d.wav" % vid)
        # Immer frisch holen. Eine liegengebliebene Datei kann von einem
        # abgebrochenen Lauf stammen und nur den Anfang enthalten — Folge 29
        # ergab so 1.197 Woerter fuer 46 Minuten Sendung.
        if os.path.exists(wav):
            os.remove(wav)
        if not ton_holen(hls, wav):
            print("  Ton nicht holbar — übersprungen")
            continue
        dauer = os.path.getsize(wav) / 32000.0
        if dauer < 300:
            print("  Ton nur %.0f s lang — unvollständig, übersprungen" % dauer)
            os.remove(wav)
            continue
        print("  Ton: %.0f min, erkenne …" % (dauer / 60), flush=True)
        if erkennen(wav, txt):
            zeichen = os.path.getsize(txt)
            print("  fertig: %d Zeichen in %.0f s (%.0fx Echtzeit)"
                  % (zeichen, time.time() - t0, dauer / max(time.time() - t0, 1)), flush=True)
            if os.path.exists(wav):
                os.remove(wav)                 # Ton wird nicht aufbewahrt
            meta = os.path.join(ZIEL, "%d.json" % vid)
            json.dump({"id": vid, "folge": folge, "titel": titel,
                       "zeichen": zeichen}, open(meta, "w"), ensure_ascii=False)


if __name__ == "__main__":
    main()
