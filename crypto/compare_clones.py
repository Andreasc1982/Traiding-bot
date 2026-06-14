#!/usr/bin/env python3
"""
Vergleichs-Report fuer das Clone-Experiment (A/B/C/D).
Liest die State/Dashboard/Trades jedes Clones, rechnet Equity, Netto-Rendite,
Win-Rate, Trade-Zahl, und gibt eine sortierte Tabelle aus + Telegram-Snapshot.

Usage:
  python3 compare_clones.py          # Tabelle ausgeben
  python3 compare_clones.py --tg     # zusaetzlich Telegram-Report senden
"""
import json, os, sys

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
try:
    from config import config
except ImportError:
    config = {}

CLONE_DIR = os.path.join(BASE, "crypto", "clones")
START = 5000.0
VARIANTS = [
    ("A_baseline",     "A · Baseline (Momentum+Spikes)"),
    ("B_nospikes",     "B · No-Spikes (Momentum)"),
    ("C_conservative", "C · Conservative (streng)"),
    ("D_contrarian",   "D · Contrarian (Oversold)"),
]


def _load(variant):
    dpath = os.path.join(CLONE_DIR, variant + "_dashboard.json")
    tpath = os.path.join(CLONE_DIR, variant + "_trades.json")
    try:
        dash = json.load(open(dpath))
    except Exception:
        return None
    try:
        trades = json.load(open(tpath))
    except Exception:
        trades = []
    pos = dash.get("positions", {})
    open_val = sum(p.get("shares", 0) * p.get("current_price", p.get("entry", 0))
                   for p in pos.values())
    equity = dash.get("balance", 0) + open_val
    wins = sum(1 for t in trades if t.get("profit", 0) > 0)
    wr = round(wins / len(trades) * 100) if trades else None
    closed_pnl = sum(t.get("profit", 0) for t in trades)
    return {
        "variant": variant,
        "equity":  equity,
        "ret":     (equity - START) / START * 100,
        "cash":    dash.get("balance", 0),
        "open":    len(pos),
        "trades":  len(trades),
        "wins":    wins,
        "wr":      wr,
        "closed_pnl": closed_pnl,
        "ws":      dash.get("ws_connected", False),
        "time":    dash.get("time", "?"),
    }


def main():
    rows = []
    for v, _ in VARIANTS:
        r = _load(v)
        if r:
            rows.append(r)
    if not rows:
        print("Keine Clone-Daten gefunden.")
        return

    rows.sort(key=lambda r: -r["ret"])
    labels = dict(VARIANTS)

    # ── Konsolen-Tabelle ──────────────────────────────────────────────────────
    print("=" * 72)
    print("  CLONE-EXPERIMENT VERGLEICH  (Start je $" + "{:,.0f}".format(START) + ")")
    print("=" * 72)
    hdr = "{:<32} {:>9} {:>8} {:>6} {:>7} {:>6}".format(
        "Variante", "Equity", "Rendite", "Pos", "Trades", "WR")
    print(hdr)
    print("-" * 72)
    for i, r in enumerate(rows):
        crown = " <" if i == 0 else "  "
        print("{:<32} {:>9} {:>7}% {:>6} {:>7} {:>5}{}".format(
            labels[r["variant"]][:32],
            "${:,.0f}".format(r["equity"]),
            ("+" if r["ret"] >= 0 else "") + "{:.2f}".format(r["ret"]),
            str(r["open"]) + "/8",
            r["trades"],
            (str(r["wr"]) + "%") if r["wr"] is not None else "–",
            crown))
    print("=" * 72)

    # ── Telegram-Report ───────────────────────────────────────────────────────
    if "--tg" in sys.argv:
        tok = config.get("telegram_bot_token", "")
        cid = config.get("telegram_chat_id", "")
        if tok and cid:
            lines = ["\U0001F9EC <b>Clone-Experiment</b> (Start je $5.000)"]
            medals = ["\U0001F947", "\U0001F948", "\U0001F949", "  "]
            for i, r in enumerate(rows):
                arrow = "\U0001F4C8" if r["ret"] >= 0 else "\U0001F4C9"
                lines.append(
                    medals[i] + " <b>" + labels[r["variant"]].split(" · ")[0] + "</b> " +
                    arrow + " " + ("+" if r["ret"] >= 0 else "") + "{:.2f}".format(r["ret"]) + "%" +
                    "  ($" + "{:,.0f}".format(r["equity"]) + ")")
                lines.append("    " + str(r["open"]) + " Pos · " + str(r["trades"]) +
                             " Trades · WR " + ((str(r["wr"]) + "%") if r["wr"] is not None else "–"))
            import requests
            try:
                requests.post("https://api.telegram.org/bot" + tok + "/sendMessage",
                              json={"chat_id": cid, "text": "\n".join(lines), "parse_mode": "HTML"},
                              timeout=10)
                print("[TG] Report gesendet")
            except Exception as e:
                print("[TG] Fehler: " + str(e))


if __name__ == "__main__":
    main()
