#!/usr/bin/env python3
"""
Equity-Logger fuer das Clone-Experiment.
- Schreibt alle ~30 Min eine Zeile je Clone nach clones/equity_log.csv
  (time, variant, equity, return_pct, trades, positions, wins, win_rate)
  -> Grundlage fuer Equity-Kurven, Max-Drawdown, Sharpe, Konsistenz.
- Alarmiert SOFORT per Telegram bei unplausibler Rendite (|ret| > ANOMALY_PCT)
  = frueher Bug-Fang (haette den Contrarian-Phantom-Gewinn in 30 Min erwischt).
"""
import json, os, sys
from datetime import datetime

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
try:
    from config import config
except ImportError:
    config = {}

CLONE_DIR   = os.path.join(BASE, "crypto", "clones")
CSV         = os.path.join(CLONE_DIR, "equity_log.csv")
START       = 5000.0
ANOMALY_PCT = 25.0                       # Tagesrenditen > 25% sind unrealistisch -> Bug
VARIANTS    = ["A_baseline", "B_nospikes", "C_conservative", "D_contrarian", "E_moonshot"]


def equity_of(d):
    eq = d.get("balance", 0)
    for p in d.get("positions", {}).values():
        eq += p.get("shares", 0) * p.get("current_price", p.get("entry", 0))
    return eq


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows, anomalies = [], []

    for v in VARIANTS:
        try:
            d = json.load(open(os.path.join(CLONE_DIR, v + "_dashboard.json")))
        except Exception:
            continue
        try:
            trades = json.load(open(os.path.join(CLONE_DIR, v + "_trades.json")))
        except Exception:
            trades = []
        eq   = equity_of(d)
        ret  = (eq - START) / START * 100
        wins = sum(1 for t in trades if t.get("profit", 0) > 0)
        wr   = round(wins / len(trades) * 100) if trades else 0
        rows.append((v, eq, ret, len(trades), len(d.get("positions", {})), wins, wr))
        if abs(ret) > ANOMALY_PCT:
            anomalies.append((v, ret))

    newfile = not os.path.exists(CSV)
    with open(CSV, "a") as f:
        if newfile:
            f.write("time,variant,equity,return_pct,trades,positions,wins,win_rate\n")
        for v, eq, ret, tr, pos, wins, wr in rows:
            f.write(",".join([now, v, str(round(eq, 2)), str(round(ret, 2)),
                              str(tr), str(pos), str(wins), str(wr)]) + "\n")

    # Anomalie-Alarm
    if anomalies and config.get("telegram_bot_token") and config.get("telegram_chat_id"):
        import requests
        lines = ["⚠️ <b>CLONE-ANOMALIE</b> (Bug-Verdacht):"]
        for v, r in anomalies:
            lines.append("  " + v + ": " + ("+" if r >= 0 else "") + str(round(r, 1)) +
                         "%  (>" + str(int(ANOMALY_PCT)) + "% ist unrealistisch)")
        lines.append("Bitte pruefen — kein echter Edge, eher Rechen-/Preis-Fehler.")
        try:
            requests.post("https://api.telegram.org/bot" + config["telegram_bot_token"] + "/sendMessage",
                          json={"chat_id": config["telegram_chat_id"], "text": "\n".join(lines),
                                "parse_mode": "HTML"}, timeout=10)
            print("[ALARM] Anomalie gemeldet: " + str(anomalies))
        except Exception as e:
            print("[ALARM] TG-Fehler: " + str(e))

    print("[EQUITY-LOG] " + now + " | " + str(len(rows)) + " Clones geloggt" +
          (" | ANOMALIEN: " + str(len(anomalies)) if anomalies else ""))


if __name__ == "__main__":
    main()
