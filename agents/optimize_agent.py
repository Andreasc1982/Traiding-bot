#!/usr/bin/env python3
"""
Optimization Agent — weekly parameter optimizer for both trading bots.

Runs automatically every Sunday at 00:00. Four analysis phases:
  1. Trade-history audit  — profitability, win rate, exit-reason breakdown per symbol
  2. Indicator block audit — which gates block the most entries (from skip-log snapshot)
  3. False-signal audit    — stop-loss rate as proxy for bad-entry rate per symbol
  4. Walk-forward optimization — RSI threshold × Supertrend mult × SL% × TP%
                             rolling in-sample grid-search → out-of-sample validation
                             on multi-year daily bars. Sortino-scored. Reports the
                             HONEST out-of-sample performance + parameter stability
                             across folds (only stable params are recommended).

Outputs:
  ~/trading_bot/agents/optimize_results.json  — full machine-readable results
  ~/trading_bot/agents/optimize_log.txt       — timestamped run log
  Telegram                                    — weekly HTML report

Usage:
  python3 optimize_agent.py           # waits for next Sunday 00:00
  python3 optimize_agent.py --now     # run analysis immediately and exit
"""

import os, sys, json, time, math, requests, argparse
from datetime import datetime, timedelta
from collections import defaultdict

# ── Config / paths ──────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
try:
    from config import config
except ImportError:
    config = {}

TELEGRAM_TOKEN   = config.get("telegram_bot_token", "")
TELEGRAM_CHAT_ID = config.get("telegram_chat_id", "")
ALPACA_KEY       = config.get("alpaca_api_key", "")
ALPACA_SECRET    = config.get("alpaca_secret_key", "")

BASE_DIR     = "/home/trading2025/trading_bot"
AGENTS_DIR   = os.path.join(BASE_DIR, "agents")
SUPER_HIST   = os.path.join(BASE_DIR, "trades_history.json")
CRYPTO_HIST  = os.path.join(BASE_DIR, "crypto", "trades_history.json")
SUPER_DASH   = os.path.join(BASE_DIR, "dashboard.json")
CRYPTO_DASH  = os.path.join(BASE_DIR, "crypto", "crypto_dashboard.json")
RESULTS_FILE = os.path.join(AGENTS_DIR, "optimize_results.json")
LOG_FILE     = os.path.join(AGENTS_DIR, "optimize_log.txt")

DATA_URL = "https://data.alpaca.markets"

# ── Bot universes ────────────────────────────────────────────────────────────────

ETF_SYMBOLS = ["XLE", "XOP", "XLI", "SLX", "ITA", "XLF", "XLK", "GLD", "PAVE", "IBIT"]
CRYPTO_SYMBOLS = [
    "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "AVAX/USD",
    "LINK/USD", "LTC/USD", "DOGE/USD", "SHIB/USD",
]  # PEPE/WIF excluded — often no Alpaca data for recent periods

# Current live parameters — READ DYNAMICALLY from the bot source so the
# "current vs suggested" diffs are always correct (no more stale hardcodes).
SUPER_BOT_PATH  = "/home/trading2025/trading_bot/super_bot.py"
CRYPTO_BOT_PATH = "/home/trading2025/trading_bot/crypto/crypto_bot.py"

def _read_current_params(path, defaults):
    """Regex-read the live params from a bot file. Defaults = correct current
    values, used as fallback if a pattern does not match."""
    import re
    p = dict(defaults)
    try:
        with open(path) as f:
            src = f.read()
        m = re.search(r"self\.stop_loss\s*=\s*([\d.]+)", src)
        if m: p["stop_loss"] = float(m.group(1))
        m = re.search(r"self\.take_profit\s*=\s*([\d.]+)", src)
        if m: p["take_profit"] = float(m.group(1))
        m = re.search(r'ind\["rsi"\]\s*<\s*(\d+)', src)
        if m: p["rsi_threshold"] = int(m.group(1))
        m = re.search(r"hl2\s*\+\s*([\d.]+)\s*\*\s*st_atr", src)
        if m: p["st_mult"] = float(m.group(1))
        m = re.search(r"self\.trailing_stop\s*=\s*([\d.]+)", src)
        if m: p["trailing_stop"] = float(m.group(1))
    except Exception as e:
        print("[OPT] Parameter-Read fehlgeschlagen (" + path + "): " + str(e))
    return p

SUPER_BASELINE = _read_current_params(SUPER_BOT_PATH, {
    "rsi_threshold": 75, "st_mult": 4.0,
    "stop_loss": 2.0, "take_profit": 12.0, "trailing_stop": 3.0,
})
CRYPTO_BASELINE = _read_current_params(CRYPTO_BOT_PATH, {
    "rsi_threshold": 65, "st_mult": 3.5,
    "stop_loss": 2.5, "take_profit": 5.0, "trailing_stop": 1.5,
})

MIN_BARS = 78   # Ichimoku minimum (52 lookback + 26 displacement)

# ── Walk-forward config ────────────────────────────────────────────────────────
WARMUP          = 100    # bars of history before trading starts (indicator warmup)
MIN_WINDOW_BARS = 20     # minimum bars in a sim window to be meaningful
SORTINO_CAP     = 5.0    # cap Sortino so degenerate (few-trade) combos can't dominate
STABILITY_MIN   = 0.5    # a param axis' mode must win ≥50% of folds to be a candidate
WF_IS_LEN       = 252    # in-sample (train) window ≈ 1 trading year
WF_OOS_LEN      = 63     # out-of-sample (test) window ≈ 1 quarter (also the step)
MIN_OOS_SORTINO_GAIN = 0.15  # adopt new params only on a real OOS Sortino gain (not noise)
MIN_OOS_RETURN_GAIN  = 0.0   # …and only if OOS return does not drop

# ── Utilities ────────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    # Telegram limit is 4096 chars; split long messages
    for i in range(0, len(msg), 3800):
        chunk = msg[i:i + 3800]
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID,
                                     "text": chunk, "parse_mode": "HTML"},
                          timeout=10)
            time.sleep(0.3)
        except Exception as e:
            log(f"[TG] send error: {e}")

def _hdrs():
    return {"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET}

# ── Alpaca bar fetching ──────────────────────────────────────────────────────────

def fetch_stock_bars(symbols, days=275):
    """Fetch daily adjusted bars for ETF symbols. Returns {sym: [bar, ...]}."""
    start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    end   = datetime.utcnow().strftime("%Y-%m-%d")
    result = defaultdict(list)
    page_token = None
    url = DATA_URL + "/v2/stocks/bars"
    for _ in range(10):
        params = {
            "symbols": ",".join(symbols), "timeframe": "1Day",
            "start": start, "end": end, "limit": 10000,
            "adjustment": "all", "feed": "iex",
        }
        if page_token:
            params["page_token"] = page_token
        try:
            r = requests.get(url, headers=_hdrs(), params=params, timeout=30)
            r.raise_for_status()
        except Exception as e:
            log(f"  [fetch_stock] error: {e}")
            break
        data = r.json()
        for sym, bars in data.get("bars", {}).items():
            for b in bars:
                result[sym].append({"t": b["t"][:10],
                                    "h": b["h"], "l": b["l"],
                                    "c": b["c"], "v": b["v"]})
        page_token = data.get("next_page_token")
        if not page_token:
            break
        time.sleep(0.2)
    return dict(result)

def fetch_crypto_bars_daily(symbols, days=1100):
    """Fetch daily bars for crypto symbols. Returns {sym: [bar, ...]}."""
    start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    end   = datetime.utcnow().strftime("%Y-%m-%d")
    result = defaultdict(list)
    page_token = None
    url = DATA_URL + "/v1beta3/crypto/us/bars"
    for _ in range(10):
        params = {
            "symbols": ",".join(symbols),   # requests handles URL encoding; don't pre-encode
            "timeframe": "1Day", "start": start, "end": end, "limit": 10000,
        }
        if page_token:
            params["page_token"] = page_token
        try:
            r = requests.get(url, headers=_hdrs(), params=params, timeout=30)
            r.raise_for_status()
        except Exception as e:
            log(f"  [fetch_crypto] error: {e}")
            break
        data = r.json()
        for sym, bars in data.get("bars", {}).items():
            for b in bars:
                result[sym].append({"t": b["t"][:10],
                                    "h": b["h"], "l": b["l"],
                                    "c": b["c"], "v": b["v"]})
        page_token = data.get("next_page_token")
        if not page_token:
            break
        time.sleep(0.2)
    return dict(result)

def fetch_stock_bars_yf(symbols, years=4):
    """Fetch daily adjusted ETF bars via yfinance. Preferred over Alpaca because the
    Alpaca paper account returns null stock bars (known gotcha) and yfinance gives
    reliable multi-year history — needed for meaningful walk-forward folds.
    Returns {sym: [bar, ...]} oldest→newest."""
    try:
        import yfinance as yf
    except Exception as e:
        log(f"  [yf] yfinance nicht verfügbar: {e}")
        return {}
    result = {}
    for sym in symbols:
        try:
            df = yf.download(sym, period=f"{years}y", interval="1d",
                             auto_adjust=True, progress=False)
            if df is None or len(df) == 0:
                log(f"    {sym}: keine yfinance-Daten")
                continue
            multi = hasattr(df.columns, "levels")   # single-symbol → MultiIndex
            def _col(name):
                return df[(name, sym)] if multi else df[name]
            highs  = _col("High").tolist()
            lows   = _col("Low").tolist()
            closes = _col("Close").tolist()
            vols   = _col("Volume").tolist()
            dates  = [d.strftime("%Y-%m-%d") for d in df.index]
            bars = []
            for i in range(len(dates)):
                c, h, l, v = closes[i], highs[i], lows[i], vols[i]
                if not (c > 0 and h > 0 and l > 0):   # skip NaN / bad rows
                    continue
                if v != v:                            # NaN volume → 0
                    v = 0.0
                bars.append({"t": dates[i], "h": float(h), "l": float(l),
                             "c": float(c), "v": float(v)})
            if bars:
                result[sym] = bars
        except Exception as e:
            log(f"    [yf {sym}] error: {e}")
    return result

# ── Indicator engine (parameterized) ────────────────────────────────────────────

def _ema_series(values, period):
    """Exponential moving average. Returns full series."""
    k   = 2.0 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out

def _rsi_full(closes, period=14):
    """Compute RSI for every bar using Wilder smoothing. Returns list[float]."""
    n = len(closes)
    rsi = [50.0] * n
    if n <= period:
        return rsi
    diffs  = [closes[i] - closes[i-1] for i in range(1, n)]
    gains  = [max(d, 0.0) for d in diffs]
    losses = [max(-d, 0.0) for d in diffs]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    rsi[period] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0
    for i in range(period, len(diffs)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
        rsi[i + 1] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0
    return rsi

def _supertrend_full(highs, lows, closes, period=7, mult=3.5):
    """Supertrend direction array (+1 bullish, -1 bearish) for all bars."""
    n = len(closes)
    atr = [highs[0] - lows[0]] + [
        max(highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i]  - closes[i-1]))
        for i in range(1, n)
    ]
    # Wilder ATR
    for i in range(1, n):
        atr[i] = (atr[i-1] * (period - 1) + atr[i]) / period

    ub     = [0.0] * n
    lb     = [0.0] * n
    st_dir = [1]   * n
    for i in range(period - 1, n):
        hl2  = (highs[i] + lows[i]) / 2
        b_ub = hl2 + mult * atr[i]
        b_lb = hl2 - mult * atr[i]
        if i == period - 1:
            ub[i], lb[i] = b_ub, b_lb
        else:
            ub[i] = b_ub if b_ub < ub[i-1] or closes[i-1] > ub[i-1] else ub[i-1]
            lb[i] = b_lb if b_lb > lb[i-1] or closes[i-1] < lb[i-1] else lb[i-1]
            st_dir[i] = (-1 if closes[i] < lb[i] else 1) if st_dir[i-1] == 1 \
                        else (1 if closes[i] > ub[i] else -1)
    return st_dir

def _psar_full(highs, lows, af0=0.02, af_max=0.20):
    """Parabolic SAR for all bars. Returns list[float]."""
    n = len(highs)
    psar   = [0.0] * n
    rising = True
    sar, ep, af = lows[0], highs[0], af0
    psar[0] = sar
    for i in range(1, n):
        prev = sar
        if rising:
            sar = prev + af * (ep - prev)
            sar = min(sar, lows[i-1], lows[i-2] if i >= 2 else lows[i-1])
            if lows[i] < sar:
                rising = False; sar = ep; ep = lows[i]; af = af0
            else:
                if highs[i] > ep: ep = highs[i]; af = min(af + af0, af_max)
        else:
            sar = prev + af * (ep - prev)
            sar = max(sar, highs[i-1], highs[i-2] if i >= 2 else highs[i-1])
            if highs[i] > sar:
                rising = True; sar = ep; ep = highs[i]; af = af0
            else:
                if lows[i] < ep: ep = lows[i]; af = min(af + af0, af_max)
        psar[i] = sar
    return psar

def _ichimoku_ok_full(highs, lows, closes):
    """Pre-compute Ichimoku cloud-above bool for every bar. O(n) per bar."""
    n = len(closes)
    ok = [False] * n
    for i in range(77, n):
        h = highs[i-77:i+1]   # 78 bars (indices i-77..i inclusive)
        l = lows [i-77:i+1]
        # t26/k26 are as-of 26 bars ago within the window (index 52 of 78-bar slice)
        t26_pos = 52 - 9        # start of 9-bar tenkan window ending at index 51
        k26_pos = 52 - 26       # start of 26-bar kijun window ending at index 51
        tenkan_26ago = (max(h[t26_pos:52]) + min(l[t26_pos:52])) / 2
        kijun_26ago  = (max(h[k26_pos:52]) + min(l[k26_pos:52])) / 2
        span_a = (tenkan_26ago + kijun_26ago) / 2
        span_b = (max(h[:52]) + min(l[:52])) / 2
        ok[i]  = closes[i] > max(span_a, span_b)
    return ok

def _ma20_full(closes):
    """20-bar SMA for all bars. Returns list (None for i < 19)."""
    n = len(closes)
    ma = [None] * n
    s  = sum(closes[:20]) if n >= 20 else 0
    if n >= 20:
        ma[19] = s / 20
        for i in range(20, n):
            s += closes[i] - closes[i-20]
            ma[i] = s / 20
    return ma

def _obv_ok_full(closes, volumes):
    """OBV rising-over-10-bars flag for all bars. Returns list[bool]."""
    n   = len(closes)
    obv = [0.0]
    for i in range(1, n):
        d = closes[i] - closes[i-1]
        obv.append(obv[-1] + (volumes[i] if d > 0 else -volumes[i] if d < 0 else 0))
    ok       = [False] * n
    avg20sum = sum(volumes[:20]) if n >= 20 else sum(volumes)
    for i in range(11, n):
        if i >= 20:
            avg20sum += volumes[i] - volumes[i-20]
            avg20 = avg20sum / 20
        else:
            avg20 = avg20sum / (i + 1)
        ok[i] = (obv[i] > obv[i-10]) or (volumes[i] > avg20 * 0.5)
    return ok

def _macd_ok_full(closes):
    """MACD > signal line flag for all bars. Returns list[bool]."""
    n = len(closes)
    if n < 35:
        return [False] * n
    ema12  = _ema_series(closes, 12)
    ema26  = _ema_series(closes, 26)
    # ema12 starts at index 11, ema26 at index 25 — align by offsetting
    macd   = [ema12[i + 14] - ema26[i] for i in range(len(ema26))]
    sig    = _ema_series(macd, 9)
    # macd/sig series starts at bar index 25; prepend False for first 25+8=33 bars
    offset = 26 + 8   # 26 for ema26 warmup, 8 for signal warmup
    result = [False] * min(offset, n)
    for i in range(len(sig)):
        result.append(macd[i] > sig[i])
    return result[:n]

def precompute(bars, st_mult_list):
    """
    One-pass pre-computation of all indicators for a symbol.
    bars: list of {"t","h","l","c","v"} oldest→newest
    st_mult_list: list of multiplier values to pre-compute Supertrend for

    Returns dict with per-bar arrays (all same length as bars).
    """
    highs   = [b["h"] for b in bars]
    lows    = [b["l"] for b in bars]
    closes  = [b["c"] for b in bars]
    volumes = [b["v"] for b in bars]
    n = len(bars)

    st_dirs = {}
    for m in st_mult_list:
        st_dirs[m] = _supertrend_full(highs, lows, closes, period=7, mult=m)

    return {
        "n":         n,
        "closes":    closes,
        "highs":     highs,
        "lows":      lows,
        "volumes":   volumes,
        "rsi":       _rsi_full(closes),
        "ma20":      _ma20_full(closes),
        "macd_ok":   _macd_ok_full(closes),
        "obv_ok":    _obv_ok_full(closes, volumes),
        "ichi_ok":   _ichimoku_ok_full(highs, lows, closes),
        "psar":      _psar_full(highs, lows),
        "st_dirs":   st_dirs,
    }

# ── Mini simulator (uses pre-computed indicator arrays) ──────────────────────────

def simulate(pc, params, start=None, end=None, cost=0.0):
    """
    Simulate a single symbol with given parameters over the bar window [start, end)
    using pre-computed indicators. `start` must be ≥ WARMUP so indicators are stable.
    Returns performance dict (incl. Sortino) or None if the window is too small.

    Gates used:  RSI<threshold · price>MA20 · MACD bullish · Supertrend+1 · OBV rising · Ichimoku
    Stops:       fixed SL% OR PSAR (whichever fires first) · trailing TP%
    No max_pos limit — single-symbol simulation.
    """
    n = pc["n"]
    if start is None:
        start = WARMUP
    if end is None or end > n:
        end = n
    if end - start < MIN_WINDOW_BARS:
        return None

    rsi_th   = params["rsi_threshold"]
    st_mult  = params["st_mult"]
    sl_pct   = params["stop_loss"]   / 100.0
    tp_pct   = params["take_profit"] / 100.0
    trail    = params["trailing_stop"] / 100.0

    st_dirs  = pc["st_dirs"].get(st_mult)
    if st_dirs is None:
        return None

    closes  = pc["closes"]
    rsi     = pc["rsi"]
    ma20    = pc["ma20"]
    macd_ok = pc["macd_ok"]
    obv_ok  = pc["obv_ok"]
    ichi_ok = pc["ichi_ok"]
    psar    = pc["psar"]

    equity   = 1.0
    position = None   # {"entry": float, "peak": float, "psar_stop": float}
    trades   = []

    for i in range(start, end):
        price = closes[i]

        if position is not None:
            entry      = position["entry"]
            peak       = position["peak"]
            psar_stop  = position["psar_stop"]

            # Update trailing peak and ratchet PSAR stop upward
            if price > peak:
                position["peak"] = price
                peak = price
            if psar[i] > psar_stop:
                position["psar_stop"] = psar[i]
                psar_stop = psar[i]

            pnl = (price - entry) / entry

            # Fixed stop-loss
            if price <= entry * (1 - sl_pct):
                trades.append({"pnl": pnl - cost, "reason": "STOP-LOSS"})
                equity  *= (1 + pnl - cost)
                position = None
                continue

            # PSAR stop (only triggers once position has moved up — PSAR ratchets)
            if price <= psar_stop and psar_stop > entry * (1 - sl_pct):
                trades.append({"pnl": pnl - cost, "reason": "PSAR-STOP"})
                equity  *= (1 + pnl - cost)
                position = None
                continue

            # Trailing stop (activates only after take-profit threshold reached)
            if pnl >= tp_pct and price <= peak * (1 - trail):
                trades.append({"pnl": pnl - cost, "reason": "TRAIL-STOP"})
                equity  *= (1 + pnl - cost)
                position = None
            continue   # still in position

        # ── Entry gate (all 6 must pass, no PSAR as gate) ──────────────────────
        if (ma20[i] is not None           and
                closes[i] > ma20[i]       and
                rsi[i]    < rsi_th        and
                macd_ok[i]                and
                st_dirs[i] == 1           and
                obv_ok[i]                 and
                ichi_ok[i]):
            position = {
                "entry":     price,
                "peak":      price,
                "psar_stop": psar[i],   # PSAR at entry as initial stop
            }

    # Close open position at the last bar of the window
    if position is not None:
        pnl = (closes[end - 1] - position["entry"]) / position["entry"]
        trades.append({"pnl": pnl - cost, "reason": "OPEN"})
        equity *= (1 + pnl - cost)

    if not trades:
        return {"return_pct": 0.0, "win_rate": 0.0, "trades": 0,
                "max_drawdown": 0.0, "profit_factor": 0.0, "stop_loss_rate": 0.0,
                "sortino": 0.0}

    wins       = sum(1 for t in trades if t["pnl"] > 0)
    stop_count = sum(1 for t in trades if t["reason"] == "STOP-LOSS")
    gains_sum  = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    loss_sum   = sum(abs(t["pnl"]) for t in trades if t["pnl"] < 0)

    # Sortino ratio (trade-level): mean return / downside deviation. Capped so a
    # combo with 1-2 lucky trades and no losers cannot dominate the ranking.
    rets     = [t["pnl"] for t in trades]
    mean_r   = sum(rets) / len(rets)
    downside = [r for r in rets if r < 0]
    if downside:
        dstd    = (sum(r * r for r in downside) / len(downside)) ** 0.5
        sortino = mean_r / dstd if dstd > 0 else 0.0
    else:
        sortino = SORTINO_CAP           # no losing trades → cap (not infinity)
    sortino = max(-SORTINO_CAP, min(SORTINO_CAP, sortino))

    # Max drawdown from equity curve
    eq_curve  = [1.0]
    for t in trades:
        eq_curve.append(eq_curve[-1] * (1 + t["pnl"]))
    peak_eq = eq_curve[0]
    max_dd  = 0.0
    for e in eq_curve:
        if e > peak_eq:
            peak_eq = e
        dd = (peak_eq - e) / peak_eq if peak_eq > 0 else 0
        if dd > max_dd:
            max_dd = dd

    return {
        "return_pct":     round((equity - 1.0) * 100, 2),
        "win_rate":       round(wins / len(trades) * 100, 1),
        "trades":         len(trades),
        "max_drawdown":   round(max_dd * 100, 2),
        "profit_factor":  round(gains_sum / loss_sum, 2) if loss_sum > 0 else 99.0,
        "stop_loss_rate": round(stop_count / len(trades) * 100, 1),
        "sortino":        round(sortino, 3),
    }

# ── Grid search ──────────────────────────────────────────────────────────────────

def _build_grid(baseline, is_crypto):
    """Parameter grid. Always includes the live baseline value per axis so the
    baseline is inside the search space and directly comparable."""
    rsi_vals = sorted(set([65, 70, 75] + [baseline["rsi_threshold"]]))
    st_vals  = sorted(set([3.0, 3.5, 4.0] + [baseline["st_mult"]]))
    sl_vals  = sorted(set(([3.0, 4.0, 5.0] if is_crypto else [2.0, 3.0, 4.0]) + [baseline["stop_loss"]]))
    tp_vals  = sorted(set(([8.0, 10.0, 15.0] if is_crypto else [12.0, 15.0, 20.0]) + [baseline["take_profit"]]))
    combos = []
    for rsi in rsi_vals:
        for st in st_vals:
            for sl in sl_vals:
                for tp in tp_vals:
                    combos.append({
                        "rsi_threshold": rsi, "st_mult": st,
                        "stop_loss": sl, "take_profit": tp,
                        "trailing_stop": baseline["trailing_stop"],
                    })
    return combos, st_vals

def _aggregate(sym_metrics):
    """Average a list of per-symbol metric dicts (None entries ignored)."""
    rs = [m for m in sym_metrics if m is not None]
    if not rs:
        return None
    k = len(rs)
    return {
        "return_pct": sum(m["return_pct"]     for m in rs) / k,
        "win_rate":   sum(m["win_rate"]       for m in rs) / k,
        "drawdown":   sum(m["max_drawdown"]   for m in rs) / k,
        "sortino":    sum(m["sortino"]        for m in rs) / k,
        "sl_rate":    sum(m["stop_loss_rate"] for m in rs) / k,
        "trades":     sum(m["trades"]         for m in rs),
    }

def _score(agg):
    """Sortino-primary composite, penalised when too few trades (unreliable)."""
    if agg is None or agg["trades"] == 0:
        return -999.0
    penalty = max(0.3, min(1.0, agg["trades"] / 20.0))
    return agg["sortino"] * penalty

def _round_agg(agg):
    if agg is None:
        return None
    return {"return_pct": round(agg["return_pct"], 2), "win_rate": round(agg["win_rate"], 1),
            "drawdown": round(agg["drawdown"], 2), "sortino": round(agg["sortino"], 3),
            "sl_rate": round(agg["sl_rate"], 1), "trades": agg["trades"]}

def run_walkforward(bars_by_sym, baseline, is_crypto,
                    warmup=WARMUP, is_len=WF_IS_LEN, oos_len=WF_OOS_LEN):
    """
    Walk-forward optimization. Rolling folds: on each in-sample window the full
    grid is searched (Sortino-scored) and the winning params are validated on the
    following out-of-sample window. The reported numbers are the HONEST
    out-of-sample result — not the in-sample fit. Parameters are only recommended
    if they are stable (chosen in ≥STABILITY_MIN of folds); otherwise the live
    baseline is kept for that axis.
    """
    combos, st_vals = _build_grid(baseline, is_crypto)
    # Fee-aware roundtrip cost per trade (Crypto 2×(0.26%+0.05%), Stocks 2×0.02%)
    cost = (0.0026 + 0.0005) * 2 if is_crypto else 0.0002 * 2

    # Qualify symbols with enough history, then align all to the most-recent common
    # window (last n_ref bars) so a given bar index ≈ the same calendar date across
    # symbols — required for coherent portfolio-level fold selection.
    qualifying = {sym: bars for sym, bars in bars_by_sym.items()
                  if len(bars) >= warmup + MIN_WINDOW_BARS}
    for sym, bars in bars_by_sym.items():
        if len(bars) < warmup + MIN_WINDOW_BARS:
            log(f"    {sym}: nur {len(bars)} Bars — übersprungen (min {warmup + MIN_WINDOW_BARS})")
    if not qualifying:
        log("  Walk-Forward: keine Symbole mit genug Daten — abgebrochen")
        return {}

    n_ref = min(len(bars) for bars in qualifying.values())
    precomps = {}
    for sym, bars in qualifying.items():
        precomps[sym] = precompute(bars[-n_ref:], st_vals)
        log(f"    {sym}: {len(bars)} Bars → letzte {n_ref} aligned")

    def _make_folds(is_l, oos_l):
        f, s = [], warmup
        while s + is_l + oos_l <= n_ref:
            f.append((s, s + is_l, s + is_l + oos_l))
            s += oos_l
        return f

    folds = _make_folds(is_len, oos_len)
    if len(folds) < 2:
        # Not enough history for the default windows — shrink adaptively.
        avail = n_ref - warmup
        if avail < 90:
            log(f"  Walk-Forward: nur {avail} handelbare Bars — zu wenig für Folds")
            return {"insufficient_data": True, "tradeable_bars": avail,
                    "best_params": dict(baseline), "symbols_tested": list(precomps.keys())}
        oos_len = max(20, avail // 5)
        is_len  = max(40, avail // 2)
        folds   = _make_folds(is_len, oos_len)

    log(f"  Walk-Forward: {len(folds)} Folds (IS={is_len}/OOS={oos_len}), "
        f"{len(precomps)} Symbole, {len(combos)} Combos/Fold, n_ref={n_ref}")

    param_keys   = ["rsi_threshold", "st_mult", "stop_loss", "take_profit"]
    chosen       = {k: [] for k in param_keys}
    fold_records = []

    for fi, (is_s, is_e, oos_e) in enumerate(folds):
        best_sc, best_p = -999.0, dict(baseline)
        for combo in combos:
            agg = _aggregate([simulate(pc, combo, is_s, is_e, cost) for pc in precomps.values()])
            sc  = _score(agg)
            if sc > best_sc:
                best_sc, best_p = sc, dict(combo)
        oos_best = _aggregate([simulate(pc, best_p,   is_e, oos_e, cost) for pc in precomps.values()])
        oos_base = _aggregate([simulate(pc, baseline, is_e, oos_e, cost) for pc in precomps.values()])
        for k in param_keys:
            chosen[k].append(best_p[k])
        fold_records.append({
            "fold": fi, "is": [is_s, is_e], "oos": [is_e, oos_e],
            "chosen": {k: best_p[k] for k in param_keys},
            "oos_best": _round_agg(oos_best), "oos_base": _round_agg(oos_base),
        })

    # Candidate params from per-axis stability (mode must win ≥STABILITY_MIN of folds)
    stability, cand_params = {}, dict(baseline)
    for k in param_keys:
        vals   = chosen[k]
        counts = {}
        for v in vals:
            counts[v] = counts.get(v, 0) + 1
        mode_v = max(counts, key=counts.get)
        stab   = counts[mode_v] / len(vals)
        stability[k] = {"mode": mode_v, "stability_pct": round(stab * 100),
                        "stable": stab >= STABILITY_MIN, "chosen": vals}
        cand_params[k] = mode_v if stab >= STABILITY_MIN else baseline[k]
    cand_params["trailing_stop"] = baseline["trailing_stop"]

    # Pooled OOS over ALL out-of-sample windows: candidate vs current baseline
    def _pooled(params):
        return _round_agg(_aggregate([
            simulate(pc, params, is_e, oos_e, cost)
            for (is_s, is_e, oos_e) in folds for pc in precomps.values()
        ]))
    base_oos = _pooled(baseline) or {"return_pct": 0.0, "win_rate": 0.0, "drawdown": 0.0,
                                     "sortino": 0.0, "sl_rate": 0.0, "trades": 0}
    cand_oos = _pooled(cand_params) or dict(base_oos)

    improvement = {
        "return_delta":  round(cand_oos["return_pct"] - base_oos["return_pct"], 2),
        "wr_delta":      round(cand_oos["win_rate"]   - base_oos["win_rate"], 1),
        "dd_delta":      round(cand_oos["drawdown"]   - base_oos["drawdown"], 2),
        "sortino_delta": round(cand_oos["sortino"]    - base_oos["sortino"], 3),
    }

    # Adopt the candidate ONLY on a MEANINGFUL out-of-sample gain (not noise): a real
    # Sortino improvement AND no loss of return. Otherwise keep the live baseline —
    # that is the whole point of walk-forward (never ship in-sample-overfit params).
    cand_differs = any(cand_params[k] != baseline[k] for k in param_keys)
    adopted = (cand_differs
               and improvement["sortino_delta"] >= MIN_OOS_SORTINO_GAIN
               and improvement["return_delta"]  >= MIN_OOS_RETURN_GAIN)
    rec_params = dict(cand_params) if adopted else dict(baseline)

    # Adaptive (re-fit each fold) OOS — informative upper bound of what tuning could do
    def _favg(field):
        xs = [fr["oos_best"][field] for fr in fold_records if fr["oos_best"]]
        return round(sum(xs) / len(xs), 2) if xs else 0.0
    wf_oos = {f: _favg(f) for f in ["return_pct", "win_rate", "drawdown", "sortino", "sl_rate"]}

    return {
        "best_params":     rec_params,     # what /apply reads — baseline unless a real OOS win
        "candidate":       cand_params,    # stable grid pick (adopted only if it beats baseline OOS)
        "adopted":         adopted,
        "changed":         adopted and cand_differs,
        "n_folds":         len(folds),
        "is_len":          is_len,
        "oos_len":         oos_len,
        "candidate_oos":   cand_oos,       # OOS of the stable grid pick
        "recommended_oos": cand_oos if adopted else base_oos,
        "baseline_oos":    base_oos,       # OOS of current live params (pooled)
        "walkforward_oos": wf_oos,         # adaptive re-fit OOS (informative)
        "improvement":     improvement,    # candidate vs baseline (pooled OOS)
        "stability":       stability,
        "folds":           fold_records,
        "symbols_tested":  list(precomps.keys()),
    }

# ── Trade-history analysis ───────────────────────────────────────────────────────

def analyze_trades(trades, bot_name):
    """Analyze completed trade records for profitability and false-signal patterns."""
    if not trades:
        return {"bot": bot_name, "total": 0,
                "note": "No trade history yet — grid results will be the main signal."}

    total  = len(trades)
    wins   = [t for t in trades if t.get("profit", 0) > 0]
    losses = [t for t in trades if t.get("profit", 0) <= 0]

    # Exit-reason breakdown
    reasons = defaultdict(int)
    for t in trades:
        reasons[t.get("reason", "UNKNOWN")] += 1

    sl_count    = reasons.get("STOP-LOSS", 0) + reasons.get("WS-STOP-LOSS", 0)
    trail_count = reasons.get("TRAIL-STOP", 0) + reasons.get("WS-TRAIL-STOP", 0)
    psar_count  = reasons.get("PSAR-STOP", 0)  + reasons.get("WS-PSAR-STOP", 0)
    spike_count = sum(1 for t in trades if t.get("spike"))

    # Per-symbol breakdown
    by_sym = defaultdict(lambda: {"trades": 0, "profit": 0.0, "wins": 0, "stop_losses": 0})
    for t in trades:
        sym = t.get("symbol", "?")
        by_sym[sym]["trades"] += 1
        by_sym[sym]["profit"] += t.get("profit", 0)
        if t.get("profit", 0) > 0:
            by_sym[sym]["wins"] += 1
        if t.get("reason", "") in ("STOP-LOSS", "WS-STOP-LOSS"):
            by_sym[sym]["stop_losses"] += 1

    # Sort by total profit (descending)
    ranked_syms = sorted(
        {k: dict(v) for k, v in by_sym.items()}.items(),
        key=lambda x: x[1]["profit"], reverse=True
    )

    return {
        "bot":             bot_name,
        "total":           total,
        "wins":            len(wins),
        "losses":          len(losses),
        "win_rate":        round(len(wins) / total * 100, 1),
        "total_profit":    round(sum(t.get("profit", 0) for t in trades), 2),
        "avg_profit":      round(sum(t.get("profit", 0) for t in trades) / total, 2),
        "false_signal_rate": round(sl_count / total * 100, 1),
        "exit_reasons": {
            "stop_loss":   sl_count,
            "trail_stop":  trail_count,
            "psar_stop":   psar_count,
            "spike":       spike_count,
            "other":       total - sl_count - trail_count - psar_count,
        },
        "by_symbol":       dict(ranked_syms),
    }

# ── Indicator-block analysis (from dashboard skip log) ───────────────────────────

def analyze_indicator_blocks(dash, bot_name):
    """Count how often each indicator gate blocks a trade from the live skip log."""
    if not dash:
        return {"bot": bot_name, "skips_analyzed": 0,
                "note": "Dashboard not readable"}

    skips = dash.get("skips", [])
    if not skips:
        return {"bot": bot_name, "skips_analyzed": 0,
                "note": "No recent skip data in dashboard"}

    n = len(skips)
    indicator_keys = ["rsi_ok", "ma_ok", "macd_ok", "st_ok", "obv_ok", "ichi_ok", "psar_ok"]
    block_counts   = defaultdict(int)

    rsi_values = []
    for skip in skips:
        for key in indicator_keys:
            if not skip.get(key, True):
                block_counts[key] += 1
        if "rsi" in skip:
            rsi_values.append(skip["rsi"])

    block_rates = {
        k: round(block_counts[k] / n * 100, 1)
        for k in indicator_keys
    }
    ranked = sorted(block_rates.items(), key=lambda x: x[1], reverse=True)

    avg_rsi          = round(sum(rsi_values) / len(rsi_values), 1) if rsi_values else None
    rsi_near_thresh  = sum(1 for r in rsi_values if 65 <= r <= 75) if rsi_values else 0
    rsi_near_pct     = round(rsi_near_thresh / len(rsi_values) * 100, 1) if rsi_values else 0.0

    return {
        "bot":             bot_name,
        "skips_analyzed":  n,
        "block_rates":     dict(ranked),
        "top_blocker":     ranked[0][0] if ranked else None,
        "top_block_rate":  ranked[0][1] if ranked else 0,
        "avg_rsi_at_skip": avg_rsi,
        "rsi_near_threshold_pct": rsi_near_pct,
    }

# ── Suggestion engine ────────────────────────────────────────────────────────────

IND_LABELS = {
    "rsi_ok": "RSI", "ma_ok": "MA20", "macd_ok": "MACD",
    "st_ok": "Supertrend", "obv_ok": "OBV", "ichi_ok": "Ichimoku",
    "psar_ok": "PSAR (info only)",
}

def generate_suggestions(ta_super, ta_crypto, ia_super, ia_crypto,
                          gs_super, gs_crypto):
    """Produce a list of prioritised, actionable suggestion strings."""
    sugg = []

    for bot_name, ta, ia, gs, baseline in [
        ("Super Bot",  ta_super,  ia_super,  gs_super,  SUPER_BASELINE),
        ("Crypto Bot", ta_crypto, ia_crypto, gs_crypto, CRYPTO_BASELINE),
    ]:
        # ── Grid-based parameter changes ──────────────────────────────────────
        if gs and gs.get("insufficient_data"):
            sugg.append(f"<b>{bot_name}</b>: Zu wenig Historie für Walk-Forward — "
                        f"keine belastbare Parameter-Empfehlung")
        elif gs and gs.get("candidate"):
            impr = gs.get("improvement", {})
            cand = gs["candidate"]
            changes = []
            if cand["rsi_threshold"] != baseline["rsi_threshold"]:
                changes.append(f"RSI-Threshold: {baseline['rsi_threshold']} → {cand['rsi_threshold']}")
            if abs(cand["st_mult"] - baseline["st_mult"]) >= 0.4:
                changes.append(f"Supertrend-Mult: {baseline['st_mult']} → {cand['st_mult']}")
            if abs(cand["stop_loss"] - baseline["stop_loss"]) >= 0.5:
                changes.append(f"Stop-Loss: {baseline['stop_loss']}% → {cand['stop_loss']}%")
            if abs(cand["take_profit"] - baseline["take_profit"]) >= 1.5:
                changes.append(f"Take-Profit: {baseline['take_profit']}% → {cand['take_profit']}%")

            if gs.get("adopted") and changes:
                delta = (f" → OOS-Verbesserung: "
                         f"Return {impr.get('return_delta',0):+.1f}% · "
                         f"Sortino {impr.get('sortino_delta',0):+.2f} · "
                         f"DD {impr.get('dd_delta',0):+.1f}%")
                sugg.append(f"<b>{bot_name}</b>: Parameteränderung übernommen (Walk-Forward) — "
                            + ", ".join(changes) + delta)
            elif changes:
                sugg.append(f"<b>{bot_name}</b>: Grid-Pick ({', '.join(changes)}) brachte KEINE "
                            f"belastbare OOS-Verbesserung (Sortino {impr.get('sortino_delta',0):+.2f}) — "
                            f"Baseline behalten, Overfitting vermieden")
            else:
                sugg.append(f"<b>{bot_name}</b>: Parameter im Walk-Forward bestätigt "
                            f"(stabil, kein Änderungsbedarf)")

        # ── High false-signal rate ────────────────────────────────────────────
        fs = ta.get("false_signal_rate", 0)
        if ta.get("total", 0) >= 5 and fs > 35:
            sugg.append(
                f"<b>{bot_name}</b>: Stop-Loss-Rate {fs:.0f}% (>{35}% Schwelle) — "
                f"Einstiegssignal zu schwach; strengere RSI/MA-Bedingung erwägen")

        # ── Dominant indicator blocker ────────────────────────────────────────
        top = ia.get("top_blocker")
        top_rate = ia.get("top_block_rate", 0)
        if top and top_rate > 55:
            sugg.append(
                f"<b>{bot_name}</b>: {IND_LABELS.get(top, top)} blockiert "
                f"{top_rate:.0f}% aller analysierten Skips — "
                f"Schwellenwert ggf. lockern oder Daten prüfen")

        # ── RSI near threshold ────────────────────────────────────────────────
        rsi_near = ia.get("rsi_near_threshold_pct", 0)
        avg_rsi  = ia.get("avg_rsi_at_skip")
        if rsi_near > 50 and avg_rsi:
            sugg.append(
                f"<b>{bot_name}</b>: Ø RSI bei gesperrten Trades = {avg_rsi} "
                f"({rsi_near:.0f}% davon zwischen 65–75) — "
                f"RSI-Schwelle von {baseline['rsi_threshold']} auf 75 erhöhen "
                f"würde mehr Eintritte erlauben")

        # ── Worst per-symbol performers ───────────────────────────────────────
        by_sym = ta.get("by_symbol", {})
        bad    = [(s, d) for s, d in by_sym.items()
                  if d["profit"] < -100 and d["trades"] >= 2
                  and d["stop_losses"] / d["trades"] >= 0.5]
        if bad:
            worst = ", ".join(s for s, _ in bad[:3])
            sugg.append(
                f"<b>{bot_name}</b>: Symbole mit ≥50% Stop-Loss-Exits: {worst} — "
                f"engere Stop-Levels oder manueller Ausschluss sinnvoll")

    if not sugg:
        sugg.append("Alle Parameter sind innerhalb optimaler Bereiche — keine Änderungen nötig.")

    return sugg

# ── Telegram report formatting ───────────────────────────────────────────────────

def format_report(ta_s, ta_c, ia_s, ia_c, gs_s, gs_c, suggestions):
    """Build HTML Telegram report. Returns a string (may be sent in chunks)."""
    now = datetime.now().strftime("%Y-%m-%d")
    L   = [f"<b>📊 Wöchentliche Optimierungs-Analyse — {now}</b>", ""]

    # ── Section 1: Trade history ─────────────────────────────────────────────
    L.append("<b>1️⃣ Trade-Auswertung (Live-History)</b>")
    for ta in [ta_s, ta_c]:
        bot = ta["bot"]
        if ta.get("total", 0) == 0:
            L.append(f"  {bot}: {ta.get('note', 'Noch keine Trades')}")
            continue
        er = ta.get("exit_reasons", {})
        L.append(
            f"  <b>{bot}</b>  {ta['total']} Trades | WR {ta['win_rate']}% | "
            f"P&amp;L ${ta['total_profit']:+,.0f} | "
            f"False-Signal-Rate: {ta['false_signal_rate']:.0f}%"
        )
        L.append(
            f"    SL={er.get('stop_loss',0)}  Trail={er.get('trail_stop',0)}  "
            f"PSAR={er.get('psar_stop',0)}"
            + (f"  Spike={er['spike']}" if er.get("spike") else "")
        )
        by_sym = ta.get("by_symbol", {})
        if by_sym:
            items = list(by_sym.items())
            best  = items[:3]
            worst = [x for x in items if x[1]["profit"] < 0][-3:]
            if best:
                b_str = " | ".join(
                    f"{s} ${d['profit']:+.0f} ({d['wins']}/{d['trades']})"
                    for s, d in best
                )
                L.append(f"    Best: {b_str}")
            if worst:
                w_str = " | ".join(
                    f"{s} ${d['profit']:+.0f}" for s, d in reversed(worst)
                )
                L.append(f"    Worst: {w_str}")
    L.append("")

    # ── Section 2: Indicator block rates ─────────────────────────────────────
    L.append("<b>2️⃣ Indikator-Blockierungsrate (aktueller Snapshot)</b>")
    for ia in [ia_s, ia_c]:
        bot = ia["bot"]
        n   = ia.get("skips_analyzed", 0)
        if n == 0:
            L.append(f"  {bot}: {ia.get('note', 'Keine Daten')}")
            continue
        L.append(f"  <b>{bot}</b> ({n} Skips analysiert):")
        br      = ia.get("block_rates", {})
        sorted_br = sorted(br.items(), key=lambda x: x[1], reverse=True)
        for key, pct in sorted_br[:5]:
            bar = "█" * int(pct / 10)
            L.append(f"    {IND_LABELS.get(key,key):15s} {pct:4.0f}% {bar}")
        if ia.get("avg_rsi_at_skip"):
            L.append(
                f"    Ø RSI bei Skip: {ia['avg_rsi_at_skip']}  "
                f"({ia.get('rsi_near_threshold_pct',0):.0f}% im Bereich 65–75)"
            )
    L.append("")

    # ── Section 3: Grid search results ───────────────────────────────────────
    L.append("<b>3️⃣ Walk-Forward-Optimierung (Out-of-Sample)</b>")
    IND_ABBR = {"rsi_threshold": "RSI", "st_mult": "ST×", "stop_loss": "SL", "take_profit": "TP"}
    for name, gs, baseline in [
        ("Super Bot",  gs_s, SUPER_BASELINE),
        ("Crypto Bot", gs_c, CRYPTO_BASELINE),
    ]:
        if not gs:
            L.append(f"  {name}: Keine Daten (Datenquelle nicht erreichbar?)")
            continue
        if gs.get("insufficient_data"):
            L.append(f"  {name}: zu wenig Historie für Walk-Forward "
                     f"({gs.get('tradeable_bars', 0)} handelbare Bars)")
            continue

        cand = gs.get("candidate", gs.get("best_params", {}))
        coos = gs.get("candidate_oos", {})
        base = gs.get("baseline_oos", {})
        stab = gs.get("stability", {})

        L.append(f"  <b>{name}</b> — {gs.get('n_folds', 0)} Folds "
                 f"(IS {gs.get('is_len', '?')}/OOS {gs.get('oos_len', '?')} Bars · "
                 f"{len(gs.get('symbols_tested', []))} Symbole)")

        # Grid's stable pick — underline axes differing from live + per-axis stability %
        parts = []
        for key in ["rsi_threshold", "st_mult", "stop_loss", "take_profit"]:
            v       = cand.get(key, baseline[key])
            changed = abs(v - baseline[key]) > 0.01
            tag     = f"<u>{v}</u>" if changed else f"{v}"
            parts.append(f"{IND_ABBR[key]}{tag}({stab.get(key, {}).get('stability_pct', 0):.0f}%)")
        L.append("    Grid-Pick: " + " · ".join(parts))

        if base and coos:
            L.append(
                f"    OOS aktuell→Pick: "
                f"Rtn {base.get('return_pct', 0):+.1f}%→{coos.get('return_pct', 0):+.1f}% · "
                f"Sortino {base.get('sortino', 0):.2f}→{coos.get('sortino', 0):.2f} · "
                f"DD {base.get('drawdown', 0):.1f}%→{coos.get('drawdown', 0):.1f}%"
            )
        if gs.get("adopted"):
            L.append("    ✅ übernommen — belastbare OOS-Verbesserung")
        else:
            L.append("    → NICHT übernommen — keine belastbare OOS-Verbesserung, Baseline bleibt")
    L.append("")

    # ── Section 4: Suggestions ───────────────────────────────────────────────
    if suggestions:
        L.append("<b>4️⃣ Empfehlungen</b>")
        for s in suggestions:
            L.append(f"• {s}")
        L.append("")

    L.append("📁 <code>agents/optimize_results.json</code>  |  "
             "Log: <code>agents/optimize_log.txt</code>")

    return "\n".join(L)

# ── Main optimization routine ────────────────────────────────────────────────────

def run_optimization():
    log("=" * 60)
    log("Optimierungs-Analyse gestartet")
    log("=" * 60)

    # Phase 1 — load live data ─────────────────────────────────────────────────
    super_trades  = load_json(SUPER_HIST)  or []
    crypto_trades = load_json(CRYPTO_HIST) or []
    super_dash    = load_json(SUPER_DASH)
    crypto_dash   = load_json(CRYPTO_DASH)
    log(f"Trades: Super={len(super_trades)}, Crypto={len(crypto_trades)}")

    # Phase 2 — trade analysis ─────────────────────────────────────────────────
    ta_super  = analyze_trades(super_trades,  "Super Bot")
    ta_crypto = analyze_trades(crypto_trades, "Crypto Bot")

    # Phase 3 — indicator block analysis ───────────────────────────────────────
    ia_super  = analyze_indicator_blocks(super_dash,  "Super Bot")
    ia_crypto = analyze_indicator_blocks(crypto_dash, "Crypto Bot")
    log(f"Skips analysiert: Super={ia_super.get('skips_analyzed',0)}, "
        f"Crypto={ia_crypto.get('skips_analyzed',0)}")

    # Phase 4 — grid search ────────────────────────────────────────────────────
    gs_super  = {}
    gs_crypto = {}

    # Super bot — ETF daily bars via yfinance (multi-year; Alpaca paper has no stock bars)
    log("Lade ETF Tagesbars (yfinance, 4J)...")
    super_bars = fetch_stock_bars_yf(ETF_SYMBOLS, years=4)
    log(f"  {len(super_bars)} Symbole geladen: "
        + ", ".join(f"{s}({len(b)})" for s, b in super_bars.items()))
    if super_bars:
        log("Starte Walk-Forward Super Bot...")
        gs_super = run_walkforward(super_bars, SUPER_BASELINE, is_crypto=False)
        log(f"  Empfohlene Params: {gs_super.get('best_params')}")

    # Crypto bot — daily bars via Alpaca (needs key; crypto data available on free tier)
    if ALPACA_KEY:
        log("Lade Crypto Tagesbars (Alpaca, ~3J)...")
        crypto_bars = fetch_crypto_bars_daily(CRYPTO_SYMBOLS, days=1100)
        log(f"  {len(crypto_bars)} Symbole geladen: "
            + ", ".join(f"{s}({len(b)})" for s, b in crypto_bars.items()))
        if crypto_bars:
            log("Starte Walk-Forward Crypto Bot...")
            gs_crypto = run_walkforward(crypto_bars, CRYPTO_BASELINE, is_crypto=True)
            log(f"  Empfohlene Params: {gs_crypto.get('best_params')}")
    else:
        log("Kein Alpaca-Key — Crypto Walk-Forward übersprungen")

    # Phase 5 — generate suggestions ───────────────────────────────────────────
    suggestions = generate_suggestions(
        ta_super, ta_crypto, ia_super, ia_crypto, gs_super, gs_crypto
    )
    log(f"{len(suggestions)} Empfehlungen generiert")

    # Phase 6 — Telegram report ────────────────────────────────────────────────
    report = format_report(
        ta_super, ta_crypto, ia_super, ia_crypto,
        gs_super, gs_crypto, suggestions
    )
    log("Sende Telegram-Bericht...")
    send_telegram(report)

    # Phase 7 — save results ───────────────────────────────────────────────────
    results = {
        "generated_at":       datetime.now().isoformat(),
        "trade_analysis":     {"super": ta_super, "crypto": ta_crypto},
        "indicator_analysis": {"super": ia_super, "crypto": ia_crypto},
        "grid_search":        {"super": gs_super, "crypto": gs_crypto},
        "suggestions":        suggestions,
    }
    try:
        with open(RESULTS_FILE + ".tmp", "w") as f:
            json.dump(results, f, indent=2, default=str)
        os.replace(RESULTS_FILE + ".tmp", RESULTS_FILE)   # atomar — Router (/apply) liest parallel
        log(f"Ergebnisse gespeichert: {RESULTS_FILE}")
    except Exception as e:
        log(f"Fehler beim Speichern: {e}")

    log("Optimierungs-Analyse abgeschlossen")
    return results

# ── Scheduler ────────────────────────────────────────────────────────────────────

def _is_sunday_midnight():
    """True if it is Sunday (weekday==6) and the hour is 0 (00:00–00:59)."""
    now = datetime.now()
    return now.weekday() == 6 and now.hour == 0

def main():
    global RESULTS_FILE, LOG_FILE, TELEGRAM_TOKEN
    parser = argparse.ArgumentParser(description="Optimization Agent")
    parser.add_argument("--now", action="store_true",
                        help="Run optimization immediately instead of waiting for Sunday")
    parser.add_argument("--test", action="store_true",
                        help="Test mode: results/log to /tmp, NO Telegram; runs now. "
                             "Safe to run alongside the live optimize session.")
    args = parser.parse_args()

    if args.test:
        RESULTS_FILE   = "/tmp/optimize_results_test.json"
        LOG_FILE       = "/tmp/optimize_log_test.txt"
        TELEGRAM_TOKEN = ""       # send_telegram() early-returns when empty
        args.now       = True     # test implies an immediate run
        print("[TEST-MODUS] Ausgabe → /tmp, kein Telegram, sofortiger Lauf")

    log("=" * 60)
    log("Optimization Agent gestartet")
    log(f"Ergebnisdatei : {RESULTS_FILE}")
    log(f"Zeitplan      : Jeden Sonntag 00:00 Uhr")
    log("=" * 60)

    if args.now:
        log("--now Flag gesetzt: führe Analyse sofort aus")
        try:
            run_optimization()
        except Exception as e:
            log(f"FEHLER: {e}")
            import traceback
            log(traceback.format_exc())
        return

    last_run_date = None

    while True:
        try:
            if _is_sunday_midnight():
                today = datetime.now().date()
                if last_run_date != today:
                    log(f"Sonntag 00:xx erkannt — starte Wochenanalyse ({today})")
                    try:
                        run_optimization()
                    except Exception as e:
                        log(f"FEHLER bei Optimierung: {e}")
                        import traceback
                        log(traceback.format_exc())
                        send_telegram(f"❌ <b>Optimization Agent Fehler</b>\n{e}")
                    last_run_date = today
                else:
                    log(f"Analyse für {today} bereits durchgeführt — warte bis nächste Woche")
            else:
                now = datetime.now()
                # How many seconds until next Sunday 00:00?
                days_ahead = (6 - now.weekday()) % 7
                if days_ahead == 0 and now.hour >= 1:
                    days_ahead = 7   # already past midnight window this Sunday
                next_sun = now.replace(hour=0, minute=0, second=0, microsecond=0) \
                           + timedelta(days=days_ahead)
                secs = (next_sun - now).total_seconds()
                log(f"Nächster Lauf: {next_sun.strftime('%Y-%m-%d %H:%M')} "
                    f"(in {secs/3600:.1f}h)")

        except Exception as e:
            log(f"Scheduler-Fehler: {e}")

        # Sleep 55 minutes — ensures we wake within the 00:00–00:59 window
        time.sleep(3300)


if __name__ == "__main__":
    main()
