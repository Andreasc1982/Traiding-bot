#!/usr/bin/env python3
"""DEX A/B-Vergleich: Baseline v7 vs v8 Aggro-Pyramid -> Telegram (Cron).

Liest die Paper-Trades + Heartbeats beider Varianten, rechnet WR/NET/avg,
Pyramiding-Beitrag und Gewinner-Rueckgabe, und schickt einen kompakten
Vergleich per Telegram. Read-only, kein Geld.

Usage: python3 dex_compare.py [--tg]   (ohne --tg nur Konsole)
"""
import json, os, sys

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
DEX = os.path.join(BASE, "dex")
try:
    from config import config
except Exception:
    config = {}
TG_TOKEN = config.get("telegram_bot_token", "")
TG_CHAT  = config.get("telegram_chat_id", "")

# (Anzeigename, trades-Datei, heartbeat-Datei)
VARIANTS = [
    ("Baseline v7",   "paper_trades.json",     "paper_heartbeat.json"),
    ("v8 Aggro-Pyr",  "paper_trades_v8.json",  "paper_heartbeat_v8.json"),
]


def _load(name):
    try:
        return json.load(open(os.path.join(DEX, name)))
    except Exception:
        return None


def analyze(trades_f, hb_f):
    trades = _load(trades_f) or []
    hb = _load(hb_f) or {}
    n = len(trades)
    pnls = [t.get("profit", 0) for t in trades]
    net = sum(pnls)
    wr = (len([x for x in pnls if x > 0]) / n * 100) if n else 0.0
    rugs = len([t for t in trades if "RUG" in str(t.get("reason", "")).upper()])
    pyr = [t.get("profit", 0) for t in trades if t.get("adds", 0) >= 1]
    ran = [t for t in trades if t.get("peak_pct", 0) >= 20]
    gb = (sum(t.get("peak_pct", 0) - t.get("pct", 0) for t in ran) / len(ran)) if ran else 0.0
    return {
        "n": n, "wr": wr, "net": net, "avg": (net / n if n else 0.0),
        "eq": hb.get("equity", 500.0), "rugs": rugs,
        "pyr_n": len(pyr), "pyr_net": sum(pyr), "gb": gb,
    }


def build_msg():
    rows = [(name, analyze(tf, hf)) for name, tf, hf in VARIANTS]
    L = ["\U0001F9EA <b>DEX A/B — Baseline v7 vs v8 Aggro-Pyramid</b>", ""]
    for name, s in rows:
        L.append("<b>%s</b>  (Start $500)" % name)
        L.append("  Equity <b>$%.0f</b> | %d Trades | WR %.0f%%" % (s["eq"], s["n"], s["wr"]))
        L.append("  NET $%+.0f (avg $%+.2f) | Rugs %d" % (s["net"], s["avg"], s["rugs"]))
        L.append("  Pyramide: %d Trades, net $%+.0f | Ø-Rückgabe %.0f pp" % (s["pyr_n"], s["pyr_net"], s["gb"]))
        L.append("")
    b, v = rows[0][1], rows[1][1]
    if v["n"] < 20:
        L.append("→ v8 sammelt noch (%d Trades) — Urteil folgt in 1-2 Tagen" % v["n"])
    else:
        d = v["avg"] - b["avg"]
        de = v["eq"] - b["eq"]
        if d > 0:
            L.append("→ ✅ <b>v8 führt</b>: avg $%+.2f vs $%+.2f (+$%.2f/Trade, Equity %+.0f$)" % (v["avg"], b["avg"], d, de))
        else:
            L.append("→ ❌ Baseline führt: v8 avg $%+.2f vs $%+.2f (%+.0f$ Equity)" % (v["avg"], b["avg"], de))
    return "\n".join(L)


def main():
    msg = build_msg()
    print(msg.replace("<b>", "").replace("</b>", ""))
    if "--tg" in sys.argv and TG_TOKEN and TG_CHAT:
        import requests
        try:
            requests.post("https://api.telegram.org/bot" + TG_TOKEN + "/sendMessage",
                          data={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=15)
            print("[TG] gesendet")
        except Exception as e:
            print("[TG] Fehler: " + str(e)[:80])


if __name__ == "__main__":
    main()
