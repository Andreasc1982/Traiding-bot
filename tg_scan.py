#!/usr/bin/env python3
"""Vollstaendiger Dump aller Kanaele/Gruppen der User-Session nach CSV.

    python3 tg_scan.py            # alles
    python3 tg_scan.py <chat_id>  # nur ein Chat

Ausgabe: tg/scan_all.csv  (eine Zeile je Nachricht, inkl. Forum-Thema)
"""
import os, sys, csv, asyncio
from datetime import datetime

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
from config import config
from telethon import TelegramClient, functions

SESSION = os.path.join(BASE, "tg", "user_session")
OUT = os.path.join(BASE, "tg", "scan_all.csv")

COLS = ["date", "chat", "chat_id", "topic_id", "topic", "msg_id", "sender_id",
        "sender", "fwd_from", "views", "file_name", "text"]


async def topic_names(client, ent):
    try:
        t = await client(functions.messages.GetForumTopicsRequest(
            peer=ent, offset_date=None, offset_id=0, offset_topic=0, limit=100))
        return {top.id: top.title for top in t.topics}
    except Exception:
        return {}


async def main(only=None):
    client = TelegramClient(SESSION, int(config["telegram_api_id"]),
                            config["telegram_api_hash"])
    await client.connect()
    f = open(OUT, "w", newline="", encoding="utf-8")
    w = csv.writer(f)
    w.writerow(COLS)
    names = {}
    total = 0

    async for d in client.iter_dialogs():
        if not (d.is_channel or d.is_group):
            continue
        if only and d.id != only:
            continue
        ent = d.entity
        topics = await topic_names(client, ent) if getattr(ent, "forum", False) else {}
        n = 0
        async for m in client.iter_messages(ent, limit=None):
            tid = ""
            rt = getattr(m, "reply_to", None)
            if rt is not None:
                tid = getattr(rt, "reply_to_top_id", None) or getattr(rt, "reply_to_msg_id", "") or ""
                if not getattr(rt, "forum_topic", False):
                    tid = tid if topics else ""
            sid = m.sender_id
            if sid and sid not in names:
                try:
                    s = await m.get_sender()
                    names[sid] = (getattr(s, "first_name", None)
                                  or getattr(s, "title", None) or str(sid))
                except Exception:
                    names[sid] = str(sid)
            fwd = ""
            if m.forward:
                fc = getattr(m.forward, "chat", None)
                fwd = (getattr(fc, "title", None)
                       or getattr(m.forward, "from_name", None) or "?")
            w.writerow([m.date.isoformat(), d.name, d.id, tid,
                        topics.get(tid, ""), m.id, sid or "", names.get(sid, ""),
                        fwd, getattr(m, "views", "") or "",
                        (m.file.name if (m.file and m.file.name) else ""),
                        (m.raw_text or "").replace("\n", " ").replace("\r", " ")])
            n += 1
            total += 1
            if n % 500 == 0:
                f.flush()
                print("  %s: %d" % (d.name[:35], n), flush=True)
        print("FERTIG %-40s %d Nachrichten" % (d.name[:40], n), flush=True)
    f.close()
    print("GESAMT %d Nachrichten -> %s" % (total, OUT), flush=True)
    await client.disconnect()


asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else None))
