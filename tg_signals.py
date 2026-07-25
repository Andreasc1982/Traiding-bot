#!/usr/bin/env python3
"""Telegram-Signal-Collector (Telethon, User-Session) — read-only, KEIN Handel.

Liest neue Nachrichten aus den konfigurierten Kanaelen/Gruppen des Users, extrahiert
best-effort Ticker/Richtung/Preise und loggt ALLES roh nach tg/signals_log.csv.
Sinn: die Signale sammeln, spaeter gegen echte Kursdaten joinen und pro Kanal
messen "haette das Geld gemacht?". Verfeinertes Parsen passiert bei der Auswertung.

Waterproof: Singleton-Lock, atomare Writes, Auto-Reconnect, ueberlebt Neustart.
Login VORHER einmalig via tg_login.py (erzeugt die Session-Datei).
"""
import os, sys, csv, re, json, time, asyncio
from datetime import datetime

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
try:
    from config import config
except Exception:
    config = {}

TG_DIR = os.path.join(BASE, "tg")
LOG_CSV = os.path.join(TG_DIR, "signals_log.csv")
HB = os.path.join(TG_DIR, "tg_signals_hb.json")
SESSION = os.path.join(TG_DIR, "user_session")          # -> user_session.session

API_ID = config.get("telegram_api_id")
API_HASH = config.get("telegram_api_hash")
WATCH = config.get("tg_watch_channels", [])             # Namen/IDs; leer = alle Kanaele/Gruppen

BUY = re.compile(r"\b(buy|long|kauf|kaufen|call|einstieg|entry|accumulate|bull|moon)\b", re.I)
SELL = re.compile(r"\b(sell|short|verkauf|verkaufen|put|exit|ausstieg|bear|dump|close)\b", re.I)
CASHTAG = re.compile(r"\$([A-Za-z]{1,6})")
UPPER = re.compile(r"\b([A-Z]{2,5})\b")
PRICE = re.compile(r"(?:entry|ziel|target|tp|sl|stop|kurs|@|einstieg)[^0-9]{0,8}([0-9]+(?:[.,][0-9]+)?)", re.I)
STOP = {"THE", "AND", "FOR", "USD", "EUR", "CEO", "CFO", "ETF", "IPO", "USA", "EU", "AI",
        "ATH", "SL", "TP", "NOW", "BUY", "ALL", "NEW", "PDF", "FYI", "DYOR", "NFA", "US"}


def _atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, path)


def extract(text):
    cash = [c.upper() for c in CASHTAG.findall(text)]
    upp = [u for u in UPPER.findall(text) if u not in STOP]
    tickers = list(dict.fromkeys(cash + upp))[:6]
    b, s = bool(BUY.search(text)), bool(SELL.search(text))
    direction = "BUY" if (b and not s) else "SELL" if (s and not b) else "MIXED" if (b and s) else ""
    prices = PRICE.findall(text)[:4]
    conf = "high" if cash else ("mid" if (upp and direction) else "low")
    return tickers, direction, prices, conf


async def main():
    from telethon import TelegramClient, events
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("[TG] Nicht autorisiert — erst 'python3 tg_login.py' ausfuehren.")
        await client.disconnect()
        raise SystemExit(1)
    me = await client.get_me()
    print("[TG] eingeloggt als", (me.username or me.first_name))

    watch = WATCH or None
    if watch:
        print("[TG] beobachte Kanaele:", watch)
    else:
        print("[TG] beobachte ALLE Kanaele/Gruppen (keine tg_watch_channels gesetzt)")

    if not os.path.exists(LOG_CSV):
        _atomic(LOG_CSV, "time,channel,channel_id,sender,msg_id,direction,tickers,prices,conf,text\n")

    cnt = {"n": 0}

    def beat():
        _atomic(HB, json.dumps({"time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "logged_session": cnt["n"], "watch": watch or "alle"}))

    @client.on(events.NewMessage(chats=watch) if watch else events.NewMessage())
    async def handler(event):
        try:
            if not watch and not (event.is_channel or event.is_group):
                return                                  # ohne Filter: private Chats ignorieren
            text = event.raw_text or ""
            if not text.strip():
                return
            tickers, direction, prices, conf = extract(text)
            if not tickers:
                return                                  # reine Chatter ohne Ticker ueberspringen
            try:
                chat = await event.get_chat()
                cname = getattr(chat, "title", None) or getattr(chat, "username", "") or str(event.chat_id)
            except Exception:
                cname = str(event.chat_id)
            row = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), cname, str(event.chat_id),
                   str(event.sender_id or ""), str(event.id), direction,
                   "|".join(tickers), "|".join(prices), conf,
                   text.replace("\n", " ").replace("\r", " ")[:400]]
            with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(row)
            cnt["n"] += 1
            beat()
            print("[SIG]", cname, "|", direction, tickers, conf)
        except Exception as e:
            print("[TG-ERR]", str(e)[:120])

    beat()
    print("[TG] lausche auf neue Nachrichten... (Strg+A D zum Loesen)")
    await client.run_until_disconnected()


if __name__ == "__main__":
    _lock = None
    try:
        import health
        _lock = health.acquire_singleton("tg_signals")
        if _lock is None:
            print("[SINGLETON] tg_signals laeuft bereits — diese Instanz beendet sich.")
            raise SystemExit(0)
        health.log("tg_signals", "START", "")
    except SystemExit:
        raise
    except Exception as _e:
        print("[SINGLETON] health nicht verfuegbar:", _e)

    os.makedirs(TG_DIR, exist_ok=True)
    if not API_ID or not API_HASH:
        print("[TG] telegram_api_id / telegram_api_hash fehlen in config.py — abbrechen.")
        raise SystemExit(1)
    while True:
        try:
            asyncio.run(main())
        except (KeyboardInterrupt, SystemExit):
            break
        except Exception as e:
            print("[TG] Verbindung verloren, Reconnect in 15s:", str(e)[:120])
            time.sleep(15)
