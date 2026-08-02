#!/usr/bin/env python3
"""Bestandsaufnahme: wieviel Audio liegt in den abonnierten Kanaelen?

Zaehlt nur — laedt nichts herunter. Grundlage fuer die Frage, ob sich eine
Transkriptions-Pipeline lohnt oder ob die Kanaele ohnehin textlastig sind.

    python3 tg_audio_scan.py [anzahl_nachrichten_je_kanal]
"""
import os, sys, asyncio, collections

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
try:
    from config import config
except Exception:
    config = {}

from telethon import TelegramClient

SESSION = os.path.join(BASE, "tg", "user_session")
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 400


async def main():
    client = TelegramClient(SESSION, int(config["telegram_api_id"]),
                            config["telegram_api_hash"])
    await client.connect()
    if not await client.is_user_authorized():
        print("Nicht autorisiert.")
        return

    zeilen = []
    gesamt = collections.Counter()
    sek_gesamt = 0.0

    async for d in client.iter_dialogs():
        if not (d.is_channel or d.is_group):
            continue
        z = collections.Counter()
        sek = 0.0
        n = 0
        async for m in client.iter_messages(d.entity, limit=LIMIT):
            n += 1
            if m.voice:
                art = "sprachnachricht"
            elif m.video_note:
                art = "videonachricht"
            elif m.audio:
                art = "audiodatei"
            elif getattr(m, "video", None):
                art = "video"
            else:
                continue
            z[art] += 1
            gesamt[art] += 1
            try:
                sek += m.file.duration or 0
            except Exception:
                pass
        if z:
            sek_gesamt += sek
            zeilen.append((sum(z.values()), d.name or str(d.id), n, z, sek))

    zeilen.sort(reverse=True)
    print("Kanaele mit Audio/Video (Stichprobe: je %d neueste Nachrichten)\n"
          % LIMIT)
    if not zeilen:
        print("  keine gefunden.")
    for anz, name, n, z, sek in zeilen:
        arten = ", ".join("%d %s" % (v, k) for k, v in z.most_common())
        print("  %-42s %4d von %4d Nachrichten | %s | %.0f Min"
              % (name[:42], anz, n, arten, sek / 60.0))

    print("\nSumme: %s | Spieldauer %.1f Stunden"
          % (", ".join("%d %s" % (v, k) for k, v in gesamt.most_common()),
             sek_gesamt / 3600.0))
    await client.disconnect()


asyncio.run(main())
