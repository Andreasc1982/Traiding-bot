#!/usr/bin/env python3
"""Details zu Telegram-Usern (Bio, Verifizierung, gemeinsame Chats) — hilft
echte Accounts von Nachahmern zu unterscheiden.

    python3 tg_user.py @name1 @name2 ...
"""
import os, sys, asyncio

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
from config import config
from telethon import TelegramClient, functions

SESSION = os.path.join(BASE, "tg", "user_session")


async def main(names):
    client = TelegramClient(SESSION, int(config["telegram_api_id"]),
                            config["telegram_api_hash"])
    await client.connect()
    for n in names:
        try:
            u = await client.get_entity(n)
            full = await client(functions.users.GetFullUserRequest(u))
            f = full.full_user
            print("@%s" % (u.username or "-"))
            print("   Name      : %s %s" % (getattr(u, "first_name", "") or "",
                                            getattr(u, "last_name", "") or ""))
            print("   ID        : %s" % u.id)
            print("   verifiziert: %s | premium: %s | scam: %s | fake: %s | bot: %s" % (
                getattr(u, "verified", None), getattr(u, "premium", None),
                getattr(u, "scam", None), getattr(u, "fake", None),
                getattr(u, "bot", None)))
            print("   Foto      : %s" % ("ja" if getattr(u, "photo", None) else "nein"))
            print("   gem. Chats: %s" % getattr(f, "common_chats_count", "?"))
            bio = (getattr(f, "about", None) or "").replace("\n", " | ")
            print("   Bio       : %s" % (bio[:180] if bio else "(leer)"))
        except Exception as e:
            print("@%s  FEHLER: %s" % (n, str(e)[:70]))
        print()
        await asyncio.sleep(1.5)
    await client.disconnect()


asyncio.run(main([x.lstrip("@") for x in sys.argv[1:]]))
