#!/usr/bin/env python3
"""Struktur eines Chats: Forum-Themen (Unterkanaele), verknuepfter Kanal,
angeheftete Nachrichten, Einladungslinks in den Nachrichten.

    python3 tg_struct.py -1002479283228
"""
import os, sys, asyncio, re

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
from config import config
from telethon import TelegramClient, functions

SESSION = os.path.join(BASE, "tg", "user_session")
LINK = re.compile(r"(?:t\.me/|telegram\.me/)(\+?[A-Za-z0-9_/]+)")


async def main(chat_id):
    client = TelegramClient(SESSION, int(config["telegram_api_id"]),
                            config["telegram_api_hash"])
    await client.connect()
    ent = await client.get_entity(chat_id)
    print("Chat:", getattr(ent, "title", "?"))
    print("  forum (Themen aktiv):", getattr(ent, "forum", False))
    print("  megagroup:", getattr(ent, "megagroup", False),
          "| broadcast:", getattr(ent, "broadcast", False))

    full = await client(functions.channels.GetFullChannelRequest(ent))
    fc = full.full_chat
    print("  Mitglieder:", getattr(fc, "participants_count", "?"))
    linked = getattr(fc, "linked_chat_id", None)
    print("  verknuepfter Chat-ID:", linked)
    if linked:
        for c in full.chats:
            if c.id == linked:
                print("    ->", c.title, "@%s" % (getattr(c, "username", None) or "-"))

    if getattr(ent, "forum", False):
        print("\n=== Themen (Unterkanaele) ===")
        t = await client(functions.messages.GetForumTopicsRequest(
            peer=ent, offset_date=None, offset_id=0, offset_topic=0, limit=100))
        for top in t.topics:
            print("  %-10s %s" % (getattr(top, "id", "?"), getattr(top, "title", "?")))

    print("\n=== Angeheftete Nachricht ===")
    async for m in client.iter_messages(ent, limit=1, filter=None, reverse=False):
        pass
    pinned = getattr(fc, "pinned_msg_id", None)
    if pinned:
        pm = await client.get_messages(ent, ids=pinned)
        if pm:
            print(" ", (pm.raw_text or "")[:400].replace("\n", " | "))
    else:
        print("  (keine)")

    print("\n=== t.me-Links in den letzten 500 Nachrichten ===")
    seen = {}
    async for m in client.iter_messages(ent, limit=500):
        for lk in LINK.findall(m.raw_text or ""):
            seen.setdefault(lk, m.date.strftime("%Y-%m-%d"))
        for e in (m.entities or []):
            u = getattr(e, "url", None)
            if u:
                for lk in LINK.findall(u):
                    seen.setdefault(lk, m.date.strftime("%Y-%m-%d"))
    for lk, d in sorted(seen.items()):
        print("  t.me/%-34s (zuletzt %s)" % (lk, d))
    if not seen:
        print("  (keine)")
    await client.disconnect()


asyncio.run(main(int(sys.argv[1])))
