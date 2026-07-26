#!/usr/bin/env python3
"""Person/Kanal suchen: oeffentliche Telegram-Suche + Nachrichten-Suche in den
eigenen Dialogen (inkl. Herkunft von Weiterleitungen).

    python3 tg_find.py "Hermann der Banker"
"""
import os, sys, asyncio

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
from config import config
from telethon import TelegramClient, functions

SESSION = os.path.join(BASE, "tg", "user_session")


async def main(query):
    client = TelegramClient(SESSION, int(config["telegram_api_id"]),
                            config["telegram_api_hash"])
    await client.connect()

    print("=== 1) Oeffentliche Suche: '%s' ===" % query)
    try:
        res = await client(functions.contacts.SearchRequest(q=query, limit=20))
        for ch in res.chats:
            print("  KANAL  @%-22s %s  (%s)" % (
                getattr(ch, "username", "-") or "-", (ch.title or "")[:45],
                "Kanal" if getattr(ch, "broadcast", False) else "Gruppe"))
        for u in res.users:
            nm = " ".join(x for x in [getattr(u, "first_name", ""),
                                      getattr(u, "last_name", "")] if x)
            print("  USER   @%-22s %s" % (getattr(u, "username", "-") or "-", nm[:45]))
        if not res.chats and not res.users:
            print("  (nichts gefunden)")
    except Exception as e:
        print("  FEHLER:", str(e)[:80])

    print("\n=== 2) Treffer in deinen Chats ===")
    async for d in client.iter_dialogs():
        if not (d.is_channel or d.is_group):
            continue
        hits = 0
        try:
            async for m in client.iter_messages(d.entity, search=query, limit=15):
                hits += 1
                src = ""
                if m.forward:
                    f = m.forward
                    fc = getattr(f, "chat", None)
                    src = " [FWD von: %s]" % (
                        getattr(fc, "title", None)
                        or getattr(f, "from_name", None)
                        or str(getattr(f, "from_id", "?")))
                sender = ""
                try:
                    s = await m.get_sender()
                    sender = getattr(s, "first_name", None) or getattr(s, "title", "") or ""
                except Exception:
                    pass
                print("  %-22s %s | %s%s" % (d.name[:22], m.date.strftime("%Y-%m-%d"),
                                             sender[:18], src))
                print("      %s" % (m.raw_text or "")[:150].replace("\n", " "))
        except Exception as e:
            print("  %-22s Suchfehler: %s" % (d.name[:22], str(e)[:50]))
        if hits:
            print("  --> %d Treffer in %s\n" % (hits, d.name))
    await client.disconnect()


asyncio.run(main(" ".join(sys.argv[1:])))
