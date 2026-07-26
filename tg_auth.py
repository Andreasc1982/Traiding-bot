#!/usr/bin/env python3
"""Telegram-Login in zwei nicht-interaktiven Schritten (Ersatz fuer tg_login.py,
wenn kein Terminal-Prompt moeglich ist).

    python3 tg_auth.py code   +4915112345678      # Schritt 1: Code anfordern
    python3 tg_auth.py signin 12345 [2FA-PW]      # Schritt 2: einloggen
    python3 tg_auth.py list                       # Kanaele/Gruppen auflisten

Der Code kommt in die Telegram-App. WICHTIG: den Code NICHT in einen Telegram-Chat
schreiben — Telegram entwertet Codes, die in Chats auftauchen.
"""
import os, sys, json, asyncio

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
try:
    from config import config
except Exception:
    config = {}

from telethon import TelegramClient
from telethon.errors import (SessionPasswordNeededError, PhoneCodeInvalidError,
                             PhoneCodeExpiredError)

TG_DIR = os.path.join(BASE, "tg")
os.makedirs(TG_DIR, exist_ok=True)
SESSION = os.path.join(TG_DIR, "user_session")
PENDING = os.path.join(TG_DIR, "login_pending.json")

API_ID = config.get("telegram_api_id")
API_HASH = config.get("telegram_api_hash")


async def cmd_code(phone):
    client = TelegramClient(SESSION, int(API_ID), API_HASH)
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print("Bereits eingeloggt als:", me.username or me.first_name)
        await client.disconnect()
        return
    sent = await client.send_code_request(phone)
    with open(PENDING, "w") as f:
        json.dump({"phone": phone, "hash": sent.phone_code_hash}, f)
    print("Code angefordert fuer %s (Typ: %s)." % (phone, type(sent.type).__name__))
    print("Schau in die Telegram-App. Dann: python3 tg_auth.py signin <CODE>")
    await client.disconnect()


async def cmd_signin(code, password=None):
    if not os.path.exists(PENDING):
        print("FEHLER: kein laufender Login. Erst 'tg_auth.py code <nummer>'.")
        raise SystemExit(1)
    p = json.load(open(PENDING))
    client = TelegramClient(SESSION, int(API_ID), API_HASH)
    await client.connect()
    try:
        await client.sign_in(p["phone"], code, phone_code_hash=p["hash"])
    except SessionPasswordNeededError:
        if not password:
            print("2FA aktiv — Passwort noetig: python3 tg_auth.py signin %s <PASSWORT>" % code)
            await client.disconnect()
            raise SystemExit(2)
        await client.sign_in(password=password)
    except PhoneCodeInvalidError:
        print("FEHLER: Code falsch. Nochmal pruefen (oder neu anfordern).")
        await client.disconnect()
        raise SystemExit(1)
    except PhoneCodeExpiredError:
        print("FEHLER: Code abgelaufen. Neu anfordern mit 'tg_auth.py code <nummer>'.")
        await client.disconnect()
        raise SystemExit(1)
    me = await client.get_me()
    print("OK — eingeloggt als:", me.username or me.first_name, "| Session gespeichert.")
    os.remove(PENDING)
    await _list(client)
    await client.disconnect()


async def cmd_list():
    client = TelegramClient(SESSION, int(API_ID), API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("Nicht autorisiert — erst einloggen.")
        await client.disconnect()
        raise SystemExit(1)
    await _list(client)
    await client.disconnect()


async def _list(client):
    print("\n=== Kanaele/Gruppen (ID | Name) ===")
    n = 0
    async for d in client.iter_dialogs():
        if d.is_channel or d.is_group:
            print("  %-16s | %s" % (d.id, d.name))
            n += 1
    print("\n%d Kanaele/Gruppen." % n)


if __name__ == "__main__":
    if not API_ID or not API_HASH:
        print("FEHLER: telegram_api_id / telegram_api_hash fehlen in config.py.")
        raise SystemExit(1)
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    if args[0] == "code" and len(args) == 2:
        asyncio.run(cmd_code(args[1]))
    elif args[0] == "signin" and len(args) in (2, 3):
        asyncio.run(cmd_signin(args[1], args[2] if len(args) == 3 else None))
    elif args[0] == "list":
        asyncio.run(cmd_list())
    else:
        print(__doc__)
        raise SystemExit(1)
