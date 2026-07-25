#!/usr/bin/env python3
"""Einmal-Reset: Super-Bot auf $5000 + Risk-Agent-Re-Baseline (2026-07-25).
Voraussetzung: trading/risk/monitor Sessions sind GESTOPPT (keine Concurrent-Writer).
Analog zum Crypto-Reset 09.07.: ohne Peak-Re-Baseline feuert die -15%-Bremse sofort."""
import json, os, time, shutil

BASE = "/home/trading2025/trading_bot"
ts = time.strftime("%Y%m%d-%H%M%S")
today = time.strftime("%Y-%m-%d")


def arch(p):
    if os.path.exists(p):
        shutil.copy(p, p[:-5] + "_pre5k_" + ts + ".json")


# Crypto-Equity live -> neue Combined-Basis fuer den Risk-Peak
c = json.load(open(BASE + "/crypto/crypto_dashboard.json"))
ceq = c.get("balance", 0) + sum(
    (p.get("shares", 0) or 0) * (p.get("current_price", p.get("entry", 0)) or 0)
    for p in (c.get("positions") or {}).values())
combined = 5000.0 + ceq

# super_state -> $5000, keine Positionen
arch(BASE + "/super_state.json")
try:
    ss = json.load(open(BASE + "/super_state.json"))
except Exception:
    ss = {}
ss["balance"] = 5000.0
ss["day_start_balance"] = 5000.0
ss["day_date"] = today
ss["positions"] = {}
json.dump(ss, open(BASE + "/super_state.json", "w"))

# Trade-Historie archivieren, frisch starten (die 35 waren grosstenteils der Blind-Zeitraum)
arch(BASE + "/trades_history.json")
json.dump([], open(BASE + "/trades_history.json", "w"))

# Dashboard sofort auf $5000 (damit der Risk-Agent nie den alten $66k-Wert liest)
arch(BASE + "/dashboard.json")
json.dump({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": "DEMO", "balance": 5000.0,
           "positions": {}, "scores": {}, "trades": [], "total_pnl": 0, "wins": 0,
           "total_trades": 0, "running": True, "fear_greed": {"value": 50, "label": "N/A"}},
          open(BASE + "/dashboard.json", "w"))

# Risk-Log Re-Baseline
r = json.load(open(BASE + "/agents/risk_log.json"))
r["peak_value"] = combined
r["rolling_peak"] = combined
r["day_start_value"] = combined
r["day_start_date"] = today
r["super_day_start"] = 5000.0
r["super_day_date"] = today
r["crypto_day_start"] = ceq
r["crypto_day_date"] = today
r["halted"] = False
r["super_halted"] = False
r["crypto_halted"] = False
r["resume_at"] = None
r["super_resume_at"] = None
r["crypto_resume_at"] = None
r["manual_hold"] = False
r["drawdown_halt_times"] = []
for k in ("halt_btc_price", "halt_spy_price", "halt_time"):
    r.pop(k, None)
r.setdefault("events", []).append(
    {"time": time.strftime("%Y-%m-%d %H:%M"), "type": "RESET",
     "detail": "Super auf $5000; Peak re-baselined auf combined $%.0f (crypto $%.0f)" % (combined, ceq)})
json.dump(r, open(BASE + "/agents/risk_log.json", "w"))

# Equity-Historie auf Header truncaten (alte $66-71k-Kurve wuerde Rolling-Peak vergiften)
open(BASE + "/agents/equity_history.csv", "w").write("time,super,crypto,combined\n")

# evtl. Halt-Flag entfernen
for f in ("/agents/risk_halt.json", "/agents/manual_resume.flag"):
    try:
        os.remove(BASE + f)
    except OSError:
        pass

print("RESET OK | crypto equity $%.0f | neue combined-Basis $%.0f" % (ceq, combined))
