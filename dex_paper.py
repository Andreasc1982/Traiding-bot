#!/usr/bin/env python3
"""
DEX Paper-Moonshot (Phase 2a) — paper-tradet die vom dex_monitor gescreenten
Solana-Token. KEIN Geld, keine Wallet, keine Orders — nur simuliert, damit wir
EHRLICH messen koennen: traegt die Idee nach Kosten UND Rugs?

REALISMUS (bewusst pessimistisch — wir wollen die Wahrheit, keine schoenen Zahlen):
 - Kauf/Verkauf mit 5% Slippage pro Seite (DEX-Micro-Caps haben brutalen Spread)
 - EHRLICHE Rug-Verluste: bricht die Liquiditaet ein, wird zum ABGESTUERZTEN Preis
   gefuellt (nicht zum Stop-Level!) -> der -35%-Stop rettet NICHT vor einem Rug.
   Genau das ist die Frage, die wir testen.
 - Held-Positionen werden alle 20s geprueft (faengt langsame Dumps via Trailing;
   ein Instant-Rug in einem einzigen Solana-Block ist physisch nicht einholbar).

Lehren aus alten Bugs (bewusst eingebaut):
 - Entry UND Exit zur GLEICHEN Live-Preisquelle (DexScreener) -> kein Phantom-Gewinn
   wie beim Contrarian-Clone (Entry zu altem Bar-Schluss, Exit live).
 - harte 10s-Timeouts, atomare Writes, Heartbeat, defensives Parsen.
 - Micro-Preise als float erst beim Rechnen; gespeichert wie geliefert.
READ-ONLY gegenueber allen anderen Bots: schreibt NUR nach dex/.
"""
import os, sys, json, time, requests
from datetime import datetime

sys.path.insert(0, "/home/trading2025/trading_bot")
try:
    from config import config
except ImportError:
    config = {}

DEX_DIR   = "/home/trading2025/trading_bot/dex"
os.makedirs(DEX_DIR, exist_ok=True)
WATCHLIST = os.path.join(DEX_DIR, "watchlist.json")
PSTATE    = os.path.join(DEX_DIR, "paper_state.json")
PTRADES   = os.path.join(DEX_DIR, "paper_trades.json")
PHB       = os.path.join(DEX_DIR, "paper_heartbeat.json")

# ── Parameter ────────────────────────────────────────────────────────────────
START_BANKROLL = 500.0     # Paper-Kapital (realistische Mini-Kasse)
BET            = 20.0      # $20 Mini-Wette pro Token (kleine Betraege = Strategie)
MAX_POS        = 12        # max gleichzeitige Wetten
ENTRY_MOM      = 12.0      # Trigger: >=12% 1h-Momentum (sustained, kein 5-min-Flash)
ENTRY_VOL_H6   = 5000      # zusaetzlich: >=$5k 6h(~5h)-Volumen — echtes Interesse, kein toter Flash
ENTRY_MAX_CHG5 = 15.0      # v2 Anti-Chase: NICHT mitten im 5m-Spike kaufen — Daten v1: 5m-Mom 25%+ -> ~0% Win (Top-Kauf)
ENTRY_MAX_CHG1 = 100.0     # v2.1 Anti-Parabolic: 1h-Momentum-Deckel — schon >100% gelaufen = Top (CALVIN +256% -> -18.7%); Startwert, aus chg1-Daten zu schaerfen
ENTRY_SLIP     = 0.05      # 5% Kauf-Slippage
EXIT_SLIP      = 0.05      # 5% Verkauf-Slippage
HARD           = 0.35      # harter Stop -35% (DEX-Noise verlangt Luft)
TRAIL          = 0.30      # Trailing 30% vom Hoch (Moonshot: Gewinner laufen lassen)
RUG_LIQ        = 2500      # Liquiditaet < $2.5k = gerugged -> Fill zum Ist-Preis (Totalverlust)
RUG_CONFIRM    = 3         # so viele aufeinanderfolgende Rug-Belege noetig (gegen API-Hiccups -> keine Fake-Verluste)
RUG_RECOVERY   = 0.05      # komplett verschwundener Token: Restwert-Annahme (5% = -95%, ehrlich pessimistisch)
SCALE_AT       = 1.00      # bei +100%: Einsatz rausnehmen (House-Money), Rest laeuft
BE_TRIGGER     = 0.25      # v2: ab +25% Peak Break-Even-Floor — einen Gewinner nie ins Minus zurueckdrehen lassen
MAX_HOURS      = 48        # Zeit-Exit fuer Zombies (steht weder hoch noch tief)
POLL_SEC       = 20        # Held-Positionen alle 20s pruefen
TIMEOUT        = 10

TG_TOKEN   = config.get("telegram_bot_token", "")
TG_CHAT    = config.get("telegram_chat_id", "")
TG_WIN_PCT = 25.0          # Telegram-Alert ab diesem Gewinn-% (Moonshots)
SUMMARY_H  = 6             # Telegram-Zusammenfassung alle 6h


def _tg(msg):
    """Telegram-Nachricht (gleicher Chat wie Live-Bots). Graceful ohne Config."""
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        requests.post("https://api.telegram.org/bot" + TG_TOKEN + "/sendMessage",
                      data={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=TIMEOUT)
    except Exception as e:
        print("[TG] " + str(e)[:60])


def _get(url):
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print("[PAPER-API] " + str(e)[:80])
    return None


def _atomic(path, obj):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except Exception as e:
        print("[PAPER-WRITE] " + str(e))


def token_now(addr):
    """price+liq. None = API-Ausfall (transient, NICHT als Rug werten).
    {} = Token aus API verschwunden (echter Vanish)."""
    d = _get("https://api.dexscreener.com/latest/dex/tokens/" + addr)
    if d is None:
        return None                       # API down / 429 / Timeout -> NICHT als Rug werten
    if not d.get("pairs"):
        return {}                         # 200 OK, aber keine Pairs -> echter Vanish
    pairs = [p for p in d["pairs"] if p.get("chainId") == "solana"]
    if not pairs:
        return {}                         # echter Vanish (keine Solana-Pairs mehr)
    p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd", 0) or 0)
    try:
        price = float(p.get("priceUsd") or 0)
    except (TypeError, ValueError):
        price = 0.0
    liq = (p.get("liquidity") or {}).get("usd", 0) or 0
    return {"price": price, "liq": liq}


def tokens_now(addrs):
    """Batch: bis zu 30 Adressen in EINEM Call. -> dict addr -> {price, liq}.
    None (statt dict) bei komplettem API-Ausfall (transient, nicht werten).
    Fehlt eine Adresse im Ergebnis -> echter Vanish (Aufrufer behandelt als {})."""
    if not addrs:
        return {}
    d = _get("https://api.dexscreener.com/latest/dex/tokens/" + ",".join(addrs[:30]))
    if d is None:
        return None                       # kompletter API-Ausfall
    out = {}
    for p in (d.get("pairs") or []):
        if p.get("chainId") != "solana":
            continue
        a = (p.get("baseToken") or {}).get("address")
        if not a:
            continue
        liq = (p.get("liquidity") or {}).get("usd", 0) or 0
        try:
            price = float(p.get("priceUsd") or 0)
        except (TypeError, ValueError):
            price = 0.0
        if a not in out or liq > out[a]["liq"]:   # liquidestes Pair pro Token
            out[a] = {"price": price, "liq": liq}
    return out


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def close_paper(state, trades, addr, price, reason):
    pos = state["positions"].pop(addr, None)
    if not pos:
        return
    if reason == "RUG-TOTAL":
        fill = price          # kein sauberer Exit moeglich — Fill zum abgestuerzten Preis
    else:
        fill = price * (1 - EXIT_SLIP)
    proceeds = pos["shares"] * fill
    # bereits via Scale-Out entnommener Einsatz zaehlt zum Ergebnis
    realized = pos.get("realized", 0.0)
    profit = (proceeds + realized) - pos["bet"]
    pct = (price / pos["entry"] - 1) * 100 if pos["entry"] > 0 else -100
    state["bankroll"] += proceeds
    trades.append({
        "addr": addr, "symbol": pos["symbol"], "profit": round(profit, 2),
        "pct": round(pct, 1), "reason": reason,
        "entry": pos["entry"], "exit": price,
        "peak_pct": round((pos.get("peak", pos["entry"]) / pos["entry"] - 1) * 100, 1) if pos["entry"] > 0 else 0,
        "opened": pos["time"], "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "scaled": pos.get("scaled", False),
    })
    tag = "💀" if reason == "RUG-TOTAL" else ("🚀" if profit > 0 else "")
    print("[PAPER-CLOSE] " + reason + " " + pos["symbol"] + " " +
          ("+" if pct >= 0 else "") + str(round(pct, 1)) + "% -> $" +
          str(round(profit, 2)) + " " + tag)
    if reason == "RUG-TOTAL":
        _tg("💀 <b>DEX-Rug</b>: " + pos["symbol"] + " " + str(round(pct, 1)) +
            "% = $" + str(round(profit, 2)) + " (Screening hat ihn durchgelassen)")
    elif pct >= TG_WIN_PCT:
        _tg("🚀 <b>DEX-Gewinn</b>: " + pos["symbol"] + " +" + str(round(pct, 1)) +
            "% = $" + str(round(profit, 2)) + " (" + reason + ")")


def scale_out(state, trades, addr, price):
    """House-Money: bei +100% den Einsatz ($BET) zum Ist-Preis rausnehmen, Rest laeuft."""
    pos = state["positions"][addr]
    fill = price * (1 - EXIT_SLIP)
    sell_shares = min(pos["shares"], pos["bet"] / fill)   # so viele Shares = 1x Einsatz
    proceeds = sell_shares * fill
    pos["shares"] -= sell_shares
    pos["realized"] = pos.get("realized", 0.0) + proceeds
    pos["scaled"] = True
    state["bankroll"] += proceeds
    print("[PAPER-SCALE] " + pos["symbol"] + " +100% -> Einsatz $" +
          str(round(proceeds, 2)) + " gesichert (House-Money laeuft)")
    _tg("🏠 <b>DEX House-Money</b>: " + pos["symbol"] + " +100% — Einsatz $" +
        str(round(proceeds, 2)) + " gesichert, Rest laeuft 🎰")


def equity(state):
    open_val = sum(p["shares"] * p.get("last_price", p["entry"]) for p in state["positions"].values())
    return state["bankroll"] + open_val


def _tg_summary(state, trades):
    eq = equity(state)
    n = len(trades)
    wins = sum(1 for tr in trades if tr.get("profit", 0) > 0)
    rugs = sum(1 for tr in trades if tr.get("reason") == "RUG-TOTAL")
    wr = (wins / n * 100) if n else 0
    best = max((tr.get("pct", 0) for tr in trades), default=0)
    _tg("🛰️ <b>DEX Paper-Moonshot</b>\n"
        "Equity: $" + str(round(eq, 2)) + " (" + ("%+.1f" % ((eq / START_BANKROLL - 1) * 100)) + "%)\n"
        "Offen: " + str(len(state["positions"])) + " | Trades: " + str(n) +
        " | Win-Rate: " + str(round(wr)) + "%\n"
        "Rugs: " + str(rugs) + " | Bester Trade: +" + str(round(best, 1)) + "%")


def run():
    print("=" * 58)
    print("  DEX PAPER-MOONSHOT — kein Geld, REALISTISCH (Slippage+Rugs)")
    print("  Bankroll $" + str(START_BANKROLL) + " | Wette $" + str(BET) +
          " | Entry >=" + str(ENTRY_MOM) + "% 1h-Mom + >=$" + str(ENTRY_VOL_H6) + " 5h-Vol")
    print("  Stop -" + str(int(HARD * 100)) + "% | Trail " + str(int(TRAIL * 100)) +
          "% | Slippage " + str(int(ENTRY_SLIP * 100)) + "%/Seite | Rug<$" + str(RUG_LIQ))
    print("  v2: 1h-Mom " + str(int(ENTRY_MOM)) + "-" + str(int(ENTRY_MAX_CHG1)) +
          "% | Anti-Chase 5m<=" + str(ENTRY_MAX_CHG5) + "% | Break-Even ab +" +
          str(int(BE_TRIGGER * 100)) + "%")
    print("=" * 58)

    state = {"bankroll": START_BANKROLL, "positions": {}, "traded": []}
    if os.path.exists(PSTATE):
        try:
            state = json.load(open(PSTATE))
            state.setdefault("traded", [])
            for _p in state.get("positions", {}).values():   # alte/partielle State-Files absichern
                _p.setdefault("peak", _p.get("entry", 0))
                _p.setdefault("last_price", _p.get("entry", 0))
                _p.setdefault("realized", 0.0)
                _p.setdefault("scaled", False)
                _p.setdefault("rug_misses", 0)
            print("[STATE] wiederhergestellt: Bankroll $" + str(round(state["bankroll"], 2)) +
                  ", " + str(len(state["positions"])) + " offene Wetten")
        except Exception:
            pass
    trades = []
    if os.path.exists(PTRADES):
        try:
            trades = json.load(open(PTRADES))
        except Exception:
            pass

    state.setdefault("last_summary", time.time())   # erste 6h-Summary erst in 6h (ueberlebt Restarts via State)
    _tg("🛰️ DEX Paper-Moonshot laeuft — Equity $" + str(round(equity(state), 2)) +
        " | offen " + str(len(state["positions"])) + " | Trades " + str(len(trades)))

    cycle = 0
    while True:
        cycle += 1
        try:
            # ── 1. ENTRIES aus der Watchlist (Momentum-Trigger) ──────────────
            wl = {}
            try:
                wl = json.load(open(WATCHLIST))
            except Exception:
                pass
            for addr, t in wl.items():
                if len(state["positions"]) >= MAX_POS or state["bankroll"] < BET:
                    break
                if addr in state["positions"] or addr in state["traded"]:
                    continue
                mom   = t.get("chg1", t.get("chg5", 0)) or 0
                volh6 = t.get("vol_h6", 0) or 0
                chg5  = t.get("chg5", 0) or 0
                if mom < ENTRY_MOM or mom > ENTRY_MAX_CHG1:   # 1h-Momentum im Band: genug Trend, aber nicht schon parabolisch (CALVIN)
                    continue
                if volh6 < ENTRY_VOL_H6:                      # genug 5h-Volumen
                    continue
                if chg5 > ENTRY_MAX_CHG5:                     # v2 Anti-Chase: nicht mitten im 5m-Spike (Top-Kauf)
                    continue
                live = token_now(addr)        # gleiche Live-Quelle wie der Exit -> kein Freshness-Phantom
                if not live or live.get("price", 0) <= 0 or live.get("liq", 0) < RUG_LIQ:
                    continue                  # weg/illiquide/geruggt zwischen Screening und Entry -> nicht kaufen
                price = live["price"]
                fill = price * (1 + ENTRY_SLIP)        # Kauf-Slippage auf LIVE-Preis
                shares = BET / fill
                state["bankroll"] -= BET
                state["positions"][addr] = {
                    "symbol": t.get("symbol", "?"), "entry": fill, "shares": shares,
                    "peak": fill, "last_price": fill, "bet": BET, "realized": 0.0,
                    "scaled": False, "rug_misses": 0,
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                state["traded"].append(addr)
                print("[PAPER-BUY] " + t.get("symbol", "?") + " @ $" +
                      str(price) + " mom=" + str(mom) + "% (fill $" +
                      str(round(fill, 10)) + " inkl. Slippage)")

            # ── 2. EXITS — alle held positions in EINEM Batch-Call (bis 30 Adressen) ──
            held = list(state["positions"].keys())
            batch = tokens_now(held)
            for addr in held:
                pos = state["positions"][addr]
                now = None if batch is None else batch.get(addr, {})   # batch=None -> API-Ausfall; fehlt -> Vanish ({})

                # Transienter API-Ausfall -> diesen Zyklus ueberspringen, NICHT als Rug werten
                if now is None:
                    pos["rug_misses"] = 0
                    continue

                # Echter Vanish ({}) ODER Liquiditaet kollabiert -> erst nach RUG_CONFIRM Polls buchen
                if not now or now.get("liq", 0) < RUG_LIQ:
                    pos["rug_misses"] = pos.get("rug_misses", 0) + 1
                    if pos["rug_misses"] < RUG_CONFIRM:
                        continue
                    crashed = now["price"] if (now and now.get("price", 0) > 0) else pos["last_price"] * RUG_RECOVERY
                    pos["last_price"] = crashed
                    close_paper(state, trades, addr, crashed, "RUG-TOTAL")
                    continue

                pos["rug_misses"] = 0          # gesund -> Bestaetigungs-Zaehler zuruecksetzen
                cur = now["price"]
                pos["last_price"] = cur
                if cur > pos["peak"]:
                    pos["peak"] = cur
                pnl = (cur - pos["entry"]) / pos["entry"] * 100 if pos["entry"] > 0 else 0
                try:
                    age_h = (datetime.now() - datetime.strptime(pos["time"], "%Y-%m-%d %H:%M")).total_seconds() / 3600
                except (ValueError, KeyError):
                    age_h = 0.0

                # House-Money: Einsatz bei +100% sichern (einmal)
                if not pos["scaled"] and pnl >= SCALE_AT * 100:
                    scale_out(state, trades, addr, cur)

                reason = None
                be_armed = pos["peak"] >= pos["entry"] * (1 + BE_TRIGGER)   # war die Position je >= +25%?
                if cur <= pos["entry"] * (1 - HARD):
                    reason = "HARD-STOP"
                elif be_armed and cur <= pos["entry"]:
                    reason = "BREAKEVEN"      # war im Plus, jetzt zurueck am Entry -> Gewinn nicht ins Minus drehen
                elif pos["peak"] > pos["entry"] and cur <= pos["peak"] * (1 - TRAIL):
                    reason = "TRAIL"
                elif age_h >= MAX_HOURS and -20 < pnl < 25:
                    reason = "TIMEOUT"
                if reason:
                    close_paper(state, trades, addr, cur, reason)

            # ── 3. Persist + Heartbeat ───────────────────────────────────────
            if len(state["traded"]) > 1000:
                state["traded"] = state["traded"][-1000:]
            _atomic(PSTATE, state)
            _atomic(PTRADES, trades)
            wins = sum(1 for tr in trades if tr.get("profit", 0) > 0)
            _atomic(PHB, {
                "cycle": cycle, "ts": time.time(),
                "bankroll": round(state["bankroll"], 2), "equity": round(equity(state), 2),
                "open": len(state["positions"]), "trades": len(trades), "wins": wins,
            })
            if cycle % 5 == 1:
                print("[PAPER] Zyklus " + str(cycle) + " | Equity $" +
                      str(round(equity(state), 2)) + " | offen " +
                      str(len(state["positions"])) + " | Trades " + str(len(trades)) +
                      " (" + str(wins) + " Gewinner)")
            # 6h-Telegram-Zusammenfassung
            if time.time() - state.get("last_summary", 0) >= SUMMARY_H * 3600:
                state["last_summary"] = time.time()
                _atomic(PSTATE, state)
                _tg_summary(state, trades)
        except Exception as e:
            print("[PAPER-LOOP] " + str(e))
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    run()
