#!/usr/bin/env python3
"""
Telegram Router — single long-poll handler for both trading bots.

Both bots previously called getUpdates independently, causing a race condition:
Telegram delivers each update to whichever caller wins the race, so only one
bot ever responds. This router is the only process calling getUpdates; bots
communicate state via JSON files:

  Read  (for status/positions/risk):
    dashboard.json                  — super_bot live state
    crypto/crypto_dashboard.json    — crypto_bot live state
    agents/risk_log.json            — risk agent state

  Write (for stop/pause/start):
    bot_control.json                — super_bot reads {"paused": true/false}
    crypto/crypto_control.json      — crypto_bot reads {"paused": true/false}

Commands:
  /status          — Both bots: balance, P&L, positions, F&G
  /positions       — All open positions (Super + Crypto combined)
  /risk            — Portfolio risk, drawdown, halt status
  /stop            — Pause new trades on BOTH bots
  /start           — Resume new trades on BOTH bots
  /stop_super      — Pause Super Bot only
  /start_super     — Resume Super Bot only
  /stop_crypto     — Pause Crypto Bot only
  /start_crypto    — Resume Crypto Bot only
  /help            — Show command list
"""

import os, sys, json, time, requests
from datetime import datetime

sys.path.insert(0, "/home/trading2025/trading_bot")
try:
    from config import config
except ImportError:
    config = {}

TELEGRAM_TOKEN   = config.get("telegram_bot_token", "")
TELEGRAM_CHAT_ID = str(config.get("telegram_chat_id", ""))

BASE_DIR     = "/home/trading2025/trading_bot"
SUPER_DASH   = os.path.join(BASE_DIR, "dashboard.json")
CRYPTO_DASH  = os.path.join(BASE_DIR, "crypto", "crypto_dashboard.json")
RISK_LOG     = os.path.join(BASE_DIR, "agents", "risk_log.json")
SUPER_CTRL   = os.path.join(BASE_DIR, "bot_control.json")
CRYPTO_CTRL  = os.path.join(BASE_DIR, "crypto", "crypto_control.json")

API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ── Utilities ────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def _load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None

def _write_ctrl(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)
        return True
    except Exception as e:
        log(f"ctrl write error {path}: {e}")
        return False

def _dash_age_min(dash):
    """Minutes since dashboard was last written. None if unreadable."""
    t = (dash or {}).get("time")
    if not t:
        return None
    try:
        dt = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
        return round((datetime.now() - dt).total_seconds() / 60, 1)
    except Exception:
        return None

def send(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    for i in range(0, len(text), 3800):
        chunk = text[i:i + 3800]
        try:
            requests.post(API + "/sendMessage",
                          json={"chat_id": TELEGRAM_CHAT_ID, "text": chunk,
                                "parse_mode": "HTML"},
                          timeout=10)
            if len(text) > 3800:
                time.sleep(0.3)
        except Exception as e:
            log(f"send error: {e}")

# ── Command handlers ─────────────────────────────────────────────────────────

def cmd_status():
    sd = _load(SUPER_DASH)
    cd = _load(CRYPTO_DASH)
    rl = _load(RISK_LOG)

    sc  = _load(SUPER_CTRL)  or {}
    cc  = _load(CRYPTO_CTRL) or {}
    super_paused  = sc.get("paused", False)
    crypto_paused = cc.get("paused", False)

    lines = ["<b>📊 Trading Bot Status</b>", ""]

    for dash, name, emoji, paused in [
        (sd, "Super Bot (ETFs)", "📈", super_paused),
        (cd, "Crypto Bot",       "🪙", crypto_paused),
    ]:
        age = _dash_age_min(dash)
        if not dash:
            lines.append(f"{emoji} <b>{name}</b>: Dashboard nicht lesbar ⚠️")
            continue

        bal    = dash.get("balance", 0)
        pnl    = dash.get("total_pnl", 0)
        n_t    = dash.get("total_trades", 0)
        n_wins = dash.get("wins", n_t)  # crypto has no 'wins' field
        wr_s   = f"{n_wins/n_t*100:.0f}%" if n_t else "—"
        n_pos  = len(dash.get("positions", {}))
        ws     = "WS✓" if dash.get("ws_connected") else "WS✗"
        fg     = dash.get("fear_greed", {})
        fg_s   = f"{fg.get('value','?')} {fg.get('label','?')}" if fg else "?"
        state  = "⏸ PAUSIERT" if paused else ("▶ AKTIV" if dash.get("running", True) else "⏹ GESTOPPT")
        age_s  = f" | Daten {age:.0f}min alt ⚠️" if age and age > 10 else ""

        lines.append(f"{emoji} <b>{name}</b> — {state} | {ws}{age_s}")
        lines.append(f"   Bal: <b>${bal:,.0f}</b>  P&amp;L: ${pnl:+,.0f}")
        lines.append(f"   Trades: {n_t} | WR: {wr_s} | Pos: {n_pos} | F&amp;G: {fg_s}")

    # Combined risk line
    if rl:
        peak    = rl.get("peak_value", 0)
        halted  = rl.get("halted", False)
        s_bal   = (sd or {}).get("balance", 0)
        c_bal   = (cd or {}).get("balance", 0)
        comb    = s_bal + c_bal
        dd_pct  = (comb - peak) / peak * 100 if peak else 0
        status  = "🔴 HALTED" if halted else "🟢 OK"
        lines.append("")
        lines.append(f"⚠️ Risiko: {status}  |  Drawdown: {dd_pct:+.1f}%  |  Peak: ${peak:,.0f}")

    send("\n".join(lines))


def cmd_positions():
    sd = _load(SUPER_DASH)
    cd = _load(CRYPTO_DASH)
    lines = ["<b>📋 Offene Positionen</b>", ""]
    any_pos = False

    for dash, name, emoji in [
        (sd, "Super Bot (ETFs)", "📈"),
        (cd, "Crypto Bot",       "🪙"),
    ]:
        positions = (dash or {}).get("positions", {})
        if not positions:
            lines.append(f"{emoji} <b>{name}</b>: keine offenen Positionen")
            continue
        any_pos = True
        lines.append(f"{emoji} <b>{name}</b> ({len(positions)} offen):")
        for sym, p in positions.items():
            entry   = p.get("entry", 0)
            price   = p.get("current_price", entry)
            pnl_pct = p.get("pnl_pct", ((price - entry) / entry * 100) if entry else 0)
            pnl_usd = p.get("pnl_usd", (price - entry) * p.get("shares", 0))
            sector  = p.get("sector", "")
            spike   = " ⚡SPIKE" if p.get("spike") else ""
            sect_s  = f" [{sector}]" if sector else ""
            lines.append(
                f"   <b>{sym}</b>{sect_s}{spike}  "
                f"${entry:.2f}→${price:.2f}  "
                f"{pnl_pct:+.1f}% (${pnl_usd:+.0f})"
            )

    if not any_pos:
        lines.append("📭 Beide Bots haben keine offenen Positionen.")

    send("\n".join(lines))


def cmd_risk():
    rl  = _load(RISK_LOG)
    sd  = _load(SUPER_DASH)
    cd  = _load(CRYPTO_DASH)
    sc  = _load(SUPER_CTRL)  or {}
    cc  = _load(CRYPTO_CTRL) or {}

    s_bal  = (sd or {}).get("balance", 0)
    c_bal  = (cd or {}).get("balance", 0)
    comb   = s_bal + c_bal
    lines  = ["<b>⚠️ Risiko-Status</b>", ""]

    if rl:
        peak      = rl.get("peak_value", comb)
        day_start = rl.get("day_start_value", comb)
        halted    = rl.get("halted", False)
        dd_pct    = (comb - peak)      / peak      * 100 if peak      else 0
        day_pct   = (comb - day_start) / day_start * 100 if day_start else 0
        status    = "🔴 HALTED" if halted else "🟢 OK"
        lines.append(f"Status      : {status}")
        lines.append(f"Tages-P&amp;L   : {day_pct:+.2f}%  (Limit: −5%)")
        lines.append(f"Drawdown    : {dd_pct:+.2f}%  (Limit: −15%)")
        lines.append(f"Peak-Equity : ${peak:,.2f}")
        lines.append(f"Gesamt-Bal. : ${comb:,.2f}")
        events = rl.get("events", [])
        if events:
            ev = events[-1]
            lines.append(f"Letztes Ereignis: {ev.get('type','?')} @ {str(ev.get('time',''))[:16]}")
    else:
        lines.append(f"Gesamt-Bal. : ${comb:,.2f}")
        lines.append("(risk_log.json nicht lesbar)")

    lines.append("")
    super_paused  = sc.get("paused", False)
    crypto_paused = cc.get("paused", False)
    lines.append(f"Super Bot : {'⏸ PAUSIERT' if super_paused else '▶ aktiv'}")
    lines.append(f"Crypto Bot: {'⏸ PAUSIERT' if crypto_paused else '▶ aktiv'}")

    send("\n".join(lines))


def _set_paused(super_val=None, crypto_val=None):
    """
    Write paused state to control files.
    super_val / crypto_val: True = pause, False = resume, None = don't touch.
    Returns list of (bot_name, new_state, success).
    """
    results = []
    if super_val is not None:
        existing = _load(SUPER_CTRL) or {}
        existing["paused"] = super_val
        ok = _write_ctrl(SUPER_CTRL, existing)
        results.append(("Super Bot", super_val, ok))
    if crypto_val is not None:
        existing = _load(CRYPTO_CTRL) or {}
        existing["paused"] = crypto_val
        ok = _write_ctrl(CRYPTO_CTRL, existing)
        results.append(("Crypto Bot", crypto_val, ok))
    return results


def cmd_stop(super_only=False, crypto_only=False):
    sv = None if crypto_only else True
    cv = None if super_only  else True
    results = _set_paused(sv, cv)
    lines = []
    for bot, _, ok in results:
        icon = "✅" if ok else "❌"
        lines.append(f"{icon} <b>{bot}</b>: Trading pausiert — offene Positionen laufen weiter")
    resume_cmd = "/start_super" if super_only else "/start_crypto" if crypto_only else "/start"
    lines.append(f"Zum Fortsetzen: <code>{resume_cmd}</code>")
    send("\n".join(lines))


def cmd_start(super_only=False, crypto_only=False):
    sv = None if crypto_only else False
    cv = None if super_only  else False
    results = _set_paused(sv, cv)
    lines = []
    for bot, _, ok in results:
        icon = "✅" if ok else "❌"
        lines.append(f"{icon} <b>{bot}</b>: Trading fortgesetzt ▶")
    send("\n".join(lines))


def cmd_help():
    send(
        "<b>🤖 Trading Bot — Befehle</b>\n\n"
        "<b>Status &amp; Info</b>\n"
        "/status         — Beide Bots: Balance, P&amp;L, Positionen, F&amp;G\n"
        "/positions      — Alle offenen Positionen (Super + Crypto)\n"
        "/risk           — Portfolio-Risiko, Drawdown, Halt-Status\n\n"
        "<b>Steuerung (beide Bots)</b>\n"
        "/stop           — Neue Trades pausieren (Stops laufen weiter)\n"
        "/start          — Trading fortsetzen\n\n"
        "<b>Einzelsteuerung</b>\n"
        "/stop_super     — Nur Super Bot pausieren\n"
        "/start_super    — Nur Super Bot fortsetzen\n"
        "/stop_crypto    — Nur Crypto Bot pausieren\n"
        "/start_crypto   — Nur Crypto Bot fortsetzen\n\n"
        "/help           — Diese Hilfe\n\n"
        "<i>Hinweis: /stop pausiert nur neue Eintritte. "
        "Stop-Loss &amp; Take-Profit laufen immer weiter.</i>"
    )


# ── Command dispatch ─────────────────────────────────────────────────────────

DISPATCH = {
    "/status":       cmd_status,
    "/positions":    cmd_positions,
    "/risk":         cmd_risk,
    "/stop":         cmd_stop,
    "/start":        cmd_start,
    "/stop_super":   lambda: cmd_stop(super_only=True),
    "/start_super":  lambda: cmd_start(super_only=True),
    "/stop_crypto":  lambda: cmd_stop(crypto_only=True),
    "/start_crypto": lambda: cmd_start(crypto_only=True),
    "/help":         cmd_help,
}

# ── Polling loop ─────────────────────────────────────────────────────────────

def poll_loop():
    offset = 0
    log("Long-polling gestartet (einziger getUpdates-Aufrufer)")
    while True:
        try:
            r = requests.get(
                API + "/getUpdates",
                params={"offset": offset, "timeout": 30,
                        "allowed_updates": ["message"]},
                timeout=35,
            )
            if r.status_code != 200:
                log(f"getUpdates HTTP {r.status_code} — retry in 5s")
                time.sleep(5)
                continue

            for upd in r.json().get("result", []):
                offset = upd["update_id"] + 1
                msg    = upd.get("message", {})
                cid    = str(msg.get("chat", {}).get("id", ""))
                if cid != TELEGRAM_CHAT_ID:
                    continue   # silently drop unauthorised senders

                # Take only the first word (handles "/status@botname" form)
                raw  = msg.get("text", "").strip()
                word = raw.split()[0].split("@")[0].lower() if raw else ""

                handler = DISPATCH.get(word)
                if handler:
                    log(f"CMD: {word}")
                    try:
                        handler()
                    except Exception as e:
                        log(f"CMD error [{word}]: {e}")
                        send(f"❌ Fehler bei {word}: {e}")
                # Unknown commands silently ignored

        except requests.exceptions.ReadTimeout:
            pass   # normal — long-poll expired, no updates; loop immediately
        except Exception as e:
            log(f"poll error: {e}")
            time.sleep(5)


def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("FEHLER: telegram_bot_token oder telegram_chat_id fehlt in config.py")
        return

    log("=" * 55)
    log("Telegram Router gestartet")
    log(f"Chat-ID  : {TELEGRAM_CHAT_ID}")
    log(f"Befehle  : {', '.join(DISPATCH.keys())}")
    log("=" * 55)

    send("🤖 <b>Telegram Router gestartet</b>\n/help für Befehlsliste")
    poll_loop()


if __name__ == "__main__":
    main()
