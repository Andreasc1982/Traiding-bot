#!/usr/bin/env python3
"""Einmaliger Telegram-Login — erzeugt die Session-Datei fuer tg_signals.py.

INTERAKTIV auf dem Pi ausfuehren (fragt Telefonnummer + den Code, den Telegram
dir in die App schickt; ggf. dein 2FA-Passwort). Danach nie wieder noetig.

    ssh trading
    cd /home/trading2025/trading_bot
    source /home/trading2025/trading_bot_env/bin/activate
    python3 tg_login.py

Am Ende listet es alle deine Kanaele/Gruppen mit ID + Name — daraus waehlst du,
welche der Collector beobachten soll (-> config['tg_watch_channels']).
"""
import os, sys

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
try:
    from config import config
except Exception:
    config = {}

from telethon import TelegramClient

TG_DIR = os.path.join(BASE, "tg")
os.makedirs(TG_DIR, exist_ok=True)
SESSION = os.path.join(TG_DIR, "user_session")
api_id = config.get("telegram_api_id")
api_hash = config.get("telegram_api_hash")

if not api_id or not api_hash:
    print("FEHLER: telegram_api_id / telegram_api_hash fehlen in config.py.")
    print("Hole sie auf https://my.telegram.org -> API development tools.")
    sys.exit(1)

with TelegramClient(SESSION, int(api_id), api_hash) as client:
    me = client.get_me()
    print("\nOK — eingeloggt als:", (me.username or me.first_name), "| Session gespeichert.\n")
    print("=== Deine Kanaele/Gruppen (ID | Name) — daraus die zu beobachtenden waehlen ===")
    n = 0
    for d in client.iter_dialogs():
        if d.is_channel or d.is_group:
            print("  %-16s | %s" % (d.id, d.name))
            n += 1
    print("\n%d Kanaele/Gruppen. Schick mir die IDs (oder @Namen) der gewuenschten." % n)
