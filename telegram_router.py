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
    agents/optimize_results.json    — optimization suggestions (/apply)

  Write (for stop/pause/start):
    bot_control.json                — super_bot reads {"paused": true/false}
    crypto/crypto_control.json      — crypto_bot reads {"paused": true/false}

  Modify (for /apply + /confirm):
    super_bot.py                    — parameter values updated in-place via regex
    crypto/crypto_bot.py            — same

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
  /apply           — Show pending optimisation suggestions from optimize_results.json
  /confirm         — Apply the shown suggestions and restart both bots
  /help            — Show command list
"""

import os, sys, re, json, time, subprocess, requests
from datetime import datetime

sys.path.insert(0, "/home/trading2025/trading_bot")
try:
    from config import config
except ImportError:
    config = {}

TELEGRAM_TOKEN   = config.get("telegram_bot_token", "")
TELEGRAM_CHAT_ID = str(config.get("telegram_chat_id", ""))

BASE_DIR         = "/home/trading2025/trading_bot"
SUPER_DASH       = os.path.join(BASE_DIR, "dashboard.json")
CRYPTO_DASH      = os.path.join(BASE_DIR, "crypto", "crypto_dashboard.json")
RISK_LOG         = os.path.join(BASE_DIR, "agents", "risk_log.json")
SUPER_CTRL       = os.path.join(BASE_DIR, "bot_control.json")
CRYPTO_CTRL      = os.path.join(BASE_DIR, "crypto", "crypto_control.json")
OPTIMIZE_RESULTS = os.path.join(BASE_DIR, "agents", "optimize_results.json")
SUPER_BOT_PATH   = os.path.join(BASE_DIR, "super_bot.py")
CRYPTO_BOT_PATH  = os.path.join(BASE_DIR, "crypto", "crypto_bot.py")

API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Pending /apply state — filled by cmd_apply(), consumed by cmd_confirm()
# {"ts": float, "super": {param: new_val}, "crypto": {param: new_val}}
_pending_apply = {}
APPLY_TIMEOUT  = 300   # seconds before /apply expires


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


# ── /apply + /confirm — optimisation parameter update ────────────────────────

# Parameter labels for display
_PARAM_LABELS = {
    "rsi_threshold": "RSI-Schwelle",
    "stop_loss":     "Stop-Loss",
    "take_profit":   "Take-Profit",
    "st_mult":       "ST-Multiplikator",
}

def _fmt_val(key, val):
    """Format a parameter value for display."""
    if key == "rsi_threshold":
        return str(int(val))
    if key == "st_mult":
        return f"{val:.1f}×"
    return f"{val:.1f}%"   # stop_loss, take_profit


def _read_current_params(bot_path):
    """
    Extract current trading parameters from a bot source file using regex.
    Returns dict with keys: stop_loss, take_profit, rsi_threshold, st_mult.
    Missing keys = regex didn't match (file may have changed structure).
    """
    try:
        with open(bot_path) as f:
            content = f.read()

        params = {}

        for key, pattern in [
            ("stop_loss",   r"self\.stop_loss\s*=\s*([\d.]+)"),
            ("take_profit", r"self\.take_profit\s*=\s*([\d.]+)"),
        ]:
            m = re.search(pattern, content)
            if m:
                params[key] = float(m.group(1))

        # RSI threshold — in trade() method: rsi_ok = ind["rsi"] < XX
        m = re.search(r'rsi_ok\s*=\s*ind\["rsi"\]\s*<\s*([\d]+)', content)
        if m:
            params["rsi_threshold"] = int(m.group(1))

        # Supertrend multiplier — b_ub = hl2 + X.X * st_atr[i]
        m = re.search(r'b_ub\s*=\s*hl2\s*\+\s*([\d.]+)\s*\*\s*st_atr', content)
        if m:
            params["st_mult"] = float(m.group(1))

        return params
    except Exception as e:
        log(f"read_current_params error {bot_path}: {e}")
        return {}


def _apply_params_to_file(bot_path, new_params):
    """
    Apply a dict of {param: new_value} to a bot source file using regex
    substitution.  Returns (ok: bool, detail: str).
    """
    try:
        with open(bot_path) as f:
            content = f.read()
        original = content

        if "stop_loss" in new_params:
            val = f"{new_params['stop_loss']:.1f}"
            content = re.sub(
                r"(self\.stop_loss\s*=\s*)[\d.]+",
                r"\g<1>" + val, content)

        if "take_profit" in new_params:
            val = f"{new_params['take_profit']:.1f}"
            content = re.sub(
                r"(self\.take_profit\s*=\s*)[\d.]+",
                r"\g<1>" + val, content)

        if "rsi_threshold" in new_params:
            val = str(int(new_params["rsi_threshold"]))
            content = re.sub(
                r'(rsi_ok\s*=\s*ind\["rsi"\]\s*<\s*)[\d]+',
                r"\g<1>" + val, content)

        if "st_mult" in new_params:
            val = f"{new_params['st_mult']:.1f}"
            # Both b_ub and b_lb lines carry the multiplier
            content = re.sub(
                r"(b_ub\s*=\s*hl2\s*\+\s*)[\d.]+(\s*\*\s*st_atr)",
                r"\g<1>" + val + r"\g<2>", content)
            content = re.sub(
                r"(b_lb\s*=\s*hl2\s*-\s*)[\d.]+(\s*\*\s*st_atr)",
                r"\g<1>" + val + r"\g<2>", content)

        if content == original:
            return True, "no_change"

        with open(bot_path, "w") as f:
            f.write(content)
        return True, "updated"

    except Exception as e:
        return False, str(e)


def _restart_bot(session, workdir, script):
    """Kill a screen session and relaunch it."""
    subprocess.run(
        f"screen -S {session} -X quit 2>/dev/null || true",
        shell=True)
    time.sleep(2)
    subprocess.run(
        f"screen -dmS {session} bash -c '"
        f"cd {workdir} && "
        f"source /home/trading2025/trading_bot_env/bin/activate && "
        f"PYTHONUNBUFFERED=1 python3 -u {script} > /tmp/{session}.log 2>&1'",
        shell=True)


def cmd_apply():
    global _pending_apply

    opt = _load(OPTIMIZE_RESULTS)
    if not opt:
        send("❌ optimize_results.json nicht gefunden — Optimizer noch nicht gelaufen.\n"
             "<i>Manuell starten: screen -r optimize</i>")
        return

    generated   = opt.get("generated_at", "?")[:16].replace("T", " ")
    gs          = opt.get("grid_search", {})
    super_best  = gs.get("super",  {}).get("best_params", {})
    crypto_best = gs.get("crypto", {}).get("best_params", {})
    super_imp   = gs.get("super",  {}).get("improvement", {})
    crypto_imp  = gs.get("crypto", {}).get("improvement", {})

    if not super_best and not crypto_best:
        send("❌ Keine Grid-Search-Ergebnisse in optimize_results.json")
        return

    # Read live parameter values from the actual bot files
    super_cur  = _read_current_params(SUPER_BOT_PATH)
    crypto_cur = _read_current_params(CRYPTO_BOT_PATH)

    # Compute diffs — only params that have meaningfully changed
    RELEVANT = {"rsi_threshold", "stop_loss", "take_profit", "st_mult"}
    super_changes  = {}
    crypto_changes = {}

    for key in RELEVANT:
        if key in super_best and key in super_cur:
            if abs(float(super_best[key]) - super_cur[key]) > 0.01:
                super_changes[key] = (super_cur[key], float(super_best[key]))
        if key in crypto_best and key in crypto_cur:
            if abs(float(crypto_best[key]) - crypto_cur[key]) > 0.01:
                crypto_changes[key] = (crypto_cur[key], float(crypto_best[key]))

    if not super_changes and not crypto_changes:
        send(
            f"✅ <b>Keine Änderungen erforderlich</b>\n"
            f"Beide Bots haben bereits die optimalen Parameter.\n"
            f"<i>Optimierung vom {generated}</i>"
        )
        return

    # Check for open positions — warn if restart would lose tracking
    sd = _load(SUPER_DASH)
    cd = _load(CRYPTO_DASH)
    open_super  = len((sd or {}).get("positions", {}))
    open_crypto = len((cd or {}).get("positions", {}))
    pos_warning = ""
    if open_super + open_crypto > 0:
        parts = []
        if open_super:  parts.append(f"{open_super} Super")
        if open_crypto: parts.append(f"{open_crypto} Crypto")
        pos_warning = (
            f"\n⚠️ <b>Achtung:</b> {' + '.join(parts)} offene Position(en) vorhanden. "
            f"Nach dem Neustart werden diese nicht mehr verfolgt "
            f"(Demo: kein Schaden; Kraken-Live: Positionen bleiben offen auf der Börse)."
        )

    lines = [f"<b>🔧 Optimierungs-Vorschläge</b>  <i>(vom {generated})</i>", ""]

    if super_changes:
        lines.append("📈 <b>Super Bot (ETFs):</b>")
        for key, (old, new) in super_changes.items():
            label = _PARAM_LABELS.get(key, key)
            lines.append(f"   {label}: {_fmt_val(key, old)} → <b>{_fmt_val(key, new)}</b>")
        if super_imp:
            lines.append(
                f"   <i>Erwartet: Return {super_imp.get('return_delta',0):+.1f}% · "
                f"WR {super_imp.get('wr_delta',0):+.1f}% · "
                f"DD {super_imp.get('dd_delta',0):+.1f}%</i>"
            )
    else:
        lines.append("📈 <b>Super Bot:</b> bereits optimal ✓")

    lines.append("")

    if crypto_changes:
        lines.append("🪙 <b>Crypto Bot:</b>")
        for key, (old, new) in crypto_changes.items():
            label = _PARAM_LABELS.get(key, key)
            lines.append(f"   {label}: {_fmt_val(key, old)} → <b>{_fmt_val(key, new)}</b>")
        if crypto_imp:
            lines.append(
                f"   <i>Erwartet: Return {crypto_imp.get('return_delta',0):+.1f}% · "
                f"WR {crypto_imp.get('wr_delta',0):+.1f}% · "
                f"DD {crypto_imp.get('dd_delta',0):+.1f}%</i>"
            )
    else:
        lines.append("🪙 <b>Crypto Bot:</b> bereits optimal ✓")

    if pos_warning:
        lines.append(pos_warning)

    lines.append("")
    lines.append("✅ Anwenden &amp; Bots neu starten: /confirm")
    lines.append("❌ Abbrechen: ignorieren  <i>(Timeout: 5 Min)</i>")

    # Store pending changes
    _pending_apply = {
        "ts":     time.time(),
        "super":  {k: v[1] for k, v in super_changes.items()},
        "crypto": {k: v[1] for k, v in crypto_changes.items()},
    }

    log("APPLY pending: super=" + str(super_changes) + " crypto=" + str(crypto_changes))
    send("\n".join(lines))


def cmd_confirm():
    global _pending_apply

    if not _pending_apply:
        send("❌ Kein ausstehender /apply — zuerst /apply senden")
        return

    if time.time() - _pending_apply.get("ts", 0) > APPLY_TIMEOUT:
        _pending_apply = {}
        send("❌ /apply-Anfrage abgelaufen (Timeout 5 Min) — erneut /apply senden")
        return

    super_params  = _pending_apply.get("super",  {})
    crypto_params = _pending_apply.get("crypto", {})
    _pending_apply = {}   # consume immediately — no double-confirm

    lines = ["<b>⚙️ Wende Parameter an...</b>", ""]
    errors = []

    # ── Apply to super_bot.py ────────────────────────────────────────────
    if super_params:
        ok, detail = _apply_params_to_file(SUPER_BOT_PATH, super_params)
        if ok:
            lines.append("✅ super_bot.py aktualisiert")
            log(f"Applied to super_bot.py: {super_params}")
        else:
            lines.append(f"❌ super_bot.py Fehler: {detail}")
            errors.append("super")
            log(f"Failed to apply super_bot.py: {detail}")

    # ── Apply to crypto_bot.py ───────────────────────────────────────────
    if crypto_params:
        ok, detail = _apply_params_to_file(CRYPTO_BOT_PATH, crypto_params)
        if ok:
            lines.append("✅ crypto_bot.py aktualisiert")
            log(f"Applied to crypto_bot.py: {crypto_params}")
        else:
            lines.append(f"❌ crypto_bot.py Fehler: {detail}")
            errors.append("crypto")
            log(f"Failed to apply crypto_bot.py: {detail}")

    if errors:
        lines.append("")
        lines.append("⚠️ Fehler beim Schreiben — kein Neustart durchgeführt.")
        lines.append("Prüfe Datei-Rechte auf dem Server.")
        send("\n".join(lines))
        return

    # ── Restart bots ─────────────────────────────────────────────────────
    lines.append("")
    lines.append("🔄 Starte Bots neu...")
    send("\n".join(lines))

    log("Restarting trading + crypto screen sessions")
    _restart_bot("trading", BASE_DIR,
                 "super_bot.py")
    _restart_bot("crypto",  BASE_DIR + "/crypto",
                 "crypto_bot.py")

    # Wait for processes to start
    time.sleep(10)

    # ── Verify sessions are alive ─────────────────────────────────────────
    result      = subprocess.run("screen -list", shell=True,
                                 capture_output=True, text=True)
    trading_ok  = "trading" in result.stdout
    crypto_ok   = "crypto"  in result.stdout

    confirm_lines = ["<b>🚀 Neustart abgeschlossen</b>", ""]
    confirm_lines.append(
        f"{'✅' if trading_ok else '❌'} Super Bot: {'läuft' if trading_ok else 'FEHLER — prüfe /tmp/trading.log'}")
    confirm_lines.append(
        f"{'✅' if crypto_ok  else '❌'} Crypto Bot: {'läuft' if crypto_ok  else 'FEHLER — prüfe /tmp/crypto.log'}")

    if super_params:
        confirm_lines.append("")
        confirm_lines.append("<b>Super Bot — aktive Werte:</b>")
        for key, val in super_params.items():
            confirm_lines.append(f"   {_PARAM_LABELS.get(key, key)}: <b>{_fmt_val(key, val)}</b>")

    if crypto_params:
        confirm_lines.append("")
        confirm_lines.append("<b>Crypto Bot — aktive Werte:</b>")
        for key, val in crypto_params.items():
            confirm_lines.append(f"   {_PARAM_LABELS.get(key, key)}: <b>{_fmt_val(key, val)}</b>")

    send("\n".join(confirm_lines))


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
        "<b>Optimierung</b>\n"
        "/apply          — Vorschläge aus letzter Optimierung anzeigen\n"
        "/confirm        — Vorschläge anwenden &amp; Bots neu starten\n\n"
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
    "/apply":        cmd_apply,
    "/confirm":      cmd_confirm,
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
