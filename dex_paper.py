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
# v8 Clone-Support: optionales Variant-Arg -> eigene State-Files + Singleton + Live-Gate-Toggle.
# "baseline" (Default, kein Arg) = unveraendert (v7, monitored). "livegate" = v8 mit Live-Momentum-Gate.
VARIANT   = sys.argv[1] if (len(sys.argv) > 1 and not sys.argv[1].startswith("-")) else "baseline"
_SUF      = "" if VARIANT == "baseline" else "_" + VARIANT
LIVE_GATE = (VARIANT == "livegate")
TUNED     = (VARIANT == "tuned")
SINGLETON = "dex_paper" + _SUF
WATCHLIST = os.path.join(DEX_DIR, "watchlist.json")                 # geteilt (gleicher Markt fuer beide Varianten)
PSTATE    = os.path.join(DEX_DIR, "paper_state"     + _SUF + ".json")
PTRADES   = os.path.join(DEX_DIR, "paper_trades"    + _SUF + ".json")
PHB       = os.path.join(DEX_DIR, "paper_heartbeat" + _SUF + ".json")

# ── Parameter ────────────────────────────────────────────────────────────────
START_BANKROLL = 500.0     # Paper-Kapital (realistische Mini-Kasse)
BET            = 20.0      # $20 Mini-Wette pro Token (kleine Betraege = Strategie)
MAX_POS        = 12        # max gleichzeitige Wetten
ENTRY_MOM      = 12.0      # Trigger: >=12% 1h-Momentum (sustained, kein 5-min-Flash)
ENTRY_VOL_H6   = 5000      # zusaetzlich: >=$5k 6h(~5h)-Volumen — echtes Interesse, kein toter Flash
ENTRY_MIN_LIQ  = 20000     # v5: min $20k Liquiditaet beim Entry — Daten: $20-50k=33% Win vs <$20k=16%
ENTRY_MIN_CHG5 = -5.0      # v5: 5m-Untergrenze — keine aktiv fallenden Coins (chg5<0 = 19% Win, Haupt-EARLY-EXIT-Quelle)
ENTRY_MAX_CHG5 = 25.0      # v5 (war 15): 5m-Obergrenze — Sweet-Spot 0-25% = 27% Win; Kauf-Fenster jetzt [-5,+25]
ENTRY_MAX_CHG1 = 100.0     # v6 zurueck auf 100: chg1->200 ergab 33% Rug-Rate (v5, 5/15) — der Deckel ist ein RUG-FILTER, keine Vorsicht (v4: 0 Rugs/185)
# v9 tuned-Variante (nur wenn VARIANT=="tuned"): Fine-Tuning aus Winner/Loser-Daten (46 Live-Trades)
TUNED_MIN_BS   = 1.5       # min Buy/Sell-Ratio (Winner-Median 1.80 vs Loser 1.46)
TUNED_MIN_CHG5 = 0.0       # nur positives 5m-Momentum (0-25% = 45% WR vs <0% = 31%)
ENTRY_SLIP     = 0.05      # 5% Kauf-Slippage
EXIT_SLIP      = 0.05      # 5% Verkauf-Slippage
HARD           = 0.35      # harter Stop -35% (DEX-Noise verlangt Luft)
TRAIL          = 0.30      # Trailing 30% vom Hoch (Moonshot: Gewinner laufen lassen)
RUG_LIQ        = 2500      # Liquiditaet < $2.5k = gerugged -> Fill zum Ist-Preis (Totalverlust)
RUG_CONFIRM    = 3         # so viele aufeinanderfolgende Rug-Belege noetig (gegen API-Hiccups -> keine Fake-Verluste)
RUG_RECOVERY   = 0.05      # komplett verschwundener Token: Restwert-Annahme (5% = -95%, ehrlich pessimistisch)
SCALE_AT       = 1.00      # v7 DEAKTIVIERT (kein Einsatz-Rausnehmen mehr) — volle Position laeuft, Pyramiding statt Scale-Out
BE_TRIGGER     = 0.25      # ab +25% Peak -> Gewinn-Floor Stufe 1 aktiv
BE_FLOOR       = 0.10      # Floor-Stufe 1: Entry+10% (deckt 5% Exit-Slippage + Buffer ab)
# v7 Pyramiding: zu Gewinnern dazukaufen im rug-freien Fenster (>+25% Peak = 0 Rugs in 300+ Trades); Tranchen SCHRUMPFEN (Turtle-Regel)
PYR_ADD1_AT    = 50.0      # bei +50% vom Ersteinstieg -> Nachkauf 1
PYR_ADD1_BET   = 10.0      # ...$10 (halbe Basis)
PYR_ADD2_AT    = 150.0     # bei +150% -> Nachkauf 2
PYR_ADD2_BET   = 5.0       # ...$5 (viertel Basis)
# v7 ratchetierender Gewinn-Floor (garantierter Mindest-Exit, waechst mit dem Peak)
FLOOR_L2_PEAK  = 100.0     # Peak >=+100% -> Floor +50%
FLOOR_L2_VAL   = 50.0
FLOOR_L3_PEAK  = 200.0     # Peak >=+200% -> Floor +120%
FLOOR_L3_VAL   = 120.0
MAX_HOURS      = 48        # Zeit-Exit fuer Zombies (steht weder hoch noch tief)
POLL_SEC       = 20        # Held-Positionen alle 20s pruefen
EARLY_EXIT_SEC = 180       # v3: Frueh-Exit-Fenster (3 Min = 9 Polls nach Kauf)
EARLY_EXIT_DROP= 12.0      # v3: wenn in den ersten 3 Min schon -12% -> sofort raus (statt -35% abwarten)
TIMEOUT        = 10

STALE_HOURS    = 2.0       # v4 Stale-Swap: nach 2h gehalten ohne je +10% Peak zu sehen
STALE_PEAK     = 10.0      # ...Peak-Schwelle (%)
STALE_PNL      = -5.0      # ...und aktuell im Minus (nicht nur flach)
STALE_VOL_MIN  = 200_000   # frischer Kandidat muss >= $200k 6h-Volumen haben
STALE_FRESH_H  = 1.0       # frischer Kandidat muss in letzter Stunde gesehen worden sein

MAX_POS_PREMIUM = 5        # v4 Premium-Slots: extra Kapazitaet fuer Ausnahme-Kandidaten
PREMIUM_MOM     = 60.0     # Premium: >= 60% 1h-Momentum (Skully/MMGA-Niveau)
PREMIUM_VOL     = 500_000  # Premium: >= $500k 6h-Volumen (echtes Interesse, kein Micro-Cap)

TG_TOKEN   = config.get("telegram_bot_token", "")
TG_CHAT    = config.get("telegram_chat_id", "")
TG_WIN_PCT = 25.0          # Telegram-Alert ab diesem Gewinn-% (Moonshots)
SUMMARY_H  = 3             # Telegram-Zusammenfassung alle 3h


def _tg(msg):
    """Telegram-Nachricht mit Variant-Label vorn (🟦 Baseline / 🟩 Livegate). Graceful ohne Config."""
    if not TG_TOKEN or not TG_CHAT:
        return
    head = ("🟩 <b>Livegate v8</b>\n" if LIVE_GATE
            else "🟨 <b>Tuned v9</b>\n" if TUNED
            else "🟦 <b>Baseline v7</b>\n")
    try:
        requests.post("https://api.telegram.org/bot" + TG_TOKEN + "/sendMessage",
                      data={"chat_id": TG_CHAT, "text": head + msg, "parse_mode": "HTML"}, timeout=TIMEOUT)
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
    pc  = p.get("priceChange") or {}
    return {"price": price, "liq": liq, "chg5": _f(pc.get("m5")), "chg1": _f(pc.get("h1"))}


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


def _has_fresh_candidate(state):
    """True wenn ein frischer, filter-konformer Kandidat in der Watchlist wartet."""
    try:
        wl = json.load(open(WATCHLIST))
    except Exception:
        return False
    held   = set(state["positions"])
    traded = set()
    for t in state.get("traded", []):
        if isinstance(t, dict): traded.add(t.get("addr", ""))
        elif isinstance(t, str): traded.add(t)
    now = datetime.now()
    for addr, t in wl.items():
        if addr in held or addr in traded:
            continue
        chg1  = t.get("chg1", 0)
        chg5  = t.get("chg5", 0)
        volh6 = t.get("vol_h6", 0)
        if chg1 < ENTRY_MOM or chg1 > ENTRY_MAX_CHG1:
            continue
        if chg5 > ENTRY_MAX_CHG5 or chg5 < ENTRY_MIN_CHG5:
            continue
        if volh6 < STALE_VOL_MIN:
            continue
        if (t.get("liq", 0) or 0) < ENTRY_MIN_LIQ:
            continue
        try:
            last_seen = datetime.strptime(t.get("last_seen", ""), "%Y-%m-%d %H:%M")
            if (now - last_seen).total_seconds() / 3600 > STALE_FRESH_H:
                continue
        except Exception:
            continue
        return True
    return False


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
        "premium": pos.get("premium", False),
        "adds": (1 if pos.get("added1") else 0) + (1 if pos.get("added2") else 0),
        "bet": pos.get("bet", BET),
        "esnap": pos.get("esnap", {}),
    })
    tag = "💀" if reason == "RUG-TOTAL" else ("🚀" if profit > 0 else "")
    print("[PAPER-CLOSE] " + reason + " " + pos["symbol"] + " " +
          ("+" if pct >= 0 else "") + str(round(pct, 1)) + "% -> $" +
          str(round(profit, 2)) + " " + tag)
    if reason == "RUG-TOTAL":
        _tg("💀 <b>DEX-Rug</b>: " + pos["symbol"] + " " + str(round(pct, 1)) +
            "% = $" + str(round(profit, 2)) + " (Screening hat ihn durchgelassen)")
    elif reason == "STALE-SWAP":
        try:
            _age_h = (datetime.now() - datetime.strptime(pos["time"], "%Y-%m-%d %H:%M")).total_seconds() / 3600
        except Exception:
            _age_h = 0
        _tg("🔄 <b>DEX Stale-Swap</b>: " + pos["symbol"] + " " + str(round(pct, 1)) +
            "% nach " + str(round(_age_h, 1)) + "h — Slot frei fuer frischen Kandidaten")
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


def pyramid(state, pos, price, add_bet, tag):
    """v7: auf Staerke nachlegen — kleinere Tranche zum Live-Preis, Ø-Einstieg steigt.
    True wenn nachgelegt (genug Bankroll), sonst False (naechster Zyklus erneut)."""
    if state["bankroll"] < add_bet:
        return False
    fill = price * (1 + ENTRY_SLIP)
    add_shares = add_bet / fill
    total_cost = pos["entry"] * pos["shares"] + fill * add_shares
    pos["shares"] += add_shares
    pos["bet"]    += add_bet
    pos["entry"]   = total_cost / pos["shares"] if pos["shares"] > 0 else pos["entry"]
    state["bankroll"] -= add_bet
    print("[PAPER-PYRAMID] " + pos["symbol"] + " Nachkauf" + tag + " $" +
          str(add_bet) + " @ $" + str(price) + " -> avg-Entry $" + str(round(pos["entry"], 10)))
    g = (price / pos.get("entry0", price) - 1) * 100 if pos.get("entry0") else 0
    _tg("📈 <b>Pyramide</b> — " + pos["symbol"] + ": Nachkauf" + tag + " +$" + str(int(add_bet)) +
        " bei <b>+" + str(round(g)) + "%</b>\nEinsatz jetzt $" + str(int(pos["bet"])) +
        " · Position läuft weiter (avg-Entry steigt)")
    return True


def floor_pct_for(peak_pct):
    """v7: ratchetierender Gewinn-Floor — garantierter Mindest-Exit je Peak-Stufe."""
    if peak_pct >= FLOOR_L3_PEAK:
        return FLOOR_L3_VAL
    if peak_pct >= FLOOR_L2_PEAK:
        return FLOOR_L2_VAL
    if peak_pct >= BE_TRIGGER * 100:
        return BE_FLOOR * 100
    return 0.0


def equity(state):
    open_val = sum(p["shares"] * p.get("last_price", p["entry"]) for p in state["positions"].values())
    return state["bankroll"] + open_val


def _tg_summary(state, trades):
    from collections import Counter
    eq   = equity(state)
    n    = len(trades)
    wins = sum(1 for tr in trades if tr.get("profit", 0) > 0)
    rugs = sum(1 for tr in trades if tr.get("reason") == "RUG-TOTAL")
    wr   = (wins / n * 100) if n else 0
    net  = sum(tr.get("profit", 0) for tr in trades)
    best = max((tr.get("pct", 0) for tr in trades), default=0)
    worst= min((tr.get("pct", 0) for tr in trades), default=0)
    mix  = Counter(tr.get("reason", "?") for tr in trades)
    mix_str = " · ".join(k + ":" + str(v) for k, v in mix.most_common(4)) if mix else "—"
    opos = state.get("positions", {})
    op_lines = []
    for p in sorted(opos.values(),
                    key=lambda x: (x.get("last_price", x["entry"]) / x["entry"] - 1) if x["entry"] else 0,
                    reverse=True)[:5]:
        pct = (p.get("last_price", p["entry"]) / p["entry"] - 1) * 100 if p["entry"] > 0 else 0
        op_lines.append("  " + p.get("symbol", "?") + " " + ("%+.0f" % pct) + "%" +
                        (" ⚡pyr" if p.get("added1") else ""))
    op_str = ("\n" + "\n".join(op_lines)) if op_lines else " —"
    _tg("🛰️ <b>6h-Übersicht</b>\n"
        "💰 Equity <b>$" + str(round(eq, 2)) + "</b> (" +
        ("%+.1f" % ((eq / START_BANKROLL - 1) * 100)) + "% · Netto $" + ("%+.0f" % net) + ")\n"
        "📊 " + str(n) + " Trades · WR <b>" + str(round(wr)) + "%</b> · 💀 " + str(rugs) + " Rugs\n"
        "🏆 Bester +" + str(round(best)) + "% · Schlechtester " + str(round(worst)) + "%\n"
        "🎯 Exits: " + mix_str + "\n"
        "📈 Offen (" + str(len(opos)) + "):" + op_str)


def run():
    print("=" * 58)
    print("  DEX PAPER-MOONSHOT — kein Geld, REALISTISCH (Slippage+Rugs)")
    print("  Bankroll $" + str(START_BANKROLL) + " | Wette $" + str(BET) +
          " | Entry >=" + str(ENTRY_MOM) + "% 1h-Mom + >=$" + str(ENTRY_VOL_H6) + " 5h-Vol")
    print("  Stop -" + str(int(HARD * 100)) + "% | Trail " + str(int(TRAIL * 100)) +
          "% | Slippage " + str(int(ENTRY_SLIP * 100)) + "%/Seite | Rug<$" + str(RUG_LIQ))
    print("  v7: 1h-Mom " + str(int(ENTRY_MOM)) + "-" + str(int(ENTRY_MAX_CHG1)) +
          "% | 5m-Fenster " + str(int(ENTRY_MIN_CHG5)) + ".." + str(int(ENTRY_MAX_CHG5)) +
          "% | Liq>=$" + str(int(ENTRY_MIN_LIQ / 1000)) + "k | Early-Exit -" +
          str(int(EARLY_EXIT_DROP)) + "%/" + str(EARLY_EXIT_SEC) + "s")
    print("  v7 NEU: Pyramide +$" + str(int(PYR_ADD1_BET)) + "@+" + str(int(PYR_ADD1_AT)) +
          "% /+$" + str(int(PYR_ADD2_BET)) + "@+" + str(int(PYR_ADD2_AT)) +
          "% | Scale-Out AUS | Gewinn-Floor +10/+50/+120%@Peak+25/+100/+200% | ProgTrail 30/25/20/15%")
    _gate = ("AN (v8 LIVE-Momentum)" if LIVE_GATE
             else "TUNED v9 (Buy/Sell>=" + str(TUNED_MIN_BS) + " & chg5>=" + str(TUNED_MIN_CHG5) + ")" if TUNED
             else "AUS (v7-baseline)")
    print("  VARIANTE: " + VARIANT + " | Gate: " + _gate + " | State: " + os.path.basename(PSTATE))
    print("  Slots: " + str(MAX_POS) + " normal + " + str(MAX_POS_PREMIUM) +
          " Premium (>=" + str(int(PREMIUM_MOM)) + "% mom + $" + str(int(PREMIUM_VOL/1000)) + "k vol) | Stale-Swap >" +
          str(STALE_HOURS) + "h / Peak<" + str(int(STALE_PEAK)) + "%")
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
                _p.setdefault("entry0", _p.get("entry", 0))
                _p.setdefault("added1", False)
                _p.setdefault("added2", False)
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
                n_pos = len(state["positions"])
                if n_pos >= MAX_POS + MAX_POS_PREMIUM or state["bankroll"] < BET:
                    break
                if addr in state["positions"] or addr in state["traded"]:
                    continue
                mom   = t.get("chg1", t.get("chg5", 0)) or 0
                volh6 = t.get("vol_h6", 0) or 0
                chg5  = t.get("chg5", 0) or 0
                liq   = t.get("liq", 0) or 0
                if mom < ENTRY_MOM or mom > ENTRY_MAX_CHG1:   # 1h-Momentum im Band 12-200%: Trend, aber nicht extrem-parabolisch
                    continue
                if volh6 < ENTRY_VOL_H6:                      # genug 5h-Volumen
                    continue
                if liq < ENTRY_MIN_LIQ:                       # v5: Liquiditaets-Floor ($20k+ verdoppelt die Win-Rate)
                    continue
                if chg5 > ENTRY_MAX_CHG5 or chg5 < ENTRY_MIN_CHG5:   # v5: 5m-Fenster [-5,+25] — kein Top-Kauf UND kein fallender Dip
                    continue
                if TUNED:
                    # v9 Fine-Tuning (Winner/Loser-Daten): mehr Kaufdruck + nur positives 5m-Momentum
                    if (t.get("buys", 0) or 0) / max(t.get("sells", 0) or 0, 1) < TUNED_MIN_BS:
                        continue
                    if chg5 < TUNED_MIN_CHG5:
                        continue
                # v4 Premium-Slots: normaler Slot voll -> nur Premium-Kandidaten (>=60% mom + $500k vol)
                is_premium = (mom >= PREMIUM_MOM and volh6 >= PREMIUM_VOL)
                if n_pos >= MAX_POS and not is_premium:
                    continue
                live = token_now(addr)        # gleiche Live-Quelle wie der Exit -> kein Freshness-Phantom
                if not live or live.get("price", 0) <= 0 or live.get("liq", 0) < RUG_LIQ:
                    continue                  # weg/illiquide/geruggt zwischen Screening und Entry -> nicht kaufen
                if LIVE_GATE:
                    # v8: Momentum+Liq LIVE gegenpruefen — die Watchlist-Werte sind im Schnitt ~18h alt!
                    lc1 = live.get("chg1", 0); lc5 = live.get("chg5", 0)
                    if lc1 < ENTRY_MOM or lc1 > ENTRY_MAX_CHG1:      # 1h-Momentum JETZT nicht mehr im Band
                        continue
                    if lc5 > ENTRY_MAX_CHG5 or lc5 < ENTRY_MIN_CHG5:  # 5m JETZT ausserhalb [-5,+25]
                        continue
                    if live.get("liq", 0) < ENTRY_MIN_LIQ:           # Liq JETZT zu duenn
                        continue
                price = live["price"]
                fill = price * (1 + ENTRY_SLIP)        # Kauf-Slippage auf LIVE-Preis
                shares = BET / fill
                state["bankroll"] -= BET
                state["positions"][addr] = {
                    "symbol": t.get("symbol", "?"), "entry": fill, "entry0": fill, "shares": shares,
                    "peak": fill, "last_price": fill, "bet": BET, "realized": 0.0,
                    "scaled": False, "rug_misses": 0, "added1": False, "added2": False,
                    "entry_ts": time.time(),                       # v3: Frueh-Exit-Uhr
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "premium": is_premium,
                    "esnap": {"chg1": round(mom, 1), "chg5": round(chg5, 1), "liq": int(liq),
                              "buys": t.get("buys", 0) or 0, "sells": t.get("sells", 0) or 0,
                              "vol_h6": int(volh6), "age_h": t.get("age_h", 0)},
                }
                state["traded"].append(addr)
                slot_tag = " [PREMIUM 🌟]" if is_premium else ""
                print("[PAPER-BUY] " + t.get("symbol", "?") + " @ $" +
                      str(price) + " mom=" + str(mom) + "% (fill $" +
                      str(round(fill, 10)) + " inkl. Slippage)" + slot_tag)
                if is_premium:
                    _tg("🌟 <b>DEX Premium-Entry</b>: " + t.get("symbol", "?") +
                        " | mom=" + str(round(mom, 1)) + "% | vol=$" +
                        str(int(volh6 / 1000)) + "k — Extra-Slot genutzt")

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

                # v7: Pyramiding statt Scale-Out — auf Staerke nachlegen (Tranchen schrumpfen),
                # im rug-freien Fenster (Daten: 0 Rugs ueber +25% Peak). Trigger vom Ersteinstieg.
                e0 = pos.get("entry0", pos["entry"])
                if not pos.get("added1") and cur >= e0 * (1 + PYR_ADD1_AT / 100):
                    if pyramid(state, pos, cur, PYR_ADD1_BET, "1"):
                        pos["added1"] = True
                elif pos.get("added1") and not pos.get("added2") and cur >= e0 * (1 + PYR_ADD2_AT / 100):
                    if pyramid(state, pos, cur, PYR_ADD2_BET, "2"):
                        pos["added2"] = True
                pnl = (cur - pos["entry"]) / pos["entry"] * 100 if pos["entry"] > 0 else 0   # nach evtl. Nachkauf neu

                reason = None
                # Progressives Trailing: grosse Gewinner enger fassen
                peak_pct_val = (pos["peak"] / pos["entry"] - 1) * 100 if pos["entry"] > 0 else 0
                if peak_pct_val >= 200:
                    trail_now = 0.15
                elif peak_pct_val >= 100:
                    trail_now = 0.20
                elif peak_pct_val >= 50:
                    trail_now = 0.25
                else:
                    trail_now = TRAIL        # 0.30 default

                # v7 ratchetierender Gewinn-Floor (ersetzt Break-Even): garantierter Mindest-Exit je Peak-Stufe
                floor_v = floor_pct_for(peak_pct_val)
                age_s = time.time() - pos.get("entry_ts", time.time())
                if age_s < EARLY_EXIT_SEC and pnl <= -EARLY_EXIT_DROP:
                    reason = "EARLY-EXIT"
                elif floor_v > 0 and cur <= pos["entry"] * (1 + floor_v / 100):
                    reason = "FLOOR"
                elif cur <= pos["entry"] * (1 - HARD):
                    reason = "HARD-STOP"
                elif pos["peak"] > pos["entry"] and cur <= pos["peak"] * (1 - trail_now):
                    reason = "TRAIL"
                elif age_h >= MAX_HOURS and -20 < pnl < 25:
                    reason = "TIMEOUT"
                elif (age_h >= STALE_HOURS
                      and peak_pct_val < STALE_PEAK
                      and pnl < STALE_PNL
                      and _has_fresh_candidate(state)):
                    reason = "STALE-SWAP"
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
    try:
        import health
        if health.acquire_singleton(SINGLETON) is None:
            health.log(SINGLETON, "DUPLICATE_BLOCKED", "")
            print("[SINGLETON] " + SINGLETON + " laeuft bereits — Instanz beendet sich.")
            raise SystemExit(0)
        health.log(SINGLETON, "START", "")
    except SystemExit:
        raise
    except Exception as _e:
        print("[SINGLETON] health n/a: " + str(_e))
    run()
