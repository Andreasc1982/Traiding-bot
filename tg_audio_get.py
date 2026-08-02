#!/usr/bin/env python3
"""Laedt eine Audiodatei aus einem Kanal — fuer den Transkriptions-Test.

    python3 tg_audio_get.py "NAKMAK"           # listet nur
    python3 tg_audio_get.py "NAKMAK" --kuerzeste   # laedt die kuerzeste
"""
import os, sys, asyncio

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
from config import config
from telethon import TelegramClient

ZIEL = os.path.join(BASE, "tg", "audio")
KANAL = sys.argv[1] if len(sys.argv) > 1 else "NAKMAK"
LADEN = "--kuerzeste" in sys.argv


async def main():
    os.makedirs(ZIEL, exist_ok=True)
    c = TelegramClient(os.path.join(BASE, "tg", "user_session"),
                       int(config["telegram_api_id"]),
                       config["telegram_api_hash"])
    await c.connect()
    async for d in c.iter_dialogs():
        if KANAL.lower() not in (d.name or "").lower():
            continue
        print("Kanal: %s" % d.name)
        treffer = []
        async for m in c.iter_messages(d.entity, limit=400):
            if not (m.audio or m.voice):
                continue
            treffer.append((m.file.duration or 0, m))
        treffer.sort()
        for dur, m in treffer:
            print("  %s | %5.1f Min | %6.1f MB | %s"
                  % (m.date.strftime("%Y-%m-%d"), dur / 60.0,
                     (m.file.size or 0) / 1e6,
                     (m.file.name or (m.raw_text or "")[:50] or "Sprachnachricht")))
        if LADEN and treffer:
            dur, m = treffer[0]
            print("\nLade kuerzeste (%.1f Min) ..." % (dur / 60.0), flush=True)
            p = await c.download_media(m, ZIEL + "/")
            print("-> %s (%.1f MB)" % (p, os.path.getsize(p) / 1e6))
        break
    await c.disconnect()


asyncio.run(main())
