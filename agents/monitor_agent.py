#!/usr/bin/env python3
"""
Monitor Agent -- watches all 8 screen sessions.
Checks every 60s, restarts on crash, sends Telegram alerts, daily 08:00 report,
alerts on high CPU/RAM/disk usage, and alerts if no trades fire in NO_TRADES_HOURS.

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

# -- Config -------------------------------------------------------------------

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

CHECK_INTERVAL     = 60     # seconds between watchdog cycles
STALE_MINUTES      = 15     # alert if dashboard JSON older than this
CPU_WARN           = 85.0   # % -- alert threshold
RAM_WARN           = 85.0   # %
DISK_WARN          = 85.0   # %
SYS_ALERT_COOLDOWN = 3600   # seconds between repeated system-health alerts

# No-trades alert: fire if neither bot has traded in this many hours.
# Only fires when bots are running and not risk-halted.
NO_TRADES_HOURS        = 8      # hours of silence before alerting
NO_TRADES_MIN_HISTORY  = 3      # don't alert if combined trade history < this (fresh start)
NO_TRADES_COOLDOWN     = 7200   # seconds (2h) between repeated no-trades alerts
SKIP_ANALYSIS_COOLDOWN = 14400  # seconds (4h) between skip-analysis reports

# -- Bot / service definitions ------------------------------------------------
#
# "trading_only" = True  -> skip restart while risk_agent halt is active
# "trading_only" = False -> always restart (infrastructure processes)
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
    "dex": {
        "name":         "DEX-Monitor (Solana)",
        "session":      "dex",
        "trading_only": False,
        "cmd": (
            "cd /home/trading2025/trading_bot && "
            "source /home/trading2025/trading_bot_env/bin/activate && "
            "PYTHONUNBUFFERED=1 python3 -u dex_monitor.py > /tmp/dex_monitor.log 2>&1"
        ),
    },
    "dex_dashboard": {
        "name":         "DEX Dashboard HTTP :8091",
        "session":      "dex_dashboard",
        "trading_only": False,
        "cmd": (
            "fuser -k 8091/tcp 2>/dev/null; sleep 1; "
            "cd /home/trading2025/trading_bot/dex && "
            "python3 /home/trading2025/trading_bot/dash_server.py 8091 dex_dashboard.html watchlist.json heartbeat.json > /tmp/dex_dashboard.log 2>&1"
        ),
    },
    "gateway": {
        "name":         "Market-Data Gateway",
        "session":      "gateway",
        "trading_only": False,
        "cmd": (
            "cd /home/trading2025/trading_bot/crypto && "
            "source /home/trading2025/trading_bot_env/bin/activate && "
            "PYTHONUNBUFFERED=1 python3 -u gateway.py > /tmp/gateway.log 2>&1"
        ),
    },
    "clone_A_baseline": {
        "name":         "Clone A (baseline)",
        "session":      "clone_A_baseline",
        "trading_only": False,
        "cmd": (
            "cd /home/trading2025/trading_bot/crypto && "
            "source /home/trading2025/trading_bot_env/bin/activate && "
            "PYTHONUNBUFFERED=1 python3 -u clone.py A_baseline > /tmp/clone_A_baseline.log 2>&1"
        ),
    },
    "clone_B_nospikes": {
        "name":         "Clone B (no-spikes)",
        "session":      "clone_B_nospikes",
        "trading_only": False,
        "cmd": (
            "cd /home/trading2025/trading_bot/crypto && "
            "source /home/trading2025/trading_bot_env/bin/activate && "
            "PYTHONUNBUFFERED=1 python3 -u clone.py B_nospikes > /tmp/clone_B_nospikes.log 2>&1"
        ),
    },
    "clone_C_conservative": {
        "name":         "Clone C (conservative)",
        "session":      "clone_C_conservative",
        "trading_only": False,
        "cmd": (
            "cd /home/trading2025/trading_bot/crypto && "
            "source /home/trading2025/trading_bot_env/bin/activate && "
            "PYTHONUNBUFFERED=1 python3 -u clone.py C_conservative > /tmp/clone_C_conservative.log 2>&1"
        ),
    },
    "clone_D_contrarian": {
        "name":         "Clone D (contrarian)",
        "session":      "clone_D_contrarian",
        "trading_only": False,
        "cmd": (
            "cd /home/trading2025/trading_bot/crypto && "
            "source /home/trading2025/trading_bot_env/bin/activate && "
            "PYTHONUNBUFFERED=1 python3 -u clone.py D_contrarian > /tmp/clone_D_contrarian.log 2>&1"
        ),
    },
    "clone_E_moonshot": {
        "name":         "Clone E (moonshot)",
        "session":      "clone_E_moonshot",
        "trading_only": False,
        "cmd": (
            "cd /home/trading2025/trading_bot/crypto && "
            "source /home/trading2025/trading_bot_env/bin/activate && "
            "PYTHONUNBUFFERED=1 python3 -u clone.py E_moonshot > /tmp/clone_E_moonshot.log 2>&1"
        ),
    },
    "clones_dashboard": {
        "name":         "Clones Dashboard HTTP :8090",
        "session":      "clones_dashboard",
        "trading_only": False,
        "cmd": (
            "fuser -k 8090/tcp 2>/dev/null; sleep 1; "
            "cd /home/trading2025/trading_bot/crypto/clones && "
            "python3 /home/trading2025/trading_bot/dash_server.py 8090 clones_dashboard.html A_baseline_dashboard.json B_nospikes_dashboard.json C_conservative_dashboard.json D_contrarian_dashboard.json E_moonshot_dashboard.json > /tmp/clones_dashboard.log 2>&1"
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
            "python3 /home/trading2025/trading_bot/dash_server.py 8080 dashboard_super.html dashboard.html dashboard.json > /tmp/dashboard.log 2>&1"
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
            "python3 /home/trading2025/trading_bot/dash_server.py 8081 dashboard_crypto.html crypto_dashboard.json > /tmp/dashboard_crypto.log 2>&1"
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

# -- State --------------------------------------------------------------------

_crash_alerted    = {k: False for k in BOTS}   # True while bot is down (prevents spam)
_last_daily       = None                         # date of last daily report
_last_sys_alert   = 0.0                          # timestamp of last sys-health alert
_last_no_trades   = 0.0                          # timestamp of last no-trades alert
_last_skip_report = 0.0                          # timestamp of last skip-analysis report
_last_update_alert = None                        # date of last apt update notification
_auth_log_pos      = 0                              # byte offset -- only read new lines
_last_sec_alert    = 0.0                             # timestamp of last security alert
_sec_fail_counts   = {}                              # ip -> (count, first_seen)
SEC_ALERT_COOLDOWN = 1800                            # 30 min between repeated security alerts

# -- Telegram -----------------------------------------------------------------

def tg(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TG] " + msg)
        return
    try:
        url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("[TG ERROR] " + str(e))

# -- Screen helpers -----------------------------------------------------------

def screen_alive(session):
    """True if a screen session with this name is listed in `screen -ls`."""
    try:
        result = subprocess.run(["screen", "-ls"], capture_output=True, text=True)
        # screen -ls lines look like:  "    12345.trading\t(date)\t(Detached)"
        return ("." + session + "\t") in result.stdout
    except Exception as e:
        print("[SCREEN] " + str(e))
        return False   # assume dead on error -- better to restart than ignore

def start_bot(session):
    bot = BOTS[session]
    subprocess.run(["screen", "-dmS", session, "bash", "-c", bot["cmd"]])

# -- Watchdog -----------------------------------------------------------------

def check_bots():
    now_str = datetime.now().strftime("%H:%M")

    # If risk agent has halted trading, skip restart of trading bots only.
    # Dashboard, monitor, and risk agent itself still get restarted if they crash.
    # Read per-bot halt targets from halt file (v2 format)
    # halted_sessions = set of screen session names that are risk-halted
    halted_sessions = set()
    if os.path.exists(RISK_HALT_FILE):
        try:
            with open(RISK_HALT_FILE) as _hf:
                _hd = json.load(_hf)
            _bots = _hd.get("halted_bots", ["super", "crypto"])
            _map  = {"super": "trading", "crypto": "crypto"}
            halted_sessions = {_map[b] for b in _bots if b in _map}
        except Exception:
            halted_sessions = {"trading", "crypto"}  # safe fallback
    risk_halted = bool(halted_sessions)
    if risk_halted:
        print("[MONITOR] Risk halt aktiv fuer: " + str(halted_sessions))

    for session, bot in BOTS.items():
        name  = bot["name"]
        alive = screen_alive(session)

        if alive:
            if _crash_alerted[session]:
                # Came back on its own (e.g. manual restart by user)
                print("[OK] " + name + " wieder aktiv")
                _crash_alerted[session] = False
            print("[OK] " + name + " laeuft  (screen:" + session + ")")
            continue

        # -- Bot is down -----------------------------------------------------
        # Don't restart trading/crypto during a risk halt -- risk agent owns them.
        # Infrastructure services (dashboards, router, agents) always restart.
        if session in halted_sessions:
            print("[MONITOR] " + name + " ist gestoppt (Risk Halt aktiv -- kein Restart)")
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
            msg = "❌ RESTART FEHLGESCHLAGEN: " + name + " laeuft immer noch nicht! " + now_str
            print(msg)
            tg(msg)

# -- Stale dashboard check ----------------------------------------------------

def check_stale():
    # Skip stale alert when risk halt is active -- bots are intentionally stopped
    if os.path.exists(RISK_HALT_FILE):
        return
    for path, name in [(SUPER_JSON, "Super Bot"), (CRYPTO_JSON, "Crypto Bot")]:
        if not os.path.exists(path):
            continue
        age_min = (time.time() - os.path.getmtime(path)) / 60
        if age_min > STALE_MINUTES:
            msg = ("⚠️ " + name + " Dashboard seit " + str(round(age_min, 0)) +
                   " min nicht aktualisiert -- Bot evtl. haengend?")
            print(msg)
            tg(msg)

# -- No-trades alert ----------------------------------------------------------

def _latest_trade_time(trades):
    """
    Return the most recent trade timestamp as a datetime, or None.
    trades is a list of dicts, each with a "time" key like "2026-05-23 14:30:00".
    """
    latest = None
    for t in trades:
        ts_str = t.get("time", "")
        if not ts_str:
            continue
        try:
            # Accept both "YYYY-MM-DD HH:MM:SS" and "YYYY-MM-DD HH:MM"
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    ts = datetime.strptime(ts_str[:19], fmt)
                    if latest is None or ts > latest:
                        latest = ts
                    break
                except ValueError:
                    continue
        except Exception:
            continue
    return latest

def check_skip_analysis():
    """
    Analyse welche Indikatoren den Super Bot am meisten blockieren.
    Liest das skips-Array aus dashboard.json und sendet Telegram-Report.
    Nur wenn Super Bot laeuft, nicht halted, min. 10 Skips vorhanden.
    """
    global _last_skip_report

    if os.path.exists(RISK_HALT_FILE):
        return
    if not screen_alive("trading"):
        return
    if (time.time() - _last_skip_report) < SKIP_ANALYSIS_COOLDOWN:
        return

    try:
        super_d = read_json(SUPER_JSON)
        if not super_d:
            return
        skips = super_d.get("skips", [])
        if len(skips) < 10:
            return  # Nicht genug Daten

        total = len(skips)
        # Indicator field -> display name
        ind_fields = [
            ("rsi_ok",   "RSI"),
            ("macd_ok",  "MACD"),
            ("st_ok",    "Supertrend"),
            ("ichi_ok",  "Ichimoku"),
            ("ma_ok",    "MA20"),
            ("cmf_ok",   "CMF"),
            ("obv_ok",   "OBV"),
            ("psar_ok",  "PSAR"),
            ("stoch_ok", "StochRSI"),
            ("vwap_ok",  "VWAP"),
        ]
        blocked = []
        for field, name in ind_fields:
            count = sum(1 for s in skips if s.get(field) is False)
            if count > 0:
                blocked.append((name, count, round(count / total * 100)))
        if not blocked:
            return

        blocked.sort(key=lambda x: -x[1])

        # Recent symbols being skipped
        recent_syms = list(dict.fromkeys([s.get("symbol","?") for s in skips[-10:]]))

        lines = [chr(128269) + " <b>Super Bot Skip-Analyse</b> (" + str(total) + " Skips):"]
        for name, count, pct in blocked:
            bar = chr(9608) * (pct // 10) + chr(9617) * (10 - pct // 10)
            lines.append(name.ljust(12) + " " + bar + " " + str(pct) + "%")
        lines.append("")
        lines.append("Zuletzt geblockt: " + ", ".join(recent_syms[-6:]))

        # Warn if one indicator blocks > 60%
        top_name, top_count, top_pct = blocked[0]
        if top_pct >= 60:
            lines.append("")
            lines.append(chr(9888) + chr(65039) + " <b>" + top_name + "</b> blockiert " +
                         str(top_pct) + "% aller Entries -- Schwellwert evtl. zu streng?")

        msg = chr(10).join(lines)
        print("[SKIP-ANALYSIS] " + top_name + " " + str(top_pct) + "% (top blocker)")
        tg(msg)
        _last_skip_report = time.time()

    except Exception as e:
        print("[SKIP-ANALYSIS ERROR] " + str(e))


def check_no_trades():
    """
    Alert if neither bot has made any trade in NO_TRADES_HOURS hours.
    Guards:
      - Risk halt active -> skip (bots are intentionally stopped)
      - Either bot session dead -> skip (crash alert already firing)
      - Combined trade history < NO_TRADES_MIN_HISTORY -> skip (fresh start)
      - Cooldown: at most one alert per NO_TRADES_COOLDOWN seconds
    """
    global _last_no_trades

    # Skip if halted
    if os.path.exists(RISK_HALT_FILE):
        return

    # Skip if either trading session is dead (crash alert handles that)
    if not screen_alive("trading") or not screen_alive("crypto"):
        return

    # Cooldown
    if (time.time() - _last_no_trades) < NO_TRADES_COOLDOWN:
        return

    try:
        super_d  = read_json(SUPER_JSON)
        crypto_d = read_json(CRYPTO_JSON)

        super_trades  = super_d.get("trades", [])
        crypto_trades = crypto_d.get("trades", [])
        total_trades  = len(super_trades) + len(crypto_trades)

        # Fresh start -- don't alert before we have enough history
        if total_trades < NO_TRADES_MIN_HISTORY:
            return

        # Find most recent trade across both bots
        super_latest  = _latest_trade_time(super_trades)
        crypto_latest = _latest_trade_time(crypto_trades)

        candidates = [t for t in [super_latest, crypto_latest] if t is not None]
        if not candidates:
            return

        most_recent = max(candidates)
        silence_hours = (datetime.now() - most_recent).total_seconds() / 3600.0

        print("[NO_TRADES] Letzter Trade: " + most_recent.strftime("%Y-%m-%d %H:%M") +
              " (vor " + str(round(silence_hours, 1)) + "h)")

        if silence_hours >= NO_TRADES_HOURS:
            msg = (
                "⚠️ KEIN TRADE seit " + str(round(silence_hours, 1)) + "h\n"
                "Letzter Trade: " + most_recent.strftime("%Y-%m-%d %H:%M") + "\n"
                "Super Bot: " + str(len(super_trades)) + " Trades insgesamt\n"
                "Crypto Bot: " + str(len(crypto_trades)) + " Trades insgesamt\n"
                "Moegliche Ursachen: Indikatoren zu streng, Markt rangiert, "
                "Sentiment-Feeds ausgefallen?"
            )
            print("[NO_TRADES] " + msg)
            tg(msg)
            _last_no_trades = time.time()

    except Exception as e:
        print("[NO_TRADES ERROR] " + str(e))

# -- System health ------------------------------------------------------------

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



# -- Log monitoring ----------------------------------------------------------

def check_auth_log():
    """
    Read new SSH/auth journal entries via journalctl --cursor-file.
    Alerts: brute-force (>=10 fails from one IP), SSH logins, unexpected sudo.
    """
    global _last_sec_alert, _sec_fail_counts
    import re as _re
    CURSOR = '/tmp/ssh_journal_cursor'
    try:
        import os as _os
        if not _os.path.exists(CURSOR):
            # First run: initialize cursor to NOW so we skip historical entries
            subprocess.run(['journalctl', '-u', 'ssh', '--no-pager',
                            '--cursor-file', CURSOR, '-n', '0'], capture_output=True)
        cmd = ['journalctl', '-u', 'ssh', '--no-pager', '-o', 'short',
               '--cursor-file', CURSOR]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        lines  = result.stdout.splitlines()
        now    = time.time()
        alerts = []
        for line in lines:
            ll = line.lower()
            # Failed auth attempt
            if 'failed' in ll or 'invalid user' in ll or 'connection closed' in ll:
                m = _re.search(r'from ([0-9.]+)', line)
                if m:
                    ip = m.group(1)
                    cnt, first = _sec_fail_counts.get(ip, (0, now))
                    if now - first > 3600:
                        cnt = 0; first = now
                    cnt += 1
                    _sec_fail_counts[ip] = (cnt, first)
                    if cnt == 10:
                        alerts.append(chr(128680) + ' Brute-Force: ' + str(cnt) +
                                      ' SSH-Versuche von ' + ip)
                    elif cnt > 10 and cnt % 20 == 0:
                        alerts.append(chr(9888)+chr(65039) + ' Brute-Force weiter: ' +
                                      str(cnt) + ' Versuche von ' + ip)
            # Successful SSH login -- only alert for non-LAN IPs
            if 'accepted publickey' in ll or 'accepted password' in ll:
                m = _re.search(r'for (\S+) from ([0-9.]+)', line)
                if m:
                    ip2 = m.group(2)
                    is_lan = (ip2.startswith('192.168.') or
                              ip2.startswith('10.') or
                              ip2.startswith('172.') or
                              ip2 == '127.0.0.1')
                    if not is_lan:
                        alerts.append(chr(128680) + ' SSH-Login von FREMDER IP: ' + m.group(1) +
                                      ' von ' + ip2)
        # Also check sudo
        cmd2 = ['journalctl', '_COMM=sudo', '--no-pager', '-o', 'short',
                '--cursor-file', '/tmp/sudo_journal_cursor',
                '--since', '2 minutes ago']
        r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=10)
        for line in r2.stdout.splitlines():
            if 'command' in line.lower() and 'trading2025' not in line and 'root' not in line:
                alerts.append(chr(9888)+chr(65039) + ' Unerwartetes sudo: ' + line[:100])
        if alerts and (now - _last_sec_alert) > SEC_ALERT_COOLDOWN:
            msg = chr(10).join([chr(128737)+chr(65039) + ' SECURITY ALERT'] + alerts)
            print('[SEC] ' + chr(10).join(alerts))
            tg(msg)
            _last_sec_alert = now
    except Exception as e:
        print('[AUTH LOG ERROR] ' + str(e))


def check_suspicious_procs():
    """
    Look for processes from /tmp or /dev/shm (malware/miners).
    Also alerts if an unknown process uses >80% CPU.
    """
    global _last_sec_alert
    try:
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=10)
        alerts = []
        known = {
            'python3', 'python', 'bash', 'screen', 'sshd', 'systemd',
            'ps', 'grep', 'top', 'htop', 'apt', 'dpkg', 'sh', 'sudo',
            'cron', 'rsyslog', 'dbus', 'avahi', 'ntpd', 'syslog',
            'init', 'agetty', 'login', 'su', 'ufw', 'fail2ban',
        }
        for line in result.stdout.splitlines()[1:]:
            parts = line.split(None, 10)
            if len(parts) < 11:
                continue
            user, cpu_s, cmd_full = parts[0], parts[2], parts[10]
            cmd = cmd_full.split()[0].split('/')[-1] if cmd_full.split() else ''
            if cmd_full.startswith('/tmp/') or cmd_full.startswith('/dev/shm/'):
                alerts.append(chr(128680) + ' Verdaechtiger Prozess: ' + cmd_full[:80])
            try:
                if float(cpu_s) > 80 and cmd not in known:
                    alerts.append(chr(9888)+chr(65039) + ' Hohe CPU von unbekanntem Prozess: '
                                  + cmd + ' (' + cpu_s + '%) User=' + user)
            except ValueError:
                pass
        if alerts:
            now = time.time()
            if (now - _last_sec_alert) > SEC_ALERT_COOLDOWN:
                msg = chr(10).join([chr(128737)+chr(65039) + ' SECURITY ALERT'] + alerts)
                print('[SEC] ' + chr(10).join(alerts))
                tg(msg)
                _last_sec_alert = now
    except Exception as e:
        print('[PROC CHECK ERROR] ' + str(e))

# -- Update check -------------------------------------------------------------

def check_updates():
    """
    Once per day: check apt for upgradable packages and notify via Telegram.
    Distinguishes security updates from normal updates.
    """
    global _last_update_alert
    today = date.today()
    if _last_update_alert == today:
        return
    _last_update_alert = today

    try:
        result = subprocess.run(
            ["apt", "list", "--upgradable"],
            capture_output=True, text=True, timeout=30
        )
        # Skip 'Listing... Done' header; keep only lines containing '/'
        pkgs = [l.strip() for l in result.stdout.splitlines()
                if "/" in l and l.strip()]

        if not pkgs:
            print("[UPDATE] System ist aktuell -- keine Updates ausstehend.")
            return

        # Security packages have '-security' in their suite field (after '/')
        sec  = [l for l in pkgs if "-security" in l.split("/")[1].split()[0]]
        norm = [l for l in pkgs if l not in sec]

        icon  = chr(9888) + chr(65039) if sec else chr(128260)
        parts = [
            icon + " System-Updates verfuegbar: " + str(len(pkgs)) + " Pakete",
            "  " + chr(128274) + " Sicherheits-Updates: " + str(len(sec)),
            "  " + chr(128230) + " Normale Updates:     " + str(len(norm)),
            "",
            "Bots kurz pausieren empfohlen:",
            "sudo apt update && sudo apt upgrade",
        ]
        if sec:
            parts.append("")
            parts.append("Sicherheits-Pakete:")
            for p in sec[:8]:
                parts.append("  " + p.split("/")[0])

        msg = chr(10).join(parts)
        print("[UPDATE] " + str(len(pkgs)) + " Updates (" + str(len(sec)) + " Security)")
        tg(msg)

    except Exception as e:
        print("[UPDATE ERROR] " + str(e))

# -- Dashboard reader ---------------------------------------------------------

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

# -- Daily performance report -------------------------------------------------

def daily_report():
    super_d  = read_json(SUPER_JSON)
    crypto_d = read_json(CRYPTO_JSON)
    now_str  = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines    = ["📊 TAGESBERICHT -- " + now_str, ""]

    # -- Super Bot -----------------------------------------------------------
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
        lines.append("⚡ SUPER BOT -- keine Daten (JSON fehlt)")

    lines.append("")

    # -- Crypto Bot ----------------------------------------------------------
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
        lines.append("  Positionen: " + str(len(pos)) + "/8")
        for sym, p in list(pos.items())[:6]:
            pct  = p.get("pnl_pct", 0)
            sign = "+" if pct >= 0 else ""
            spike = " [SPIKE]" if p.get("spike") else ""
            lines.append("    " + sym.ljust(10) + sign + str(pct) + "%" + spike)
        lines.append("  F&G: " + str(fg.get("value", "?")) + " " + fg.get("label", ""))
        lines.append("  (JSON " + str(age) + " min alt)")
    else:
        lines.append("₿ CRYPTO BOT -- keine Daten (JSON fehlt)")

    lines.append("")

    # -- System health -------------------------------------------------------
    cpu, ram, disk_pct, disk_free = system_health()
    lines.append("🖥️  System")
    if cpu is not None:
        lines.append("  CPU: " + str(cpu) + "%  RAM: " + str(ram) + "%" +
                     ("  Disk: " + str(disk_pct) + "% (frei " + str(disk_free) + ")" if disk_pct else ""))
    else:
        lines.append("  (Systemdaten nicht verfuegbar)")

    # -- Screen session status -----------------------------------------------
    lines.append("")
    lines.append("🖥️  Screen Sessions")
    for session, bot in BOTS.items():
        status = "✅ laeuft" if screen_alive(session) else "❌ TOT"
        lines.append("  " + session.ljust(16) + status)

    msg = "\n".join(lines)
    print("[REPORT]\n" + msg)
    tg(msg)

# -- Main loop ----------------------------------------------------------------

def run():
    global _last_daily

    print("=" * 55)
    print("  MONITOR AGENT gestartet")
    print("  Check-Interval: " + str(CHECK_INTERVAL) + "s")
    print("  No-trades alert: >" + str(NO_TRADES_HOURS) + "h Stille")
    print("  Update-Check:    taeglich 08:00")
    print("  Log-Monitoring:  jedes Zyklus (auth.log + procs)")
    print("  Ueberwacht: " + ", ".join(BOTS.keys()))
    print("=" * 55)
    tg("🟢 Monitor Agent gestartet\nUeberwacht: " + ", ".join(b["name"] for b in BOTS.values()))

    cycle = 0
    while True:
        try:
            now   = datetime.now()
            cycle += 1
            print("\n[" + now.strftime("%H:%M:%S") + "] Zyklus " + str(cycle))

            # 1) Watchdog -- restart dead screen sessions
            check_bots()

            # 2) Stale dashboard check
            check_stale()

            # 3) No-trades alert + skip analysis (each has own cooldown)
            check_no_trades()
            check_skip_analysis()

            # 4) System health -- prints every cycle; Telegram only on threshold breach + cooldown
            system_health()

            # 5) Security: auth log + suspicious processes
            check_auth_log()
            if cycle % 5 == 0:   # every 5 min
                check_suspicious_procs()

            # 6) Daily report at 08:00 (fires once per day)
            today = now.date()
            if now.hour == 8 and now.minute == 0 and _last_daily != today:
                _last_daily = today
                print("[REPORT] Sende Tagesbericht...")
                daily_report()
                check_updates()   # einmal taeglich: apt-Updates pruefen

        except KeyboardInterrupt:
            print("[MONITOR] Gestoppt")
            tg("🔴 Monitor Agent gestoppt")
            break
        except Exception as e:
            print("[MONITOR ERROR] " + str(e))

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run()
