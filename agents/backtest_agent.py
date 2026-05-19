#!/usr/bin/env python3
"""
Backtest Agent — simulates SuperBot and CryptoBot on full-year 2024
historical data from Alpaca.

Indicator settings match the current live bots:
  Gates (6): RSI<70, price>MA20, MACD>signal, Supertrend(3.5)==1, OBV rising,
             price>Ichimoku cloud
  PSAR:      dynamic stop-loss only (not a buy gate)
  Sentiment: assumed bullish for all symbols — tests indicator gates in isolation

Results:
  ~/trading_bot/agents/backtest_results.json   — full machine-readable data
  ~/trading_bot/agents/backtest_report.txt     — human-readable summary

Usage:
  python3 backtest_agent.py           # full year 2024
  python3 backtest_agent.py --quick   # Q1 2024 only (fast sanity check)
"""

import os, sys, json, time, requests, argparse
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, "/home/trading2025/trading_bot")
try:
    from config import config
except ImportError:
    config = {}

ALPACA_KEY    = config.get("alpaca_api_key", "")
ALPACA_SECRET = config.get("alpaca_secret_key", "")
DATA_URL      = "https://data.alpaca.markets"

# ── Universe ───────────────────────────────────────────────────────────────────

ETF_SYMBOLS  = ["XLE","XOP","XLI","SLX","ITA","XLF","XLK","GLD","PAVE","IBIT"]
CRYPTO_MAIN  = ["BTC/USD","ETH/USD","SOL/USD","XRP/USD","AVAX/USD","LINK/USD","LTC/USD"]
CRYPTO_MEME  = ["DOGE/USD","SHIB/USD","PEPE/USD","WIF/USD"]
CRYPTO_ALL   = CRYPTO_MAIN + CRYPTO_MEME

# ── Bot parameters (must match live bots exactly) ──────────────────────────────

SUPER_PARAMS = dict(
    start_balance = 100_000.0,
    pos_size      = 0.05,        # 5% per trade
    max_pos       = 15,
    stop_loss     = 3.0,         # %
    take_profit   = 15.0,        # % — trailing activates after this
    trailing_stop = 3.0,         # % pullback from peak
)
CRYPTO_PARAMS = dict(
    start_balance = 10_000.0,
    pos_size_main = 0.08,        # 8% main coins
    pos_size_meme = 0.03,        # 3% meme coins
    max_pos       = 6,
    stop_loss     = 4.0,
    take_profit   = 10.0,
    trailing_stop = 2.0,
)

MIN_BARS = 78    # Ichimoku needs 78+ bars (52 lookback + 26 displacement)
WARMUP_DAYS = 120  # calendar days before backtest start to build MIN_BARS

# ── Alpaca data fetching ───────────────────────────────────────────────────────

def _headers():
    return {"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET}

def fetch_stock_bars(symbols, start, end):
    """Daily adjusted bars for ETF symbols. Returns {symbol: [bar, ...]}."""
    result = defaultdict(list)
    page_token = None
    url = DATA_URL + "/v2/stocks/bars"
    while True:
        params = {
            "symbols":    ",".join(symbols),
            "timeframe":  "1Day",
            "start":      start,
            "end":        end,
            "limit":      10000,
            "adjustment": "all",
            "feed":       "iex",
        }
        if page_token:
            params["page_token"] = page_token
        try:
            r = requests.get(url, headers=_headers(), params=params, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"[DATA] Stock fetch error: {e}")
            break
        data = r.json()
        for sym, bars in data.get("bars", {}).items():
            for b in bars:
                result[sym].append({"t": b["t"][:10],
                                    "o": b["o"], "h": b["h"],
                                    "l": b["l"], "c": b["c"], "v": b["v"]})
        page_token = data.get("next_page_token")
        if not page_token:
            break
        time.sleep(0.15)
    return dict(result)

def fetch_crypto_bars(symbols, start, end):
    """Daily bars for crypto symbols. Returns {symbol: [bar, ...]}."""
    result = defaultdict(list)
    page_token = None
    url = DATA_URL + "/v1beta3/crypto/us/bars"
    while True:
        params = {
            "symbols":   ",".join(symbols),
            "timeframe": "1Day",
            "start":     start,
            "end":       end,
            "limit":     10000,
        }
        if page_token:
            params["page_token"] = page_token
        try:
            r = requests.get(url, headers=_headers(), params=params, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"[DATA] Crypto fetch error: {e}")
            break
        data = r.json()
        for sym, bars in data.get("bars", {}).items():
            for b in bars:
                result[sym].append({"t": b["t"][:10],
                                    "o": b["o"], "h": b["h"],
                                    "l": b["l"], "c": b["c"], "v": b["v"]})
        page_token = data.get("next_page_token")
        if not page_token:
            break
        time.sleep(0.15)
    return dict(result)

# ── Indicator engine (mirrors live bot exactly) ────────────────────────────────

def calc_indicators(bars):
    """
    Compute all indicators from bars list (oldest→newest).
    Returns None if len(bars) < MIN_BARS.
    Returns dict with gate_ok = True if all 6 buy gates pass.
    PSAR is returned for use as dynamic stop but NOT included in gate_ok.
    """
    if len(bars) < MIN_BARS:
        return None

    closes  = [b["c"] for b in bars]
    highs   = [b["h"] for b in bars]
    lows    = [b["l"] for b in bars]
    volumes = [b["v"] for b in bars]
    n = len(closes)

    # ── RSI(14) ───────────────────────────────────────────────────────────────
    gains  = [max(closes[i] - closes[i-1], 0) for i in range(1, 15)]
    losses = [max(closes[i-1] - closes[i], 0) for i in range(1, 15)]
    avg_g  = sum(gains)  / 14
    avg_l  = sum(losses) / 14
    rsi    = 100 - (100 / (1 + avg_g / avg_l)) if avg_l > 0 else 100.0

    # ── MA20 ──────────────────────────────────────────────────────────────────
    ma20 = sum(closes[-20:]) / 20

    # ── MACD(12, 26, 9) ───────────────────────────────────────────────────────
    def ema_series(vals, period):
        k   = 2 / (period + 1)
        out = [sum(vals[:period]) / period]
        for v in vals[period:]:
            out.append(v * k + out[-1] * (1 - k))
        return out

    ema12       = ema_series(closes, 12)
    ema26       = ema_series(closes, 26)
    macd_line   = [ema12[i + 14] - ema26[i] for i in range(len(ema26))]
    signal_line = ema_series(macd_line, 9)
    macd_val    = macd_line[-1]
    signal_val  = signal_line[-1]

    # ── Supertrend(7, 3.5) — updated multiplier ───────────────────────────────
    st_trs = [highs[0] - lows[0]] + [
        max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        for i in range(1, n)
    ]
    st_atr = [0.0] * n
    st_atr[6] = sum(st_trs[:7]) / 7
    for i in range(7, n):
        st_atr[i] = (st_atr[i-1] * 6 + st_trs[i]) / 7
    ub     = [0.0] * n
    lb     = [0.0] * n
    st_dir = [1]   * n
    for i in range(6, n):
        hl2  = (highs[i] + lows[i]) / 2
        b_ub = hl2 + 3.5 * st_atr[i]
        b_lb = hl2 - 3.5 * st_atr[i]
        if i == 6:
            ub[i], lb[i] = b_ub, b_lb
        else:
            ub[i] = b_ub if b_ub < ub[i-1] or closes[i-1] > ub[i-1] else ub[i-1]
            lb[i] = b_lb if b_lb > lb[i-1] or closes[i-1] < lb[i-1] else lb[i-1]
            if st_dir[i-1] == 1:
                st_dir[i] = -1 if closes[i] < lb[i] else 1
            else:
                st_dir[i] =  1 if closes[i] > ub[i] else -1
    supertrend = st_dir[-1]

    # ── OBV ───────────────────────────────────────────────────────────────────
    obv = [volumes[0]]
    for i in range(1, n):
        if   closes[i] > closes[i-1]: obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i-1]: obv.append(obv[-1] - volumes[i])
        else:                          obv.append(obv[-1])
    avg_vol_20 = sum(volumes[-20:]) / 20
    obv_rising = (len(obv) > 11 and obv[-1] > obv[-11]) or volumes[-1] > avg_vol_20 * 0.5

    # ── Parabolic SAR(0.02, 0.2) — stop-loss use only, not in gate ────────────
    def calc_psar(hs, ls, af0=0.02, af_max=0.2):
        rising = True
        sar, ep, af = ls[0], hs[0], af0
        for i in range(1, len(hs)):
            prev = sar
            if rising:
                sar = prev + af * (ep - prev)
                sar = min(sar, ls[i-1], ls[max(0, i-2)])
                if ls[i] < sar:
                    rising = False; sar = ep; ep = ls[i]; af = af0
                else:
                    if hs[i] > ep: ep = hs[i]; af = min(af + af0, af_max)
            else:
                sar = prev + af * (ep - prev)
                sar = max(sar, hs[i-1], hs[max(0, i-2)])
                if hs[i] > sar:
                    rising = True; sar = ep; ep = hs[i]; af = af0
                else:
                    if ls[i] < ep: ep = ls[i]; af = min(af + af0, af_max)
        return sar

    psar_val = calc_psar(highs, lows)

    # ── Ichimoku Cloud ────────────────────────────────────────────────────────
    tenkan    = (max(highs[-9:])       + min(lows[-9:]))       / 2
    kijun     = (max(highs[-26:])      + min(lows[-26:]))      / 2
    t26       = (max(highs[-35:-26])   + min(lows[-35:-26]))   / 2
    k26       = (max(highs[-52:-26])   + min(lows[-52:-26]))   / 2
    span_a    = (t26 + k26) / 2
    span_b    = (max(highs[-78:-26])   + min(lows[-78:-26]))   / 2
    cloud_top = max(span_a, span_b)

    price = closes[-1]

    gate_ok = (
        rsi        <  70          and   # not overbought
        price      >  ma20        and   # above 20-day MA
        macd_val   >  signal_val  and   # bullish MACD crossover
        supertrend == 1           and   # Supertrend bullish
        obv_rising                and   # volume trend up
        price      >  cloud_top         # above Ichimoku cloud
    )

    return {
        "price":      price,
        "rsi":        round(rsi, 1),
        "ma20":       round(ma20, 4),
        "macd":       round(macd_val, 6),
        "macd_sig":   round(signal_val, 6),
        "supertrend": supertrend,
        "obv_rising": obv_rising,
        "psar":       round(psar_val, 6),
        "cloud_top":  round(cloud_top, 4),
        "gate_ok":    gate_ok,
    }

# ── Backtesting engine ─────────────────────────────────────────────────────────

class BacktestBot:
    def __init__(self, name, symbols, params, bars_by_sym, date_range, meme_syms=None):
        self.name          = name
        self.symbols       = symbols
        self.params        = params
        self.bars_by_sym   = bars_by_sym   # full history including warmup
        self.dates         = date_range    # backtest window only
        self.meme_syms     = set(meme_syms or [])

        self.balance       = params["start_balance"]
        self.start_balance = params["start_balance"]
        self.positions     = {}    # sym → position dict
        self.trades        = []    # closed trade records
        self.equity_curve  = []    # [(date_str, portfolio_value), ...]

    def _pos_size(self, sym):
        if sym in self.meme_syms:
            return self.params.get("pos_size_meme", self.params.get("pos_size"))
        return self.params.get("pos_size_main", self.params.get("pos_size"))

    def _bars_up_to(self, sym, date_str):
        return [b for b in self.bars_by_sym.get(sym, []) if b["t"] <= date_str]

    def simulate(self):
        print(f"\n{'─'*55}")
        print(f"  {self.name}")
        print(f"  {self.dates[0]} → {self.dates[-1]}  ({len(self.dates)} days)")
        print(f"  Start balance: ${self.start_balance:,.0f}")
        print(f"{'─'*55}")

        for i, date_str in enumerate(self.dates):
            self._step(date_str)
            if i % 50 == 0:
                pv = self.equity_curve[-1][1] if self.equity_curve else self.start_balance
                ret = (pv - self.start_balance) / self.start_balance * 100
                print(f"  {date_str}  pos={len(self.positions)}  "
                      f"bal=${self.balance:,.0f}  total={ret:+.1f}%")

        # Close any open positions at end of backtest at last available close
        for sym, pos in list(self.positions.items()):
            bars = self._bars_up_to(sym, self.dates[-1])
            if bars:
                self._close(sym, pos, bars[-1]["c"], self.dates[-1], "END-OF-BACKTEST")

        final_pv = self.equity_curve[-1][1] if self.equity_curve else self.balance
        ret = (final_pv - self.start_balance) / self.start_balance * 100
        print(f"\n  Done: {len(self.trades)} trades | "
              f"final ${final_pv:,.2f} ({ret:+.1f}%)")

    def _step(self, date_str):
        sl    = self.params["stop_loss"]    / 100
        tp    = self.params["take_profit"]  / 100
        trail = self.params["trailing_stop"] / 100

        # ── 1. Manage open positions ──────────────────────────────────────────
        for sym in list(self.positions.keys()):
            pos  = self.positions[sym]
            bars = self._bars_up_to(sym, date_str)
            if not bars or bars[-1]["t"] != date_str:
                continue

            bar   = bars[-1]
            high  = bar["h"]
            low   = bar["l"]
            entry = pos["entry"]

            # Ratchet PSAR stop upward each day
            if len(bars) >= MIN_BARS:
                ind = calc_indicators(bars)
                if ind:
                    # Only move stop up, never down
                    new_psar = ind["psar"]
                    if new_psar > pos.get("psar_stop", 0):
                        pos["psar_stop"] = new_psar

            # Update running peak
            if high > pos["highest"]:
                pos["highest"] = high

            psar_stop = pos.get("psar_stop", 0)

            # Priority 1: PSAR stop (dynamic)
            if psar_stop and low < psar_stop:
                self._close(sym, pos, max(psar_stop, low), date_str, "PSAR-STOP")
                continue

            # Priority 2: Hard stop-loss
            hard_stop = entry * (1 - sl)
            if low < hard_stop:
                self._close(sym, pos, hard_stop, date_str, "STOP-LOSS")
                continue

            # Priority 3: Trailing stop (only once take-profit threshold reached)
            peak_gain = (pos["highest"] - entry) / entry
            if peak_gain >= tp:
                trail_price = pos["highest"] * (1 - trail)
                if low <= trail_price:
                    self._close(sym, pos, max(trail_price, low), date_str, "TRAIL-STOP")
                    continue

        # ── 2. Scan for new entries ───────────────────────────────────────────
        if len(self.positions) < self.params["max_pos"]:
            for sym in self.symbols:
                if sym in self.positions:
                    continue
                if len(self.positions) >= self.params["max_pos"]:
                    break

                bars = self._bars_up_to(sym, date_str)
                if not bars or bars[-1]["t"] != date_str:
                    continue

                ind = calc_indicators(bars)
                if ind is None or not ind["gate_ok"]:
                    continue

                price  = bars[-1]["c"]    # entry at today's close
                size   = self._pos_size(sym)
                shares = (self.balance * size) / price
                cost   = shares * price
                if cost < 1.0 or cost > self.balance:
                    continue

                self.balance -= cost
                self.positions[sym] = {
                    "entry":     price,
                    "shares":    shares,
                    "highest":   price,
                    "psar_stop": ind["psar"],
                    "open_date": date_str,
                }

        # ── 3. Record portfolio equity ────────────────────────────────────────
        port_val = self.balance
        for sym, pos in self.positions.items():
            bars = self._bars_up_to(sym, date_str)
            if bars and bars[-1]["t"] == date_str:
                port_val += pos["shares"] * bars[-1]["c"]
            else:
                port_val += pos["shares"] * pos["entry"]
        self.equity_curve.append((date_str, round(port_val, 2)))

    def _close(self, sym, pos, price, date_str, reason):
        self.positions.pop(sym, None)
        pnl_usd = pos["shares"] * (price - pos["entry"])
        pnl_pct = (price - pos["entry"]) / pos["entry"] * 100
        self.balance += pos["shares"] * price
        self.trades.append({
            "symbol":     sym,
            "open_date":  pos["open_date"],
            "close_date": date_str,
            "days_held":  (datetime.strptime(date_str, "%Y-%m-%d") -
                           datetime.strptime(pos["open_date"], "%Y-%m-%d")).days,
            "entry":      round(pos["entry"], 6),
            "exit":       round(price, 6),
            "shares":     round(pos["shares"], 6),
            "pnl_usd":    round(pnl_usd, 2),
            "pnl_pct":    round(pnl_pct, 2),
            "reason":     reason,
            "win":        pnl_usd > 0,
        })

    # ── Statistics ─────────────────────────────────────────────────────────────

    def stats(self):
        eq     = self.equity_curve
        trades = self.trades
        start  = self.start_balance
        end    = eq[-1][1] if eq else start

        total_ret = (end - start) / start * 100
        wins      = [t for t in trades if t["win"]]
        losses    = [t for t in trades if not t["win"]]
        win_rate  = len(wins) / len(trades) * 100 if trades else 0.0
        avg_win   = sum(t["pnl_pct"] for t in wins)   / len(wins)   if wins   else 0.0
        avg_loss  = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0.0
        gross_win = sum(t["pnl_usd"] for t in wins)
        gross_los = abs(sum(t["pnl_usd"] for t in losses))
        pf        = round(gross_win / gross_los, 2) if gross_los > 0 else None
        avg_hold  = sum(t["days_held"] for t in trades) / len(trades) if trades else 0.0

        # Max drawdown from equity curve
        peak   = start
        max_dd = 0.0
        for _, val in eq:
            if val > peak: peak = val
            dd = (peak - val) / peak * 100
            if dd > max_dd: max_dd = dd

        # Monthly returns (first→last equity value each month)
        month_first, month_last = {}, {}
        for d, v in eq:
            m = d[:7]
            if m not in month_first: month_first[m] = v
            month_last[m] = v
        monthly = {m: round((month_last[m] - month_first[m]) / month_first[m] * 100, 2)
                   for m in sorted(month_first)}

        best_m  = max(monthly.items(), key=lambda x: x[1]) if monthly else ("N/A", 0)
        worst_m = min(monthly.items(), key=lambda x: x[1]) if monthly else ("N/A", 0)

        # Exit reason breakdown
        reasons = defaultdict(int)
        for t in trades: reasons[t["reason"]] += 1

        # Per-symbol stats
        sym_map = defaultdict(lambda: {"trades":0,"wins":0,"pnl_usd":0.0,"pnl_pct_sum":0.0})
        for t in trades:
            s = sym_map[t["symbol"]]
            s["trades"]      += 1
            s["wins"]        += int(t["win"])
            s["pnl_usd"]     += t["pnl_usd"]
            s["pnl_pct_sum"] += t["pnl_pct"]
        sym_table = sorted([
            {"symbol":      sym,
             "trades":      s["trades"],
             "win_rate":    round(s["wins"] / s["trades"] * 100, 1) if s["trades"] else 0,
             "pnl_usd":     round(s["pnl_usd"], 2),
             "avg_pnl_pct": round(s["pnl_pct_sum"] / s["trades"], 2) if s["trades"] else 0}
            for sym, s in sym_map.items()
        ], key=lambda x: x["pnl_usd"], reverse=True)

        return {
            "bot":              self.name,
            "start_date":       self.dates[0],
            "end_date":         self.dates[-1],
            "start_balance":    start,
            "end_balance":      round(end, 2),
            "total_return_pct": round(total_ret, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "total_trades":     len(trades),
            "wins":             len(wins),
            "losses":           len(losses),
            "win_rate_pct":     round(win_rate, 2),
            "avg_win_pct":      round(avg_win, 2),
            "avg_loss_pct":     round(avg_loss, 2),
            "avg_hold_days":    round(avg_hold, 1),
            "profit_factor":    pf,
            "exit_reasons":     dict(reasons),
            "best_month":       {"month": best_m[0],  "return_pct": best_m[1]},
            "worst_month":      {"month": worst_m[0], "return_pct": worst_m[1]},
            "monthly_returns":  monthly,
            "per_symbol":       sym_table,
            "trades":           trades,
            "equity_curve":     eq,
        }

# ── Report formatter ───────────────────────────────────────────────────────────

def make_report(ss, cs):
    W = 62
    lines = []

    def rule(ch="═"): lines.append(ch * W)
    def h(txt):       lines.append(f"  {txt}")
    def blank():      lines.append("")

    rule()
    h("TRADING BOT BACKTEST REPORT")
    h(f"Period : {ss['start_date']} → {ss['end_date']}")
    h(f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    blank()
    h("Indicator gates  : RSI<70 · MA20 · MACD · ST(mul=3.5) · OBV · Ichimoku")
    h("PSAR             : dynamic stop-loss only (not a buy gate)")
    h("Sentiment        : assumed bullish — pure indicator gate test")
    rule()

    for stats in [ss, cs]:
        blank()
        rule("─")
        h(stats["bot"])
        rule("─")
        sign = "+" if stats["total_return_pct"] >= 0 else ""
        h(f"Start balance    : ${stats['start_balance']:>12,.2f}")
        h(f"End balance      : ${stats['end_balance']:>12,.2f}")
        h(f"Total return     : {sign}{stats['total_return_pct']:.2f}%")
        h(f"Max drawdown     : -{stats['max_drawdown_pct']:.2f}%")
        h(f"Profit factor    : {stats['profit_factor'] or 'N/A'}")
        blank()
        h(f"Total trades     : {stats['total_trades']}  "
          f"(Wins: {stats['wins']}  Losses: {stats['losses']})")
        h(f"Win rate         : {stats['win_rate_pct']:.1f}%")
        h(f"Avg win          : +{stats['avg_win_pct']:.2f}%")
        h(f"Avg loss         :  {stats['avg_loss_pct']:.2f}%")
        h(f"Avg hold time    : {stats['avg_hold_days']:.0f} days")
        blank()
        h(f"Best month       : {stats['best_month']['month']}"
          f"  (+{stats['best_month']['return_pct']:.2f}%)")
        h(f"Worst month      : {stats['worst_month']['month']}"
          f"  ({stats['worst_month']['return_pct']:.2f}%)")
        blank()
        h("Exit reasons:")
        for reason, count in sorted(stats["exit_reasons"].items(),
                                    key=lambda x: x[1], reverse=True):
            h(f"  {reason:<22} {count:>4}")
        blank()
        h("Monthly returns:")
        for month, ret in stats["monthly_returns"].items():
            bar_len  = min(int(abs(ret) * 1.5), 28)
            bar      = ("█" * bar_len) if bar_len > 0 else "▏"
            sign     = "+" if ret >= 0 else ""
            h(f"  {month}  {sign}{ret:>7.2f}%  {bar}")
        blank()
        h("Per-symbol P&L (best → worst):")
        h(f"  {'Symbol':<12} {'Trades':>6}  {'WinRate':>7}  {'P&L $':>10}  {'Avg%':>6}")
        h("  " + "─" * 50)
        sym = stats["per_symbol"]
        for row in sym:
            sign = "+" if row["pnl_usd"] >= 0 else ""
            h(f"  {row['symbol']:<12} {row['trades']:>6}  "
              f"{row['win_rate']:>6.1f}%  "
              f"{sign}${abs(row['pnl_usd']):>9,.2f}  "
              f"{row['avg_pnl_pct']:>+6.2f}%")

    blank()
    rule()
    h("COMBINED PORTFOLIO")
    rule()
    c_start = ss["start_balance"] + cs["start_balance"]
    c_end   = ss["end_balance"]   + cs["end_balance"]
    c_ret   = (c_end - c_start) / c_start * 100
    c_tr    = ss["total_trades"]  + cs["total_trades"]
    c_wins  = ss["wins"]          + cs["wins"]
    c_wr    = c_wins / c_tr * 100 if c_tr else 0
    sign    = "+" if c_ret >= 0 else ""
    h(f"Total capital    : ${c_start:,.2f}  →  ${c_end:,.2f}")
    h(f"Combined return  : {sign}{c_ret:.2f}%")
    h(f"Combined trades  : {c_tr}  |  Win rate: {c_wr:.1f}%")
    blank()
    rule()

    return "\n".join(lines)

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Trading Bot Backtester — 2024")
    parser.add_argument("--quick", action="store_true",
                        help="Run Q1 2024 only for a fast sanity check")
    args = parser.parse_args()

    if args.quick:
        START, END = "2024-01-01", "2024-03-31"
        label = "Q1 2024"
    else:
        START, END = "2024-01-01", "2024-12-31"
        label = "Full Year 2024"

    warmup = (datetime.strptime(START, "%Y-%m-%d")
              - timedelta(days=WARMUP_DAYS)).strftime("%Y-%m-%d")

    out_dir   = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(out_dir, "backtest_results.json")
    txt_path  = os.path.join(out_dir, "backtest_report.txt")

    print(f"\n{'═'*55}")
    print(f"  BACKTEST AGENT — {label}")
    print(f"  Warmup start : {warmup}  (builds {MIN_BARS}+ bars for Ichimoku)")
    print(f"  Backtest     : {START} → {END}")
    print(f"{'═'*55}")

    # ── 1. Download data ──────────────────────────────────────────────────────
    print(f"\n[1/4] Downloading ETF bars ({len(ETF_SYMBOLS)} symbols)...")
    etf_bars = fetch_stock_bars(ETF_SYMBOLS, warmup, END)
    for sym in ETF_SYMBOLS:
        n = len(etf_bars.get(sym, []))
        ok = "✓" if n >= MIN_BARS else "✗ NOT ENOUGH"
        print(f"  {sym:<6}  {n:>4} bars  {ok}")

    print(f"\n[2/4] Downloading crypto bars ({len(CRYPTO_ALL)} symbols)...")
    crypto_bars = fetch_crypto_bars(CRYPTO_ALL, warmup, END)
    for sym in CRYPTO_ALL:
        n = len(crypto_bars.get(sym, []))
        ok = "✓" if n >= MIN_BARS else "✗ NOT ENOUGH"
        print(f"  {sym:<12}  {n:>4} bars  {ok}")

    # ── 2. Build date calendars ───────────────────────────────────────────────
    print(f"\n[3/4] Building trading calendars...")
    etf_dates = sorted({b["t"] for bars in etf_bars.values()
                         for b in bars if START <= b["t"] <= END})
    crypto_dates = sorted({b["t"] for bars in crypto_bars.values()
                            for b in bars if START <= b["t"] <= END})
    print(f"  ETF trading days   : {len(etf_dates)}")
    print(f"  Crypto trading days: {len(crypto_dates)}")

    # ── 3. Simulate ───────────────────────────────────────────────────────────
    print(f"\n[4/4] Running simulations...")

    super_bot = BacktestBot(
        name        = "SUPER BOT (ETFs)",
        symbols     = ETF_SYMBOLS,
        params      = SUPER_PARAMS,
        bars_by_sym = etf_bars,
        date_range  = etf_dates,
    )
    super_bot.simulate()
    super_stats = super_bot.stats()

    crypto_bot_bt = BacktestBot(
        name        = "CRYPTO BOT",
        symbols     = CRYPTO_ALL,
        params      = CRYPTO_PARAMS,
        bars_by_sym = crypto_bars,
        date_range  = crypto_dates,
        meme_syms   = CRYPTO_MEME,
    )
    crypto_bot_bt.simulate()
    crypto_stats = crypto_bot_bt.stats()

    # ── 4. Save results ───────────────────────────────────────────────────────
    # Thin equity curve for JSON (keep ~bi-weekly samples + endpoints)
    def thin_curve(curve):
        keep = set()
        for i, (d, _) in enumerate(curve):
            if i == 0 or i == len(curve)-1 or d[8:10] in ("01","15"):
                keep.add(i)
        return [curve[i] for i in sorted(keep)]

    results = {
        "generated":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "period":      {"start": START, "end": END},
        "settings": {
            "supertrend_multiplier": 3.5,
            "psar_in_buy_gate":      False,
            "buy_gates": ["RSI<70","price>MA20","MACD>signal",
                          "Supertrend==1","OBV_rising","price>Ichimoku_cloud"],
        },
        "super_bot": {**super_stats,
                      "equity_curve": thin_curve(super_stats["equity_curve"])},
        "crypto_bot": {**crypto_stats,
                       "equity_curve": thin_curve(crypto_stats["equity_curve"])},
    }

    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Saved: {json_path}")

    report_text = make_report(super_stats, crypto_stats)
    with open(txt_path, "w") as f:
        f.write(report_text)
    print(f"  Saved: {txt_path}")

    print("\n" + report_text)


if __name__ == "__main__":
    main()
