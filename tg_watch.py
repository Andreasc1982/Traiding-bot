#!/usr/bin/env python3
"""Regelmaessiges Screening der Telegram-Kanaele — inkrementell + Telegram-Digest.

Holt nur NEUE Nachrichten seit dem letzten Lauf (msg_id je Chat gemerkt) und
meldet vier Dinge:
  - Nachrichten von Hermann dem Banker        -> selten, deshalb immer melden
  - neue Contract-Adressen (Solana/EVM)       -> potenziell messbare Token
  - neue nummerierte Wiki-Eintraege (#NN)     -> nur im NAKMAK-Chat, je Nummer einmal
  - Fachbegriffs-Dichte                       -> ein starker Begriff ODER drei schwache
Alles andere (Community-Geplauder, Moderation, Werbung) wird bewusst ignoriert.

    python3 tg_watch.py            # normaler Lauf (Cron)
    python3 tg_watch.py --dry      # ohne Telegram-Versand
    python3 tg_watch.py --init     # nur Stand merken, nichts melden
"""
import os, sys, csv, re, json, hashlib, asyncio, urllib.parse, urllib.request
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

# Kanaele, die ueberhaupt gescreent werden. Leer = alle Dialoge (alter Stand).
# Bewusst NUR die zwei, in denen Hermann/Mike/die Podcast-Ankuendigungen laufen —
# Eva Herman, MES & Co. lieferten in 325 Meldungen kein einziges Handelssignal.
DEFAULT_CHANNELS = [
    -1002479283228,   # NAKMAK - Community Chat der Nackten Mark
    -1001390897042,   # Paul Brandenburg (Ankuendigung "Nacktes Geld")
]

# Hermann postet ~7x pro 1200 Nachrichten — so selten, dass jede Meldung zaehlt.
HIGH_VALUE_SENDERS = {"banker_hermann"}

# Nachahmer-Accounts mit identischem Anzeigenamen. Taucht einer auf: Warnung.
IMPOSTORS = {"banker_hermannd", "hermann_banker", "banker_hermann11",
             "banker_hermann1", "bankerr_hermann"}

# Shop-/Zahlungs-Wallets aus den Werbeposts — keine Token-Calls, nie melden.
ADDR_BLACKLIST = {
    "5sVPPfcNUateDpkAzU7ng7mAeojBWXmBBQQyPDErj4T1",
    "5Y1RkyUZTnXKpfzeLZX9Ee2FjLFWt8QThfvnXqbV8ioQ",
    "BAp1em6KuUrb4B7MHFEayDLbB5YC8wfG4YySPRT4VfxD",
}

# Ein starker Begriff genuegt fuer eine Meldung — die sind eindeutig.
STRONG = ["jupiter", "raydium", "orca", "jito", "dydx", "birdeye", "rugcheck",
          "dexscreener", "gmgn", "solscan", "mint authority", "freeze authority",
          "honeypot", "bundler", "sniper", "wallet tracker", "xstock", "paxg",
          "monero", "letsexchange", "hodl hodl", "atomic swap", "no-kyc",
          "priority fee", "funding rate", "orderbook", "mev", "sandwich",
          "validator", "rpc", "limit order", "slippage", "perp"]
# Schwache Begriffe: allein nichtssagend, zaehlen nur zur Schwelle.
WEAK = ["api", "bot", "staking", "lending", "trigger"]
MIN_WEAK = 3

# Wortgrenzen statt Substring: sonst trifft "Mallorca"->orca, "Kapital"->api,
# "Botschaft"->bot, und ein beliebiger Politiksatz gilt als Fund.
def _rx(words):
    return re.compile(r"(?<!\w)(?:%s)(?!\w)"
                      % "|".join(re.escape(w) for w in words), re.I)

RX_STRONG, RX_WEAK = _rx(STRONG), _rx(WEAK)


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
    seen = set(ADDR_BLACKLIST)
    for path in (os.path.join(TG_DIR, "scan_all.csv"),
                 os.path.join(TG_DIR, "watch_log_v1.csv"), LOG):
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


def classify(text, sender):
    """Gibt (grund, addrs, kw, nums) zurueck — grund=None heisst: ignorieren."""
    addrs = SOL.findall(text) + EVM.findall(text)
    strong = sorted(set(m.group(0).lower() for m in RX_STRONG.finditer(text)))
    weak = sorted(set(m.group(0).lower() for m in RX_WEAK.finditer(text)))
    if sender in HIGH_VALUE_SENDERS:
        return "hermann", addrs, strong + weak, []
    if addrs:
        return "adresse", addrs, strong + weak, []
    if strong:
        return "werkzeug", [], strong + weak, []
    if len(weak) >= MIN_WEAK:
        return "werkzeug", [], weak, []
    return None, [], [], []


async def main():
    csv.field_size_limit(10_000_000)
    state = load_state()
    seen_addr = known_addresses()
    seen_hash = set(state.get("_hashes", []))
    seen_nums = set(state.get("_nums", []))
    wanted = config.get("tg_watch_channels") or DEFAULT_CHANNELS

    client = TelegramClient(SESSION, int(config["telegram_api_id"]),
                            config["telegram_api_hash"])
    await client.connect()
    if not await client.is_user_authorized():
        print("Nicht autorisiert.")
        return

    new_rows, finds, skipped = [], [], 0
    async for d in client.iter_dialogs():
        if not (d.is_channel or d.is_group):
            continue
        if wanted and d.id not in wanted:
            continue
        key = str(d.id)
        last = state.get(key, 0)
        newest = last
        count = 0
        is_nakmak = d.id == DEFAULT_CHANNELS[0]

        async for m in client.iter_messages(d.entity, min_id=last, limit=500):
            newest = max(newest, m.id)
            count += 1
            text = (m.raw_text or "").replace("\n", " ").strip()
            if not text:
                continue

            sender = ""
            try:
                s = await m.get_sender()
                sender = (getattr(s, "username", "") or "").lower()
            except Exception:
                pass

            reason, addrs, kw, _ = classify(text, sender)
            addrs = [a for a in addrs if a not in seen_addr]
            if reason == "adresse" and not addrs:
                reason = "werkzeug" if kw else None

            # Wiki-Eintraege nur im NAKMAK-Chat und je Nummer genau einmal
            nums = []
            if is_nakmak and len(text) > 200:
                for n in NUMBERED.findall(text):
                    tag = "%s#%s" % (key, n)
                    if tag not in seen_nums:
                        seen_nums.add(tag)
                        nums.append(n)
            if nums and not reason:
                reason = "wiki"
            if not reason:
                continue

            # gleicher Text (z.B. weitergeleitete Podcast-Ankuendigung) nur einmal
            h = hashlib.sha1(text[:400].encode("utf-8")).hexdigest()[:16]
            if h in seen_hash:
                skipped += 1
                continue
            seen_hash.add(h)

            if sender in IMPOSTORS:
                reason = "NACHAHMER"

            new_rows.append([m.date.isoformat(), d.name, m.id, sender, reason,
                             "|".join(addrs), "|".join(kw),
                             "|".join(CASHTAG.findall(text)), text[:400]])
            if not INIT:
                finds.append({"chat": d.name, "sender": sender, "reason": reason,
                              "date": m.date.strftime("%d.%m %H:%M"),
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
                w.writerow(["date", "chat", "msg_id", "sender", "grund",
                            "addresses", "keywords", "cashtags", "text"])
            w.writerows(new_rows)

    # Hashes/Nummern begrenzen, sonst waechst der State unbegrenzt
    state["_hashes"] = list(seen_hash)[-4000:]
    state["_nums"] = list(seen_nums)[-2000:]
    save_state(state)

    if INIT:
        print("Stand gemerkt (%d Chats). Kuenftige Laeufe melden nur Neues."
              % len([k for k in state if not k.startswith("_")]))
        return
    if skipped:
        print("%d Doppel-Meldungen unterdrueckt." % skipped)
    if not finds:
        print("Nichts Meldenswertes.")
        return

    ICON = {"hermann": "🏦 HERMANN", "adresse": "🔗 NEUE ADRESSE",
            "werkzeug": "🔧 Werkzeug", "wiki": "📘 Wiki",
            "NACHAHMER": "⚠️ NACHAHMER"}
    lines = ["🔭 Telegram-Screening %s — %d Fund(e)"
             % (datetime.now().strftime("%d.%m %H:%M"), len(finds)), ""]
    for f in sorted(finds, key=lambda x: x["reason"] != "hermann")[:20]:
        head = "• %s | %s | %s" % (ICON.get(f["reason"], f["reason"]),
                                   f["chat"][:20], f["date"])
        if f["sender"]:
            head += " | @" + f["sender"]
        if f["addrs"]:
            head += " | " + ", ".join(a[:12] + "…" for a in f["addrs"])
        if f["nums"]:
            head += " | #" + ",#".join(f["nums"][:3])
        if f["kw"]:
            head += " | " + ", ".join(f["kw"][:6])
        lines.append(head)
        lines.append("   " + f["text"][:200])
    if len(finds) > 20:
        lines.append("… und %d weitere (siehe tg/watch_log.csv)" % (len(finds) - 20))
    msg = "\n".join(lines)
    print(msg)
    if not DRY:
        tg_send(msg)


asyncio.run(main())
