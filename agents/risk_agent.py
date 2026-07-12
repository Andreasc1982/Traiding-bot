#!/usr/bin/env python3
"""
Risk Agent v2 — per-bot daily limits + combined drawdown brake.

Per-bot independent limits:
  Super Bot  daily loss > -8%  -> halt Super Bot ONLY, Crypto continues
  Crypto Bot daily loss > -8%  -> halt Crypto Bot ONLY, Super continues

Combined emergency brake:
  Combined drawdown > -15%     -> halt BOTH bots

Resume:
  Per-bot daily loss halt   -> time-based: +2h cooldown
  Combined drawdown halt    -> market-based, per bot:
                               Crypto Bot: BTC +5% from trigger low (min 2h, max 48h)
                               Super Bot:  SPY +2% from trigger low (min 2h, max 24h)

halt file format (read by monitor_agent):
  { "halted_bots": ["super"] | ["crypto"] | ["super","crypto"], ... }
"""

import os, sys, json, time, subprocess, requests
from datetime import datetime, date, timedelta

sys.path.insert(0, "/home/trading2025/trading_bot")
try:
    from config import config
except ImportError:
    config = {}

TELEGRAM_TOKEN     = config.get("telegram_bot_token", "")
TELEGRAM_CHAT_ID   = config.get("telegram_chat_id", "")

BASE_DIR           = "/home/trading2025/trading_bot"
AGENTS_DIR         = os.path.join(BASE_DIR, "agents")
SUPER_JSON         = os.path.join(BASE_DIR, "dashboard.json")
CRYPTO_JSON        = os.path.join(BASE_DIR, "crypto", "crypto_dashboard.json")
CONTROL_FILE       = os.path.join(BASE_DIR, "bot_control.json")
HALT_FILE          = os.path.join(AGENTS_DIR, "risk_halt.json")
LOG_FILE           = os.path.join(AGENTS_DIR, "risk_log.json")
EQUITY_CSV         = os.path.join(AGENTS_DIR, "equity_history.csv")
MANUAL_RESUME_FLAG = os.path.join(AGENTS_DIR, "manual_resume.flag")

CHECK_INTERVAL            = 30
SUPER_DAILY_LIMIT         = -8.0
CRYPTO_DAILY_LIMIT        = -8.0
DRAWDOWN_LIMIT            = -15.0
HALT_CONFIRM              = 2     # Halts erst nach N aufeinanderfolgenden Zyklen (30s) ueber dem Limit
                                  # — ein einzelner korrupter Dashboard-Read zieht keine Notbremse mehr
                                  # (Fehlalarm 2026-07-12 03:04: ein Read=None -> combined kollabiert -> "DD -93%")
RESUME_HOURS_BOT          = 2     # per-bot daily loss halt: time-based 2h
RESUME_MIN_HOURS_DRAWDOWN = 2     # drawdown halt: minimum wait before market check
RESUME_RECOVERY_BTC       = 5.0   # crypto bot: BTC must recover +5% from low
RESUME_MAX_HOURS_CRYPTO   = 48    # crypto bot: safety net after 48h
RESUME_RECOVERY_SPY       = 2.0   # super bot:  SPY must recover +2% from low
RESUME_MAX_HOURS_SUPER    = 24    # super bot:  safety net after 24h (1 trading day)
STALE_MINUTES             = 10
ESCALATE_HALTS            = 2     # >= N Drawdown-Halts im Fenster -> manueller Halt
ESCALATE_WINDOW_H         = 48    # Stunden-Fenster fuer Eskalation
ROLLING_PEAK_DAYS         = 30    # Drawdown-Referenz: rollendes N-Tage-Hoch statt Allzeithoch

BOT_SESSION = {'super': 'trading', 'crypto': 'crypto'}
BOT_CMD = {
    'super': (
        'cd /home/trading2025/trading_bot && '
        'source /home/trading2025/trading_bot_env/bin/activate && '
        'PYTHONUNBUFFERED=1 python3 -u super_bot.py > /tmp/super_bot.log 2>&1'
    ),
    'crypto': (
        'cd /home/trading2025/trading_bot/crypto && '
        'source /home/trading2025/trading_bot_env/bin/activate && '
        'PYTHONUNBUFFERED=1 python3 -u crypto_bot.py > /tmp/crypto_bot.log 2>&1'
    ),
}

def tg(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TG] " + msg); return
    try:
        requests.post("https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage",
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
                      timeout=10)
    except Exception as e:
        print("[TG ERROR] " + str(e))

def _get_btc_price():
    KEY    = config.get("alpaca_api_key", "")
    SECRET = config.get("alpaca_secret_key", "")
    if not KEY or not SECRET:
        return None
    try:
        r = requests.get(
            "https://data.alpaca.markets/v1beta3/crypto/us/latest/quotes",
            headers={"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET},
            params={"symbols": "BTC/USD"},
            timeout=10)
        q = r.json().get("quotes", {}).get("BTC/USD", {})
        price = q.get("ap") or q.get("bp")
        return float(price) if price else None
    except Exception as e:
        print("[BTC-PRICE] " + str(e))
        return None

def _get_spy_price():
    """Fetch latest SPY trade price from Alpaca IEX for Super Bot resume check."""
    KEY    = config.get("alpaca_api_key", "")
    SECRET = config.get("alpaca_secret_key", "")
    if not KEY or not SECRET:
        return None
    try:
        r = requests.get(
            "https://data.alpaca.markets/v2/stocks/trades/latest",
            headers={"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET},
            params={"symbols": "SPY", "feed": "iex"},
            timeout=10)
        t = r.json().get("trades", {}).get("SPY", {})
        price = t.get("p")
        return float(price) if price else None
    except Exception as e:
        print("[SPY-PRICE] " + str(e))
        return None


def _rolling_peak(days):
    """Hoechster kombinierter Equity-Wert der letzten N Tage aus equity_history.csv."""
    try:
        if not os.path.exists(EQUITY_CSV):
            return None
        cutoff = datetime.now() - timedelta(days=days)
        hi = 0.0
        with open(EQUITY_CSV) as f:
            next(f, None)
            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 4:
                    continue
                try:
                    t = datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
                except Exception:
                    continue
                if t < cutoff:
                    continue
                try:
                    val = float(parts[3])
                except Exception:
                    continue
                if val > hi:
                    hi = val
        return hi if hi > 0 else None
    except Exception as e:
        print("[ROLLING-PEAK] " + str(e))
        return None

def _default_state():
    return {"peak_value": None, "halted": False, "resume_at": None,
            "halt_btc_price": None, "halt_spy_price": None, "halt_time": None,
            "super_day_start": None, "super_day_date": None,
            "super_halted": False, "super_resume_at": None,
            "crypto_day_start": None, "crypto_day_date": None,
            "crypto_halted": False, "crypto_resume_at": None,
            "manual_hold": False, "drawdown_halt_times": [], "rolling_peak": None,
            "events": []}

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

def save_state(s):
    try:
        s["events"] = s["events"][-500:]
        with open(LOG_FILE, "w") as f:
            json.dump(s, f, indent=2)
    except Exception as e:
        print("[STATE] Save error: " + str(e))

def log_event(s, t, **kw):
    ev = {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": t, **kw}
    s["events"].append(ev)
    print("[EVENT] " + t + ": " + str(kw))
    try:
        import health
        health.log("risk_agent", t, str(kw)[:150])
    except Exception:
        pass

def _update_halt_file(s):
    sh = s.get("super_halted"); ch = s.get("crypto_halted")
    if not sh and not ch:
        try:
            if os.path.exists(HALT_FILE): os.remove(HALT_FILE)
        except Exception as e:
            print("[HALT] Remove error: " + str(e))
        return
    bots = []
    if sh: bots.append("super")
    if ch: bots.append("crypto")
    times = [t for t in [s.get("super_resume_at"), s.get("crypto_resume_at"), s.get("resume_at")] if t]
    with open(HALT_FILE, "w") as f:
        json.dump({"halted": True, "halted_bots": bots,
                   "halted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "manual_hold": s.get("manual_hold", False),
                   "resume_at": min(times) if times else None}, f, indent=2)

def _stop_super():
    try:
        with open(CONTROL_FILE, "w") as f:
            json.dump({"command": "close_all"}, f)
        print("[HALT] Wrote close_all -> bot_control.json (warte max 45s auf Position-Abbau)")
    except Exception as e:
        print("[HALT] Control file: " + str(e))
    # Poll for control file removal — bot removes it after executing close_all
    for _ in range(9):
        time.sleep(5)
        if not os.path.exists(CONTROL_FILE):
            print("[HALT] close_all bestaetigt — Super Bot Positionen geschlossen")
            break
    else:
        print("[HALT] close_all Timeout (45s) — Fahre fort mit Hard-Kill")
    r = subprocess.run(["screen", "-ls"], capture_output=True, text=True)
    if ".trading\t" in r.stdout:
        subprocess.run(["screen", "-S", "trading", "-X", "quit"])
        print("[HALT] Hard-killed screen:trading")

def _stop_crypto():
    crypto_ctrl = os.path.join(BASE_DIR, "crypto", "crypto_control.json")
    try:
        with open(crypto_ctrl, "w") as f:
            json.dump({"command": "close_all"}, f)
        print("[HALT] Wrote close_all -> crypto_control.json (warte max 45s auf Position-Abbau)")
    except Exception as e:
        print("[HALT] Crypto control file: " + str(e))
    # Poll for control file removal — bot removes it after executing close_all
    for _ in range(9):
        time.sleep(5)
        if not os.path.exists(crypto_ctrl):
            print("[HALT] close_all bestaetigt — Crypto Bot Positionen geschlossen")
            break
    else:
        print("[HALT] close_all Timeout (45s) — Fahre fort mit Hard-Kill")
    subprocess.run(["screen", "-S", "crypto", "-X", "quit"])
    print("[HALT] Killed screen:crypto")

def halt_super(s, reason, pct, sv):
    resume = (datetime.now() + timedelta(hours=RESUME_HOURS_BOT)).strftime("%Y-%m-%d %H:%M")
    print("\n" + "!"*55 + "\n  SUPER BOT HALT -- " + reason +
          "\n  Tagesverlust: " + "{:+.2f}".format(pct) + "%" +
          "\n  Resume: " + resume + "  |  Crypto Bot: aktiv\n" + "!"*55)
    s["super_halted"] = True; s["super_resume_at"] = resume
    _update_halt_file(s); _stop_super()
    log_event(s, "HALT_SUPER", reason=reason, daily_pct=round(pct,2), sv=round(sv,2), resume=resume)
    save_state(s)
    tg("STOP <b>SUPER BOT HALT</b>\n" + reason +
       "\nTagesverlust: " + "{:+.2f}".format(pct) + "% (Limit " + str(SUPER_DAILY_LIMIT) + "%)" +
       "\nWert: $" + "{:,.2f}".format(sv) +
       "\nCrypto Bot laeuft weiter\nResume: " + resume + " (+" + str(RESUME_HOURS_BOT) + "h)")

def halt_crypto(s, reason, pct, cv):
    resume = (datetime.now() + timedelta(hours=RESUME_HOURS_BOT)).strftime("%Y-%m-%d %H:%M")
    print("\n" + "!"*55 + "\n  CRYPTO BOT HALT -- " + reason +
          "\n  Tagesverlust: " + "{:+.2f}".format(pct) + "%" +
          "\n  Resume: " + resume + "  |  Super Bot: aktiv\n" + "!"*55)
    s["crypto_halted"] = True; s["crypto_resume_at"] = resume
    _update_halt_file(s); _stop_crypto()
    log_event(s, "HALT_CRYPTO", reason=reason, daily_pct=round(pct,2), cv=round(cv,2), resume=resume)
    save_state(s)
    tg("STOP <b>CRYPTO BOT HALT</b>\n" + reason +
       "\nTagesverlust: " + "{:+.2f}".format(pct) + "% (Limit " + str(CRYPTO_DAILY_LIMIT) + "%)" +
       "\nWert: $" + "{:,.2f}".format(cv) +
       "\nSuper Bot laeuft weiter\nResume: " + resume + " (+" + str(RESUME_HOURS_BOT) + "h)")

def halt_both(s, reason, spct, ddpct, combined):
    peak    = s.get("peak_value") or combined
    btc     = _get_btc_price()
    spy     = _get_spy_price()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    s["halted"]         = True
    s["halt_time"]      = now_str
    s["halt_btc_price"] = btc
    s["halt_spy_price"] = spy
    s["resume_at"]      = None
    s["super_halted"]   = True;  s["super_resume_at"]  = None
    s["crypto_halted"]  = True;  s["crypto_resume_at"] = None
    # Eskalation: wiederholte Drawdown-Halts = strukturelles Problem -> manueller Halt
    s.setdefault("drawdown_halt_times", [])
    s["drawdown_halt_times"].append(now_str)
    s["drawdown_halt_times"] = s["drawdown_halt_times"][-10:]
    recent = []
    for _t in s["drawdown_halt_times"]:
        try:
            if (datetime.now() - datetime.strptime(_t, "%Y-%m-%d %H:%M")).total_seconds() < ESCALATE_WINDOW_H * 3600:
                recent.append(_t)
        except Exception:
            pass
    if len(recent) >= ESCALATE_HALTS:
        s["manual_hold"] = True
        tg("STOP <b>MANUELLER HALT AKTIV</b>\n" + str(len(recent)) + " Drawdown-Halts in " +
           str(ESCALATE_WINDOW_H) + "h -- Strategie verliert wiederholt.\n"
           "Bots bleiben AUS bis manuelles /start. Bitte Strategie pruefen.")
    btc_str = ("$" + "{:,.0f}".format(btc)) if btc else "?"
    spy_str = ("$" + "{:.2f}".format(spy))  if spy else "?"
    resume_info = ("Crypto: BTC " + btc_str + " +" + str(RESUME_RECOVERY_BTC) +
                   "% (max " + str(RESUME_MAX_HOURS_CRYPTO) + "h)  |  " +
                   "Super: SPY " + spy_str + " +" + str(RESUME_RECOVERY_SPY) +
                   "% (max " + str(RESUME_MAX_HOURS_SUPER) + "h)  |  " +
                   "min " + str(RESUME_MIN_HOURS_DRAWDOWN) + "h Wartezeit")
    print("\n" + "!"*55 + "\n  BEIDE BOTS HALT (DRAWDOWN) -- " + reason +
          "\n  Drawdown: " + "{:+.2f}".format(ddpct) + "%" +
          "\n  Portfolio: $" + "{:,.2f}".format(combined) +
          "\n  BTC: " + btc_str + "  |  SPY: " + spy_str +
          "\n  " + resume_info + "\n" + "!"*55)
    _update_halt_file(s); _stop_crypto(); _stop_super()
    log_event(s, "HALT_BOTH", reason=reason, drawdown_pct=round(ddpct,2),
              combined=round(combined,2), peak=round(peak,2),
              halt_btc=round(btc,2) if btc else None,
              halt_spy=round(spy,2) if spy else None)
    save_state(s)
    tg("ALARM <b>BEIDE BOTS GESTOPPT - DRAWDOWN</b>\n" + reason +
       "\nPortfolio: $" + "{:,.2f}".format(combined) +
       "\nDrawdown: " + "{:+.2f}".format(ddpct) + "% (Limit " + str(DRAWDOWN_LIMIT) + "%)" +
       "\nPeak war: $" + "{:,.2f}".format(peak) +
       "\nBTC: " + btc_str + "  |  SPY: " + spy_str +
       "\n" + resume_info)

def _restart_bot(bot):
    session = BOT_SESSION[bot]
    ctrl = {'super': '/home/trading2025/trading_bot/bot_control.json',
            'crypto': '/home/trading2025/trading_bot/crypto/crypto_control.json'}
    try:
        with open(ctrl[bot], 'w') as cf: json.dump({'paused': False}, cf)
        print('[RESUME] ' + ctrl[bot] + ' bereinigt')
    except Exception as ce:
        print('[RESUME] ctrl-file fehler: ' + str(ce))
    subprocess.run(['screen', '-S', session, '-X', 'quit'], capture_output=True)
    time.sleep(2)
    subprocess.run(['screen', '-dmS', session, 'bash', '-c', BOT_CMD[bot]])
    time.sleep(4)
    r = subprocess.run(['screen', '-ls'], capture_output=True, text=True)
    alive = ('.' + session + chr(9)) in r.stdout
    print('[RESUME] screen:' + session + ' neu: ' + ('OK' if alive else 'FEHLER'))
    return alive

def resume_bot(s, bot, value, reason=""):
    today = date.today().isoformat()
    name  = "Super Bot" if bot == "super" else "Crypto Bot"
    print("\n" + "="*55 + "\n  RESUME " + name.upper() +
          (" (" + reason + ")" if reason else "") +
          " | $" + "{:,.2f}".format(value) + "\n" + "="*55)
    s[bot + "_halted"] = False; s[bot + "_resume_at"] = None
    s[bot + "_day_start"] = value; s[bot + "_day_date"] = today
    if not s.get("super_halted") and not s.get("crypto_halted"):
        s["halted"] = False; s["resume_at"] = None
        s["halt_btc_price"] = None; s["halt_spy_price"] = None; s["halt_time"] = None
        s["peak_value"] = None   # Re-Baseline: Drawdown ab hier frisch messen (bricht Halt-Schleife)
        print("[REBASELINE] Peak zurueckgesetzt -- Drawdown misst ab aktuellem kombinierten Wert")
    _update_halt_file(s)
    log_event(s, "RESUME_" + bot.upper(), value=round(value,2), reason=reason)
    save_state(s)
    ok = _restart_bot(bot)
    st = "Bot gestartet " + ("OK" if ok else "FEHLER!")
    tg("OK <b>" + name + " RESUME</b>" +
       ("\n<i>" + reason + "</i>" if reason else "") +
       "\n" + st +
       "\nTagesverlust-Zaehler zurueckgesetzt.\nWert: $" + "{:,.2f}".format(value))

def read_dashboard(path):
    try:
        if not os.path.exists(path): return None, None
        age = (time.time() - os.path.getmtime(path)) / 60
        with open(path) as f: d = json.load(f)
        cash = float(d.get("balance", 0))
        pos  = sum(float(p.get("shares",0)) * float(p.get("current_price", p.get("entry",0)))
                   for p in d.get("positions",{}).values())
        return cash + pos, round(age, 1)
    except Exception as e:
        print("[READ] " + str(e)); return None, None

def run():
    s = load_state()

    if os.path.exists(HALT_FILE) and not s.get("super_halted") and not s.get("crypto_halted"):
        try:
            with open(HALT_FILE) as f: hf = json.load(f)
            bots = hf.get("halted_bots", ["super", "crypto"])
            if "super"  in bots: s["super_halted"]  = True
            if "crypto" in bots: s["crypto_halted"] = True
            print("[INIT] Halt synced: " + str(bots))
        except Exception: pass

    # Halt-File beim Start neu schreiben/loeschen -- korrigiert veraltete Eintraege
    _update_halt_file(s)

    print("=" * 55)
    print("  RISK AGENT v2 -- getrennte Bot-Limits")
    print("  Super Bot  daily : " + str(SUPER_DAILY_LIMIT)  + "% (nur Super stoppt)")
    print("  Crypto Bot daily : " + str(CRYPTO_DAILY_LIMIT) + "% (nur Crypto stoppt)")
    print("  Drawdown (beide) : " + str(DRAWDOWN_LIMIT)     + "% (Notbremse)")
    print("  Cooldown Bot     : +" + str(RESUME_HOURS_BOT)  + "h (zeitbasiert)")
    print("  Drawdown Resume  : Crypto=BTC +" + str(RESUME_RECOVERY_BTC) +
          "% (max " + str(RESUME_MAX_HOURS_CRYPTO) +
          "h)  Super=SPY +" + str(RESUME_RECOVERY_SPY) +
          "% (max " + str(RESUME_MAX_HOURS_SUPER) + "h)")
    print("=" * 55)

    log_event(s, "START", super_limit=SUPER_DAILY_LIMIT,
              crypto_limit=CRYPTO_DAILY_LIMIT, drawdown_limit=DRAWDOWN_LIMIT)
    save_state(s)
    tg("OK <b>Risk Agent v2 gestartet</b>\n"
       "Super: " + str(SUPER_DAILY_LIMIT) + "%/Tag | Crypto: " + str(CRYPTO_DAILY_LIMIT) + "%/Tag\n"
       "Drawdown Notbremse: " + str(DRAWDOWN_LIMIT) + "% (beide)\n"
       "Resume: Bot=" + str(RESUME_HOURS_BOT) + "h | Crypto=BTC+" +
       str(RESUME_RECOVERY_BTC) + "% Super=SPY+" + str(RESUME_RECOVERY_SPY) + "%")

    cycle = 0; last_stale_tg = 0.0; last_equity = 0.0
    breach = {"super": 0, "crypto": 0, "dd": 0}   # aufeinanderfolgende Limit-Verletzungen je Bremse

    while True:
        try:
            now = datetime.now(); today = date.today().isoformat(); cycle += 1
            sv, sa = read_dashboard(SUPER_JSON)
            cv, ca = read_dashboard(CRYPTO_JSON)

            stale = []
            if sa and sa > STALE_MINUTES: stale.append("S(" + str(sa) + "m)")
            if ca and ca > STALE_MINUTES: stale.append("C(" + str(ca) + "m)")
            # Gehaltene Bots sind erwartet stale -- kein Telegram-Spam waehrend Halt
            stale_tg = []
            if sa and sa > STALE_MINUTES and not s.get("super_halted"):
                stale_tg.append("S(" + str(sa) + "m)")
            if ca and ca > STALE_MINUTES and not s.get("crypto_halted"):
                stale_tg.append("C(" + str(ca) + "m)")
            if stale_tg and time.time() - last_stale_tg > 3600:
                tg("WARN Stale: " + ",".join(stale_tg)); last_stale_tg = time.time()

            if sv is None and cv is None:
                print("[" + now.strftime("%H:%M:%S") + "] Keine Daten"); time.sleep(CHECK_INTERVAL); continue

            # Drawdown/Peak nur bewerten wenn BEIDE Dashboards lesbar sind — ein einzelner
            # kaputter Read (None -> als 0 gezaehlt) liess combined kollabieren -> Fehlalarm-Halt
            dd_valid = (sv is not None) and (cv is not None)
            combined = (sv or 0) + (cv or 0)
            if dd_valid and s["peak_value"] is None and combined > 0:
                s["peak_value"] = combined
                print("[INIT] Peak: $" + "{:,.2f}".format(combined))
            if dd_valid and combined > (s["peak_value"] or 0): s["peak_value"] = combined
            _rp_cur = s.get("rolling_peak")
            if dd_valid and _rp_cur and s["peak_value"] and _rp_cur < s["peak_value"]:
                s["peak_value"] = max(_rp_cur, combined)   # altes Hoch altert aus 30-Tage-Fenster

            if sv and (s["super_day_date"] != today or not s["super_day_start"]):
                s["super_day_start"] = sv; s["super_day_date"] = today
                print("[DAY] Super Basis: $" + "{:,.2f}".format(sv))
            if cv and (s["crypto_day_date"] != today or not s["crypto_day_start"]):
                s["crypto_day_start"] = cv; s["crypto_day_date"] = today
                print("[DAY] Crypto Basis: $" + "{:,.2f}".format(cv))

            peak  = s["peak_value"] or combined
            ddpct = (combined - peak) / peak * 100 if (dd_valid and peak > 0) else 0.0
            spct  = (sv - s["super_day_start"])  / s["super_day_start"]  * 100 if sv and s["super_day_start"]  else 0.0
            cpct  = (cv - s["crypto_day_start"]) / s["crypto_day_start"] * 100 if cv and s["crypto_day_start"] else 0.0

            # Equity-Kurve: stuendlich eine Zeile (nur mit vollstaendigen Daten — keine 0-Zeilen)
            if dd_valid and time.time() - last_equity >= 3600:
                try:
                    newfile = not os.path.exists(EQUITY_CSV)
                    with open(EQUITY_CSV, "a") as ef:
                        if newfile:
                            ef.write("time,super,crypto,combined\n")
                        ef.write(now.strftime("%Y-%m-%d %H:%M") + "," +
                                 str(round(sv or 0, 2)) + "," +
                                 str(round(cv or 0, 2)) + "," +
                                 str(round(combined, 2)) + "\n")
                    last_equity = time.time()
                    _rp = _rolling_peak(ROLLING_PEAK_DAYS)
                    if _rp: s["rolling_peak"] = _rp
                except Exception as e:
                    print("[EQUITY] " + str(e))

            st = "[HALT]" if s.get("super_halted")  else "OK"
            ct = "[HALT]" if s.get("crypto_halted") else "OK"
            print("[" + now.strftime("%H:%M:%S") + "] "
                  "S=$" + "{:,.0f}".format(sv or 0) + " " + "{:+.1f}".format(spct) + "% " + st + "  "
                  "C=$" + "{:,.0f}".format(cv or 0) + " " + "{:+.1f}".format(cpct) + "% " + ct + "  "
                  "DD=" + "{:+.1f}".format(ddpct) + "% Peak=$" + "{:,.0f}".format(peak)
                  + ("  STALE:" + ",".join(stale) if stale else ""))

            # Manueller Resume nach Eskalation -- raeumt manual_hold, re-baselined, startet beide
            if s.get("manual_hold") and os.path.exists(MANUAL_RESUME_FLAG):
                try: os.remove(MANUAL_RESUME_FLAG)
                except Exception: pass
                s["manual_hold"] = False
                s["drawdown_halt_times"] = []
                s["peak_value"] = None
                print("[MANUAL] Manueller Resume bestaetigt -- Peak neu, beide Bots starten")
                tg("OK <b>Manueller Resume</b>\nManueller Halt aufgehoben, Peak neu gesetzt, Bots starten neu.")
                if s.get("super_halted"):
                    resume_bot(s, "super", sv or s.get("super_day_start") or 0, "Manueller Resume")
                if s.get("crypto_halted"):
                    resume_bot(s, "crypto", cv or s.get("crypto_day_start") or 0, "Manueller Resume")

            for bot, val in [("super", sv), ("crypto", cv)]:
                if not s.get(bot + "_halted") or not val:
                    continue
                if s.get("manual_hold"):
                    if cycle % 40 == 0 and bot == "super":
                        print("[MANUAL HOLD] Bots gehalten -- warte auf /start (manueller Eingriff)")
                    continue

                if s.get("halted"):
                    halt_time_str = s.get("halt_time")
                    if not halt_time_str:
                        # First cycle: set halt_time + baselines for both indicators
                        s["halt_time"] = now.strftime("%Y-%m-%d %H:%M")
                        if not s.get("halt_btc_price"):
                            p = _get_btc_price()
                            if p: s["halt_btc_price"] = p; print("[DRAWDOWN HALT] BTC Baseline: $" + "{:,.0f}".format(p))
                        if not s.get("halt_spy_price"):
                            p = _get_spy_price()
                            if p: s["halt_spy_price"] = p; print("[DRAWDOWN HALT] SPY Baseline: $" + "{:.2f}".format(p))
                        save_state(s)
                        continue
                    halt_dt   = datetime.strptime(halt_time_str, "%Y-%m-%d %H:%M")
                    elapsed_h = (now - halt_dt).total_seconds() / 3600

                    # Ensure baselines are set (may be missing after agent restart)
                    if not s.get("halt_btc_price"):
                        p = _get_btc_price()
                        if p: s["halt_btc_price"] = p; save_state(s); print("[DRAWDOWN HALT] BTC Baseline: $" + "{:,.0f}".format(p))
                    if not s.get("halt_spy_price"):
                        p = _get_spy_price()
                        if p: s["halt_spy_price"] = p; save_state(s); print("[DRAWDOWN HALT] SPY Baseline: $" + "{:.2f}".format(p))

                    # Per-bot indicator and thresholds
                    if bot == "crypto":
                        max_h      = RESUME_MAX_HOURS_CRYPTO
                        target_pct = RESUME_RECOVERY_BTC
                        halt_ref   = s.get("halt_btc_price")
                        cur_price  = _get_btc_price()
                        ind_name   = "BTC"
                        fmt_p      = lambda p: "$" + "{:,.0f}".format(p)
                    else:
                        max_h      = RESUME_MAX_HOURS_SUPER
                        target_pct = RESUME_RECOVERY_SPY
                        halt_ref   = s.get("halt_spy_price")
                        cur_price  = _get_spy_price()
                        ind_name   = "SPY"
                        fmt_p      = lambda p: "$" + "{:.2f}".format(p)

                    if elapsed_h >= max_h:
                        print("[RESUME] " + bot + " Safety-Net: " + str(max_h) + "h erreicht")
                        resume_bot(s, bot, val, str(max_h) + "h Safety-Net")
                        continue

                    if elapsed_h < RESUME_MIN_HOURS_DRAWDOWN:
                        if cycle % 20 == 0:
                            print("[DRAWDOWN HALT] " + bot + " Mindestwartezeit: " +
                                  "{:.0f}".format(elapsed_h * 60) + "min / " +
                                  str(int(RESUME_MIN_HOURS_DRAWDOWN * 60)) + "min")
                        continue

                    # Set baseline if missing (legacy halt)
                    if cur_price and not halt_ref:
                        if bot == "crypto": s["halt_btc_price"] = cur_price
                        else:               s["halt_spy_price"] = cur_price
                        save_state(s)
                        print("[DRAWDOWN HALT] " + ind_name + " Baseline (legacy): " + fmt_p(cur_price))
                        continue

                    if cur_price and halt_ref:
                        recovery = (cur_price - halt_ref) / halt_ref * 100
                        if recovery >= target_pct:
                            reason_str = (ind_name + " +" + "{:.1f}".format(recovery) +
                                          "% erholt (" + fmt_p(halt_ref) + " -> " + fmt_p(cur_price) + ")")
                            print("[RESUME] " + bot + " " + reason_str)
                            resume_bot(s, bot, val, reason_str)
                        elif cycle % 20 == 0:
                            print("[DRAWDOWN HALT] " + bot + " " + ind_name +
                                  " " + "{:+.2f}".format(recovery) + "% (Ziel +" +
                                  str(target_pct) + "%) | " +
                                  "{:.1f}".format(elapsed_h) + "h | " +
                                  fmt_p(halt_ref) + " -> " + fmt_p(cur_price))
                    elif cur_price is None and cycle % 20 == 0:
                        print("[DRAWDOWN HALT] " + bot + " " + ind_name + " Preis nicht abrufbar")

                else:
                    ra = s.get(bot + "_resume_at")
                    if ra:
                        try:
                            rdt = datetime.strptime(ra, "%Y-%m-%d %H:%M")
                            if now >= rdt:
                                resume_bot(s, bot, val, "Zeit-Cooldown " + str(RESUME_HOURS_BOT) + "h")
                            elif cycle % 20 == 0:
                                print("[HALT] " + bot + " resume in " +
                                      str(int((rdt-now).total_seconds()/60)) + " min")
                        except Exception: pass

            # Halts erst nach HALT_CONFIRM aufeinanderfolgenden Verletzungen (~60s):
            # transiente/korrupte Messwerte ziehen keine Notbremse, echte Crashes bleiben >60s verletzt
            if sv and not s.get("super_halted") and spct <= SUPER_DAILY_LIMIT:
                breach["super"] += 1
                if breach["super"] >= HALT_CONFIRM:
                    halt_super(s, "SUPER_DAILY_LOSS " + "{:+.2f}".format(spct) + "% (Limit " + str(SUPER_DAILY_LIMIT) + "%)", spct, sv)
                else:
                    print("[CONFIRM] Super " + "{:+.2f}".format(spct) + "% Zyklus " + str(breach["super"]) + "/" + str(HALT_CONFIRM))
            else:
                breach["super"] = 0
            if cv and not s.get("crypto_halted") and cpct <= CRYPTO_DAILY_LIMIT:
                breach["crypto"] += 1
                if breach["crypto"] >= HALT_CONFIRM:
                    halt_crypto(s, "CRYPTO_DAILY_LOSS " + "{:+.2f}".format(cpct) + "% (Limit " + str(CRYPTO_DAILY_LIMIT) + "%)", cpct, cv)
                else:
                    print("[CONFIRM] Crypto " + "{:+.2f}".format(cpct) + "% Zyklus " + str(breach["crypto"]) + "/" + str(HALT_CONFIRM))
            else:
                breach["crypto"] = 0
            if (dd_valid and not s.get("halted")
                    and not (s.get("super_halted") and s.get("crypto_halted"))
                    and ddpct <= DRAWDOWN_LIMIT):
                breach["dd"] += 1
                if breach["dd"] >= HALT_CONFIRM:
                    halt_both(s, "DRAWDOWN " + "{:+.2f}".format(ddpct) + "% (Limit " + str(DRAWDOWN_LIMIT) + "%)", spct, ddpct, combined)
                else:
                    print("[CONFIRM] Drawdown " + "{:+.2f}".format(ddpct) + "% Zyklus " + str(breach["dd"]) + "/" + str(HALT_CONFIRM))
            else:
                breach["dd"] = 0

            if cycle % 20 == 0: save_state(s)

        except KeyboardInterrupt:
            print("[RISK] Gestoppt"); tg("STOP Risk Agent gestoppt"); save_state(s); break
        except Exception as e:
            print("[RISK ERROR] " + str(e))
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    run()
