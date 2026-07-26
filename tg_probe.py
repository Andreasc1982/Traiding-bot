#!/usr/bin/env python3
"""Test: Verlauf oeffentlicher Kanaele lesen OHNE beizutreten.

    python3 tg_probe.py @kanal1 @kanal2 ...
"""
import os, sys, asyncio

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
from config import config
from telethon import TelegramClient

SESSION = os.path.join(BASE, "tg", "user_session")


async def main(names):
    client = TelegramClient(SESSION, int(config["telegram_api_id"]),
                            config["telegram_api_hash"])
    await client.connect()
    for name in names:
        try:
            ent = await client.get_entity(name)
            msgs = []
            async for m in client.iter_messages(ent, limit=200):
                msgs.append(m)
            if not msgs:
                print("%-26s LEER" % name)
                continue
            oldest, newest = msgs[-1], msgs[0]
            span_d = (newest.date - oldest.date).days or 1
            print("%-26s %d Msgs | %s .. %s (%dd, %.1f/Tag)" % (
                name, len(msgs), oldest.date.strftime("%Y-%m-%d"),
                newest.date.strftime("%Y-%m-%d"), span_d, len(msgs) / span_d))
            for m in msgs[:2]:
                print("      %s | %s" % (m.date.strftime("%m-%d %H:%M"),
                                         (m.raw_text or "")[:90].replace("\n", " ")))
        except Exception as e:
            print("%-26s FEHLER: %s" % (name, str(e)[:70]))
        await asyncio.sleep(1.5)
    await client.disconnect()


asyncio.run(main(sys.argv[1:]))
