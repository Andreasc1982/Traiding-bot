#!/usr/bin/env python3
"""
Super-Bot Strenge-Backtest ueber ~10 Jahre ETF-Historie (yfinance).

Frage: Ist der Super Bot zu streng? Er kauft nur, wenn der gewichtete
Indikator-Score >= Schwelle (live: 75% im Trending-Regime). Hier sweepen wir
die Schwelle von 75% bis 25% und messen, ob lockerere Gates real profitabel
traden wuerden — oder nur mehr Verlierer produzieren.

Bildet den ECHTEN gewichteten Score nach:
  RSI*1.5 + MACD*1.5 + ST*1.5 + ICHI*1.2 + MA*1.0 + CMF*0.8 + StochRSI*0.5 + VWAP*0.5
  score_pct = score / 8.5   (VWAP im Tages-Backtest neutral=True)
Exits wie live: SL 2% / TP 12% / Trailing 3% / PSAR-Stop. Fees: 0.02%/Seite.
"""
import sys
sys.path.insert(0, "/home/trading2025/trading_bot/agents")
from optimize_agent import (_rsi_full, _ma20_full, _macd_ok_full,
                            _supertrend_full, _ichimoku_ok_full, _psar_full)

import yfinance as yf

ETFS = ["XLE", "XOP", "XLI", "SLX", "ITA", "XLF", "XLK", "GLD", "PAVE", "IBIT"]
THRESHOLDS = [0.75, 0.65, 0.55, 0.45, 0.35, 0.25]
SL, TP, TRAIL = 0.02, 0.12, 0.03
COST = 0.0002 * 2          # 0.02% Slippage pro Seite (Stocks kommissionsfrei)
WARMUP = 100
MIN_BARS = 78


# ── Zusatz-Indikatoren (CMF, StochRSI) ───────────────────────────────────────
def _cmf_full(highs, lows, closes, vols, period=20):
    n = len(closes); out = [None] * n
    mfv = []
    for i in range(n):
        rng = highs[i] - lows[i]
        mfm = ((2 * closes[i] - highs[i] - lows[i]) / rng) if rng > 0 else 0.0
        mfv.append(mfm * vols[i])
    for i in range(period - 1, n):
        vsum = sum(vols[i - period + 1:i + 1])
        out[i] = (sum(mfv[i - period + 1:i + 1]) / vsum) if vsum > 0 else 0.0
    return out


def _stoch_ok_full(closes, period=14):
    rsi = _rsi_full(closes, period)
    n = len(rsi); stoch = [None] * n
    for i in range(n):
        if rsi[i] is None:
            continue
        window = [r for r in rsi[max(0, i - period + 1):i + 1] if r is not None]
        if len(window) < period:
            continue
        lo, hi = min(window), max(window)
        stoch[i] = (rsi[i] - lo) / (hi - lo) if hi > lo else 0.5
    # %K = SMA3(stoch), %D = SMA3(%K)
    k = [None] * n
    for i in range(n):
        w = [stoch[j] for j in range(max(0, i - 2), i + 1) if stoch[j] is not None]
        if len(w) == 3:
            k[i] = sum(w) / 3
    ok = [False] * n
    for i in range(n):
        w = [k[j] for j in range(max(0, i - 2), i + 1) if k[j] is not None]
        if len(w) == 3 and k[i] is not None:
            d = sum(w) / 3
            ok[i] = (k[i] > d and k[i] < 0.8)
    return ok


def fetch(sym):
    try:
        df = yf.download(sym, period="10y", interval="1d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        def col(name):
            try:
                return [float(x) for x in df[name].values.flatten()]
            except Exception:
                return [float(x) for x in df[(name, sym)].values.flatten()]
        return {"highs": col("High"), "lows": col("Low"),
                "closes": col("Close"), "volumes": col("Volume")}
    except Exception as e:
        print("  " + sym + ": Fehler " + str(e))
        return None


def precompute(bars):
    c, h, l, v = bars["closes"], bars["highs"], bars["lows"], bars["volumes"]
    return {
        "closes": c, "psar": _psar_full(h, l),
        "rsi": _rsi_full(c), "ma20": _ma20_full(c),
        "macd_ok": _macd_ok_full(c), "st": _supertrend_full(h, l, c, 7, 3.5),
        "ichi_ok": _ichimoku_ok_full(h, l, c),
        "cmf": _cmf_full(h, l, c, v), "stoch_ok": _stoch_ok_full(c),
        "n": len(c),
    }


def simulate(pc, threshold):
    n = pc["n"]
    if n < WARMUP + MIN_BARS:
        return None
    c, rsi, ma20 = pc["closes"], pc["rsi"], pc["ma20"]
    macd_ok, st, ichi_ok = pc["macd_ok"], pc["st"], pc["ichi_ok"]
    cmf, stoch_ok, psar = pc["cmf"], pc["stoch_ok"], pc["psar"]

    equity, pos, trades = 1.0, None, []
    for i in range(WARMUP, n):
        price = c[i]
        if pos is not None:
            if price > pos["peak"]:
                pos["peak"] = price
            if psar[i] is not None and psar[i] > pos["psar"]:
                pos["psar"] = psar[i]
            pnl = (price - pos["entry"]) / pos["entry"]
            exit_reason = None
            if price <= pos["entry"] * (1 - SL):
                exit_reason = "SL"
            elif psar[i] is not None and price <= pos["psar"] and pos["psar"] > pos["entry"]:
                exit_reason = "PSAR"
            elif pnl >= TP and price <= pos["peak"] * (1 - TRAIL):
                exit_reason = "TRAIL"
            if exit_reason:
                net = pnl - COST
                trades.append({"pnl": net, "reason": exit_reason})
                equity *= (1 + net)
                pos = None
            continue
        # Entry: gewichteter Score >= Schwelle
        if ma20[i] is None or rsi[i] is None or cmf[i] is None:
            continue
        rsi_ok = rsi[i] < 75
        ma_ok  = c[i] > ma20[i]
        st_ok  = st[i] == 1
        cmf_ok = cmf[i] > 0
        score = (rsi_ok * 1.5 + macd_ok[i] * 1.5 + st_ok * 1.5 + ichi_ok[i] * 1.2 +
                 ma_ok * 1.0 + cmf_ok * 0.8 + stoch_ok[i] * 0.5 + 1 * 0.5)  # VWAP neutral
        if score / 8.5 >= threshold:
            pos = {"entry": price, "peak": price, "psar": psar[i] or price}
    if pos is not None:
        net = (c[-1] - pos["entry"]) / pos["entry"] - COST
        trades.append({"pnl": net, "reason": "OPEN"})
        equity *= (1 + net)
    if not trades:
        return {"ret": 0.0, "wr": 0.0, "n": 0, "mdd": 0.0, "pf": 0.0}
    wins = sum(1 for t in trades if t["pnl"] > 0)
    gains = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    losses = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    # Max drawdown der Equity-Kurve
    eq, peak, mdd = 1.0, 1.0, 0.0
    for t in trades:
        eq *= (1 + t["pnl"]); peak = max(peak, eq); mdd = max(mdd, (peak - eq) / peak)
    return {"ret": (equity - 1) * 100, "wr": wins / len(trades) * 100,
            "n": len(trades), "mdd": mdd * 100,
            "pf": (gains / losses) if losses > 0 else 999.0}


def main():
    print("Lade 10J ETF-Daten...")
    pcs = {}
    for s in ETFS:
        b = fetch(s)
        if b:
            pc = precompute(b)
            if pc["n"] >= WARMUP + MIN_BARS:
                pcs[s] = pc
                print("  " + s + ": " + str(pc["n"]) + " Tagesbars")
            else:
                print("  " + s + ": nur " + str(pc["n"]) + " Bars — uebersprungen")
    print()
    print("=" * 78)
    print("  SUPER-BOT STRENGE-BACKTEST  (" + str(len(pcs)) + " ETFs, ~10 Jahre, fee-aware)")
    print("=" * 78)
    print("{:>10} | {:>9} | {:>7} | {:>8} | {:>8} | {:>6}".format(
        "Schwelle", "Ø Return", "Ø WR", "Trades", "Ø MaxDD", "Ø PF"))
    print("-" * 78)
    results = []
    for th in THRESHOLDS:
        rs = [simulate(pc, th) for pc in pcs.values()]
        rs = [r for r in rs if r]
        if not rs:
            continue
        avg_ret = sum(r["ret"] for r in rs) / len(rs)
        avg_wr  = sum(r["wr"]  for r in rs) / len(rs)
        tot_n   = sum(r["n"]   for r in rs)
        avg_mdd = sum(r["mdd"] for r in rs) / len(rs)
        avg_pf  = sum(min(r["pf"], 10) for r in rs) / len(rs)
        tag = "  <- LIVE" if abs(th - 0.75) < 0.01 else ""
        print("{:>9.0f}% | {:>+8.1f}% | {:>6.1f}% | {:>8} | {:>7.1f}% | {:>6.2f}{}".format(
            th * 100, avg_ret, avg_wr, tot_n, avg_mdd, avg_pf, tag))
        results.append((th, avg_ret, avg_wr, tot_n, avg_mdd))
    print("=" * 78)
    print("Lesart: Ø Return = mittlere Gesamtrendite pro ETF ueber 10J (fee-aware).")
    print("        'LIVE' = aktuelle Strenge des Super Bots (75%).")


if __name__ == "__main__":
    main()
