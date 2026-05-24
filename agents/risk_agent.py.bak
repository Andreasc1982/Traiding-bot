#!/usr/bin/env python3
"""
Risk Agent — monitors combined portfolio risk across both bots every 30 seconds.

Thresholds:
  • Combined daily loss   > 5%   → halt both bots
  • Combined drawdown     > 15%  → halt both bots (from all-time peak)

Halt mechanism:
  1. Writes agents/risk_halt.json        (monitor_agent respects this, skips restart)
  2. Writes bot_control.json {"command":"stop"}  (super_bot graceful exit)
  3. screen -S crypto -X quit            (crypto_bot hard stop)
  4. screen -S trading -X quit after 15s (super_bot hard kill if still alive)

Resume:
  Deletes risk_halt.json at RESUME_TIME next day → monitor_agent restarts both bots.
  Daily P&L counter resets automatically at midnight.

State is persisted in agents/risk_log.json (survives restarts, tracks all events).

Launch:
  screen -dmS risk bash -c '
    cd /home/trading2025/trading_bot/agents &&
    source /home/trading2025/trading_bot_env/bin/activate &&
    PYTHONUNBUFFERED=1 python3 -u risk_agent.py > /tmp/risk.log 2>&1'
"""

import os, sys, json, time, subprocess, requests
from datetime import datetime, date, timedelta

sys.path.insert(0, "/home/trading2025/trading_bot")
try:
    from config import config
except ImportError:
    config = {}

# ── Config ─────────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN   = config.get("telegram_bot_token", "")
TELEGRAM_CHAT_ID = config.get("telegram_chat_id", "")

BASE_DIR     = "/home/trading2025/trading_bot"
AGENTS_DIR   = os.path.join(BASE_DIR, "agents")
SUPER_JSON   = os.path.join(BASE_DIR, "dashboard.json")
CRYPTO_JSON  = os.path.join(BASE_DIR, "crypto", "crypto_dashboard.json")
CONTROL_FILE = os.path.join(BASE_DIR, "bot_control.json")
HALT_FILE    = os.path.join(AGENTS_DIR, "risk_halt.json")
LOG_FILE     = os.path.join(AGENTS_DIR, "risk_log.json")

CHECK_INTERVAL   = 30       # seconds between risk checks
DAILY_LOSS_LIMIT = -5.0     # % — halt if combined daily loss hits this
DRAWDOWN_LIMIT   = -15.0    # % — halt if combined drawdown from peak hits this
RESUME_TIME      = "09:30"  # local server time — resume trading next day
STALE_MINUTES    = 10       # warn if dashboard JSON not updated in this many minutes

# ── Telegram ───────────────────────────────────────────────────────────────────

def tg(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TG] " + msg)
        return
    try:
        requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=10,
        )
    except Exception as e:
        print("[TG ERROR] " + str(e))

# ── State persistence ──────────────────────────────────────────────────────────

def _default_state():
    return {
        "peak_value":      None,   # highest combined portfolio value ever seen
        "day_start_value": None,   # combined value at start of current day
        "day_start_date":  None,   # ISO date string "YYYY-MM-DD"
        "halted":          False,
        "resume_at":       None,   # ISO datetime "YYYY-MM-DD HH:MM" or None
        "events":          [],     # list of risk event records (capped at 500)
    }

def load_state():
    default = _default_state()
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE) as f:
                data = json.load(f)
            for k, v in default.items():
                data.setdefault(k, v)
            return data
    except Exception as e:
        print("[STATE] Load error: " + str(e))
    return default

def save_state(state):
    try:
        state["events"] = state["events"][-500:]
        with open(LOG_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print("[STATE] Save error: " + str(e))

def log_event(state, event_type, **kwargs):
    event = {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "type": event_type, **kwargs}
    state["events"].append(event)
    print("[EVENT] " + event_type + ": " + str(kwargs))
    return event

# ── Portfolio reader ───────────────────────────────────────────────────────────

def read_dashboard(path):
    """
    Returns (total_value, age_minutes) or (None, None) on failure.
    total_value = cash balance + market value of all open positions.
    """
    try:
        if not os.path.exists(path):
            return None, None
        age_min = (time.time() - os.path.getmtime(path)) / 60
        with open(path) as f:
            d = json.load(f)
        cash = float(d.get("balance", 0))
        pos_value = sum(
            float(p.get("shares", 0)) * float(p.get("current_price", p.get("entry", 0)))
            for p in d.get("positions", {}).values()
        )
        return cash + pos_value, round(age_min, 1)
    except Exception as e:
        print("[READ] " + path + ": " + str(e))
        return None, None

def read_combined():
    """
    Returns (combined, super_val, crypto_val, stale_warnings).
    combined is None if either dashboard is unreadable.
    """
    sv, sa = read_dashboard(SUPER_JSON)
    cv, ca = read_dashboard(CRYPTO_JSON)

    stale = []
    if sa is not None and sa > STALE_MINUTES:
        stale.append("SuperBot(" + str(sa) + "m)")
    if ca is not None and ca > STALE_MINUTES:
        stale.append("CryptoBot(" + str(ca) + "m)")

    if sv is None or cv is None:
        missing = (["SuperBot"] if sv is None else []) + \
                  (["CryptoBot"] if cv is None else [])
        print("[READ] No data from: " + ", ".join(missing))
        return None, sv, cv, stale

    return sv + cv, sv, cv, stale

# ── Halt / resume ──────────────────────────────────────────────────────────────

def _write_halt_file(reason, resume_at_str):
    with open(HALT_FILE, "w") as f:
        json.dump({
            "halted":    True,
            "reason":    reason,
            "halted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "resume_at": resume_at_str,
        }, f, indent=2)

def _remove_halt_file():
    try:
        if os.path.exists(HALT_FILE):
            os.remove(HALT_FILE)
    except Exception as e:
        print("[HALT] Remove error: " + str(e))

def halt_file_exists():
    return os.path.exists(HALT_FILE)

def _stop_super_bot():
    """Write stop command, then hard-kill after 15s if session still alive."""
    try:
        with open(CONTROL_FILE, "w") as f:
            json.dump({"command": "stop"}, f)
        print("[HALT] Wrote stop command → bot_control.json")
    except Exception as e:
        print("[HALT] Control file error: " + str(e))
    # Grace period — give super_bot time to exit cleanly
    time.sleep(15)
    r = subprocess.run(["screen", "-ls"], capture_output=True, text=True)
    if ".trading\t" in r.stdout:
        subprocess.run(["screen", "-S", "trading", "-X", "quit"])
        print("[HALT] Hard-killed screen:trading (still alive after 15s)")

def _stop_crypto_bot():
    """Hard-kill crypto screen session immediately."""
    subprocess.run(["screen", "-S", "crypto", "-X", "quit"])
    print("[HALT] Killed screen:crypto")

def halt_bots(state, reason, daily_pct, drawdown_pct, combined):
    """Full halt sequence: files → stop bots → Telegram → log."""
    now      = datetime.now()
    tomorrow = (now + timedelta(days=1)).date()
    resume_dt  = datetime.strptime(
        str(tomorrow) + " " + RESUME_TIME, "%Y-%m-%d %H:%M"
    )
    resume_str = resume_dt.strftime("%Y-%m-%d %H:%M")
    peak       = state.get("peak_value") or combined

    print("\n" + "!" * 55)
    print("  RISK HALT — " + reason)
    print("  Daily P&L : " + "{:+.2f}".format(daily_pct) + "%  (limit " + str(DAILY_LOSS_LIMIT) + "%)")
    print("  Drawdown  : " + "{:+.2f}".format(drawdown_pct) + "%  (limit " + str(DRAWDOWN_LIMIT) + "%)")
    print("  Portfolio : $" + "{:,.2f}".format(combined))
    print("  Resume at : " + resume_str)
    print("!" * 55 + "\n")

    # 1. Write halt file first so monitor_agent skips restart during the stop window
    _write_halt_file(reason, resume_str)

    # 2. Stop both bots (crypto fast, super_bot graceful then hard)
    _stop_crypto_bot()
    _stop_super_bot()

    # 3. Update state and persist
    state["halted"]    = True
    state["resume_at"] = resume_str
    log_event(state, "HALT",
              reason=reason,
              daily_pct=round(daily_pct, 2),
              drawdown_pct=round(drawdown_pct, 2),
              portfolio_value=round(combined, 2),
              peak_value=round(peak, 2),
              resume_at=resume_str)
    save_state(state)

    # 4. Telegram alert
    tg(
        "\U0001f6d1 RISK HALT — " + reason + "\n"
        "Portfolio : $" + "{:,.2f}".format(combined) + "\n"
        "Daily P&L : " + "{:+.2f}".format(daily_pct) + "%  (limit " + str(DAILY_LOSS_LIMIT) + "%)\n"
        "Drawdown  : " + "{:+.2f}".format(drawdown_pct) + "%  (limit " + str(DRAWDOWN_LIMIT) + "%)\n"
        "Peak was  : $" + "{:,.2f}".format(peak) + "\n"
        "Both bots stopped.\n"
        "Resuming  : " + resume_str
    )

def resume_bots(state, combined):
    """Remove halt file, reset day counter, alert. Monitor restarts bots on next cycle."""
    now_str = datetime.now().strftime("%H:%M")
    today   = date.today().isoformat()

    print("\n" + "=" * 55)
    print("  RISK RESUME — " + now_str)
    print("  Portfolio : $" + "{:,.2f}".format(combined))
    print("=" * 55 + "\n")

    _remove_halt_file()

    state["halted"]          = False
    state["resume_at"]       = None
    state["day_start_value"] = combined
    state["day_start_date"]  = today
    log_event(state, "RESUME",
              portfolio_value=round(combined, 2),
              new_day_start=round(combined, 2))
    save_state(state)

    tg(
        "✅ RISK RESUME — " + now_str + "\n"
        "Trading resumed. Monitor will restart both bots.\n"
        "Portfolio : $" + "{:,.2f}".format(combined) + "\n"
        "Daily loss counter reset."
    )

# ── Main loop ──────────────────────────────────────────────────────────────────

def run():
    state = load_state()

    # Sync state if halt file exists but state doesn't reflect it (e.g. manual halt)
    if halt_file_exists() and not state["halted"]:
        print("[INIT] Halt file found — syncing state to halted=True")
        state["halted"] = True

    print("=" * 55)
    print("  RISK AGENT gestartet")
    print("  Daily loss limit : " + str(DAILY_LOSS_LIMIT) + "%")
    print("  Drawdown limit   : " + str(DRAWDOWN_LIMIT) + "%")
    print("  Check interval   : " + str(CHECK_INTERVAL) + "s")
    print("  Resume time      : " + RESUME_TIME + " (next day)")
    print("  Log file         : " + LOG_FILE)
    print("=" * 55)

    log_event(state, "START",
              daily_loss_limit=DAILY_LOSS_LIMIT,
              drawdown_limit=DRAWDOWN_LIMIT)
    save_state(state)
    tg("\U0001f7e2 Risk Agent gestartet\n"
       "Limits: daily=" + str(DAILY_LOSS_LIMIT) + "% / drawdown=" + str(DRAWDOWN_LIMIT) + "%")

    cycle          = 0
    last_stale_tg  = 0.0    # timestamp of last stale-data Telegram

    while True:
        try:
            now   = datetime.now()
            today = date.today().isoformat()
            cycle += 1

            # ── Read portfolio ─────────────────────────────────────────────────
            combined, sv, cv, stale = read_combined()

            if combined is None:
                print("[" + now.strftime("%H:%M:%S") + "] No data — skipping cycle")
                time.sleep(CHECK_INTERVAL)
                continue

            # ── Initialise peak on very first successful read ───────────────
            if state["peak_value"] is None:
                state["peak_value"] = combined
                print("[INIT] Peak initialised to $" + "{:,.2f}".format(combined))

            # ── Reset daily counter at midnight / new day ──────────────────
            if state["day_start_date"] != today or state["day_start_value"] is None:
                state["day_start_date"]  = today
                state["day_start_value"] = combined
                log_event(state, "DAY_START",
                          date=today, value=round(combined, 2))
                save_state(state)
                print("[DAY] New trading day — start $" + "{:,.2f}".format(combined))

            # ── Ratchet peak upward ────────────────────────────────────────
            if combined > state["peak_value"]:
                state["peak_value"] = combined

            # ── Risk metrics ────────────────────────────────────────────────
            day_start    = state["day_start_value"]
            peak         = state["peak_value"]
            daily_pct    = (combined - day_start) / day_start * 100
            drawdown_pct = (combined - peak)       / peak       * 100

            # ── Status line ─────────────────────────────────────────────────
            halted_tag = " [HALTED]" if state["halted"] else ""
            stale_tag  = " STALE:" + ",".join(stale) if stale else ""
            sv_str = "$" + "{:,.2f}".format(sv) if sv is not None else "N/A"
            cv_str = "$" + "{:,.2f}".format(cv) if cv is not None else "N/A"
            print(
                "[" + now.strftime("%H:%M:%S") + "] "
                "Total=$" + "{:,.2f}".format(combined) + " "
                "(S=" + sv_str + " C=" + cv_str + ") "
                "Day=" + "{:+.2f}".format(daily_pct) + "% "
                "DD=" + "{:+.2f}".format(drawdown_pct) + "% "
                "Peak=$" + "{:,.2f}".format(peak) +
                halted_tag + stale_tag
            )

            # ── Stale data Telegram (max once per hour) ────────────────────
            if stale and (time.time() - last_stale_tg) > 3600:
                tg("⚠️ RISK AGENT: Stale data from " + ", ".join(stale))
                last_stale_tg = time.time()

            # ── Halted: check resume time ──────────────────────────────────
            if state["halted"]:
                resume_at = state.get("resume_at")
                if resume_at:
                    resume_dt = datetime.strptime(resume_at, "%Y-%m-%d %H:%M")
                    if now >= resume_dt:
                        resume_bots(state, combined)
                    elif cycle % 20 == 0:
                        mins_left = int((resume_dt - now).total_seconds() / 60)
                        print("[HALT] Resuming in " + str(mins_left) + " min at " + resume_at)
                time.sleep(CHECK_INTERVAL)
                continue

            # ── Risk gate checks ───────────────────────────────────────────
            halt_reason = None

            if daily_pct <= DAILY_LOSS_LIMIT:
                halt_reason = (
                    "DAILY_LOSS " + "{:+.2f}".format(daily_pct) + "% "
                    "(limit " + str(DAILY_LOSS_LIMIT) + "%)"
                )
            elif drawdown_pct <= DRAWDOWN_LIMIT:
                halt_reason = (
                    "DRAWDOWN " + "{:+.2f}".format(drawdown_pct) + "% from peak "
                    "$" + "{:,.2f}".format(peak) + " (limit " + str(DRAWDOWN_LIMIT) + "%)"
                )

            if halt_reason:
                halt_bots(state, halt_reason, daily_pct, drawdown_pct, combined)

            # ── Periodic save ──────────────────────────────────────────────
            if cycle % 20 == 0:   # every ~10 minutes
                save_state(state)

        except KeyboardInterrupt:
            print("[RISK] Gestoppt")
            tg("\U0001f534 Risk Agent gestoppt")
            save_state(state)
            break
        except Exception as e:
            print("[RISK ERROR] " + str(e))

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run()
