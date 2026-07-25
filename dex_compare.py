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
# 2x2-Faktorial (v7 Kontrolle, v9 Fade-Cut, v10 Velocity<=300, v11 beides) SUNSET
# 2026-07-20: Live-Ergebnis nach 9 Tagen war -96..-98% (Equity $10-19 von $500),
# Pauschal-Kostenmodell erwies sich als 7x zu pessimistisch (siehe v12). Prozesse
# gestoppt (Backup-Kopien: *_sunset_20260720-*.json), Original-Dateien bleiben
# unveraendert liegen -> Equity friert ab jetzt einfach ein (keine neuen Trades).
# v12 (Jupiter-Fill, echte Kosten) ist die einzige AKTIVE Variante.
SUNSET = {"Baseline v7", "v9 Fade-Cut", "v10 Vel300", "v11 Vel+Fade"}
VARIANTS = [
    ("Baseline v7",   "paper_trades.json",     "paper_heartbeat.json"),
    ("v9 Fade-Cut",   "paper_trades_v9.json",  "paper_heartbeat_v9.json"),
    ("v10 Vel300",    "paper_trades_v10.json", "paper_heartbeat_v10.json"),
    ("v11 Vel+Fade",  "paper_trades_v11.json", "paper_heartbeat_v11.json"),
    ("v12 JupFill",   "paper_trades_v12.json", "paper_heartbeat_v12.json"),
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
    # 25.07.: SUNSET-Zeilen raus aus dem Report — eingefrorene Zahlen jeden Tag neu
    # zu melden ist Feed-Rauschen. Die Historie liegt in den *_sunset_*-Dateien.
    rows = [(name, analyze(tf, hf)) for name, tf, hf in VARIANTS if name not in SUNSET]
    L = ["\U0001F9EA <b>DEX Paper — v12 Jupiter-Fill</b> (v7-v11 sunset 20.07., eingefroren)", ""]
    for name, s in rows:
        tag = " ✅ AKTIV"
        L.append("<b>%s</b>%s  (Start $500)" % (name, tag))
        L.append("  Equity <b>$%.0f</b> | %d Trades | WR %.0f%%" % (s["eq"], s["n"], s["wr"]))
        L.append("  NET $%+.0f (avg $%+.2f) | Rugs %d" % (s["net"], s["avg"], s["rugs"]))
        L.append("  Pyramide: %d Trades, net $%+.0f | Ø-Rückgabe %.0f pp" % (s["pyr_n"], s["pyr_net"], s["gb"]))
        L.append("")
    v12 = next(s for nm, s in rows if nm == "v12 JupFill")
    L.append("→ v12 ist die einzige aktive Variante: Equity $%.0f (avg $%+.2f/Trade, n=%d)."
             % (v12["eq"], v12["avg"], v12["n"]))
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
