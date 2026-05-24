#!/usr/bin/env python3
"""
Monitor Agent — watches all 8 screen sessions.
Checks every 60s, restarts on crash, sends Telegram alerts, daily 08:00 report,
and alerts on high CPU/RAM/disk usage.

Launch:
  screen -dmS monitor bash -c '
    cd /home/trading2025/trading_bot/agents &&
    source /home/trading2025/trading_bot_env/bin/activate &&
    PYTHONUNBUFFERED=1 python3 -u monitor_agent.py > /tmp/monitor.log 2>&1'
"""

import os
import sys
import json
import time
import subprocess
import requests
from datetime import datetime, date

# ── Config ────────────────────────────────────────────────────────────────────

sys.path.insert(0, "/home/trading2025/trading_bot")
try:
    from config import config
except ImportError:
    config = {}

TELEGRAM_TOKEN   = config.get("telegram_bot_token", "")
TELEGRAM_CHAT_ID = config.get("telegram_chat_id", "")

SUPER_JSON       = "/home/trading2025/trading_bot/dashboard.json"
CRYPTO_JSON      = "/home/trading2025/trading_bot/crypto/crypto_dashboard.json"
VENV_ACTIVATE    = "/home/trading2025/trading_bot_env/bin/activate"
BOT_DIR          = "/home/trading2025/trading_bot"
RISK_HALT_FILE   = "/home/trading2025/trading_bot/agents/risk_halt.json"

CHECK_INTERVAL   = 60    # seconds between watchdog cycles
STALE_MINUTES    = 15    # alert if dashboard JSON older than this
CPU_WARN         = 85.0  # % — alert threshold
RAM_WARN         = 85.0  # %
DISK_WARN        = 85.0  # %
SYS_ALERT_COOLDOWN = 3600  # seconds between repeated system-health alerts

# ── Bot / service definitions ─────────────────────────────────────────────────
#
# "trading_only" = True  → skip restart while risk_agent halt is active
# "trading_only" = False → always restart (infrastructure processes)
#
BOTS = {
    "trading": {
        "name":         "Super Bot",
        "session":      "trading",
        "trading_only": True,
        "cmd": (
            "cd /home/trading2025/trading_bot && "
            "source /home/trading2025/trading_bot_env/bin/activate && "
            "PYTHONUNBUFFERED=1 python3 -u super_bot.py > /tmp/super_bot.log 2>&1"
        ),
    },
    "crypto": {
        "name":         "Crypto Bot",
        "session":      "crypto",
        "trading_only": True,
        "cmd": (
            "cd /home/trading2025/trading_bot/crypto && "
            "source /home/trading2025/trading_bot_env/bin/activate && "
            "PYTHONUNBUFFERED=1 python3 -u crypto_bot.py > /tmp/crypto_bot.log 2>&1"
        ),
    },
    "dashboard": {
        "name":         "Dashboard HTTP :8080",
        "session":      "dashboard",
        "trading_only": False,
        # Kill any orphaned process on 8080 before binding (handles ungraceful shutdowns)
        "cmd": (
            "fuser -k 8080/tcp 2>/dev/null; sleep 1; "
            "cd /home/trading2025/trading_bot && "
            "python3 -m http.server 8080 > /tmp/dashboard.log 2>&1"
        ),
    },
    "dashboard_crypto": {
        "name":         "Crypto Dashboard HTTP :8081",
        "session":      "dashboard_crypto",
        "trading_only": False,
        # Kill any orphaned process on 8081 before binding
        "cmd": (
            "fuser -k 8081/tcp 2>/dev/null; sleep 1; "
            "cd /home/trading2025/trading_bot/crypto && "
            "python3 -m http.server 8081 > /tmp/dashboard_crypto.log 2>&1"
        ),
    },
    "risk": {
        "name":         "Risk Agent",
        "session":      "risk",
        "trading_only": False,
        "cmd": (
            "cd /home/trading2025/trading_bot/agents && "
            "source /home/trading2025/trading_bot_env/bin/activate && "
            "PYTHONUNBUFFERED=1 python3 -u risk_agent.py > /tmp/risk.log 2>&1"
        ),
    },
    "optimize": {
        "name":         "Optimize Agent",
        "session":      "optimize",
        "trading_only": False,
        "cmd": (
            "cd /home/trading2025/trading_bot/agents && "
            "source /home/trading2025/trading_bot_env/bin/activate && "
            "PYTHONUNBUFFERED=1 python3 -u optimize_agent.py > /tmp/optimize.log 2>&1"
        ),
    },
    "tgrouter": {
        "name":         "Telegram Router",
        "session":      "tgrouter",
        "trading_only": False,
        "cmd": (
            "cd /home/trading2025/trading_bot && "
            "source /home/trading2025/trading_bot_env/bin/activate && "
            "PYTHONUNBUFFERED=1 python3 -u telegram_router.py > /tmp/tgrouter.log 2>&1"
        ),
    },
}

# ── State ─────────────────────────────────────────────────────────────────────

_crash_alerted   = {k: False for k in BOTS}   # True while bot is down (prevents spam)
_last_daily      = None                         # date of last daily report
_last_sys_alert  = 0.0                          # timestamp of last sys-health alert

# ── Telegram ──────────────────────────────────────────────────────────────────

def tg(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TG] " + msg)
        return
    try:
        url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("[TG ERROR] " + str(e))

# ── Screen helpers ─────────────────────────────────────────────────────────────

def screen_alive(session):
    """True if a screen session with this name is listed in `screen -ls`."""
    try:
        result = subprocess.run(["screen", "-ls"], capture_output=True, text=True)
        # screen -ls lines look like:  "    12345.trading\t(date)\t(Detached)"
        return ("." + session + "\t") in result.stdout
    except Exception as e:
        print("[SCREEN] " + str(e))
        return False   # assume dead on error — better to restart than ignore

def start_bot(session):
    bot = BOTS[session]
    subprocess.run(["screen", "-dmS", session, "bash", "-c", bot["cmd"]])

# ── Watchdog ───────────────────────────────────────────────────────────────────

def check_bots():
    now_str = datetime.now().strftime("%H:%M")

    # If risk agent has halted trading, skip restart of trading bots only.
    # Dashboard, monitor, and risk agent itself still get restarted if they crash.
    risk_halted = os.path.exists(RISK_HALT_FILE)
    if risk_halted:
        print("[MONITOR] Risk halt aktiv — trading/crypto-Restart übersprungen")

    for session, bot in BOTS.items():
        name  = bot["name"]
        alive = screen_alive(session)

        if alive:
            if _crash_alerted[session]:
                # Came back on its own (e.g. manual restart by user)
                print("[OK] " + name + " wieder aktiv")
                _crash_alerted[session] = False
            print("[OK] " + name + " läuft  (screen:" + session + ")")
            continue

        # ── Bot is down ────────────────────────────────────────────────────
        # Don't restart trading/crypto during a risk halt — risk agent owns them.
        # Infrastructure services (dashboards, router, agents) always restart.
        if risk_halted and bot.get("trading_only", False):
            print("[MONITOR] " + name + " ist gestoppt (Risk Halt aktiv — kein Restart)")
            continue

        if not _crash_alerted[session]:
            msg = "🚨 CRASH: " + name + " (screen:" + session + ") ist ausgefallen! " + now_str
            print(msg)
            tg(msg)
            _crash_alerted[session] = True

        # Wait briefly so any lingering zombie screen clears, then restart
        time.sleep(3)
        print("[RESTART] Starte " + name + " neu...")
        start_bot(session)
        time.sleep(5)

        if screen_alive(session):
            msg = "✅ RESTART OK: " + name + " erfolgreich neu gestartet. " + now_str
            print(msg)
            tg(msg)
            _crash_alerted[session] = False
        else:
            msg = "❌ RESTART FEHLGESCHLAGEN: " + name + " läuft immer noch nicht! " + now_str
            print(msg)
            tg(msg)

# ── Stale dashboard check ─────────────────────────────────────────────────────

def check_stale():
    for path, name in [(SUPER_JSON, "Super Bot"), (CRYPTO_JSON, "Crypto Bot")]:
        if not os.path.exists(path):
            continue
        age_min = (time.time() - os.path.getmtime(path)) / 60
        if age_min > STALE_MINUTES:
            msg = ("⚠️ " + name + " Dashboard seit " + str(round(age_min, 0)) +
                   " min nicht aktualisiert — Bot evtl. hängend?")
            print(msg)
            tg(msg)

# ── System health ─────────────────────────────────────────────────────────────

def cpu_percent():
    """Measure real CPU % over a 0.5s sample from /proc/stat."""
    def read_stat():
        with open("/proc/stat") as f:
            parts = f.readline().split()
        vals = list(map(int, parts[1:]))
        idle  = vals[3] + vals[4]          # idle + iowait
        total = sum(vals)
        return idle, total

    idle1, total1 = read_stat()
    time.sleep(0.5)
    idle2, total2 = read_stat()
    delta_total = total2 - total1
    delta_idle  = idle2  - idle1
    if delta_total == 0:
        return 0.0
    return round(100 * (1 - delta_idle / delta_total), 1)

def ram_percent():
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 2:
                mem[parts[0].rstrip(":")] = int(parts[1])
    used = mem["MemTotal"] - mem.get("MemAvailable", mem.get("MemFree", 0))
    return round(used / mem["MemTotal"] * 100, 1)

def disk_info(path="/"):
    try:
        result = subprocess.run(["df", "-h", path], capture_output=True, text=True)
        line   = result.stdout.strip().split("\n")[-1].split()
        pct    = int(line[4].replace("%", ""))
        free   = line[3]
        return pct, free
    except Exception:
        return None, None

def system_health(force_print=False):
    global _last_sys_alert
    try:
        cpu       = cpu_percent()
        ram       = ram_percent()
        disk_pct, disk_free = disk_info()

        print("[SYS] CPU=" + str(cpu) + "% RAM=" + str(ram) + "%" +
              (" Disk=" + str(disk_pct) + "% (frei " + str(disk_free) + ")" if disk_pct else ""))

        alerts = []
        if cpu  > CPU_WARN:   alerts.append("CPU:  " + str(cpu)  + "% (>" + str(CPU_WARN)  + ")")
        if ram  > RAM_WARN:   alerts.append("RAM:  " + str(ram)  + "% (>" + str(RAM_WARN)  + ")")
        if disk_pct and disk_pct > DISK_WARN:
            alerts.append("Disk: " + str(disk_pct) + "% voll (frei: " + str(disk_free) + ")")

        cooldown_ok = (time.time() - _last_sys_alert) > SYS_ALERT_COOLDOWN
        if alerts and cooldown_ok:
            tg("⚠️ SYSTEM WARNUNG:\n" + "\n".join(alerts))
            _last_sys_alert = time.time()

        return cpu, ram, disk_pct, disk_free

    except Exception as e:
        print("[SYS ERROR] " + str(e))
        return None, None, None, None

# ── Dashboard reader ──────────────────────────────────────────────────────────

def read_json(path):
    try:
        if not os.path.exists(path):
            return {}
        age_min = (time.time() - os.path.getmtime(path)) / 60
        with open(path) as f:
            d = json.load(f)
        d["_age_min"] = round(age_min, 1)
        return d
    except Exception as e:
        print("[JSON] " + path + ": " + str(e))
        return {}

# ── Daily performance report ──────────────────────────────────────────────────

def daily_report():
    super_d  = read_json(SUPER_JSON)
    crypto_d = read_json(CRYPTO_JSON)
    now_str  = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines    = ["📊 TAGESBERICHT — " + now_str, ""]

    # ── Super Bot ────────────────────────────────────────────────────────────
    if super_d:
        bal   = super_d.get("balance", 0)
        pnl   = super_d.get("total_pnl", 0)
        wins  = super_d.get("wins", 0)
        total = super_d.get("total_trades", 0)
        pos   = super_d.get("positions", {})
        mode  = super_d.get("mode", "?")
        fg    = super_d.get("fear_greed", {})
        age   = super_d.get("_age_min", "?")
        pnl_s = ("+" if pnl >= 0 else "") + str(round(pnl, 0))

        lines.append("⚡ SUPER BOT  [" + mode + "]")
        lines.append("  Balance:    $" + "{:,.2f}".format(bal))
        lines.append("  Gesamt P&L: $" + pnl_s)
        lines.append("  Trades: " + str(total) + " | Wins: " + str(wins) +
                     (" | WR: " + str(round(wins / total * 100, 0)) + "%" if total else ""))
        lines.append("  Positionen: " + str(len(pos)) + "/15")
        for sym, p in list(pos.items())[:8]:
            pct = p.get("pnl_pct", 0)
            sign = "+" if pct >= 0 else ""
            lines.append("    " + sym.ljust(5) + "  " + sign + str(pct) + "%")
        lines.append("  F&G: " + str(fg.get("value", "?")) + " " + fg.get("label", ""))
        lines.append("  (JSON " + str(age) + " min alt)")
    else:
        lines.append("⚡ SUPER BOT — keine Daten (JSON fehlt)")

    lines.append("")

    # ── Crypto Bot ────────────────────────────────────────────────────────────
    if crypto_d:
        bal   = crypto_d.get("balance", 0)
        pnl   = crypto_d.get("total_pnl", 0)
        total = crypto_d.get("total_trades", 0)
        pos   = crypto_d.get("positions", {})
        mode  = crypto_d.get("mode", "?")
        fg    = crypto_d.get("fear_greed", {})
        age   = crypto_d.get("_age_min", "?")
        pnl_s = ("+" if pnl >= 0 else "") + str(round(pnl, 0))

        lines.append("₿ CRYPTO BOT  [" + mode + "]")
        lines.append("  Balance:    $" + "{:,.2f}".format(bal))
        lines.append("  Gesamt P&L: $" + pnl_s)
        lines.append("  Trades: " + str(total))
        lines.append("  Positionen: " + str(len(pos)) + "/6")
        for sym, p in list(pos.items())[:6]:
            pct  = p.get("pnl_pct", 0)
            sign = "+" if pct >= 0 else ""
            spike = " [SPIKE]" if p.get("spike") else ""
            lines.append("    " + sym.ljust(10) + sign + str(pct) + "%" + spike)
        lines.append("  F&G: " + str(fg.get("value", "?")) + " " + fg.get("label", ""))
        lines.append("  (JSON " + str(age) + " min alt)")
    else:
        lines.append("₿ CRYPTO BOT — keine Daten (JSON fehlt)")

    lines.append("")

    # ── System health ─────────────────────────────────────────────────────────
    cpu, ram, disk_pct, disk_free = system_health()
    lines.append("🖥️  System")
    if cpu is not None:
        lines.append("  CPU: " + str(cpu) + "%  RAM: " + str(ram) + "%" +
                     ("  Disk: " + str(disk_pct) + "% (frei " + str(disk_free) + ")" if disk_pct else ""))
    else:
        lines.append("  (Systemdaten nicht verfügbar)")

    # ── Screen session status ─────────────────────────────────────────────────
    lines.append("")
    lines.append("🖥️  Screen Sessions")
    for session, bot in BOTS.items():
        status = "✅ läuft" if screen_alive(session) else "❌ TOT"
        lines.append("  " + session.ljust(16) + status)

    msg = "\n".join(lines)
    print("[REPORT]\n" + msg)
    tg(msg)

# ── Main loop ─────────────────────────────────────────────────────────────────

def run():
    global _last_daily

    print("=" * 55)
    print("  MONITOR AGENT gestartet")
    print("  Check-Interval: " + str(CHECK_INTERVAL) + "s")
    print("  Überwacht: " + ", ".join(BOTS.keys()))
    print("=" * 55)
    tg("🟢 Monitor Agent gestartet\nÜberwacht: " + ", ".join(b["name"] for b in BOTS.values()))

    cycle = 0
    while True:
        try:
            now   = datetime.now()
            cycle += 1
            print("\n[" + now.strftime("%H:%M:%S") + "] Zyklus " + str(cycle))

            # 1) Watchdog — restart dead screen sessions
            check_bots()

            # 2) Stale dashboard check
            check_stale()

            # 3) System health — prints every cycle; Telegram only on threshold breach + cooldown
            system_health()

            # 4) Daily report at 08:00 (fires once per day)
            today = now.date()
            if now.hour == 8 and now.minute == 0 and _last_daily != today:
                _last_daily = today
                print("[REPORT] Sende Tagesbericht...")
                daily_report()

        except KeyboardInterrupt:
            print("[MONITOR] Gestoppt")
            tg("🔴 Monitor Agent gestoppt")
            break
        except Exception as e:
            print("[MONITOR ERROR] " + str(e))

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run()
