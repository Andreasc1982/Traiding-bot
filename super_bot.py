#!/usr/bin/env python3
from datetime import datetime, timedelta
import time, requests, os, json, re, threading

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
        self.tg_ok       = False
        self.alpaca_ok   = False
        self.alpaca_headers = {}
        self.running     = True
        self.last_skips  = []
        self.last_congress = {}
        self.last_fg     = {"value": 50, "label": "N/A"}
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

        # Thread safety — RLock so _ws_check_price can call close_position safely
        self.positions_lock = threading.RLock()

        # WebSocket state
        self.ws_prices    = {}      # symbol → latest trade price from stream
        self.ws_connected = False
        self._ws          = None    # WebSocketApp handle

        # Telegram command flag — set True by /stop command, False by /start
        self.tg_paused    = False

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

    # ── Indicators ─────────────────────────────────────────────────────────

    def get_indicators(self, symbol):
        try:
            url = ALPACA_BASE_URL + "/v2/stocks/" + symbol + "/bars"
            params = {"timeframe": "1Day", "limit": 100}
            r = requests.get(url, headers=self.alpaca_headers, params=params, timeout=5)
            if r.status_code != 200:
                return None
            bars = r.json().get("bars", [])
            if len(bars) < 78:
                return None
            closes  = [b["c"] for b in bars]
            highs   = [b["h"] for b in bars]
            lows    = [b["l"] for b in bars]
            volumes = [b["v"] for b in bars]
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
                "price":       closes[-1],
            }
        except Exception:
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
        """Restore balance (demo) and start_balance (daily loss baseline) from disk."""
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
        except Exception as e:
            print("[STATE] Load error: " + str(e))

    def _save_state(self):
        """Persist balance and daily-loss baseline to disk."""
        try:
            with self.positions_lock:
                bal   = self.balance
                start = self.start_balance
            st = {
                "balance":           round(bal, 2),
                "day_start_balance": round(start, 2),
                "day_date":          datetime.now().strftime("%Y-%m-%d"),
            }
            with open(SUPER_STATE_PATH, "w") as f:
                json.dump(st, f)
        except Exception as e:
            print("[STATE] Save error: " + str(e))

    # ── Earnings calendar ──────────────────────────────────────────────────

    def _fetch_earnings(self):
        """Fetch next-earnings dates for all ETF constituents. Cached once per day."""
        today = datetime.now().date()
        if self._earnings_cache_date == today:
            return
        # New calendar day — reset alert set so positions get re-alerted if still open
        self._earnings_alerted = set()
        cache = {}
        try:
            import yfinance as yf
            all_stocks = set(s for stocks in ETF_CONSTITUENTS.values() for s in stocks)
            for stock in sorted(all_stocks):
                try:
                    cal = yf.Ticker(stock).calendar
                    ed = None
                    if isinstance(cal, dict):
                        raw = cal.get("Earnings Date")
                        if raw:
                            # May be list or single value
                            item = raw[0] if isinstance(raw, list) else raw
                            ed = self._parse_earnings_date(item)
                    elif hasattr(cal, "columns"):
                        # Old DataFrame format
                        if "Earnings Date" in cal.columns:
                            ed = self._parse_earnings_date(cal["Earnings Date"].iloc[0])
                    if ed:
                        cache[stock] = ed
                except Exception:
                    pass   # stock might be unavailable — skip silently
        except ImportError:
            print("[EARNINGS] yfinance nicht installiert — Earnings-Check deaktiviert")
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

        profit = pos["shares"] * (price - pos["entry"])

        # Network calls outside lock
        if not self.demo and self.alpaca_ok:
            self.alpaca_order(symbol, pos["shares"], "sell")
            self._sync_balance()
        else:
            with self.positions_lock:
                self.balance += pos["shares"] * price

        trade_record = {
            "symbol":  symbol,
            "profit":  round(profit, 0),
            "pnl_pct": round(pnl_pct, 1),
            "reason":  reason,
            "time":    datetime.now().strftime("%Y-%m-%d %H:%M"),
            "sector":  pos.get("sector", ""),
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

    # ── News & sentiment ───────────────────────────────────────────────────

    def fetch_twitter(self):
        tweets = []
        accounts = ["realDonaldTrump", "elonmusk", "POTUS"]
        try:
            from bs4 import BeautifulSoup
            for acc in accounts:
                r = requests.get("https://nitter.poast.org/" + acc, timeout=10,
                    headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "html.parser")
                    for t in soup.find_all("div", class_="tweet-content")[:5]:
                        tweets.append({"title": t.get_text(), "description": ""})
        except Exception as e:
            print("[TWITTER] " + str(e))
        print("[TWITTER] " + str(len(tweets)) + " Tweets")
        return tweets

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
        for url in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:10]:
                    articles.append(entry.title + " " + getattr(entry, "summary", ""))
            except Exception as e:
                print("[RSS] Fehler: " + str(e))
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
                feed = feedparser.parse(url)
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
        return scores

    # ── Trade entry ────────────────────────────────────────────────────────

    def trade(self, scores):
        if self.tg_paused:
            print("[TRADE] Pausiert (via Telegram /stop)")
            return
        ranked = sorted(scores.items(), key=lambda x: abs(x[1]), reverse=True)
        for sector, score in ranked:
            if abs(score) < 1.0:
                continue
            symbol = ETFS[sector]
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

            rsi_ok  = ind["rsi"] < 65   # optimized: 70 → 65
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
                regime, threshold, size_mult = "TRENDING",     0.75, 1.0
            elif adx >= 20:
                regime, threshold, size_mult = "TRANSITIONAL", 0.60, 0.6
            else:
                regime, threshold, size_mult = "RANGING",      0.45, 0.4

            # Weighted score: strong trend indicators carry more weight
            # RSI + MACD + Supertrend = 1.5 each (trend-core)
            # Ichimoku = 1.2 (trend confirmation, lagging)
            # MA20 = 1.0 (basic trend filter)
            # CMF = 0.8 (volume/money-flow confirmation — replaces OBV)
            # StochRSI = 0.5 (fast momentum confirmation)
            # Max possible = 8.0
            gate_score = (rsi_ok   * 1.5 + macd_ok * 1.5 + st_ok  * 1.5 +
                          ichi_ok  * 1.2 + ma_ok   * 1.0 + cmf_ok * 0.8 +
                          stoch_ok * 0.5)
            score_pct  = gate_score / 8.0

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
                      " ICHI=" + ("above" if ichi_ok else "below") +
                      " PSAR=" + ("bull" if psar_ok else "bear"))
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

            with self.positions_lock:
                if symbol in self.positions or len(self.positions) >= self.max_pos:
                    continue
                if self.demo or not self.alpaca_ok:
                    self.balance -= shares * price
                self.positions[symbol] = {
                    "shares":    shares,
                    "entry":     price,
                    "sector":    sector,
                    "time":      datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "highest":   price,
                    "psar_stop": ind.get("psar"),   # dynamic stop — updated each cycle
                }

            if not self.demo and self.alpaca_ok:
                self.alpaca_order(symbol, shares, "buy")
                self._sync_balance()

            self._save_state()   # persist balance after buy

            msg = ("BUY " + symbol + " (" + sector + ") " +
                   str(shares) + " @ $" + str(round(price, 2)) +
                   " [" + regime + " ADX=" + str(adx) +
                   " score=" + str(round(score_pct * 100)) + "%" +
                   " x" + str(size_mult) + "]" +
                   " ATR=" + str(ind["atr"]) +
                   " risk=$" + str(round(shares * ind["atr"] * 2, 0)) +
                   " RSI=" + str(ind["rsi"]) +
                   " MACD=" + str(ind["macd_hist"]) +
                   " ST=" + str(ind["supertrend"]) +
                   " CMF=" + str(ind.get("cmf", 0.0)) +
                   " StRSI=" + ("ok" if stoch_ok else "no") +
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

        # Telegram commands handled by telegram_router.py (single getUpdates poller)
        # Start real-time price stream in background daemon thread
        self.start_websocket()

        cycle = 0
        while True:
            try:
                self.check_control()
                if not self.running:
                    self.save_dashboard({k: 0.0 for k in ETFS.keys()})
                    time.sleep(30)
                    continue

                cycle += 1
                ws_status = "WS✓" if self.ws_connected else "WS✗"
                print("[" + str(cycle) + "] " + datetime.now().strftime("%H:%M:%S") +
                      " | " + ws_status)
                self.check_day_loss()
                self._fetch_earnings()        # no-op after first call of the day
                self._check_held_earnings()   # alert once per held position per day

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
                                pscore.get(sym) and None   # ETF tickers match directly
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
