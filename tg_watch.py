#!/usr/bin/env python3
"""Regelmaessiges Screening der Telegram-Kanaele — inkrementell + Telegram-Digest.

Holt nur NEUE Nachrichten seit dem letzten Lauf (msg_id je Chat gemerkt), sucht
nach dem, was der Vollscan als einzig Brauchbares uebrig liess:
  - neue Contract-Adressen (Solana/EVM)  -> potenziell messbare Token
  - neue nummerierte Wiki-/FAQ-Eintraege (#NN) -> Know-how
  - Nachrichten mit hoher Fachbegriffs-Dichte  -> Werkzeuge/Verfahren
Alles andere (Community-Geplauder) wird bewusst ignoriert.

    python3 tg_watch.py            # normaler Lauf (Cron)
    python3 tg_watch.py --dry      # ohne Telegram-Versand
    python3 tg_watch.py --init     # nur Stand merken, nichts melden
"""
import os, sys, csv, re, json, asyncio, urllib.parse, urllib.request
from datetime import datetime

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
try:
    from config import config
except Exception:
    config = {}

from telethon import TelegramClient

TG_DIR = os.path.join(BASE, "tg")
SESSION = os.path.join(TG_DIR, "user_session")
STATE = os.path.join(TG_DIR, "watch_state.json")
LOG = os.path.join(TG_DIR, "watch_log.csv")

DRY = "--dry" in sys.argv
INIT = "--init" in sys.argv

SOL = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
EVM = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
NUMBERED = re.compile(r"#\s?(\d{1,3})\b")
CASHTAG = re.compile(r"\$([A-Za-z]{2,10})\b")

KEYWORDS = ["jupiter", "raydium", "orca", "slippage", "limit order", "trigger",
            "mev", "jito", "sandwich", "validator", "rpc", "priority fee",
            "dydx", "orderbook", "perp", "funding rate", "xstock", "paxg",
            "solscan", "birdeye", "rugcheck", "dexscreener", "gmgn",
            "mint authority", "freeze authority", "honeypot", "bundler",
            "sniper", "wallet tracker", "api", "bot", "staking", "lending",
            "hodl hodl", "letsexchange", "monero", "atomic swap", "no-kyc"]
MIN_KEYWORDS = 3          # ab so vielen Fachbegriffen gilt eine Nachricht als Fund


def tg_send(text):
    tok, chat = config.get("telegram_bot_token"), config.get("telegram_chat_id")
    if not tok or not chat:
        print("[TG] kein Token/Chat konfiguriert — kein Versand.")
        return
    for i in range(0, len(text), 3800):
        data = urllib.parse.urlencode({
            "chat_id": chat, "text": text[i:i + 3800],
            "disable_web_page_preview": "true"}).encode()
        try:
            urllib.request.urlopen(
                "https://api.telegram.org/bot%s/sendMessage" % tok, data, timeout=15)
        except Exception as e:
            print("[TG] Sendefehler:", str(e)[:80])


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save_state(s):
    tmp = STATE + ".tmp"
    json.dump(s, open(tmp, "w"), indent=1)
    os.replace(tmp, STATE)


def known_addresses():
    """Adressen, die wir schon einmal gesehen haben (aus dem Vollscan + Log)."""
    seen = set()
    for path in (os.path.join(TG_DIR, "scan_all.csv"), LOG):
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    seen.update(SOL.findall(line))
                    seen.update(EVM.findall(line))
        except Exception:
            pass
    return seen


async def main():
    csv.field_size_limit(10_000_000)
    state = load_state()
    seen_addr = known_addresses()
    client = TelegramClient(SESSION, int(config["telegram_api_id"]),
                            config["telegram_api_hash"])
    await client.connect()
    if not await client.is_user_authorized():
        print("Nicht autorisiert.")
        return

    new_rows, finds = [], []
    async for d in client.iter_dialogs():
        if not (d.is_channel or d.is_group):
            continue
        key = str(d.id)
        last = state.get(key, 0)
        newest = last
        count = 0
        async for m in client.iter_messages(d.entity, min_id=last, limit=500):
            newest = max(newest, m.id)
            count += 1
            text = (m.raw_text or "").replace("\n", " ").strip()
            if not text:
                continue
            tl = text.lower()
            addrs = [a for a in (SOL.findall(text) + EVM.findall(text))
                     if a not in seen_addr]
            kw = [w for w in KEYWORDS if w in tl]
            nums = NUMBERED.findall(text) if len(text) > 200 else []
            tags = CASHTAG.findall(text)
            if not (addrs or len(kw) >= MIN_KEYWORDS or nums):
                continue
            new_rows.append([m.date.isoformat(), d.name, m.id,
                             "|".join(addrs), "|".join(kw), "|".join(tags),
                             text[:400]])
            if not INIT:
                finds.append({"chat": d.name, "date": m.date.strftime("%d.%m %H:%M"),
                              "addrs": addrs, "kw": kw, "nums": nums,
                              "text": text[:260]})
            seen_addr.update(addrs)
        state[key] = newest
        if count:
            print("%-42s %d neue Nachrichten" % (d.name[:42], count))
    await client.disconnect()

    if new_rows:
        exists = os.path.exists(LOG)
        with open(LOG, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(["date", "chat", "msg_id", "addresses",
                            "keywords", "cashtags", "text"])
            w.writerows(new_rows)
    save_state(state)

    if INIT:
        print("Stand gemerkt (%d Chats). Kuenftige Laeufe melden nur Neues." % len(state))
        return
    if not finds:
        print("Nichts Meldenswertes.")
        return

    lines = ["🔭 Telegram-Screening %s — %d Fund(e)"
             % (datetime.now().strftime("%d.%m %H:%M"), len(finds)), ""]
    for f in finds[:20]:
        head = "• %s | %s" % (f["chat"][:22], f["date"])
        if f["addrs"]:
            head += " | 🔗 NEUE ADRESSE: " + ", ".join(a[:12] + "…" for a in f["addrs"])
        if f["nums"]:
            head += " | 📘 Eintrag #" + ",#".join(f["nums"][:3])
        if f["kw"]:
            head += " | 🔧 " + ", ".join(f["kw"][:6])
        lines.append(head)
        lines.append("   " + f["text"][:200])
    if len(finds) > 20:
        lines.append("… und %d weitere (siehe tg/watch_log.csv)" % (len(finds) - 20))
    msg = "\n".join(lines)
    print(msg)
    if not DRY:
        tg_send(msg)


asyncio.run(main())
