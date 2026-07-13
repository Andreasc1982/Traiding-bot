#!/usr/bin/env python3
"""DEX-Equity-Logger (Cron alle 30 min) — Equity-Kurve je Paper-Variante.

Haengt eine Zeile an dex/equity_dex.csv an (time,v7,v9,v10,v11,v12).
Grundlage fuer Drawdown/Varianz-Vergleich der Varianten — NET allein
verschweigt, WIE ruppig der Weg dorthin war. Read-only, kein Geld.
"""
import json, os
from datetime import datetime

DEX = "/home/trading2025/trading_bot/dex"
OUT = os.path.join(DEX, "equity_dex.csv")
VARIANTS = [("v7", "paper_heartbeat.json"), ("v9", "paper_heartbeat_v9.json"),
            ("v10", "paper_heartbeat_v10.json"), ("v11", "paper_heartbeat_v11.json"),
            ("v12", "paper_heartbeat_v12.json")]

row = [datetime.now().strftime("%Y-%m-%d %H:%M")]
for _name, hb in VARIANTS:
    try:
        row.append(str(round(json.load(open(os.path.join(DEX, hb))).get("equity", 0), 2)))
    except Exception:
        row.append("")

new = not os.path.exists(OUT)
with open(OUT, "a") as fh:
    if new:
        fh.write("time," + ",".join(n for n, _ in VARIANTS) + "\n")
    fh.write(",".join(row) + "\n")
print("[DEX-EQUITY] " + ",".join(row))
