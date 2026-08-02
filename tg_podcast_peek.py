#!/usr/bin/env python3
"""Zeigt die neuesten Podcast-Folgen mit Groesse und Laufzeit — laedt nichts."""
import os, sys, asyncio

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
from config import config
from telethon import TelegramClient

KANAL = sys.argv[1] if len(sys.argv) > 1 else "Nacktes Niveau"


async def main():
    c = TelegramClient(os.path.join(BASE, "tg", "user_session"),
                       int(config["telegram_api_id"]),
                       config["telegram_api_hash"])
    await c.connect()
    async for d in c.iter_dialogs():
        if KANAL.lower() not in (d.name or "").lower():
            continue
        print("Kanal: %s" % d.name)
        mb_summe = min_summe = 0.0
        n = 0
        async for m in c.iter_messages(d.entity, limit=400):
            if not m.audio:
                continue
            n += 1
            mb = (m.file.size or 0) / 1e6
            mi = (m.file.duration or 0) / 60.0
            mb_summe += mb
            min_summe += mi
            if n <= 8:
                titel = (m.raw_text or "").replace("\n", " ").strip()[:68] \
                    or (m.file.name or "")
                print("  %s | %6.1f MB | %5.1f Min | %s"
                      % (m.date.strftime("%Y-%m-%d"), mb, mi, titel))
        print("\n  %d Folgen in der Stichprobe: %.1f GB, %.0f Stunden"
              % (n, mb_summe / 1000.0, min_summe / 60.0))
        break
    await c.disconnect()


asyncio.run(main())
