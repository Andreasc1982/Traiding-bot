#!/usr/bin/env python3
from datetime import datetime, timedelta
import time, requests, os, json, re, threading, socket
import yfinance as yf

# Global socket timeout — prevents feedparser.parse() and any urllib call from
# blocking the main thread indefinitely when an RSS/Nitter/Bloomberg server hangs.
# WebSocket keepalive (ping_interval=30, ping_timeout=10) is unaffected.
socket.setdefaulttimeout(15)

# ── Sentiment analyser: VADER (preferred) with TextBlob fallback ───────────
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer as _VaderIA
    _vader = _VaderIA()
    def _sentiment(text):
        """Return compound sentiment score in [-1, +1]. VADER primary."""
        return _vader.polarity_scores(text)["compound"]
    print("[SENTIMENT] VADER geladen")
except ImportError:
    from textblob import TextBlob
    def _sentiment(text):
        """Return polarity score in [-1, +1]. TextBlob fallback."""
        return TextBlob(text).sentiment.polarity
    print("[SENTIMENT] VADER nicht verfügbar — TextBlob Fallback")

try:
    import websocket as _ws_lib
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False
    print("[WARN] websocket-client fehlt: pip install websocket-client")

try:
    from config import config
except ImportError:
    config = {}

NEWSAPI_KEY       = config.get("newsapi_key", "")
TELEGRAM_TOKEN    = config.get("telegram_bot_token", "")
TELEGRAM_CHAT_ID  = config.get("telegram_chat_id", "")
ALPACA_API_KEY    = config.get("alpaca_api_key", "")
ALPACA_SECRET_KEY = config.get("alpaca_secret_key", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"   # always paper/testing
ALPACA_DATA_URL   = "https://data.alpaca.markets"
ALPACA_WS_URL     = "wss://stream.data.alpaca.markets/v2/iex"   # free IEX feed
DEMO_MODE         = config.get("demo_mode", True)

# Persists balance + daily-loss baseline between restarts
SUPER_STATE_PATH  = "/home/trading2025/trading_bot/super_state.json"

ETFS = {
    "energy":   "XLE",
    "oil":      "XOP",
    "industry": "XLI",
    "steel":    "SLX",
    "defense":  "ITA",
    "finance":  "XLF",
    "tech":     "XLK",
    "gold":     "GLD",
    "infra":    "PAVE",
    "crypto":   "IBIT",
}
ETF_SYMBOLS = list(ETFS.values())   # ["XLE", "XOP", ...] — subscribed in WS

# Top-5 constituent stocks per ETF — used for earnings-window check
# Trusts (GLD, IBIT) have no constituent earnings — empty list
ETF_CONSTITUENTS = {
    "XLE":  ["XOM", "CVX", "COP", "EOG", "SLB"],
    "XOP":  ["DVN", "MRO", "APA", "OXY", "FANG"],
    "XLI":  ["GE", "RTX", "UNP", "HON", "ETN"],
    "SLX":  ["NUE", "STLD", "RS", "CMC", "X"],
    "ITA":  ["LMT", "RTX", "NOC", "GD", "BA"],
    "XLF":  ["JPM", "BAC", "WFC", "GS", "MS"],
    "XLK":  ["MSFT", "AAPL", "NVDA", "AVGO", "META"],
    "GLD":  [],   # Gold bullion trust — no constituent earnings
    "PAVE": ["VMC", "MLM", "PWR", "CARR", "JCI"],
    "IBIT": [],   # Bitcoin ETF trust — no constituent earnings
}

KEYWORDS = {
    "tariff":    ["industry", "steel", "finance"],
    "drill":     ["energy", "oil"],
    "war":       ["defense"],
    "iran":      ["defense", "oil"],
    "ai":        ["tech"],
    "crypto":    ["crypto", "tech", "finance"],
    "bitcoin":   ["crypto", "finance"],
    "rate":      ["finance", "gold"],
    "inflation": ["gold", "energy"],
    "chip":      ["tech"],
    "oil":       ["energy", "oil"],
    "gold":      ["gold"],
    "blackrock": ["finance", "tech", "gold"],
    "goldman":   ["finance"],
    "nvidia":    ["tech"],
    "microsoft": ["tech"],
    "amazon":    ["tech", "infra"],
    "apple":     ["tech"],
    "pelosi":    ["tech", "finance"],
    "dalio":     ["gold", "finance"],
    "defense":   ["defense"],
    "military":  ["defense"],
    "fed":       ["finance", "gold"],
    "bank":      ["finance"],
    "energy":    ["energy", "oil"],
}
FIGURES = [
    "Trump", "Musk", "Powell", "Yellen", "Buffett",
    "BlackRock", "Goldman", "JPMorgan", "Citadel",
    "Pelosi", "Dalio", "Soros", "Bezos", "Zuckerberg",
    "Fink", "Dimon", "Griffin", "Icahn", "Ackman",
    "Nvidia", "Microsoft", "Amazon", "Apple", "Tesla",
    "Vanguard", "Berkshire", "OpenAI", "Mnuchin",
]


class SuperTradingBot:
    def __init__(self):
        self.demo        = DEMO_MODE
        self.balance     = 100000.0
        self.positions   = {}
        self.trades      = []
        self.stop_loss   = 2.0   # optimized: 3.0 → 2.0
        self.take_profit = 12.0  # optimized: 15.0 → 12.0
        self.max_pos     = 15
        self.pos_size    = 0.05
        self.excluded_symbols = {"XLF"}   # Optimizer-Flag 2026-06-14: >=50% SL-Exits (revidierbar)
        self.tg_ok       = False
        self.alpaca_ok   = False
        self.alpaca_headers = {}
        self.running     = True
        self.last_skips  = []
        self.last_congress = {}
        self.last_fg     = {"value": 50, "label": "N/A"}
        self.last_pc     = {"value": 1.0, "label": "N/A"}   # Put/Call ratio
        self._pc_cache   = None   # (multiplier: float, timestamp: float)
        self.start_balance = self.balance
        self.max_day_loss  = 0.10

        # Earnings calendar cache — refreshed once per calendar day
        self.earnings_cache       = {}    # stock_symbol → datetime.date
        self._earnings_cache_date = None  # date when cache was last built
        self._earnings_alerted    = set() # ETF symbols alerted this session

        # Higher-Timeframe (weekly) trend cache — refreshed every 30 min
        self._htf_cache = {}   # symbol → (bullish: bool, timestamp: float)

        # Correlation management — recent closes cached from get_indicators()
        self._bar_cache = {}   # symbol → list of last 20 daily closes

        # VWAP (session) cache — refreshed every 5 min per symbol
        self._vwap_cache = {}  # symbol → (vwap: float|None, timestamp: float)

        # ML meta-filter — Random Forest trained on trades_history.json
        self._ml_model         = None   # sklearn RandomForestClassifier or None
        self._ml_trained_count = 0      # number of labeled trades used in last training
        self._ml_last_train    = None   # date of last training (datetime.date)

        # Thread safety — RLock so _ws_check_price can call close_position safely
        self.positions_lock = threading.RLock()

        # WebSocket state
        self.ws_prices    = {}      # symbol → latest trade price from stream
        self.ws_connected = False
        self._ws          = None    # WebSocketApp handle

        # Telegram command flag — set True by /stop command, False by /start
        self.tg_paused    = False

        # Watchdog — updated each main loop iteration; watchdog thread kills on hang > 6 min
        self._last_heartbeat = time.time()

        # SPY macro cache — refreshed every 10 min
        self._spy_cache = None   # (pct_change: float, timestamp: float)

        # VIX volatility regime cache — refreshed every 30 min
        self._vix_cache = None   # ((name, size_mult), timestamp)

        # Drawdown alert flags — prevent repeated Telegram messages per zone
        self._dd_caution_sent = False
        self._dd_warning_sent = False
        self._dd_danger_sent  = False

        if os.path.exists("/home/trading2025/trading_bot/trades_history.json"):
            import json as _j
            self.trades = _j.load(open("/home/trading2025/trading_bot/trades_history.json"))
            print("[OK] " + str(len(self.trades)) + " Trades geladen")

        if TELEGRAM_TOKEN:
            try:
                import telegram
                self.tg = telegram.Bot(token=TELEGRAM_TOKEN)
                self.tg_ok = True
                print("[OK] Telegram")
            except Exception as e:
                print("[WARN] Telegram: " + str(e))
        else:
            print("[WARN] Kein Telegram")

        if ALPACA_API_KEY and ALPACA_SECRET_KEY:
            self.alpaca_headers = {
                "APCA-API-KEY-ID":     ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
            }
            try:
                r = requests.get(ALPACA_BASE_URL + "/v2/account",
                                 headers=self.alpaca_headers, timeout=10)
                if r.status_code == 200:
                    acc = r.json()
                    self.balance = float(acc.get("cash", self.balance))
                    self.alpaca_ok = True
                    print("[OK] Alpaca $" + str(round(self.balance, 2)))
                else:
                    print("[WARN] Alpaca " + str(r.status_code))
            except Exception as e:
                print("[WARN] Alpaca: " + str(e))
        else:
            print("[WARN] Kein Alpaca -> Demo")

        # Sync start_balance with API value before state restore
        self.start_balance = self.balance
        # Restore persisted balance (demo mode) and daily-loss baseline (all modes)
        self._load_state()

        # ML startup training — all other __init__ state is now set up
        self._ml_train()

        mode = "DEMO" if self.demo else "LIVE"
        print("=== SUPER BOT v3.0 | " + mode + " ===")
        print("Balance: $" + str(round(self.balance, 2)))

    # ── Telegram ───────────────────────────────────────────────────────────

    def send(self, msg):
        if self.tg_ok and TELEGRAM_CHAT_ID:
            try:
                url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
                requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=5)
            except Exception as e:
                print("[TG Error] " + str(e))

    # ── Price — WS cache → REST fallback ──────────────────────────────────

    def get_price(self, symbol):
        cached = self.ws_prices.get(symbol)
        if cached:
            return cached
        try:
            url = ALPACA_BASE_URL + "/v2/stocks/" + symbol + "/quotes/latest"
            r = requests.get(url, headers=self.alpaca_headers, timeout=5)
            if r.status_code == 200:
                price = r.json().get("quote", {}).get("ap", 0)
                if price and price > 0:
                    return float(price)
        except Exception:
            pass
        try:
            import yfinance as yf
            hist = yf.Ticker(symbol).history(period="1d", interval="1m")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            pass
        return None

    # ── Higher-Timeframe trend filter ──────────────────────────────────────

    def _get_htf_trend(self, symbol):
        """Weekly trend check — price above 10-week SMA = bullish HTF.
        Result cached 30 min so we don't spam the API on every trade() iteration."""
        cached = self._htf_cache.get(symbol)
        if cached and time.time() - cached[1] < 1800:
            return cached[0]
        try:
            url    = ALPACA_BASE_URL + "/v2/stocks/" + symbol + "/bars"
            params = {"timeframe": "1Week", "limit": 15,
                      "adjustment": "raw", "feed": "iex"}
            r = requests.get(url, headers=self.alpaca_headers,
                             params=params, timeout=8)
            bars = r.json().get("bars", []) if r.status_code == 200 else []
            if len(bars) < 10:
                # Not enough weekly data → treat as neutral (allow trade)
                self._htf_cache[symbol] = (True, time.time())
                return True
            closes  = [b["c"] for b in bars]
            ma10w   = sum(closes[-10:]) / 10
            bullish = closes[-1] > ma10w
            self._htf_cache[symbol] = (bullish, time.time())
            return bullish
        except Exception:
            return True   # neutral on error — don't block trades

    # ── VWAP — Session Fair Value ──────────────────────────────────────────

    def _get_vwap(self, symbol):
        """Volume-Weighted Average Price from today's intraday 5-min bars.
        Returns None when market is closed or data unavailable — callers treat
        None as neutral (vwap_ok = True) so trades are never blocked by connectivity."""
        cached = self._vwap_cache.get(symbol)
        if cached and time.time() - cached[1] < 300:   # 5-minute cache
            return cached[0]
        try:
            url    = ALPACA_BASE_URL + "/v2/stocks/" + symbol + "/bars"
            params = {"timeframe": "5Min", "limit": 80,
                      "adjustment": "raw", "feed": "iex"}
            r    = requests.get(url, headers=self.alpaca_headers,
                                params=params, timeout=6)
            bars = r.json().get("bars", []) if r.status_code == 200 else []
            if not bars:
                self._vwap_cache[symbol] = (None, time.time())
                return None
            # Keep only bars from today (UTC date prefix — Alpaca timestamps are UTC)
            today      = datetime.utcnow().strftime("%Y-%m-%d")
            today_bars = [b for b in bars if b["t"][:10] == today]
            if len(today_bars) < 3:
                # Market closed / pre-market — not enough intraday data
                self._vwap_cache[symbol] = (None, time.time())
                return None
            cum_tp_v = sum((b["h"] + b["l"] + b["c"]) / 3.0 * b["v"]
                           for b in today_bars)
            cum_v = sum(b["v"] for b in today_bars)
            vwap  = round(cum_tp_v / cum_v, 2) if cum_v > 0 else None
            self._vwap_cache[symbol] = (vwap, time.time())
            return vwap
        except Exception:
            return None   # neutral on any error — don't block trades

    # ── Indicators ─────────────────────────────────────────────────────────

    def get_indicators(self, symbol):
        try:
            # yfinance for daily ETF bars — Alpaca paper account returns null bars
            df = yf.download(symbol, period="6mo", interval="1d",
                             auto_adjust=True, progress=False)
            if df is None or len(df) < 78:
                return None
            # yfinance returns multi-level columns when auto_adjust=True
            def _col(name):
                if (name, symbol) in df.columns:
                    return list(df[(name, symbol)].astype(float))
                return list(df[name].astype(float))
            closes  = _col("Close")
            highs   = _col("High")
            lows    = _col("Low")
            volumes = _col("Volume")
            n = len(closes)

            ma20   = sum(closes[-20:]) / 20

            # ── Full RSI series (Wilder smoothing) — needed for StochRSI ──────
            rsi_p    = 14
            gains_r  = [max(closes[i] - closes[i-1], 0) for i in range(1, n)]
            losses_r = [max(closes[i-1] - closes[i], 0) for i in range(1, n)]
            ag = sum(gains_r[:rsi_p]) / rsi_p
            al = sum(losses_r[:rsi_p]) / rsi_p
            rsi_series = [100 - 100 / (1 + ag / al) if al > 0 else 100]
            for i in range(rsi_p, len(gains_r)):
                ag = (ag * (rsi_p - 1) + gains_r[i]) / rsi_p
                al = (al * (rsi_p - 1) + losses_r[i]) / rsi_p
                rsi_series.append(100 - 100 / (1 + ag / al) if al > 0 else 100)
            rsi = round(rsi_series[-1], 1)   # last value = current RSI (unchanged)

            # ── Stochastic RSI (%K, %D) ────────────────────────────────────────
            # StochRSI[i] = (RSI[i] - min(RSI,14)) / (max(RSI,14) - min(RSI,14))
            # %K = 3-bar SMA of StochRSI   |   %D = 3-bar SMA of %K
            stoch_ok = True   # neutral fallback if not enough bars
            sk = 0.5          # neutral %K fallback for ML feature vector
            if len(rsi_series) >= rsi_p + 5:
                stoch_raw = []
                for i in range(rsi_p - 1, len(rsi_series)):
                    win = rsi_series[i - rsi_p + 1: i + 1]
                    lo, hi = min(win), max(win)
                    stoch_raw.append((rsi_series[i] - lo) / (hi - lo) if hi > lo else 0.5)
                if len(stoch_raw) >= 5:
                    k_ser = [sum(stoch_raw[i-2:i+1]) / 3 for i in range(2, len(stoch_raw))]
                    d_ser = [sum(k_ser[i-2:i+1])    / 3 for i in range(2, len(k_ser))]
                    if k_ser and d_ser:
                        sk, sd = k_ser[-1], d_ser[-1]
                        # Bullish: %K above %D (momentum up) and not overbought
                        stoch_ok = sk > sd and sk < 0.8

            std20    = (sum((c - ma20) ** 2 for c in closes[-20:]) / 20) ** 0.5
            bb_upper = ma20 + 2 * std20
            bb_lower = ma20 - 2 * std20

            def ema_series(vals, period):
                k = 2 / (period + 1)
                out = [sum(vals[:period]) / period]
                for v in vals[period:]:
                    out.append(v * k + out[-1] * (1 - k))
                return out

            ema12 = ema_series(closes, 12)
            ema26 = ema_series(closes, 26)
            macd_line   = [ema12[i + 14] - ema26[i] for i in range(len(ema26))]
            signal_line = ema_series(macd_line, 9)
            macd_val    = macd_line[-1]
            signal_val  = signal_line[-1]

            trs = [max(highs[i] - lows[i],
                       abs(highs[i] - closes[i-1]),
                       abs(lows[i] - closes[i-1])) for i in range(1, n)]
            atr = sum(trs[-14:]) / 14

            st_trs = [highs[0] - lows[0]] + [
                max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
                for i in range(1, n)
            ]
            st_atr = [0.0] * n
            st_atr[6] = sum(st_trs[:7]) / 7
            for i in range(7, n):
                st_atr[i] = (st_atr[i-1] * 6 + st_trs[i]) / 7
            ub = [0.0] * n
            lb = [0.0] * n
            st_dir = [1] * n
            for i in range(6, n):
                hl2  = (highs[i] + lows[i]) / 2
                b_ub = hl2 + 4.0 * st_atr[i]   # optimized: 3.5 → 4.0
                b_lb = hl2 - 4.0 * st_atr[i]   # optimized: 3.5 → 4.0
                if i == 6:
                    ub[i], lb[i] = b_ub, b_lb
                else:
                    ub[i] = b_ub if b_ub < ub[i-1] or closes[i-1] > ub[i-1] else ub[i-1]
                    lb[i] = b_lb if b_lb > lb[i-1] or closes[i-1] < lb[i-1] else lb[i-1]
                    if st_dir[i-1] == 1:
                        st_dir[i] = -1 if closes[i] < lb[i] else 1
                    else:
                        st_dir[i] = 1 if closes[i] > ub[i] else -1
            supertrend = st_dir[-1]

            obv = [volumes[0]]
            for i in range(1, n):
                if closes[i] > closes[i-1]:
                    obv.append(obv[-1] + volumes[i])
                elif closes[i] < closes[i-1]:
                    obv.append(obv[-1] - volumes[i])
                else:
                    obv.append(obv[-1])
            avg_vol_20 = sum(volumes[-20:]) / 20
            obv_rising = (len(obv) > 11 and obv[-1] > obv[-11]) or volumes[-1] > avg_vol_20 * 0.5

            # ── CMF — Chaikin Money Flow (period=20) ──────────────────────────
            # MFM = (2C - H - L) / (H - L); CMF = Σ(MFM×V, 20) / Σ(V, 20)
            # Bounded [-1,+1]: >0 = net buying pressure, <0 = net selling
            mfv_sum = 0.0
            vol_sum = 0.0
            for i in range(max(0, n - 20), n):
                hl = highs[i] - lows[i]
                if hl > 0:
                    mfm = (2 * closes[i] - highs[i] - lows[i]) / hl
                else:
                    mfm = 0.0
                mfv_sum += mfm * volumes[i]
                vol_sum += volumes[i]
            cmf = round(mfv_sum / vol_sum, 4) if vol_sum > 0 else 0.0

            # Parabolic SAR (af=0.02, max=0.2)
            def calc_psar(hs, ls, af0=0.02, af_max=0.2):
                rising = True
                sar, ep, af = ls[0], hs[0], af0
                psars = [sar]
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
                    psars.append(sar)
                return psars[-1], rising

            psar_val, psar_bull = calc_psar(highs, lows)
            psar_ok = closes[-1] > psar_val   # price above PSAR → bullish

            # Ichimoku Cloud (needs 78+ bars; cloud = Spans plotted 26 bars ahead)
            tenkan = (max(highs[-9:])  + min(lows[-9:]))  / 2
            kijun  = (max(highs[-26:]) + min(lows[-26:])) / 2
            t26    = (max(highs[-35:-26]) + min(lows[-35:-26])) / 2
            k26    = (max(highs[-52:-26]) + min(lows[-52:-26])) / 2
            span_a = (t26 + k26) / 2
            span_b = (max(highs[-78:-26]) + min(lows[-78:-26])) / 2
            cloud_top = max(span_a, span_b)
            ichi_ok   = closes[-1] > cloud_top   # price above cloud → bullish

            # ── ADX — Average Directional Index (Wilder, period=14) ───────────
            # Measures trend strength: ≥25 = trending, 20-25 = transitional, <20 = ranging
            def _wilder(vals, p):
                if len(vals) < p:
                    return []
                s = [sum(vals[:p])]
                for v in vals[p:]:
                    s.append(s[-1] * (p - 1) / p + v)
                return s

            adx_p    = 14
            plus_dm  = [max(highs[i] - highs[i-1], 0)
                        if (highs[i] - highs[i-1]) > max(lows[i-1] - lows[i], 0) else 0.0
                        for i in range(1, n)]
            minus_dm = [max(lows[i-1] - lows[i], 0)
                        if (lows[i-1] - lows[i]) > max(highs[i] - highs[i-1], 0) else 0.0
                        for i in range(1, n)]
            s_tr  = _wilder(trs,      adx_p)
            s_pdm = _wilder(plus_dm,  adx_p)
            s_mdm = _wilder(minus_dm, adx_p)
            if s_tr and len(s_tr) >= adx_p:
                dx_list = []
                for i in range(len(s_tr)):
                    p_i = 100 * s_pdm[i] / s_tr[i] if s_tr[i] > 0 else 0.0
                    m_i = 100 * s_mdm[i] / s_tr[i] if s_tr[i] > 0 else 0.0
                    d   = p_i + m_i
                    dx_list.append(100 * abs(p_i - m_i) / d if d > 0 else 0.0)
                # ADX = Wilder MA of DX — initial value is AVERAGE (not sum like ATR)
                if len(dx_list) >= adx_p:
                    adx_val = sum(dx_list[:adx_p]) / adx_p
                    for dx_v in dx_list[adx_p:]:
                        adx_val = (adx_val * (adx_p - 1) + dx_v) / adx_p
                    adx = round(adx_val, 1)
                else:
                    adx = 25.0
            else:
                adx = 25.0

            # Cache recent closes for correlation check in trade()
            self._bar_cache[symbol] = closes[-20:]

            return {
                "rsi":         round(rsi, 1),
                "ma20":        round(ma20, 2),
                "bb_upper":    round(bb_upper, 2),
                "bb_lower":    round(bb_lower, 2),
                "macd":        round(macd_val, 4),
                "macd_signal": round(signal_val, 4),
                "macd_hist":   round(macd_val - signal_val, 4),
                "atr":         round(atr, 2),
                "supertrend":  supertrend,
                "obv_rising":  obv_rising,
                "cmf":         cmf,
                "psar":        round(psar_val, 2),
                "psar_ok":     psar_ok,
                "tenkan":      round(tenkan, 2),
                "kijun":       round(kijun, 2),
                "cloud_top":   round(cloud_top, 2),
                "ichi_ok":     ichi_ok,
                "adx":         adx,
                "stoch_ok":    stoch_ok,
                "stoch_k":     round(sk, 4),   # continuous %K for ML feature vector
                "price":       closes[-1],
            }
        except Exception as e:
            print("[IND-ERR] " + str(e)[:120])
            return None

    # ── Correlation management ─────────────────────────────────────────────

    @staticmethod
    def _pearson(a, b):
        """Pearson correlation of daily returns for two close-price series."""
        n = min(len(a), len(b))
        if n < 5:
            return 0.0
        a, b = a[-n:], b[-n:]
        ra = [(a[i] - a[i-1]) / a[i-1] for i in range(1, n) if a[i-1] != 0]
        rb = [(b[i] - b[i-1]) / b[i-1] for i in range(1, n) if b[i-1] != 0]
        n2 = min(len(ra), len(rb))
        if n2 < 5:
            return 0.0
        ra, rb = ra[-n2:], rb[-n2:]
        ma_ = sum(ra) / n2
        mb_ = sum(rb) / n2
        num = sum((ra[i] - ma_) * (rb[i] - mb_) for i in range(n2))
        da  = sum((ra[i] - ma_) ** 2 for i in range(n2)) ** 0.5
        db  = sum((rb[i] - mb_) ** 2 for i in range(n2)) ** 0.5
        return num / (da * db) if da * db > 0 else 0.0

    def _check_correlation(self, symbol):
        """Return (corr, worst_symbol) vs open positions. corr=0 if no positions."""
        closes_new = self._bar_cache.get(symbol)
        if not closes_new:
            return 0.0, None
        max_corr   = 0.0
        worst_sym  = None
        with self.positions_lock:
            open_syms = list(self.positions.keys())
        for pos_sym in open_syms:
            closes_pos = self._bar_cache.get(pos_sym)
            if not closes_pos:
                continue
            corr = self._pearson(closes_new, closes_pos)
            if corr > max_corr:
                max_corr  = corr
                worst_sym = pos_sym
        return round(max_corr, 2), worst_sym

    # ── WebSocket price stream ─────────────────────────────────────────────

    def start_websocket(self):
        if not WS_AVAILABLE:
            print("[WS] websocket-client nicht verfügbar — kein Echtzeit-Stream")
            return
        if not ALPACA_API_KEY:
            print("[WS] Kein Alpaca Key — WebSocket übersprungen")
            return
        t = threading.Thread(target=self._ws_run, daemon=True, name="ws-price-stream")
        t.start()
        print("[WS] Echtzeit Price-Stream Thread gestartet (" +
              str(len(ETF_SYMBOLS)) + " Symbole)")

    def _ws_run(self):
        """Reconnect loop — daemon thread, exits when self.running=False."""
        while self.running:
            try:
                self._ws = _ws_lib.WebSocketApp(
                    ALPACA_WS_URL,
                    on_open=self._ws_on_open,
                    on_message=self._ws_on_message,
                    on_error=self._ws_on_error,
                    on_close=self._ws_on_close,
                )
                self._ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                print("[WS] Crash: " + str(e))
            self.ws_connected = False
            if self.running:
                print("[WS] Verbindung verloren — Reconnect in 5s...")
                time.sleep(5)

    def _ws_on_open(self, ws):
        ws.send(json.dumps({
            "action": "auth",
            "key":    ALPACA_API_KEY,
            "secret": ALPACA_SECRET_KEY,
        }))

    def _ws_on_message(self, ws, raw):
        try:
            msgs = json.loads(raw)
            for m in msgs:
                t = m.get("T")
                if t == "success" and m.get("msg") == "authenticated":
                    ws.send(json.dumps({"action": "subscribe", "trades": ETF_SYMBOLS}))
                    self.ws_connected = True
                    print("[WS] Auth OK — abonniert: " + str(ETF_SYMBOLS))

                elif t == "subscription":
                    print("[WS] Aktive Subscriptions: " + str(m.get("trades", [])))

                elif t == "t":   # trade tick
                    symbol = m.get("S")
                    price  = m.get("p")
                    if symbol and price:
                        price = float(price)
                        self.ws_prices[symbol] = price
                        self._ws_check_price(symbol, price)

                elif t == "error":
                    print("[WS] Server Error: " + str(m))
        except Exception as e:
            print("[WS] Message parse error: " + str(e))

    def _ws_on_error(self, ws, error):
        print("[WS] Error: " + str(error))
        self.ws_connected = False

    def _ws_on_close(self, ws, code, msg):
        self.ws_connected = False
        print("[WS] Geschlossen — Code: " + str(code))

    def _ws_check_price(self, symbol, price):
        """
        Called on every trade tick from the WebSocket thread.
        Evaluates stop-loss and trailing take-profit for all open positions.
        positions_lock guards shared state against the main thread.
        """
        with self.positions_lock:
            if symbol not in self.positions:
                return
            pos = self.positions[symbol]
            pnl_pct = ((price - pos["entry"]) / pos["entry"]) * 100

            if price > pos.get("highest", pos["entry"]):
                pos["highest"] = price

            trailing = ((pos["highest"] - price) / pos["highest"]) * 100

            psar_stop = pos.get("psar_stop")
            sl = pos.get("stop_loss", self.stop_loss)
            tp = pos.get("take_profit", self.take_profit)
            if psar_stop is not None and price < psar_stop:
                trigger = "WS-PSAR-STOP"
            elif pnl_pct <= -sl:
                trigger = "WS-STOP-LOSS"
            elif pnl_pct >= tp and trailing >= 3.0:
                trigger = "WS-TRAIL-STOP"
            else:
                return

        # Fire close outside the lock — close_position does its own atomic pop
        print("[WS] " + trigger + " " + symbol +
              " $" + str(round(price, 2)) +
              " pnl=" + str(round(pnl_pct, 2)) + "%")
        self.close_position(symbol, price, trigger, pnl_pct)

    # ── Order placement ────────────────────────────────────────────────────

    def alpaca_order(self, symbol, qty, side):
        if not self.alpaca_ok:
            return
        try:
            r = requests.post(ALPACA_BASE_URL + "/v2/orders",
                headers=self.alpaca_headers,
                json={"symbol": symbol, "qty": str(qty), "side": side,
                      "type": "market", "time_in_force": "day"},
                timeout=10)
            if r.status_code in (200, 201):
                print("[ALPACA] OK: " + side + " " + str(qty) + " " + symbol)
            else:
                print("[ALPACA] Fehler: " + str(r.status_code) + " " + r.text[:100])
        except Exception as e:
            print("[ALPACA] " + str(e))

    def _sync_balance(self):
        try:
            r = requests.get(ALPACA_BASE_URL + "/v2/account",
                             headers=self.alpaca_headers, timeout=5)
            if r.status_code == 200:
                with self.positions_lock:
                    self.balance = float(r.json().get("cash", self.balance))
        except Exception:
            pass

    # ── State persistence ──────────────────────────────────────────────────────

    def _load_state(self):
        """Restore balance (demo), start_balance (daily loss baseline) and open
        positions from disk."""
        try:
            if not os.path.exists(SUPER_STATE_PATH):
                return
            with open(SUPER_STATE_PATH) as f:
                st = json.load(f)
            today = datetime.now().strftime("%Y-%m-%d")

            # Demo mode: Alpaca paper cash is always $100k — use persisted balance instead
            if self.demo or not self.alpaca_ok:
                saved_bal = st.get("balance", 0)
                if saved_bal > 0:
                    self.balance = saved_bal
                    print("[STATE] Balance wiederhergestellt: $" + str(round(self.balance, 2)))

            # Restore daily-loss baseline only if same calendar day
            # (fresh day → start_balance stays at current balance, counter resets naturally)
            if st.get("day_date") == today:
                saved_start = st.get("day_start_balance", 0)
                if saved_start > 0:
                    self.start_balance = saved_start
                    print("[STATE] Tagesbasis wiederhergestellt: $" +
                          str(round(self.start_balance, 2)))
            else:
                self.start_balance = self.balance

            # Restore open positions — always, regardless of day.
            # Without this, a Super restart loses all position tracking: the
            # position value "evaporates" from the dashboard while balance stays
            # at post-buy cash, so the combined portfolio drops by the position
            # value and the risk agent misreads it as a large drawdown (false
            # -15% HALT_BOTH). Restoring keeps stop-loss/take-profit firing after
            # a crash/restart. Mirrors crypto_bot._load_state().
            saved_pos = st.get("positions", {})
            if saved_pos and isinstance(saved_pos, dict):
                valid = {}
                for sym, pos in saved_pos.items():
                    # Basic sanity check — entry and shares must be present and positive
                    if (isinstance(pos, dict) and
                            pos.get("entry", 0) > 0 and
                            pos.get("shares", 0) > 0):
                        valid[sym] = pos
                if valid:
                    with self.positions_lock:
                        self.positions = valid
                    for sym, pos in valid.items():
                        print("[STATE] Position wiederhergestellt: " + sym +
                              " " + str(pos["shares"]) +
                              " @ $" + str(round(pos["entry"], 2)) +
                              " (" + str(pos.get("sector", "?")) + ")" +
                              " seit " + pos.get("time", "?"))
        except Exception as e:
            print("[STATE] Load error: " + str(e))

    def _save_state(self):
        """Persist balance, daily-loss baseline and open positions to disk."""
        try:
            with self.positions_lock:
                bal       = self.balance
                start     = self.start_balance
                positions = dict(self.positions)   # snapshot under lock
            st = {
                "balance":           round(bal, 2),
                "day_start_balance": round(start, 2),
                "day_date":          datetime.now().strftime("%Y-%m-%d"),
                "positions":         positions,     # full position dicts, restored on startup
            }
            with open(SUPER_STATE_PATH, "w") as f:
                json.dump(st, f)
            os.chmod(SUPER_STATE_PATH, 0o600)   # owner read/write only
        except Exception as e:
            print("[STATE] Save error: " + str(e))

    # ── Earnings calendar ──────────────────────────────────────────────────

    def _fetch_earnings(self):
        """Fetch next-earnings dates for all ETF constituents. Cached once per day.

        Runs all ~30 yfinance calls in parallel (ThreadPoolExecutor, 6 workers)
        with a hard 45-second total timeout so a hanging Yahoo Finance request
        never blocks the main bot loop.
        """
        import concurrent.futures
        today = datetime.now().date()
        if self._earnings_cache_date == today:
            return
        # New calendar day — reset alert set so positions get re-alerted if still open
        self._earnings_alerted = set()
        cache = {}
        try:
            import yfinance as yf

            all_stocks = set(s for stocks in ETF_CONSTITUENTS.values() for s in stocks)

            def _fetch_one(stock):
                """Fetch calendar for a single stock. Returns (stock, date|None)."""
                try:
                    cal = yf.Ticker(stock).calendar
                    ed = None
                    if isinstance(cal, dict):
                        raw = cal.get("Earnings Date")
                        if raw:
                            item = raw[0] if isinstance(raw, list) else raw
                            ed = self._parse_earnings_date(item)
                    elif hasattr(cal, "columns"):
                        if "Earnings Date" in cal.columns:
                            ed = self._parse_earnings_date(cal["Earnings Date"].iloc[0])
                    return stock, ed
                except Exception:
                    return stock, None   # unavailable or parse error — skip silently

            done = 0
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=6)
            futs = {pool.submit(_fetch_one, s): s for s in sorted(all_stocks)}
            try:
                for fut in concurrent.futures.as_completed(futs, timeout=45):
                    stock, ed = fut.result()
                    if ed:
                        cache[stock] = ed
                    done += 1
            except concurrent.futures.TimeoutError:
                print("[EARNINGS] Timeout nach 45s — " + str(done) + "/" +
                      str(len(all_stocks)) + " Stocks abgerufen")
            finally:
                pool.shutdown(wait=False, cancel_futures=True)  # don't block on hung yf calls

        except ImportError:
            print("[EARNINGS] yfinance nicht installiert — Earnings-Check deaktiviert")
        except Exception as e:
            print("[EARNINGS] Fehler: " + str(e))

        self.earnings_cache       = cache
        self._earnings_cache_date = today
        print("[EARNINGS] Cache aktualisiert: " + str(len(cache)) +
              " Termine für " + today.strftime("%Y-%m-%d"))

    def _parse_earnings_date(self, val):
        """Convert a yfinance earnings date value to a datetime.date, or None."""
        try:
            import pandas as pd
            return pd.Timestamp(val).date()
        except Exception:
            pass
        try:
            if hasattr(val, "date"):
                return val.date()
            return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
        except Exception:
            return None

    def _get_earnings_window(self, etf_symbol):
        """Return (blocked, stock, date_str) if ETF constituent has earnings within window.

        Window: 2 days before earnings through 1 day after.
        i.e. delta = earnings_date − today must be in [-1, +2].
        """
        today = datetime.now().date()
        for stock in ETF_CONSTITUENTS.get(etf_symbol, []):
            ed = self.earnings_cache.get(stock)
            if ed is None:
                continue
            delta = (ed - today).days
            if -1 <= delta <= 2:
                return True, stock, str(ed)
        return False, None, None

    def _check_held_earnings(self):
        """Send a one-time Telegram alert for held positions near constituent earnings."""
        with self.positions_lock:
            symbols = list(self.positions.keys())
        for sym in symbols:
            if sym in self._earnings_alerted:
                continue
            blocked, stock, ed = self._get_earnings_window(sym)
            if blocked:
                msg = ("⚠️ EARNINGS: " + sym + " — Konstituent " + stock +
                       " Earnings " + ed +
                       " | Position gehalten (kein Autoverkauf)")
                print("[EARNINGS] " + msg)
                self.send(msg)
                self._earnings_alerted.add(sym)

    # ── Stop loss / take profit (polling fallback) ─────────────────────────

    def check_stops(self):
        """Polling fallback — only runs when WebSocket is disconnected."""
        with self.positions_lock:
            symbols = list(self.positions.keys())
        for symbol in symbols:
            price = self.get_price(symbol)
            if price is None or price <= 0:
                continue
            with self.positions_lock:
                if symbol not in self.positions:
                    continue
                pos     = self.positions[symbol]
                pnl_pct = ((price - pos["entry"]) / pos["entry"]) * 100
                if price > pos.get("highest", pos["entry"]):
                    pos["highest"] = price
                trailing = ((pos["highest"] - price) / pos["highest"]) * 100
                psar_stop = pos.get("psar_stop")
                sl = pos.get("stop_loss", self.stop_loss)
                tp = pos.get("take_profit", self.take_profit)
                if psar_stop is not None and price < psar_stop:
                    trigger = "PSAR-STOP"
                elif pnl_pct <= -sl:
                    trigger = "STOP-LOSS"
                elif pnl_pct >= tp and trailing >= 3.0:
                    trigger = "TRAIL-STOP"
                else:
                    continue
            self.close_position(symbol, price, trigger, pnl_pct)

    # ── Position close ─────────────────────────────────────────────────────

    def close_position(self, symbol, price, reason, pnl_pct):
        # Atomically claim position — prevents double-close from WS + main thread
        with self.positions_lock:
            pos = self.positions.pop(symbol, None)
        if pos is None:
            return   # already closed by the other thread

        fill_out = price * (1 - getattr(self, "sim_slip", 0.0002)) if self.demo else price
        profit = pos["shares"] * (fill_out - pos["entry"])

        # Network calls outside lock
        if not self.demo and self.alpaca_ok:
            self.alpaca_order(symbol, pos["shares"], "sell")
            self._sync_balance()
        else:
            with self.positions_lock:
                self.balance += pos["shares"] * fill_out

        trade_record = {
            "symbol":   symbol,
            "profit":   round(profit, 0),
            "pnl_pct":  round(pnl_pct, 1),
            "reason":   reason,
            "time":     datetime.now().strftime("%Y-%m-%d %H:%M"),
            "sector":   pos.get("sector", ""),
            "features": pos.get("ml_features"),   # None for pre-ML trades — skipped in training
            "ml_prob":  pos.get("ml_prob"),        # model's entry confidence (informational)
        }
        with self.positions_lock:
            self.trades.append(trade_record)

        with open("/home/trading2025/trading_bot/trades_history.json", "w") as f:
            json.dump(self.trades, f)

        self._save_state()   # persist balance after every close

        with self.positions_lock:
            bal = self.balance
        msg = ("CLOSE " + reason + " " + symbol + ": " +
               str(round(pnl_pct, 1)) + "% | $" + str(round(profit, 0)) +
               " | Bal: $" + str(round(bal, 0)))
        print(msg)
        self.send(msg)

    # ── Watchdog ────────────────────────────────────────────────────────────

    def _watchdog_run(self):
        """Daemon thread — kills process if main loop hasn't updated heartbeat in 6 min.
        Monitor agent detects dead screen session and restarts within 60s."""
        TIMEOUT = 360   # 6 minutes (10-min cycle + buffer)
        while True:
            time.sleep(60)
            age = time.time() - self._last_heartbeat
            if age > TIMEOUT:
                print("[WATCHDOG] Hauptloop haengt seit {:.0f}s — erzwinge Neustart".format(age))
                os._exit(1)

    # ── Time-based exit for stuck positions ─────────────────────────────────

    def check_stuck_positions(self):
        """Exit positions that block slots without going anywhere.

        Rules (stocks — market only open ~6.5h/day):
        - Any position open > 5 trading days AND best P&L never reached +5% → TIME-EXIT
        - Any position open > 10 trading days → hard exit (free up capital)
        """
        STUCK_DAYS  = 5    # calendar days without meaningful move
        STUCK_PEAK  = 5.0  # only 'stuck' if best P&L was never above this %
        HARD_DAYS   = 10   # absolute maximum

        with self.positions_lock:
            symbols = list(self.positions.keys())

        for symbol in symbols:
            try:
                with self.positions_lock:
                    if symbol not in self.positions:
                        continue
                    pos = self.positions[symbol]

                entry_time = pos.get("time", "")
                try:
                    entry_dt = datetime.strptime(entry_time, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    try:
                        entry_dt = datetime.strptime(entry_time, "%Y-%m-%d %H:%M")
                    except ValueError:
                        continue

                age_days = (datetime.now() - entry_dt).total_seconds() / 86400
                price = self.ws_prices.get(symbol)
                if not price or price <= 0:
                    continue

                pnl_pct  = ((price - pos["entry"]) / pos["entry"]) * 100
                best_pnl = ((pos.get("highest", pos["entry"]) - pos["entry"]) / pos["entry"]) * 100

                reason = None
                if age_days >= HARD_DAYS:
                    reason = "TIME-EXIT-MAX"
                elif age_days >= STUCK_DAYS and best_pnl < STUCK_PEAK:
                    reason = "TIME-EXIT-STUCK"

                if reason:
                    print("[TIME-EXIT] {} nach {:.1f}d | P&L: {:.1f}% | {}".format(
                        symbol, age_days, pnl_pct, reason))
                    self.send("⏰ <b>TIME-EXIT</b>: {} nach <b>{:.1f}d</b>\n"
                              "P&amp;L: {:.1f}% | Best: {:.1f}% | {}".format(
                              symbol, age_days, pnl_pct, best_pnl, reason))
                    self.close_position(symbol, price, reason, pnl_pct)

            except Exception as e:
                print("[TIME-EXIT] Fehler bei {}: {}".format(symbol, e))

    # ── SPY macro filter ─────────────────────────────────────────────────────

    def _get_spy_trend(self):
        """Returns today's SPY % change as market-wide filter.
        Cached 10 min. Returns 0.0 on error (neutral — don't block trades)."""
        cached = self._spy_cache
        if cached and time.time() - cached[1] < 600:
            return cached[0]
        try:
            url = "https://data.alpaca.markets/v2/stocks/bars"
            params = {"symbols": "SPY", "timeframe": "1Day", "limit": 2, "feed": "iex"}
            r = requests.get(url, headers=self.alpaca_headers, params=params, timeout=8)
            bars = r.json().get("bars", {}).get("SPY", []) if r.status_code == 200 else []
            if len(bars) >= 2:
                pct = (bars[-1]["c"] - bars[-2]["c"]) / bars[-2]["c"] * 100
            elif len(bars) == 1:
                pct = (bars[0]["c"] - bars[0]["o"]) / bars[0]["o"] * 100
            else:
                pct = 0.0
            self._spy_cache = (round(pct, 2), time.time())
            return round(pct, 2)
        except Exception:
            return 0.0

    def _get_vix_regime(self):
        """Fetch VIX from Yahoo Finance and return volatility regime.
        Returns (regime_name, size_mult):
          LOW      VIX < 15  → 1.2× size  (calm market, go bigger)
          NORMAL   VIX 15-25 → 1.0× size  (standard)
          HIGH     VIX 25-35 → 0.5× size  (stressed, reduce exposure)
          EXTREME  VIX > 35  → 0.0× size  (no new trades — crash mode)
        Cached 30 min. Returns NORMAL on any error (never blocks trades).
        """
        cached = self._vix_cache
        if cached and time.time() - cached[1] < 1800:
            return cached[0]
        try:
            r = requests.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX",
                params={"interval": "1d", "range": "5d"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=8,
            )
            closes = r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            vix = next((v for v in reversed(closes) if v is not None), 20.0)

            if vix < 15:
                result = ("LOW",     1.2)
            elif vix < 25:
                result = ("NORMAL",  1.0)
            elif vix < 35:
                result = ("HIGH",    0.5)
            else:
                result = ("EXTREME", 0.0)

            self._vix_cache = (result, time.time())
            print("[VIX] {:.1f} → {} (size×{})".format(vix, result[0], result[1]))
            return result
        except Exception as e:
            print("[VIX] Fehler: " + str(e) + " → NORMAL")
            return ("NORMAL", 1.0)

    # ── News & sentiment ───────────────────────────────────────────────────

    def fetch_twitter(self):
        """VIP sentiment via Google News RSS (replaces dead Nitter/Twitter scraping).
        Tracks market-moving statements from Trump, Musk, and the White House through
        news articles — same 1.3x VIP boost applies in the scoring loop.
        """
        import feedparser
        feeds = [
            "https://news.google.com/rss/search?q=trump+economy+stocks+market&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=trump+tariff+trade+economy&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=elon+musk+market+economy+stocks&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=white+house+executive+order+economy&hl=en-US&gl=US&ceid=US:en",
        ]
        articles = []
        def _fetch_vip(url):
            try:
                import feedparser
                r    = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                feed = feedparser.parse(r.content)
                return [{"title": e.title, "description": getattr(e, "summary", "")}
                        for e in feed.entries[:8]]
            except Exception:
                return []
        from concurrent.futures import ThreadPoolExecutor, as_completed
        pool = ThreadPoolExecutor(max_workers=4)
        futures = {pool.submit(_fetch_vip, url): url for url in feeds}
        try:
            for fut in as_completed(futures, timeout=15):
                try:
                    articles.extend(fut.result())
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        print("[VIP-NEWS] " + str(len(articles)) + " Artikel (Trump/Musk/POTUS via Google News)")
        return articles

    def fetch_news(self):
        import feedparser
        feeds = [
            "https://feeds.bbci.co.uk/news/business/rss.xml",
            "https://feeds.marketwatch.com/marketwatch/topstories/",
            "https://finance.yahoo.com/news/rssindex",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
            "https://feeds.bloomberg.com/markets/news.rss",
            "https://news.google.com/rss/search?q=stocks+economy&hl=en-US&gl=US&ceid=US:en",
            "https://www.federalreserve.gov/feeds/press_all.xml",
            "https://www.federalreserve.gov/feeds/speeches.xml",
            "https://www.federalreserve.gov/feeds/press_monetary.xml",
            "https://news.google.com/rss/search?q=federal+reserve+interest+rate&hl=en-US&gl=US&ceid=US:en",
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&dateb=&owner=include&count=40&output=atom",
            "https://news.google.com/rss/search?q=SEC+insider+filing+executive+purchase&hl=en-US&gl=US&ceid=US:en",
            "https://unusualwhales.com/rss/congress",
            "https://unusualwhales.com/rss/political",
            "https://news.google.com/rss/search?q=congress+stock+trade+disclosure&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=senator+representative+stock+purchase&hl=en-US&gl=US&ceid=US:en",
        ]
        articles = []
        def _fetch_feed(url):
            try:
                import feedparser
                r    = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                feed = feedparser.parse(r.content)
                return [e.title + " " + getattr(e, "summary", "") for e in feed.entries[:10]]
            except Exception:
                return []
        from concurrent.futures import ThreadPoolExecutor, as_completed
        pool = ThreadPoolExecutor(max_workers=10)
        futures = {pool.submit(_fetch_feed, url): url for url in feeds}
        try:
            for fut in as_completed(futures, timeout=15):
                try:
                    articles.extend(fut.result())
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        print("[NEWS] " + str(len(articles)) + " Artikel via RSS")
        return articles

    def fetch_congress(self):
        import feedparser
        scores = {k: 0.0 for k in ETFS.keys()}
        ticker_sector = {
            "nvda": "tech",   "msft": "tech",   "aapl": "tech",   "amzn": "tech",
            "googl": "tech",  "meta": "tech",   "tsla": "tech",   "amd": "tech",
            "intc": "tech",   "crm": "tech",    "orcl": "tech",   "xlk": "tech",
            "xle": "energy",  "xop": "oil",     "cvx": "energy",  "xom": "energy",
            "cop": "energy",  "slb": "energy",  "oxy": "oil",
            "xlf": "finance", "jpm": "finance", "bac": "finance", "gs": "finance",
            "ms": "finance",  "wfc": "finance", "c": "finance",
            "ita": "defense", "lmt": "defense", "rtx": "defense", "noc": "defense",
            "ba": "defense",  "gd": "defense",
            "xli": "industry","cat": "industry","de": "industry", "hon": "industry",
            "slx": "steel",   "x": "steel",     "nue": "steel",   "stld": "steel",
            "gld": "gold",    "nem": "gold",     "gold": "gold",   "agn": "gold",
            "pave": "infra",  "uri": "infra",   "vmc": "infra",   "mlm": "infra",
            "ibit": "crypto", "coin": "crypto", "mstr": "crypto",
        }
        vip_members = [
            "pelosi", "tuberville", "ossoff", "collins", "warren",
            "ocasio", "mcconnell", "schumer", "johnson", "jeffries",
        ]
        feeds = [
            "https://unusualwhales.com/rss/congress",
            "https://unusualwhales.com/rss/political",
            "https://news.google.com/rss/search?q=congress+member+stock+purchase+sale&hl=en-US&gl=US&ceid=US:en",
        ]
        count = 0
        for url in feeds:
            try:
                r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                feed = feedparser.parse(r.content)
                for entry in feed.entries[:20]:
                    raw  = entry.title + " " + getattr(entry, "summary", "")
                    text = re.sub(r"<[^>]+>", " ", raw).lower()
                    is_buy  = any(w in text for w in ["purchase","buy","bought","call option","acquired"])
                    is_sell = any(w in text for w in ["sale","sell","sold","put option","disposed"])
                    direction = 1 if is_buy else (-1 if is_sell else 0)
                    if direction == 0:
                        continue
                    vip   = any(m in text for m in vip_members)
                    boost = 1.8 if vip else 1.0
                    for ticker, sector in ticker_sector.items():
                        if re.search(r'\b' + ticker + r'\b', text):
                            scores[sector] += direction * boost * 0.6
                            count += 1
            except Exception as e:
                print("[CONGRESS] " + str(e))
        print("[CONGRESS] " + str(count) + " Handelssignale erkannt")
        return scores

    def fetch_fear_greed(self):
        try:
            r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
            if r.status_code == 200:
                d = r.json()["data"][0]
                value = int(d["value"])
                label = d["value_classification"]
                print("[F&G] " + str(value) + " - " + label)
                return value, label
        except Exception as e:
            print("[F&G] " + str(e))
        return 50, "Neutral"

    def _fetch_put_call_ratio(self):
        """Fetch CBOE total put/call ratio from the daily market statistics page.
        Contrarian: high P/C (fear/puts dominate) → buy signal; low P/C (euphoria) → caution.
        Result cached 1 hour. Returns neutral 1.0 multiplier on any error."""
        if self._pc_cache and time.time() - self._pc_cache[1] < 3600:
            return self._pc_cache[0]
        try:
            url = "https://www.cboe.com/us/options/market_statistics/daily/"
            r   = requests.get(url, timeout=10,
                               headers={"User-Agent":
                                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            if r.status_code == 200:
                # CBOE embeds ratio data as inline JSON in the page:
                # ...\"TOTAL PUT/CALL RATIO\",\"value\":\"0.83\"...
                # Quotes may be escaped (\") in Next.js serialised scripts — use flexible regex
                m = re.search(
                    r'TOTAL PUT.CALL RATIO[^0-9]{1,40}?(\d+\.\d+)',
                    r.text, re.I)
                if m:
                    pc = float(m.group(1))
                    if   pc > 1.2:  label, mult = "Extreme Fear (contrarian Buy)",  1.3
                    elif pc > 1.0:  label, mult = "Fear (contrarian Bullish)",       1.1
                    elif pc >= 0.85:label, mult = "Neutral",                         1.0
                    elif pc >= 0.70:label, mult = "Greed (Caution)",                 0.9
                    else:           label, mult = "Extreme Greed (contrarian Sell)", 0.7
                    self._pc_cache = (mult, time.time())
                    self.last_pc   = {"value": round(pc, 2), "label": label}
                    print("[P/C] Put/Call " + str(round(pc, 2)) +
                          " → " + str(mult) + "× (" + label + ")")
                    return mult
        except Exception as e:
            print("[P/C] " + str(e))
        # Neutral fallback — don't block trading when CBOE unreachable
        self._pc_cache = (1.0, time.time())
        self.last_pc   = {"value": 1.0, "label": "Neutral (unavailable)"}
        return 1.0

    # ── ML Meta-Filter — Random Forest ────────────────────────────────────

    ML_THRESHOLD   = 0.55    # minimum win probability to allow entry
    ML_FEATURE_KEYS = [
        "rsi", "adx", "cmf", "macd_hist", "stoch_k",
        "ma_dist_pct", "vwap_dist_pct", "fg_value", "pc_ratio", "score_pct",
    ]
    ML_MIN_TRADES  = 30      # don't activate until we have this many labeled samples

    def _ml_train(self):
        """Train RandomForestClassifier on labeled trade history.
        A trade is labeled if it has a 'features' dict (stored at entry).
        Silently disabled if sklearn unavailable or < ML_MIN_TRADES samples."""
        try:
            from sklearn.ensemble import RandomForestClassifier
            import numpy as np
        except ImportError:
            print("[ML] sklearn nicht installiert (pip install scikit-learn) — deaktiviert")
            return
        with self.positions_lock:
            trades = list(self.trades)
        labeled = [(t["features"], 1 if t["profit"] > 0 else 0)
                   for t in trades
                   if isinstance(t.get("features"), dict)]
        self._ml_trained_count = len(labeled)
        if len(labeled) < self.ML_MIN_TRADES:
            self._ml_model = None
            print("[ML] " + str(len(labeled)) + " Trades mit Features — " +
                  str(self.ML_MIN_TRADES - len(labeled)) +
                  " weitere bis Aktivierung")
            return
        # Recency bias guard: only last 200 trades (older regime may differ)
        labeled = labeled[-200:]
        X = np.array([[f.get(k, 0.0) for k in self.ML_FEATURE_KEYS]
                      for f, _ in labeled])
        y = np.array([lbl for _, lbl in labeled])
        clf = RandomForestClassifier(n_estimators=100, max_depth=5,
                                     min_samples_leaf=5, random_state=42)
        clf.fit(X, y)
        self._ml_model      = clf
        self._ml_last_train = datetime.now().date()
        win_rate = round(float(y.mean()) * 100, 1)
        print("[ML] Modell trainiert: " + str(len(y)) + " Trades | " +
              str(win_rate) + "% Gewinnrate | Threshold=" +
              str(int(self.ML_THRESHOLD * 100)) + "%")

    def _ml_predict(self, features):
        """Return estimated win probability [0–1].
        Returns 1.0 (neutral/pass) when model is not yet trained."""
        if self._ml_model is None:
            return 1.0
        try:
            import numpy as np
            vec = np.array([[features.get(k, 0.0) for k in self.ML_FEATURE_KEYS]])
            return float(self._ml_model.predict_proba(vec)[0][1])
        except Exception:
            return 1.0   # neutral on any error — never block trades due to ML crash

    def analyze(self):
        scores = {k: 0.0 for k in ETFS.keys()}

        articles = self.fetch_news() + self.fetch_twitter()
        for art in articles:
            title = art.get("title", "") if isinstance(art, dict) else str(art)
            desc  = art.get("description", "") if isinstance(art, dict) else ""
            text  = re.sub(r"<[^>]+>", " ", title + " " + desc).lower()
            sentiment = _sentiment(text)
            boost = 1.0
            for fig in FIGURES:
                if fig.lower() in text:
                    boost = 1.3
                    break
            if any(w in text for w in ["federal reserve","fomc","powell","sec filing","form 4","insider"]):
                boost = max(boost, 1.5)
            for kw, sectors in KEYWORDS.items():
                if kw in text:
                    for sec in sectors:
                        if sec in scores:
                            scores[sec] += sentiment * boost

        congress = self.fetch_congress()
        self.last_congress = {k: round(v, 2) for k, v in congress.items() if abs(v) > 0.01}
        for sec, val in congress.items():
            scores[sec] += val

        fg_value, fg_label = self.fetch_fear_greed()
        if   fg_value <= 25: multiplier = 1.3
        elif fg_value <= 45: multiplier = 1.1
        elif fg_value <= 55: multiplier = 1.0
        elif fg_value <= 75: multiplier = 0.8
        else:                multiplier = 0.5

        for sec in scores:
            scores[sec] *= multiplier

        self.last_fg = {"value": fg_value, "label": fg_label}
        print("[F&G] Multiplier " + str(multiplier) + "x (" + fg_label + ")")

        # ── Put/Call Ratio — contrarian sentiment multiplier ───────────────────
        # Fetched from CBOE, cached 1h. Compounds with F&G multiplier.
        pc_mult = self._fetch_put_call_ratio()
        for sec in scores:
            scores[sec] *= pc_mult

        return scores

    # ── Trade entry ────────────────────────────────────────────────────────

    def _get_drawdown_mult(self):
        """Gradual position-size scaling based on today's P&L.
        Returns (size_mult, zone) — applied on top of ADX + VIX multipliers.

        HEALTHY  > -3%        → 1.0×  full size
        CAUTION  -3% to -6%   → 0.7×  -30% size, Telegram warning (once)
        WARNING  -6% to -9%   → 0.4×  -60% size
        DANGER   < -9%        → 0.0×  no new trades (bot stops buying before risk agent halts)
        """
        if self.start_balance <= 0:
            return 1.0, "HEALTHY"
        day_pct = (self.balance - self.start_balance) / self.start_balance * 100
        if day_pct > -3.0:
            return 1.0, "HEALTHY"
        elif day_pct > -6.0:
            if not getattr(self, "_dd_caution_sent", False):
                self.send("⚠️ Drawdown CAUTION: {:.1f}% heute — Positionsgrösse -30%".format(day_pct))
                self._dd_caution_sent = True
            return 0.7, "CAUTION"
        elif day_pct > -9.0:
            if not getattr(self, "_dd_warning_sent", False):
                self.send("🔴 Drawdown WARNING: {:.1f}% heute — Positionsgrösse -60%".format(day_pct))
                self._dd_warning_sent = True
            return 0.4, "WARNING"
        else:
            if not getattr(self, "_dd_danger_sent", False):
                self.send("🚨 Drawdown DANGER: {:.1f}% heute — keine neuen Trades!".format(day_pct))
                self._dd_danger_sent = True
            return 0.0, "DANGER"

    def trade(self, scores):
        if self.tg_paused:
            print("[TRADE] Pausiert (via Telegram /stop)")
            return

        # Gradual drawdown protection — scale down before risk agent hard-halts
        dd_mult, dd_zone = self._get_drawdown_mult()
        if dd_mult == 0.0:
            print("[TRADE] DD=" + dd_zone + " — keine neuen Käufe")
            return
        if dd_zone == "HEALTHY":
            self._dd_caution_sent = False
            self._dd_warning_sent = False
            self._dd_danger_sent  = False

        ranked = sorted(scores.items(), key=lambda x: abs(x[1]), reverse=True)
        for sector, score in ranked:
            if abs(score) < 1.0:
                continue
            symbol = ETFS[sector]
            if symbol in self.excluded_symbols:
                continue
            if score <= 0:
                continue

            with self.positions_lock:
                if symbol in self.positions or len(self.positions) >= self.max_pos:
                    continue

            # Earnings window guard — no new buys within 2 days before / 1 day after
            blocked, earn_stock, earn_date = self._get_earnings_window(symbol)
            if blocked:
                print("[SKIP] " + symbol + " Earnings " + earn_stock + " " + earn_date)
                continue

            ind = self.get_indicators(symbol)
            if ind is None:
                print("[SKIP] " + symbol + " keine Indikatoren")
                continue

            # Higher-Timeframe filter — weekly trend must be bullish
            if not self._get_htf_trend(symbol):
                print("[SKIP] " + symbol + " HTF=bear (Preis unter 10-Wochen-MA)")
                continue

            # Correlation guard — block if too similar to an open position
            corr, corr_sym = self._check_correlation(symbol)
            if corr > 0.85:
                print("[SKIP] " + symbol + " Korrelation=" + str(corr) +
                      " zu " + str(corr_sym) + " (Grenze 0.85)")
                continue

            # ── VWAP fair-value filter ─────────────────────────────────────────
            # Price at or below session VWAP (within 0.5% tolerance) = buying
            # at fair value or below. None returned outside market hours → neutral.
            vwap     = self._get_vwap(symbol)
            vwap_ok  = (vwap is None) or (ind["price"] <= vwap * 1.005)

            rsi_ok  = ind["rsi"] < 75   # optimized: 70 → 75
            ma_ok   = ind["price"] > ind["ma20"]
            macd_ok = ind["macd"] > ind["macd_signal"]
            st_ok   = ind["supertrend"] == 1
            cmf_ok   = ind.get("cmf", 0.0) > 0    # CMF > 0 = net buying pressure
            obv_ok   = ind["obv_rising"]            # kept for skip-log reference
            ichi_ok  = ind.get("ichi_ok", True)
            psar_ok  = ind.get("psar_ok", True)
            stoch_ok = ind.get("stoch_ok", True)   # StochRSI %K > %D and < 0.8

            # ── ADX Market Regime Detection ────────────────────────────────────
            adx = ind.get("adx", 25.0)
            if adx >= 25:
                regime, threshold, size_mult = "TRENDING",     0.60, 1.0
            elif adx >= 20:
                regime, threshold, size_mult = "TRANSITIONAL", 0.50, 0.6
            else:
                regime, threshold, size_mult = "RANGING",      0.40, 0.4

            # ── VIX Volatility Regime — multiplied on top of ADX size_mult ────
            vix_regime, vix_mult = self._get_vix_regime()
            if vix_mult == 0.0:
                print("[SKIP] " + symbol + " VIX=EXTREME — keine neuen Trades (Crash-Schutz)")
                continue
            size_mult = round(size_mult * vix_mult * dd_mult, 2)

            # Weighted score: strong trend indicators carry more weight
            # RSI + MACD + Supertrend = 1.5 each (trend-core)
            # Ichimoku = 1.2 (trend confirmation, lagging)
            # MA20 = 1.0 (basic trend filter)
            # CMF = 0.8 (volume/money-flow confirmation — replaces OBV)
            # StochRSI = 0.5 (fast momentum confirmation)
            # VWAP = 0.5 (intraday fair-value — neutral outside market hours)
            # Max possible = 8.5
            gate_score = (rsi_ok   * 1.5 + macd_ok * 1.5 + st_ok  * 1.5 +
                          ichi_ok  * 1.2 + ma_ok   * 1.0 + cmf_ok * 0.8 +
                          stoch_ok * 0.5 + vwap_ok * 0.5)
            score_pct  = gate_score / 8.5

            if score_pct < threshold:
                # PSAR logged for info but not a buy gate — used only as dynamic stop after entry
                with self.positions_lock:
                    self.last_skips.append({
                        "symbol": symbol, "sector": sector,
                        "time":   datetime.now().strftime("%H:%M"),
                        "rsi": ind["rsi"], "rsi_ok": rsi_ok,
                        "ma_ok": ma_ok, "macd_ok": macd_ok,
                        "st_ok": st_ok, "obv_ok": cmf_ok,
                        "ichi_ok": ichi_ok, "psar_ok": psar_ok,
                    })
                    self.last_skips = self.last_skips[-20:]
                vwap_str = ("ok($" + str(vwap) + ")" if vwap_ok
                            else "no($" + str(vwap) + ")")
                print("[SKIP] " + symbol +
                      " [" + regime + " ADX=" + str(adx) +
                      " score=" + str(round(score_pct * 100)) + "%<" +
                      str(int(threshold * 100)) + "%]" +
                      " RSI=" + str(ind["rsi"]) +
                      " MA=" + ("above" if ma_ok else "below") +
                      " MACD=" + ("bull" if macd_ok else "bear") +
                      " ST=" + ("bull" if st_ok else "bear") +
                      " CMF=" + str(ind.get("cmf", 0.0)) +
                      " StRSI=" + ("ok" if stoch_ok else "no") +
                      " VWAP=" + vwap_str +
                      " ICHI=" + ("above" if ichi_ok else "below") +
                      " PSAR=" + ("bull" if psar_ok else "bear"))
                continue

            # ── ML Meta-Filter — Random Forest win-probability gate ───────────
            # Build feature vector from current indicator state + bot context.
            # Stored in the position so it can be saved to trades_history at close.
            ma20_val = ind.get("ma20", ind["price"])
            ml_features = {
                "rsi":          float(ind["rsi"]),
                "adx":          float(ind.get("adx", 25.0)),
                "cmf":          float(ind.get("cmf", 0.0)),
                "macd_hist":    max(-2.0, min(2.0, float(ind.get("macd_hist", 0.0)))),
                "stoch_k":      float(ind.get("stoch_k", 0.5)),
                "ma_dist_pct":  round((ind["price"] / ma20_val - 1) * 100, 2),
                "vwap_dist_pct":round((ind["price"] / vwap - 1) * 100, 2) if vwap else 0.0,
                "fg_value":     float(self.last_fg.get("value", 50)),
                "pc_ratio":     float(self.last_pc.get("value", 1.0)),
                "score_pct":    round(float(score_pct), 4),
            }
            ml_prob = self._ml_predict(ml_features)
            if ml_prob < self.ML_THRESHOLD:
                print("[SKIP] " + symbol + " ML=" +
                      str(round(ml_prob * 100)) + "%<" +
                      str(int(self.ML_THRESHOLD * 100)) + "% (model trained on " +
                      str(self._ml_trained_count) + " trades)")
                continue

            price = self.get_price(symbol)
            if price is None or price <= 0:
                continue

            # ── ATR-based position sizing ──────────────────────────────────────
            # Risk 1% of balance per trade, sized by ATR distance (2× ATR stop)
            # Capped at pos_size × size_mult × balance so single position stays bounded
            atr = ind.get("atr", 0)
            if atr and atr > 0:
                risk_per_share = atr * 2.0          # 2×ATR = expected stop distance in $
                risk_budget    = self.balance * 0.01 # 1% of balance at risk per trade
                atr_shares     = int(risk_budget / risk_per_share)
                max_shares     = int(self.balance * self.pos_size * size_mult / price)
                shares = min(atr_shares, max_shares)
            else:
                shares = int(self.balance * self.pos_size * size_mult / price)
            if shares < 1:
                continue

            fill = price * (1 + getattr(self, "sim_slip", 0.0002)) if self.demo else price
            with self.positions_lock:
                if symbol in self.positions or len(self.positions) >= self.max_pos:
                    continue
                if self.demo or not self.alpaca_ok:
                    self.balance -= shares * fill
                self.positions[symbol] = {
                    "shares":      shares,
                    "entry":       fill,
                    "sector":      sector,
                    "time":        datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "highest":     price,
                    "psar_stop":   ind.get("psar"),   # dynamic stop — updated each cycle
                    "ml_features": ml_features,       # saved to trades_history at close
                    "ml_prob":     round(ml_prob, 3), # win probability at entry
                }

            if not self.demo and self.alpaca_ok:
                self.alpaca_order(symbol, shares, "buy")
                self._sync_balance()

            self._save_state()   # persist balance after buy

            ml_str = ("ML=" + str(round(ml_prob * 100)) + "% "
                      if self._ml_model is not None else "")
            msg = ("BUY " + symbol + " (" + sector + ") " +
                   str(shares) + " @ $" + str(round(price, 2)) +
                   " [" + regime + " ADX=" + str(adx) +
                   " VIX=" + vix_regime + " DD=" + dd_zone +
                   " score=" + str(round(score_pct * 100)) + "%" +
                   " " + ml_str +
                   "x" + str(size_mult) + "]" +
                   " ATR=" + str(ind["atr"]) +
                   " risk=$" + str(round(shares * ind["atr"] * 2, 0)) +
                   " RSI=" + str(ind["rsi"]) +
                   " MACD=" + str(ind["macd_hist"]) +
                   " ST=" + str(ind["supertrend"]) +
                   " CMF=" + str(ind.get("cmf", 0.0)) +
                   " StRSI=" + ("ok" if stoch_ok else "no") +
                   " VWAP=" + ("ok($" + str(vwap) + ")" if vwap_ok
                               else "no($" + str(vwap) + ")") +
                   " ICHI=" + ("above" if ichi_ok else "below") +
                   " PSAR=" + str(ind.get("psar", "?")) +
                   " | Bal: $" + str(round(self.balance, 0)))
            print(msg)
            self.send(msg)

    # ── Dashboard ──────────────────────────────────────────────────────────

    def save_dashboard(self, scores):
        with self.positions_lock:
            positions_snap = dict(self.positions)
            trades_snap    = list(self.trades)
            balance_snap   = self.balance
            skips_snap     = list(self.last_skips[-10:])

        positions_data = {}
        for sym, pos in positions_snap.items():
            curr = self.get_price(sym) or pos["entry"]
            pnl_pct = ((curr - pos["entry"]) / pos["entry"]) * 100
            pnl_usd = pos["shares"] * (curr - pos["entry"])
            positions_data[sym] = {
                "shares":        pos["shares"],
                "entry":         round(pos["entry"], 2),
                "current_price": round(curr, 2),
                "pnl_pct":       round(pnl_pct, 1),
                "pnl_usd":       round(pnl_usd, 0),
                "sector":        pos.get("sector", ""),
                "time":          pos.get("time", ""),
            }

        total_pnl = (sum(t["profit"] for t in trades_snap) +
                     sum(v.get("pnl_usd", 0) for v in positions_data.values()))
        wins = sum(1 for t in trades_snap if t["profit"] > 0)

        mode_str = "DEMO" if self.demo else "LIVE"
        if self.ws_connected:
            mode_str += " | WS✓"

        # Earnings window data for dashboard
        earnings_info = {}
        for etf_sym in ETF_SYMBOLS:
            blk, stk, ed = self._get_earnings_window(etf_sym)
            if blk:
                earnings_info[etf_sym] = {"stock": stk, "date": ed}

        data = {
            "time":         datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode":         mode_str,
            "balance":      round(balance_snap, 2),
            "positions":    positions_data,
            "scores":       {k: round(v, 2) for k, v in scores.items()},
            "trades":       trades_snap[-20:],
            "total_pnl":    round(total_pnl, 0),
            "wins":         wins,
            "total_trades": len(trades_snap),
            "running":      self.running,
            "fear_greed":   self.last_fg,
            "put_call":     self.last_pc,
            "skips":        skips_snap,
            "congress":     self.last_congress,
            "ws_connected": self.ws_connected,
            "earnings":     earnings_info,
        }
        with open("/home/trading2025/trading_bot/dashboard.json", "w") as f:
            json.dump(data, f)

    def dashboard(self, scores):
        with self.positions_lock:
            pos_snap = dict(self.positions)
            bal      = self.balance
            trades   = list(self.trades)
        now  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mode = "DEMO" if self.demo else "LIVE"
        ws   = "WS✓" if self.ws_connected else "WS✗"
        print("=" * 50)
        print("  SUPER BOT v3.0 | " + mode + " | " + ws + " | " + now)
        print("=" * 50)
        print("  Balance: $" + str(round(bal, 2)))
        print("  Pos: " + str(len(pos_snap)) + "/" + str(self.max_pos))
        for sym, pos in pos_snap.items():
            price = self.get_price(sym) or pos["entry"]
            pnl_pct = ((price - pos["entry"]) / pos["entry"]) * 100
            pnl_usd = pos["shares"] * (price - pos["entry"])
            print("  " + sym + " $" + str(round(price, 2)) + " " +
                  str(round(pnl_pct, 1)) + "% $" + str(round(pnl_usd, 0)))
        print("  SENTIMENT:")
        for sec, sc in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            if abs(sc) < 0.1:
                continue
            bar  = "#" * min(int(abs(sc) * 3), 20)
            sign = "+" if sc >= 0 else "-"
            print("  " + ETFS[sec] + " " + sign + str(round(abs(sc), 2)) + " " + bar)
        if trades:
            total = sum(t["profit"] for t in trades)
            wins  = sum(1 for t in trades if t["profit"] > 0)
            print("  TRADES: " + str(len(trades)) + " | Wins: " + str(wins) +
                  " | P&L: $" + str(round(total, 0)))
        print("=" * 50)

    # ── Safety & control ───────────────────────────────────────────────────

    def check_day_loss(self):
        with self.positions_lock:
            bal = self.balance
        loss = (self.start_balance - bal) / self.start_balance
        if loss >= self.max_day_loss:
            print("[STOP] Max Tagesverlust erreicht!")
            self.send("WARNUNG: Max Tagesverlust -10% erreicht! Bot stoppt!")
            self.running = False

    def check_control(self):
        try:
            ctrl_path = "/home/trading2025/trading_bot/bot_control.json"
            if os.path.exists(ctrl_path):
                with open(ctrl_path) as f:
                    ctrl = json.load(f)
                if ctrl.get("command") == "stop":
                    self.running = False
                    os.remove(ctrl_path)
                elif ctrl.get("command") == "start":
                    self.running = True
                    os.remove(ctrl_path)
                elif ctrl.get("command") == "close_all":
                    with self.positions_lock:
                        syms = list(self.positions.keys())
                    print("[CTRL] close_all: Schliesse " + str(len(syms)) + " Positionen vor Halt...")
                    if syms:
                        self.send("Schliesse " + str(len(syms)) + " Positionen vor Halt (RISK-CLOSE-ALL)...")
                    for sym in syms:
                        price = self.get_price(sym)
                        with self.positions_lock:
                            pos = self.positions.get(sym)
                        if not pos:
                            continue
                        if not price:
                            price = pos.get("entry", 1)
                        entry = pos.get("entry") or price
                        pnl = round((price - entry) / entry * 100, 2) if entry else 0.0
                        self.close_position(sym, price, "RISK-CLOSE-ALL", pnl)
                    self.running = False
                    try:
                        os.remove(ctrl_path)
                    except Exception:
                        pass
                # Soft-pause written by telegram_router.py
                if "paused" in ctrl:
                    self.tg_paused = bool(ctrl["paused"])
        except Exception:
            pass

    def fetch_prices(self):
        """Intra-cycle momentum check via 5-min bars (polling supplement to WS)."""
        try:
            syms = ",".join(ETF_SYMBOLS)
            url  = ALPACA_DATA_URL + "/v2/stocks/bars?symbols=" + syms + "&timeframe=5Min&limit=3"
            r = requests.get(url, headers=self.alpaca_headers, timeout=10)
            if r.status_code == 200:
                return r.json().get("bars", {})
        except Exception as e:
            print("[PRICE ERR] " + str(e))
        return {}

    # ── Main loop ──────────────────────────────────────────────────────────

    def _update_psar_stops(self):
        """Recalculate PSAR for all open normal positions each cycle so the stop ratchets up."""
        with self.positions_lock:
            symbols = [s for s, p in self.positions.items() if not p.get("spike")]
        for symbol in symbols:
            ind = self.get_indicators(symbol)
            if ind and "psar" in ind:
                with self.positions_lock:
                    if symbol in self.positions and not self.positions[symbol].get("spike"):
                        self.positions[symbol]["psar_stop"] = ind["psar"]

    def run(self, interval=600):
        self.send("Bot v3.0 | Bal: $" + str(round(self.balance, 0)))

        # Start real-time price stream in background daemon thread
        self.start_websocket()

        # Watchdog — kills process if main loop hangs > 6 min
        wd = threading.Thread(target=self._watchdog_run, daemon=True, name="watchdog")
        wd.start()
        print("[WATCHDOG] Aktiv — Neustart wenn Hauptloop > 6 min haengt")

        cycle = 0
        while True:
            try:
                self._last_heartbeat = time.time()   # watchdog: alive
                self.check_control()
                if not self.running:
                    self.save_dashboard({k: 0.0 for k in ETFS.keys()})
                    time.sleep(30)
                    continue

                cycle += 1
                ws_status = "WS✓" if self.ws_connected else "WS✗"

                # SPY macro check — log but don't block (informational for now)
                spy_pct = self._get_spy_trend()
                spy_tag = " | SPY{:+.1f}%".format(spy_pct) if spy_pct != 0.0 else ""

                print("[" + str(cycle) + "] " + datetime.now().strftime("%H:%M:%S") +
                      " | " + ws_status + spy_tag)
                self.check_day_loss()
                self.check_stuck_positions()
                self._fetch_earnings()        # no-op after first call of the day
                self._check_held_earnings()   # alert once per held position per day

                # ML daily retrain — fires once per day on first cycle after midnight
                today = datetime.now().date()
                if self._ml_last_train != today:
                    self._ml_train()

                # Twitter fast-path trade
                tweets = self.fetch_twitter()
                if tweets:
                    tw_scores = {k: 0.0 for k in ETFS.keys()}
                    for t in tweets:
                        text = t.get("title", "").lower()
                        sentiment = _sentiment(text)
                        for kw, sectors in KEYWORDS.items():
                            if kw in text:
                                for sec in sectors:
                                    if sec in tw_scores:
                                        tw_scores[sec] += sentiment * 1.5
                    self.trade(tw_scores)

                # Polling stop-check — only when WebSocket is down
                if not self.ws_connected:
                    self.check_stops()

                if self.positions:
                    time.sleep(60)

                scores = self.analyze()
                self.trade(scores)
                self._update_psar_stops()
                self.dashboard(scores)
                self.save_dashboard(scores)
                self._save_state()
                print("Check in " + str(interval // 60) + " Min... | " + ws_status)

                # Intra-cycle momentum + stop polling every 2 min
                for _ in range(interval // 120):
                    self._last_heartbeat = time.time()   # watchdog: inner loop alive
                    self.check_control()      # allow close_all to fire mid-cycle
                    if not self.running:
                        break
                    time.sleep(120)
                    import datetime as dt
                    utc_hour = dt.datetime.now(dt.timezone.utc).hour
                    if 13 <= utc_hour < 20:
                        bars = self.fetch_prices()
                    else:
                        bars = {}
                    pscore = {k: 0.0 for k in ETFS.keys()}
                    for sym, sbars in bars.items():
                        if len(sbars) >= 2:
                            chg = (sbars[-1]["c"] - sbars[-2]["c"]) / sbars[-2]["c"] * 100
                            if chg >= 2.0:
                                # Map ETF ticker back to sector key
                                for sec, etf in ETFS.items():
                                    if etf == sym:
                                        pscore[sec] = 1.5
                                        print("[PRICE] " + sym + " +" + str(round(chg, 2)) + "%")
                            elif chg <= -2.0:
                                for sec, etf in ETFS.items():
                                    if etf == sym:
                                        pscore[sec] = -1.5
                                        print("[PRICE] " + sym + " " + str(round(chg, 2)) + "%")
                    self.trade(pscore)
                    if not self.ws_connected:
                        self.check_stops()
                    self.save_dashboard(scores)
                    self._save_state()

            except KeyboardInterrupt:
                self.send("Bot gestoppt")
                break
            except Exception as e:
                print("[ERROR] " + str(e))
                time.sleep(60)


if __name__ == "__main__":
    bot = SuperTradingBot()
    bot.run(interval=600)
