#!/usr/bin/env python3
from datetime import datetime, timezone, timedelta
import time, requests, json, feedparser, re, os, hashlib, hmac, base64, urllib.parse, threading

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
    import sys as _sys
    # config.py lives one level up (trading_bot/), not in crypto/
    _sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from config import config
except ImportError:
    config = {}

TELEGRAM_TOKEN    = config.get("telegram_bot_token", "")
TELEGRAM_CHAT_ID  = config.get("telegram_chat_id", "")
EXCHANGE          = config.get("exchange", "alpaca")   # "alpaca" | "kraken"

ALPACA_API_KEY    = config.get("alpaca_api_key", "")
ALPACA_SECRET_KEY = config.get("alpaca_secret_key", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"   # always paper/testing
ALPACA_DATA_URL   = "https://data.alpaca.markets"
ALPACA_WS_URL     = "wss://stream.data.alpaca.markets/v1beta3/crypto/us"

KRAKEN_API_KEY    = config.get("kraken_api_key", "")
KRAKEN_SECRET     = config.get("kraken_secret_key", "")
KRAKEN_BASE_URL   = "https://api.kraken.com"

DEMO_MODE         = config.get("demo_mode", True)

CRYPTO_MAIN = ["BTC/USD","ETH/USD","SOL/USD","XRP/USD","AVAX/USD","LINK/USD","LTC/USD"]
CRYPTO_MEME = ["DOGE/USD","SHIB/USD","PEPE/USD","WIF/USD"]

KEYWORDS = {
    "BTC/USD":  ["bitcoin","btc"],
    "ETH/USD":  ["ethereum","eth"],
    "SOL/USD":  ["solana","sol"],
    "XRP/USD":  ["ripple","xrp"],
    "AVAX/USD": ["avalanche","avax"],
    "LINK/USD": ["chainlink","link"],
    "LTC/USD":  ["litecoin","ltc"],
    "DOGE/USD": ["dogecoin","doge"],
    "SHIB/USD": ["shiba","shib"],
    "PEPE/USD": ["pepe"],
    "WIF/USD":  ["wif","dogwifhat"],
}

KRAKEN_SYMBOL_MAP = {
    "BTC/USD":  "XBTUSD",
    "ETH/USD":  "ETHUSD",
    "SOL/USD":  "SOLUSD",
    "XRP/USD":  "XRPUSD",
    "AVAX/USD": "AVAXUSD",
    "LINK/USD": "LINKUSD",
    "LTC/USD":  "LTCUSD",
    "DOGE/USD": "DOGEUSD",
    "SHIB/USD": "SHIBUSD",
    "PEPE/USD": "PEPEUSD",
    "WIF/USD":  "WIFUSD",
}

# Kraken WebSocket pair names (different from REST — BTC uses "XBT", slashes kept)
# Only pairs available on Kraken WS; PEPE/WIF excluded (not listed)
KRAKEN_WS_URL      = "wss://ws.kraken.com"
KRAKEN_WS_PAIR_MAP = {
    "BTC/USD":  "XBT/USD",
    "ETH/USD":  "ETH/USD",
    "SOL/USD":  "SOL/USD",
    "XRP/USD":  "XRP/USD",
    "AVAX/USD": "AVAX/USD",
    "LINK/USD": "LINK/USD",
    "LTC/USD":  "LTC/USD",
    "DOGE/USD": "DOGE/USD",
    "SHIB/USD": "SHIB/USD",
}
# Reverse map: Kraken WS pair → our internal symbol
KRAKEN_WS_REVERSE  = {v: k for k, v in KRAKEN_WS_PAIR_MAP.items()}

KRAKEN_MIN_QTY = {
    "BTC/USD":  0.0001,
    "ETH/USD":  0.002,
    "SOL/USD":  0.5,
    "XRP/USD":  10.0,
    "AVAX/USD": 0.1,
    "LINK/USD": 0.5,
    "LTC/USD":  0.05,
    "DOGE/USD": 50.0,
    "SHIB/USD": 1_000_000.0,
    "PEPE/USD": 1_000_000.0,
    "WIF/USD":  1.0,
}

# Persists balance + daily-loss baseline between restarts
STATE_PATH = "/home/trading2025/trading_bot/crypto/crypto_state.json"


class CryptoBot:
    def __init__(self):
        self.demo      = DEMO_MODE
        self.balance   = 10000.0
        self.positions = {}
        self.trades    = []
        self.stop_loss    = 3.0   # optimized: 4.0 → 3.0
        self.take_profit  = 8.0   # optimized: 10.0 → 8.0
        self.max_pos      = 6
        self.pos_size     = 0.08
        self.meme_size    = 0.03
        self.running      = True
        self.last_skips   = []
        self.last_fg      = {"value": 50, "label": "N/A"}
        self.start_balance = self.balance
        self.max_day_loss  = 0.10
        self.exchange_ok   = False

        # Thread safety — RLock so close_position can re-enter from ws_check_price
        self.positions_lock = threading.RLock()

        # WebSocket state
        self.ws_prices    = {}      # symbol → latest trade price from stream
        self.ws_connected = False
        self._ws          = None    # WebSocketApp handle

        # Telegram command flag — set True by /stop command, False by /start
        self.tg_paused    = False

        # Spike trading
        self.spike_size = 0.04      # 4% of balance per spike trade
        self.avg_vol    = {}        # symbol → (avg_vol_per_min, timestamp) — main thread populates
        self.ws_volume  = {}        # symbol → {"vol": float, "start": float} — 60s rolling window

        # Higher-Timeframe (daily) trend cache — refreshed every 10 min
        self._htf_cache = {}        # symbol → (bullish: bool, timestamp: float)

        # Correlation management — recent closes cached from get_indicators()
        self._bar_cache = {}        # symbol → list of last 20 hourly closes

        self.alpaca_headers = {
            "APCA-API-KEY-ID":     ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        }

        trades_path = "/home/trading2025/trading_bot/crypto/trades_history.json"
        if os.path.exists(trades_path):
            import json as _j
            self.trades = _j.load(open(trades_path))
            print("[OK] " + str(len(self.trades)) + " Trades geladen")

        if EXCHANGE == "kraken":
            if KRAKEN_API_KEY and KRAKEN_SECRET:
                result = self._kraken_post("/0/private/Balance", {})
                if result:
                    self.balance = float(result.get("ZUSD", self.balance))
                    self.start_balance = self.balance
                    self.exchange_ok = True
                    print("[OK] Kraken $" + str(round(self.balance, 2)))
                else:
                    print("[WARN] Kraken Auth fehlgeschlagen -> Demo")
            else:
                print("[WARN] Kein Kraken Key -> Demo")
        else:
            if ALPACA_API_KEY and ALPACA_SECRET_KEY:
                try:
                    r = requests.get(ALPACA_BASE_URL + "/v2/account",
                                     headers=self.alpaca_headers, timeout=10)
                    if r.status_code == 200:
                        acc = r.json()
                        self.balance = float(acc.get("cash", self.balance))
                        self.start_balance = self.balance
                        self.exchange_ok = True
                        print("[OK] Alpaca $" + str(round(self.balance, 2)))
                    else:
                        print("[WARN] Alpaca " + str(r.status_code))
                except Exception as e:
                    print("[WARN] Alpaca: " + str(e))
            else:
                print("[WARN] Kein Alpaca Key -> Demo")

        # Restore persisted balance (demo mode) and daily-loss baseline (all modes)
        self._load_state()

        if not self.demo and EXCHANGE == "kraken":
            self._kraken_preflight()

        mode = "DEMO" if self.demo else "LIVE"
        print("=== CRYPTO BOT v2.0 | " + EXCHANGE.upper() + " | " + mode + " ===")
        print("Balance: $" + str(round(self.balance, 2)))

    # ── Kraken auth helpers ────────────────────────────────────────────────

    def _kraken_sign(self, urlpath: str, data: dict) -> str:
        postdata = urllib.parse.urlencode(data)
        encoded  = (str(data["nonce"]) + postdata).encode()
        message  = urlpath.encode() + hashlib.sha256(encoded).digest()
        mac      = hmac.new(base64.b64decode(KRAKEN_SECRET), message, hashlib.sha512)
        return base64.b64encode(mac.digest()).decode()

    def _kraken_post(self, path: str, params: dict) -> dict:
        params = dict(params)
        params["nonce"] = str(int(time.time_ns() // 1_000_000))
        headers = {
            "API-Key":  KRAKEN_API_KEY,
            "API-Sign": self._kraken_sign(path, params),
        }
        try:
            r = requests.post(KRAKEN_BASE_URL + path, headers=headers,
                              data=params, timeout=10)
            result = r.json()
            if result.get("error"):
                print("[KRAKEN] Error: " + str(result["error"]))
                return {}
            return result.get("result", {})
        except Exception as e:
            print("[KRAKEN POST] " + str(e))
            return {}

    # ── Kraken live preflight ──────────────────────────────────────────────

    def _kraken_preflight(self):
        print("=" * 55)
        print("  KRAKEN LIVE PREFLIGHT CHECK")
        print("=" * 55)
        ok = True

        if not KRAKEN_API_KEY or not KRAKEN_SECRET:
            print("  [FAIL] Kraken API Key / Secret fehlt in config.py")
            ok = False
        else:
            print("  [OK]   API Keys vorhanden")

        result = self._kraken_post("/0/private/Balance", {})
        if not result:
            print("  [FAIL] Kraken Auth fehlgeschlagen — Keys prüfen")
            ok = False
        else:
            usd = float(result.get("ZUSD", 0))
            print("  [OK]   Auth erfolgreich | USD Balance: $" + str(round(usd, 2)))
            if usd < 100:
                print("  [WARN] Balance unter $100 — genug Kapital?")

        trade_result = self._kraken_post("/0/private/QueryOrders", {"txid": "dummy"})
        errs = trade_result if isinstance(trade_result, list) else []
        if any("permission" in str(e).lower() for e in errs):
            print("  [FAIL] API Key hat keine Order-Berechtigung")
            ok = False
        else:
            print("  [OK]   Order-Berechtigung (Create & Modify) angenommen")

        pos_usd  = self.balance * self.pos_size
        meme_usd = self.balance * self.meme_size
        print("  [INFO] Positionsgrösse Main:  $" + str(round(pos_usd, 2)))
        print("  [INFO] Positionsgrösse Meme:  $" + str(round(meme_usd, 2)))
        print("  [INFO] Max Positionen:        " + str(self.max_pos))
        print("  [INFO] Stop-Loss:             " + str(self.stop_loss) + "%")
        print("  [INFO] Take-Profit:           " + str(self.take_profit) + "%")
        print("  [INFO] Max Tagesverlust:      " + str(int(self.max_day_loss * 100)) + "%")
        print("  [WARN] SHIB/PEPE/WIF: Pair-Verfügbarkeit auf Kraken prüfen")

        print("=" * 55)
        if not ok:
            print("  PREFLIGHT FAILED — Bot stoppt.")
            print("=" * 55)
            raise SystemExit(1)
        print("  PREFLIGHT OK — Live-Trading startet in 10 Sekunden.")
        print("  Ctrl+C jetzt zum Abbrechen.")
        print("=" * 55)
        time.sleep(10)

    # ── State persistence ──────────────────────────────────────────────────────

    def _load_state(self):
        """Restore balance, daily-loss baseline, and open positions from disk."""
        try:
            if not os.path.exists(STATE_PATH):
                return
            with open(STATE_PATH) as f:
                st = json.load(f)
            today = datetime.now().strftime("%Y-%m-%d")

            # Demo mode: Alpaca paper cash is always full ($100k) — use persisted balance
            if self.demo or not self.exchange_ok:
                saved_bal = st.get("balance", 0)
                if saved_bal > 0:
                    self.balance = saved_bal
                    print("[STATE] Balance wiederhergestellt: $" + str(round(self.balance, 2)))

            # Restore daily-loss baseline only if same calendar day
            # (avoids carrying yesterday's drawdown into today on restart)
            if st.get("day_date") == today:
                saved_start = st.get("day_start_balance", 0)
                if saved_start > 0:
                    self.start_balance = saved_start
                    print("[STATE] Tagesbasis wiederhergestellt: $" +
                          str(round(self.start_balance, 2)))
            else:
                # New day — start_balance = current balance (daily counter starts fresh)
                self.start_balance = self.balance

            # Restore open positions — always, regardless of day
            # (positions live until explicitly closed; stop/take still fire after restart)
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
                        spike_tag = " [SPIKE]" if pos.get("spike") else ""
                        print("[STATE] Position wiederhergestellt: " + sym +
                              " " + str(round(pos["shares"], 6)) +
                              " @ $" + str(round(pos["entry"], 4)) +
                              " seit " + pos.get("time", "?") + spike_tag)
        except Exception as e:
            print("[STATE] Load error: " + str(e))

    def _save_state(self):
        """Persist balance, daily-loss baseline, and open positions to disk."""
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
            with open(STATE_PATH, "w") as f:
                json.dump(st, f)
        except Exception as e:
            print("[STATE] Save error: " + str(e))


    # ── Balance sync ───────────────────────────────────────────────────────

    def _sync_balance(self):
        if EXCHANGE == "kraken":
            result = self._kraken_post("/0/private/Balance", {})
            if result:
                self.balance = float(result.get("ZUSD", self.balance))
        else:
            try:
                r = requests.get(ALPACA_BASE_URL + "/v2/account",
                                 headers=self.alpaca_headers, timeout=5)
                if r.status_code == 200:
                    self.balance = float(r.json().get("cash", self.balance))
            except Exception:
                pass

    # ── Telegram ───────────────────────────────────────────────────────────

    def send(self, msg):
        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
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
        if EXCHANGE == "kraken":
            return self._kraken_get_price(symbol)
        return self._alpaca_get_price(symbol)

    def _alpaca_get_price(self, symbol):
        try:
            sym_encoded = symbol.replace("/", "%2F")
            url = ALPACA_DATA_URL + "/v1beta3/crypto/us/latest/trades?symbols=" + sym_encoded
            r = requests.get(url, headers=self.alpaca_headers, timeout=5)
            if r.status_code == 200:
                price = r.json().get("trades", {}).get(symbol, {}).get("p", 0)
                if price and price > 0:
                    return float(price)
        except Exception:
            pass
        return None

    def _kraken_get_price(self, symbol):
        pair = KRAKEN_SYMBOL_MAP.get(symbol)
        if not pair:
            return None
        try:
            r = requests.get(KRAKEN_BASE_URL + "/0/public/Ticker",
                             params={"pair": pair}, timeout=5)
            result = r.json().get("result", {})
            data = next(iter(result.values()), {})
            return float(data["c"][0])
        except Exception as e:
            print("[KRAKEN PRICE] " + str(e))
            return None

    # ── OHLC bars ──────────────────────────────────────────────────────────

    def _fetch_bars(self, symbol):
        if EXCHANGE == "kraken":
            return self._kraken_get_bars(symbol)
        return self._alpaca_get_bars(symbol)

    def _alpaca_get_bars(self, symbol):
        try:
            start = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%dT00:00:00Z")
            url = ALPACA_DATA_URL + "/v1beta3/crypto/us/bars"
            params = {"symbols": symbol, "timeframe": "1Hour", "start": start, "limit": 400}
            r = requests.get(url, headers=self.alpaca_headers, params=params, timeout=10)
            if r.status_code != 200:
                return None
            raw = r.json().get("bars", {}).get(symbol, [])
            return raw if len(raw) >= 78 else None
        except Exception:
            return None

    def _kraken_get_bars(self, symbol):
        pair = KRAKEN_SYMBOL_MAP.get(symbol)
        if not pair:
            return None
        try:
            r = requests.get(KRAKEN_BASE_URL + "/0/public/OHLC",
                             params={"pair": pair, "interval": 60}, timeout=10)
            result = r.json().get("result", {})
            raw = next((v for k, v in result.items() if k != "last"), None)
            if not raw or len(raw) < 79:
                return None
            return [{"c": float(b[4]), "h": float(b[2]),
                     "l": float(b[3]), "v": float(b[6])} for b in raw[:-1]]
        except Exception as e:
            print("[KRAKEN BARS] " + str(e))
            return None

    # ── Higher-Timeframe trend filter ──────────────────────────────────────

    def _get_htf_trend(self, symbol):
        """Daily trend check — price above 20-day SMA = bullish HTF.
        Result cached 10 min so we don't spam the API on every trade() iteration."""
        cached = self._htf_cache.get(symbol)
        if cached and time.time() - cached[1] < 600:
            return cached[0]
        try:
            sym_clean = symbol.replace("/", "")
            url    = ALPACA_DATA + "/v1beta3/crypto/us/bars"
            params = {"symbols": sym_clean, "timeframe": "1Day", "limit": 30}
            r = requests.get(url, headers=self.alpaca_headers,
                             params=params, timeout=8)
            bars = (r.json().get("bars", {}).get(sym_clean, [])
                    if r.status_code == 200 else [])
            if len(bars) < 20:
                # Not enough daily data → treat as neutral (allow trade)
                self._htf_cache[symbol] = (True, time.time())
                return True
            closes  = [b["c"] for b in bars]
            ma20d   = sum(closes[-20:]) / 20
            bullish = closes[-1] > ma20d
            self._htf_cache[symbol] = (bullish, time.time())
            return bullish
        except Exception:
            return True   # neutral on error — don't block trades

    # ── Correlation management ─────────────────────────────────────────────

    @staticmethod
    def _pearson(a, b):
        """Pearson correlation of hourly returns for two close-price series."""
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
        max_corr  = 0.0
        worst_sym = None
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

    # ── Indicators ─────────────────────────────────────────────────────────

    def get_indicators(self, symbol):
        bars = self._fetch_bars(symbol)
        if bars is None or len(bars) < 78:
            return None
        try:
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
            stoch_ok = True
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
                "ma20":        round(ma20, 4),
                "bb_upper":    round(bb_upper, 4),
                "bb_lower":    round(bb_lower, 4),
                "macd":        round(macd_val, 6),
                "macd_signal": round(signal_val, 6),
                "macd_hist":   round(macd_val - signal_val, 6),
                "atr":         round(atr, 4),
                "supertrend":  supertrend,
                "obv_rising":  obv_rising,
                "cmf":         cmf,
                "psar":        round(psar_val, 4),
                "psar_ok":     psar_ok,
                "tenkan":      round(tenkan, 4),
                "kijun":       round(kijun, 4),
                "cloud_top":   round(cloud_top, 4),
                "ichi_ok":     ichi_ok,
                "adx":         adx,
                "stoch_ok":    stoch_ok,
                "price":       closes[-1],
            }
        except Exception as e:
            print("[INDICATORS] " + str(e))
            return None

    # ── WebSocket price stream (Alpaca only) ───────────────────────────────

    def _refresh_avg_vols(self):
        """Pre-populate per-minute volume baselines from 20-bar hourly OHLCV.
        Called from the main thread so the WS thread never blocks on network I/O."""
        for symbol in CRYPTO_MAIN + CRYPTO_MEME:
            cached = self.avg_vol.get(symbol)
            if cached and time.time() - cached[1] < 3600:
                continue
            bars = self._fetch_bars(symbol)
            if bars and len(bars) >= 20:
                avg_per_min = sum(b["v"] for b in bars[-20:]) / 20 / 60
                self.avg_vol[symbol] = (avg_per_min, time.time())

    def _get_avg_vol(self, symbol):
        """Non-blocking lookup for the WS thread. Returns None if not yet cached."""
        cached = self.avg_vol.get(symbol)
        return cached[0] if cached else None

    def start_websocket(self):
        if not WS_AVAILABLE:
            print("[WS] websocket-client nicht verfügbar — kein Echtzeit-Stream")
            return
        if EXCHANGE == "alpaca":
            t = threading.Thread(target=self._ws_run, daemon=True, name="ws-price-stream")
            t.start()
            print("[WS] Echtzeit Price-Stream Thread gestartet")
        elif EXCHANGE == "kraken":
            t = threading.Thread(target=self._kraken_ws_run, daemon=True, name="kraken-ws")
            t.start()
            print("[KRAKEN_WS] Echtzeit Price-Stream Thread gestartet")

    def _ws_run(self):
        """Reconnect loop — runs in daemon thread, exits when self.running=False."""
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
                    all_syms = CRYPTO_MAIN + CRYPTO_MEME
                    ws.send(json.dumps({"action": "subscribe", "trades": all_syms}))
                    self.ws_connected = True
                    print("[WS] Auth OK — " + str(len(all_syms)) + " Symbole abonniert")

                elif t == "subscription":
                    subs = m.get("trades", [])
                    print("[WS] Aktive Subscriptions: " + str(subs))

                elif t == "t":   # trade tick
                    symbol = m.get("S")
                    price  = m.get("p")
                    size   = float(m.get("s", 0))
                    if symbol and price:
                        price = float(price)
                        self.ws_prices[symbol] = price
                        self._ws_check_price(symbol, price)
                        # Rolling 60s volume accumulation for spike detection
                        now = time.time()
                        v = self.ws_volume.get(symbol)
                        if v is None or now - v["start"] > 60:
                            self.ws_volume[symbol] = {"vol": size, "start": now}
                        else:
                            self.ws_volume[symbol]["vol"] += size
                            if now - v["start"] >= 10:   # need ≥10s of data to fire
                                self._ws_spike_check(symbol, price)

                elif t == "error":
                    print("[WS] Server Error: " + str(m))
        except Exception as e:
            print("[WS] Message parse error: " + str(e))

    def _ws_spike_check(self, symbol, price):
        """
        Fires an immediate buy when 60-second volume exceeds 300% of the
        20-bar hourly average (per-minute normalised).
        Runs in the WebSocket thread — no blocking network calls here.
        """
        avg_per_min = self._get_avg_vol(symbol)
        if not avg_per_min:
            return   # baseline not yet cached — skip silently

        v = self.ws_volume.get(symbol)
        if not v:
            return

        elapsed = time.time() - v["start"]
        if elapsed < 10:
            return

        # Extrapolate accumulated volume to a full 60s rate
        vol_rate = v["vol"] / elapsed * 60
        ratio    = vol_rate / avg_per_min
        if ratio < 10.0:
            return   # not a spike (threshold: 10× hourly average)

        # Avoid re-triggering on the same spike — reset window immediately
        self.ws_volume[symbol] = {"vol": 0.0, "start": time.time()}

        with self.positions_lock:
            if symbol in self.positions or len(self.positions) >= self.max_pos:
                return
            bal    = self.balance
            shares = (bal * self.spike_size) / price
            if shares * price < 1:
                return
            if self.demo or not self.exchange_ok:
                self.balance -= shares * price
            self.positions[symbol] = {
                "shares":      shares,
                "entry":       price,
                "time":        datetime.now().strftime("%Y-%m-%d %H:%M"),
                "highest":     price,
                "stop_loss":   1.5,   # tight spike stop
                "take_profit": 3.0,   # tight spike target
                "spike":       True,
            }

        # Order placed outside lock (slow network call)
        if not self.demo and self.exchange_ok:
            self.place_order(symbol, shares, "buy")
            self._sync_balance()

        self._save_state()   # persist balance after spike buy

        msg = ("SPIKE-BUY " + symbol +
               " $" + str(round(price, 4)) +
               " vol=" + str(round(ratio, 1)) + "x avg (threshold: 10x)" +
               " SL=1.5% TP=3% | Bal: $" + str(round(self.balance, 0)))
        print(msg)
        self.send(msg)

    def _ws_on_error(self, ws, error):
        print("[WS] Error: " + str(error))
        self.ws_connected = False

    def _ws_on_close(self, ws, code, msg):
        self.ws_connected = False
        print("[WS] Geschlossen — Code: " + str(code))

    # ── Kraken WebSocket (public trade channel — no auth required) ─────────

    def _kraken_ws_run(self):
        """Reconnect loop for Kraken WS — runs in daemon thread."""
        while self.running:
            try:
                self._ws = _ws_lib.WebSocketApp(
                    KRAKEN_WS_URL,
                    on_open=self._kraken_ws_on_open,
                    on_message=self._kraken_ws_on_message,
                    on_error=self._kraken_ws_on_error,
                    on_close=self._kraken_ws_on_close,
                )
                self._ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                print("[KRAKEN_WS] Crash: " + str(e))
            self.ws_connected = False
            if self.running:
                print("[KRAKEN_WS] Verbindung verloren — Reconnect in 5s...")
                time.sleep(5)

    def _kraken_ws_on_open(self, ws):
        """Subscribe to public trade channel for all available Kraken pairs."""
        pairs = list(KRAKEN_WS_PAIR_MAP.values())
        ws.send(json.dumps({
            "event":        "subscribe",
            "pair":         pairs,
            "subscription": {"name": "trade"},
        }))
        print("[KRAKEN_WS] Subscribed: " + str(pairs))

    def _kraken_ws_on_message(self, ws, raw):
        """Parse Kraken trade messages.
        Format: [channelID, [["price","vol","time","side","type","misc"],...], "trade", "XBT/USD"]
        System messages: {"event": "heartbeat"} / {"event": "subscriptionStatus", ...}
        """
        try:
            data = json.loads(raw)

            # System/status messages are dicts — ignore heartbeat, log errors
            if isinstance(data, dict):
                ev = data.get("event", "")
                if ev == "subscriptionStatus" and data.get("status") == "subscribed":
                    self.ws_connected = True
                    print("[KRAKEN_WS] Subscription OK: " + data.get("pair", ""))
                elif ev == "error":
                    print("[KRAKEN_WS] Server Error: " + str(data))
                return

            # Trade message is a list: [channelID, [[...]], "trade", "XBT/USD"]
            if not isinstance(data, list) or len(data) != 4:
                return
            if data[2] != "trade":
                return

            pair_ws   = data[3]                              # e.g. "XBT/USD"
            our_sym   = KRAKEN_WS_REVERSE.get(pair_ws)      # e.g. "BTC/USD"
            if not our_sym:
                return

            for tick in data[1]:                             # list of trades in this msg
                try:
                    price = float(tick[0])
                except (IndexError, ValueError):
                    continue
                self.ws_prices[our_sym] = price
                self._ws_check_price(our_sym, price)

        except Exception as e:
            print("[KRAKEN_WS] Parse error: " + str(e))

    def _kraken_ws_on_error(self, ws, error):
        print("[KRAKEN_WS] Error: " + str(error))
        self.ws_connected = False

    def _kraken_ws_on_close(self, ws, code, msg):
        self.ws_connected = False
        print("[KRAKEN_WS] Geschlossen — Code: " + str(code))

    def _ws_check_price(self, symbol, price):
        """
        Called on every trade tick. Evaluates stop-loss and trailing take-profit
        against open positions. Fires close_position() when thresholds are hit.
        Runs in WebSocket thread — positions_lock guards shared state.
        """
        with self.positions_lock:
            if symbol not in self.positions:
                return
            pos = self.positions[symbol]
            pnl_pct = ((price - pos["entry"]) / pos["entry"]) * 100

            # Track intraday high for trailing stop
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
            elif pnl_pct >= tp and trailing >= 2.0:
                trigger = "WS-TRAIL-STOP"
            else:
                return

        # Close outside the lock — close_position re-acquires it internally.
        # If main thread already closed this position, close_position is a no-op.
        print("[WS] " + trigger + " " + symbol +
              " price=$" + str(round(price, 4)) +
              " pnl=" + str(round(pnl_pct, 2)) + "%")
        self.close_position(symbol, price, trigger, pnl_pct)

    # ── Order placement ────────────────────────────────────────────────────

    def place_order(self, symbol, qty, side):
        if EXCHANGE == "kraken":
            self._kraken_place_order(symbol, qty, side)
        else:
            self._alpaca_place_order(symbol, qty, side)

    def _alpaca_place_order(self, symbol, qty, side):
        if not self.exchange_ok:
            return
        order_symbol = symbol.replace("/", "")
        try:
            r = requests.post(ALPACA_BASE_URL + "/v2/orders",
                headers=self.alpaca_headers,
                json={"symbol": order_symbol, "qty": str(round(qty, 8)),
                      "side": side, "type": "market", "time_in_force": "gtc"},
                timeout=10)
            if r.status_code in (200, 201):
                print("[ALPACA] OK: " + side + " " + str(round(qty, 8)) + " " + symbol)
            else:
                print("[ALPACA] Fehler: " + str(r.status_code) + " " + r.text[:100])
        except Exception as e:
            print("[ALPACA] " + str(e))

    def _kraken_place_order(self, symbol, qty, side):
        if not self.exchange_ok:
            return
        pair = KRAKEN_SYMBOL_MAP.get(symbol)
        if not pair:
            print("[KRAKEN] Unbekanntes Symbol: " + symbol)
            return
        min_qty = KRAKEN_MIN_QTY.get(symbol, 0)
        if qty < min_qty:
            print("[KRAKEN] " + symbol + " qty " + str(round(qty, 8)) +
                  " unter Minimum " + str(min_qty) + " -> skip")
            return
        result = self._kraken_post("/0/private/AddOrder", {
            "pair":      pair,
            "type":      side,
            "ordertype": "market",
            "volume":    str(round(qty, 8)),
        })
        if result.get("txids"):
            print("[KRAKEN] OK: " + side + " " + str(round(qty, 8)) + " " + symbol +
                  " txid=" + str(result["txids"]))
        else:
            print("[KRAKEN] Order fehlgeschlagen: " + str(result))

    # ── News & sentiment ───────────────────────────────────────────────────

    def fetch_news(self):
        feeds = [
            "https://feeds.feedburner.com/CoinDesk",
            "https://cointelegraph.com/rss",
            "https://decrypt.co/feed",
            "https://cryptopanic.com/news/rss/",
            "https://unusualwhales.com/rss/congress",
            "https://news.google.com/rss/search?q=bitcoin+BTC&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=ethereum+ETH&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=solana+SOL&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=ripple+XRP&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=dogecoin+DOGE&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=crypto+whale+bitcoin&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=crypto+SEC+regulation&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=bitcoin+blackrock+etf&hl=en-US&gl=US&ceid=US:en",
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

    def fetch_whale_alerts(self):
        scores = {s: 0.0 for s in CRYPTO_MAIN + CRYPTO_MEME}
        try:
            feed = feedparser.parse("https://nitter.poast.org/whale_alert/rss")
            count = 0
            for entry in feed.entries[:30]:
                text = (entry.title + " " + getattr(entry, "summary", "")).lower()
                usd_match = re.search(r'\(([\d,]+(?:\.\d+)?)\s*usd\)', text)
                if not usd_match:
                    continue
                try:
                    usd_val = float(usd_match.group(1).replace(",", ""))
                except ValueError:
                    continue
                if usd_val < 10_000_000:
                    continue
                to_exchange   = any(x in text for x in ["to #coinbase","to #binance","to #kraken","to #okx","to #bybit"])
                from_exchange = any(x in text for x in ["from #coinbase","from #binance","from #kraken","from #okx","from #bybit"])
                for symbol, keywords in KEYWORDS.items():
                    for kw in keywords:
                        if "#" + kw in text or " " + kw + " " in text:
                            if to_exchange:
                                scores[symbol] -= 0.4
                            elif from_exchange:
                                scores[symbol] += 0.4
                            else:
                                scores[symbol] += 0.15
                            count += 1
            print("[WHALE] " + str(count) + " grosse Transfers ($10M+)")
        except Exception as e:
            print("[WHALE] " + str(e))
        return scores

    def fetch_reddit(self):
        scores = {s: 0.0 for s in CRYPTO_MAIN + CRYPTO_MEME}
        feeds = [
            ("https://www.reddit.com/r/CryptoCurrency/hot/.rss",  1.0),
            ("https://www.reddit.com/r/CryptoCurrency/new/.rss",  0.7),
            ("https://www.reddit.com/r/Bitcoin/hot/.rss",         1.3),
            ("https://www.reddit.com/r/Bitcoin/new/.rss",         0.9),
            ("https://www.reddit.com/r/ethereum/hot/.rss",        1.3),
            ("https://www.reddit.com/r/ethereum/new/.rss",        0.9),
            ("https://www.reddit.com/r/solana/hot/.rss",          1.1),
            ("https://www.reddit.com/r/dogecoin/hot/.rss",        1.1),
        ]
        total = 0
        for url, weight in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:15]:
                    raw  = entry.title + " " + getattr(entry, "summary", "")
                    text = re.sub(r"<[^>]+>", " ", raw).lower()
                    sentiment = _sentiment(text)
                    for symbol, keywords in KEYWORDS.items():
                        for kw in keywords:
                            if kw in text:
                                scores[symbol] += sentiment * weight
                                total += 1
            except Exception as e:
                print("[REDDIT] " + str(e))
        print("[REDDIT] " + str(total) + " Beiträge verarbeitet")
        return scores

    def analyze(self):
        self._refresh_avg_vols()   # keep per-minute volume baselines fresh for spike detection
        scores = {s: 0.0 for s in CRYPTO_MAIN + CRYPTO_MEME}

        for art in self.fetch_news():
            text = art.lower()
            sentiment = _sentiment(text)
            for symbol, keywords in KEYWORDS.items():
                for kw in keywords:
                    if kw in text:
                        scores[symbol] += sentiment

        for sym, val in self.fetch_reddit().items():
            scores[sym] += val * 1.2

        for sym, val in self.fetch_whale_alerts().items():
            scores[sym] += val

        fg_value, fg_label = self.fetch_fear_greed()
        if   fg_value <= 25: multiplier = 1.3
        elif fg_value <= 45: multiplier = 1.1
        elif fg_value <= 55: multiplier = 1.0
        elif fg_value <= 75: multiplier = 0.8
        else:                multiplier = 0.5

        for sym in scores:
            scores[sym] *= multiplier

        self.last_fg = {"value": fg_value, "label": fg_label}
        print("[F&G] Multiplier " + str(multiplier) + "x (" + fg_label + ")")
        return scores

    # ── Stop loss / take profit (polling fallback) ─────────────────────────

    def check_stops(self):
        """Polling fallback — WebSocket handles stops in real-time when connected."""
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
                elif pnl_pct >= tp and trailing >= 2.0:
                    trigger = "TRAIL-STOP"
                else:
                    continue
            self.close_position(symbol, price, trigger, pnl_pct)

    # ── Position close ─────────────────────────────────────────────────────

    def close_position(self, symbol, price, reason, pnl_pct):
        # Atomically claim the position — prevents double-close from WS + main thread
        with self.positions_lock:
            pos = self.positions.pop(symbol, None)
        if pos is None:
            return   # already closed by the other thread

        profit = pos["shares"] * (price - pos["entry"])

        # Network calls outside lock — slow operations shouldn't block other threads
        if not self.demo and self.exchange_ok:
            self.place_order(symbol, pos["shares"], "sell")
            self._sync_balance()
        else:
            with self.positions_lock:
                self.balance += pos["shares"] * price

        trade_record = {
            "symbol": symbol,
            "profit": round(profit, 2),
            "pct":    round(pnl_pct, 1),
            "reason": reason,
            "time":   datetime.now().strftime("%Y-%m-%d %H:%M"),
            "spike":  pos.get("spike", False),
        }
        with self.positions_lock:
            self.trades.append(trade_record)

        trades_path = "/home/trading2025/trading_bot/crypto/trades_history.json"
        with open(trades_path, "w") as f:
            json.dump(self.trades, f)

        self._save_state()   # persist balance after every close

        msg = ("CRYPTO " + reason + ": " + symbol + " " +
               str(round(pnl_pct, 1)) + "% | P&L: $" + str(round(profit, 0)))
        print(msg)
        self.send(msg)

    # ── Trade entry ────────────────────────────────────────────────────────

    def trade(self, scores):
        if self.tg_paused:
            print("[TRADE] Pausiert (via Telegram /stop)")
            return
        ranked = sorted(scores.items(), key=lambda x: abs(x[1]), reverse=True)
        for symbol, score in ranked:
            if score <= 0.1:
                continue

            # Quick check before doing slow indicator fetch
            with self.positions_lock:
                if symbol in self.positions or len(self.positions) >= self.max_pos:
                    continue

            ind = self.get_indicators(symbol)
            if ind is None:
                print("[SKIP] " + symbol + " keine Indikatoren")
                continue

            # Higher-Timeframe filter — daily trend must be bullish
            if not self._get_htf_trend(symbol):
                print("[SKIP] " + symbol + " HTF=bear (Preis unter 20-Tage-MA)")
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
            # OBV = 0.8 (volume confirmation)
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
                        "symbol": symbol,
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

            size = self.meme_size if symbol in CRYPTO_MEME else self.pos_size

            # ── ATR-based position sizing ──────────────────────────────────────
            # Risk 1% of balance per trade, sized by ATR distance (2× ATR stop)
            # Capped at size × size_mult × balance so single position stays bounded
            atr = ind.get("atr", 0)
            if atr and atr > 0:
                risk_per_unit = atr * 2.0            # 2×ATR = expected stop distance in $
                risk_budget   = self.balance * 0.01  # 1% of balance at risk per trade
                atr_shares    = risk_budget / risk_per_unit
                max_shares    = (self.balance * size * size_mult) / price
                shares = min(atr_shares, max_shares)
            else:
                shares = (self.balance * size * size_mult) / price
            if shares * price < 1:
                continue

            # Re-check under lock before committing (position may have opened meanwhile)
            with self.positions_lock:
                if symbol in self.positions or len(self.positions) >= self.max_pos:
                    continue
                if self.demo or not self.exchange_ok:
                    self.balance -= shares * price
                self.positions[symbol] = {
                    "shares":    shares,
                    "entry":     price,
                    "time":      datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "highest":   price,
                    "psar_stop": ind.get("psar"),   # dynamic stop — updated each cycle
                }

            if not self.demo and self.exchange_ok:
                self.place_order(symbol, shares, "buy")
                self._sync_balance()

            self._save_state()   # persist balance after buy

            msg = ("CRYPTO BUY " + symbol + " $" + str(round(price, 4)) +
                   " [" + regime + " ADX=" + str(adx) +
                   " score=" + str(round(score_pct * 100)) + "%" +
                   " x" + str(size_mult) + "]" +
                   " ATR=" + str(ind["atr"]) +
                   " risk=$" + str(round(shares * ind["atr"] * 2, 2)) +
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
                "shares":        round(pos["shares"], 6),
                "entry":         round(pos["entry"], 4),
                "current_price": round(curr, 4),
                "pnl_pct":       round(pnl_pct, 1),
                "pnl_usd":       round(pnl_usd, 2),
            }

        total_pnl = (sum(t["profit"] for t in trades_snap) +
                     sum(v.get("pnl_usd", 0) for v in positions_data.values()))

        mode_str = ("DEMO" if self.demo else "LIVE") + " | " + EXCHANGE.upper()
        if self.ws_connected:
            mode_str += " | WS✓"

        data = {
            "time":         datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode":         mode_str,
            "balance":      round(balance_snap, 2),
            "positions":    positions_data,
            "scores":       {k: round(v, 2) for k, v in scores.items()},
            "trades":       trades_snap[-20:],
            "total_pnl":    round(total_pnl, 0),
            "total_trades": len(trades_snap),
            "running":      self.running,
            "fear_greed":   self.last_fg,
            "skips":        skips_snap,
            "ws_connected": self.ws_connected,
        }
        with open("/home/trading2025/trading_bot/crypto/crypto_dashboard.json", "w") as f:
            json.dump(data, f)

    # ── Safety ─────────────────────────────────────────────────────────────

    def check_control(self):
        """Read crypto_control.json written by telegram_router.py for pause/stop commands."""
        try:
            ctrl_path = "/home/trading2025/trading_bot/crypto/crypto_control.json"
            if os.path.exists(ctrl_path):
                with open(ctrl_path) as f:
                    ctrl = json.load(f)
                if ctrl.get("command") == "stop":
                    self.running = False
                # Soft-pause: only blocks new trade entries, stops still fire
                if "paused" in ctrl:
                    self.tg_paused = bool(ctrl["paused"])
        except Exception:
            pass

    def check_day_loss(self):
        """Crypto trades 24/7 — no sleep on daily loss limit.
        Reset start_balance to current balance and continue immediately so no
        opportunity is missed. The -10% limit now applies to each fresh segment."""
        with self.positions_lock:
            balance = self.balance
        if self.start_balance <= 0:
            return
        loss = (self.start_balance - balance) / self.start_balance
        if loss >= self.max_day_loss:
            msg = ("WARNUNG: Tagesverlust -" + str(int(self.max_day_loss * 100)) +
                   "% erreicht ($" + str(round(balance, 0)) +
                   ") — Zähler zurückgesetzt, Bot läuft weiter (Crypto 24/7).")
            print("[DAY_LOSS] " + msg)
            self.send(msg)
            # Reset baseline to current balance — next -10% limit applies from here
            with self.positions_lock:
                self.start_balance = balance
            self._save_state()

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

    def run(self):
        self.send("Crypto Bot v2.0 | " + EXCHANGE.upper() +
                  " | Bal: $" + str(round(self.balance, 0)))

        # Start real-time price stream (Alpaca only; Kraken uses REST polling)
        self.start_websocket()

        while self.running:
            try:
                self.check_control()
                self.check_day_loss()
                scores = self.analyze()
                self.trade(scores)
                self._update_psar_stops()
                self.save_dashboard(scores)

                ws_status = "WS✓" if self.ws_connected else "WS✗"
                with self.positions_lock:
                    pos_count = len(self.positions)
                    bal       = self.balance
                print("[" + datetime.now().strftime("%H:%M") + "] Pos: " +
                      str(pos_count) + "/" + str(self.max_pos) +
                      " | Bal: $" + str(round(bal, 0)) +
                      " | " + EXCHANGE.upper() + " | " + ws_status)

                # Polling stop-check every 30s as fallback when WS is down
                for _ in range(4):
                    if not self.ws_connected:
                        self.check_stops()
                    self.save_dashboard(scores)
                    self._save_state()
                    time.sleep(30)

            except Exception as e:
                print("[ERROR] " + str(e))
                time.sleep(30)


if __name__ == "__main__":
    bot = CryptoBot()
    bot.run()
