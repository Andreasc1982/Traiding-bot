#!/usr/bin/env python3
"""Einmalige Sondierung: (1) kann die Session Verlaufs-Nachrichten lesen (Backfill),
(2) welche oeffentlichen Signal-Kanaele findet die Telegram-Suche?

    python3 tg_explore.py
"""
import os, sys, asyncio

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
try:
    from config import config
except Exception:
    config = {}

from telethon import TelegramClient, functions

SESSION = os.path.join(BASE, "tg", "user_session")
API_ID = int(config["telegram_api_id"])
API_HASH = config["telegram_api_hash"]

QUERIES = ["crypto signals", "trading signals", "krypto signale",
           "aktien trading", "solana calls"]


async def main():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("Nicht autorisiert.")
        return

    print("=== 1) Verlaufs-Test (Backfill-Faehigkeit) ===")
    async for d in client.iter_dialogs():
        if not (d.is_channel or d.is_group):
            continue
        n = 0
        try:
            async for m in client.iter_messages(d.entity, limit=3):
                txt = (m.raw_text or "").replace("\n", " ")[:70]
                print("  %-28s %s | %s" % (d.name[:28], m.date.strftime("%Y-%m-%d"), txt))
                n += 1
        except Exception as e:
            print("  %-28s FEHLER: %s" % (d.name[:28], str(e)[:60]))
        if n == 0:
            print("  %-28s (keine Nachrichten lesbar)" % d.name[:28])

    print("\n=== 2) Oeffentliche Kanal-Suche (nur lesen, kein Beitritt) ===")
    seen = set()
    for q in QUERIES:
        try:
            res = await client(functions.contacts.SearchRequest(q=q, limit=15))
        except Exception as e:
            print("  Suche '%s' fehlgeschlagen: %s" % (q, str(e)[:60]))
            await asyncio.sleep(2)
            continue
        print("\n  [%s]" % q)
        for ch in res.chats:
            uname = getattr(ch, "username", None)
            if not uname or uname in seen:
                continue
            seen.add(uname)
            broadcast = getattr(ch, "broadcast", False)
            print("    @%-24s %-40s %s" % (uname, (ch.title or "")[:40],
                                           "Kanal" if broadcast else "Gruppe"))
        await asyncio.sleep(2)

    print("\n%d eindeutige oeffentliche Kanaele gefunden." % len(seen))
    await client.disconnect()


asyncio.run(main())
