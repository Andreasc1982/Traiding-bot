#!/usr/bin/env python3
"""Findet ALLE "Nacktes Geld"-Folgen im NAKMAK-Chat (voller Verlauf).

Die Folgen liegen als MP3 im Community-Chat, nicht in einem eigenen Kanal.
Ohne Limit durchsuchen, weil die Nummerierung bis #89 laeuft — die aelteren
Folgen liegen entsprechend weit zurueck.

    python3 tg_nacktesgeld.py            # nur auflisten
    python3 tg_nacktesgeld.py --laden    # fehlende herunterladen
"""
import os, sys, re, asyncio

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
from config import config
from telethon import TelegramClient

ZIEL = os.path.join(BASE, "tg", "audio", "nacktes_geld")
LADEN = "--laden" in sys.argv
NUMMER = re.compile(r"#\s?(\d{1,3})")


async def main():
    os.makedirs(ZIEL, exist_ok=True)
    c = TelegramClient(os.path.join(BASE, "tg", "user_session"),
                       int(config["telegram_api_id"]),
                       config["telegram_api_hash"])
    await c.connect()
    async for d in c.iter_dialogs():
        if "NAKMAK" not in (d.name or ""):
            continue
        print("Kanal: %s" % d.name, flush=True)
        folgen = []
        n_ges = 0
        async for m in c.iter_messages(d.entity):     # kein Limit
            n_ges += 1
            if not m.audio:
                continue
            name = m.file.name or (m.raw_text or "")
            if "nacktes geld" not in name.lower():
                continue
            mm = NUMMER.search(name)
            folgen.append((int(mm.group(1)) if mm else 0, m, name))
        folgen.sort()
        print("  %d Nachrichten durchsucht, %d 'Nacktes Geld'-Folgen gefunden"
              % (n_ges, len(folgen)), flush=True)
        mb = sum((m.file.size or 0) for _, m, _ in folgen) / 1e6
        mi = sum((m.file.duration or 0) for _, m, _ in folgen) / 60.0
        if folgen:
            print("  Folgen #%d bis #%d | %.1f GB | %.1f Stunden"
                  % (folgen[0][0], folgen[-1][0], mb / 1000.0, mi / 60.0))
            lueck = set(range(folgen[0][0], folgen[-1][0] + 1)) - \
                set(n for n, _, _ in folgen)
            if lueck:
                print("  fehlende Nummern: %s"
                      % " ".join("#%d" % x for x in sorted(lueck)))
        for n, m, name in folgen:
            print("    #%-3d %s | %5.1f Min | %s"
                  % (n, m.date.strftime("%Y-%m-%d"),
                     (m.file.duration or 0) / 60.0, name[:60]))
        if LADEN:
            for n, m, name in folgen:
                p = os.path.join(ZIEL, "%03d.mp3" % n)
                if os.path.exists(p):
                    continue
                print("  lade #%d ..." % n, flush=True)
                await c.download_media(m, p)
            print("  fertig: %d Dateien in %s" % (len(os.listdir(ZIEL)), ZIEL))
        break
    await c.disconnect()


asyncio.run(main())
