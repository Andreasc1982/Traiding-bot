#!/usr/bin/env python3
from datetime import datetime, timezone, timedelta
import time, requests, json, feedparser, re, os, hashlib, hmac, base64, urllib.parse, threading, socket

# Global socket timeout — prevents feedparser.parse() and any urllib call from
# blocking the main thread indefinitely when an RSS/Nitter/Reddit server hangs.
# WebSocket keepalive (ping_interval=30, ping_timeout=10) is unaffected since
# websocket-client manages its own socket after the initial connection.
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

CRYPTO_MAIN = ["BTC/USD","ETH/USD","SOL/USD","XRP/USD","AVAX/USD","LINK/USD","LTC/USD",
               "ADA/USD","DOT/USD","UNI/USD","AAVE/USD",
               "ARB/USD","POL/USD","RENDER/USD"]
CRYPTO_MEME = ["DOGE/USD","SHIB/USD","PEPE/USD","WIF/USD","BONK/USD","TRUMP/USD"]

KEYWORDS = {
    "BTC/USD":  ["bitcoin","btc"],
    "ETH/USD":  ["ethereum","eth"],
    "SOL/USD":  ["solana","sol"],
    "XRP/USD":  ["ripple","xrp"],
    "AVAX/USD": ["avalanche","avax"],
    "LINK/USD": ["chainlink","link"],
    "LTC/USD":  ["litecoin","ltc"],
    "ADA/USD":  ["cardano","ada"],
    "DOT/USD":  ["polkadot","dot","parachain"],
    "UNI/USD":  ["uniswap","uni"],
    "AAVE/USD": ["aave","aave protocol","defi lending"],
    "DOGE/USD":   ["dogecoin","doge"],
    "SHIB/USD":   ["shiba","shib"],
    "PEPE/USD":   ["pepe"],
    "WIF/USD":    ["wif","dogwifhat"],
    "ARB/USD":    ["arbitrum","arb","layer 2","l2"],
    "POL/USD":    ["polygon","pol","matic"],
    "RENDER/USD": ["render","rndr","render network","gpu rendering","ai render"],
    "BONK/USD":   ["bonk","bonk coin","solana meme"],
    "TRUMP/USD":  ["trump coin","trump token","maga coin","trump crypto"],
}

KRAKEN_SYMBOL_MAP = {
    "BTC/USD":  "XBTUSD",
    "ETH/USD":  "ETHUSD",
    "SOL/USD":  "SOLUSD",
    "XRP/USD":  "XRPUSD",
    "AVAX/USD": "AVAXUSD",
    "LINK/USD": "LINKUSD",
    "LTC/USD":  "LTCUSD",
    "ADA/USD":  "ADAUSD",
    "DOT/USD":  "DOTUSD",
    "UNI/USD":  "UNIUSD",
    "AAVE/USD": "AAVEUSD",
    "DOGE/USD":   "DOGEUSD",
    "SHIB/USD":   "SHIBUSD",
    "PEPE/USD":   "PEPEUSD",
    "WIF/USD":    "WIFUSD",
    "ARB/USD":    "ARBUSD",
    "POL/USD":    "POLUSD",
    "RENDER/USD": "RENDERUSD",
    # BONK + TRUMP not on Kraken — Alpaca only
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
    "ADA/USD":  "ADA/USD",
    "DOT/USD":  "DOT/USD",
    "UNI/USD":  "UNI/USD",
    "AAVE/USD": "AAVE/USD",
    "DOGE/USD":   "DOGE/USD",
    "SHIB/USD":   "SHIB/USD",
    "ARB/USD":    "ARB/USD",
    "POL/USD":    "POL/USD",
    "RENDER/USD": "RENDER/USD",
    # PEPE, WIF, BONK, TRUMP not listed on Kraken WS — excluded intentionally
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
    "ADA/USD":  15.0,
    "DOT/USD":  0.5,
    "UNI/USD":  0.5,
    "AAVE/USD": 0.02,
    "DOGE/USD":   50.0,
    "SHIB/USD":   1_000_000.0,
    "PEPE/USD":   1_000_000.0,
    "WIF/USD":    1.0,
    "ARB/USD":    5.0,
    "POL/USD":    5.0,
    "RENDER/USD": 1.0,
    "BONK/USD":   100_000.0,
    "TRUMP/USD":  1.0,
}

# Persists balance + daily-loss baseline between restarts
STATE_PATH = "/home/trading2025/trading_bot/crypto/crypto_state.json"


class CryptoBot:
    def __init__(self):
        self.demo      = DEMO_MODE
        self.balance   = 10000.0
        self.positions = {}
        self.trades    = []
        self.stop_loss    = 2.5   # optimized: 3.0→2.5 (balance between tight SL and volatility room)
        self.take_profit  = 5.0   # optimized: 8.0→5.0 (more achievable target)
        self.max_pos      = 8     # 6→8: bigger universe (20 coins) needs more slots
        self.pos_size     = 0.06  # 8%→6%: smaller per position, more positions active
        self.meme_size    = 0.03  # meme coins stay at 3%
        self.running      = True
        self._sl_cooldown = {}   # symbol -> timestamp of last hard SL — blocks re-entry for 3h
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

        # Whale Alert fast-path — separate polling thread
        self._whale_seen  = set()   # transaction IDs already processed (dedup)
        self._whale_alerted = set() # symbols already fast-path traded this hour

        # Higher-Timeframe (daily) trend cache — refreshed every 10 min
        self._htf_cache = {}        # symbol → (bullish: bool, timestamp: float)

        # Correlation management — recent closes cached from get_indicators()
        self._bar_cache    = {}     # symbol → list of last 20 hourly closes
        self._price_changes = {}    # symbol → 24h price change % (updated each analyze cycle)

        # Watchdog — updated every main loop iteration; watchdog thread kills process if stuck > 5 min
        self._last_heartbeat = time.time()

        # On-chain scores — updated by background thread, read by analyze()
        self._onchain_scores = {s: 0.0 for s in CRYPTO_MAIN + CRYPTO_MEME}
        self._onchain_lock   = threading.Lock()

        # Volatility regime cache — BTC realized vol, refreshed every 30 min
        self._vol_cache = None   # ((name, size_mult), timestamp)

        # Drawdown alert flags — prevent repeated Telegram messages per zone
        self._dd_caution_sent = False
        self._dd_warning_sent = False
        self._dd_danger_sent  = False

        # BTC Lead Indicator — crash detection + trend filter
        self._btc_10min_ref   = None   # BTC price ~10 min ago for trend filter
        self._btc_10min_time  = 0.0
        self._btc_5min_window = []     # [(price, ts), ...] rolling 5-min crash detection
        self._btc_crash_mode  = False  # True when BTC dropped ≥2% in 5 min

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

            # Restore SL cooling periods — only if still active
            saved_cooldowns = st.get("sl_cooldown", {})
            now = time.time()
            active_cooldowns = {sym: ts for sym, ts in saved_cooldowns.items()
                                if now - ts < 5400}
            if active_cooldowns:
                self._sl_cooldown = active_cooldowns
                for sym, ts in active_cooldowns.items():
                    mins_left = int((5400 - (now - ts)) / 60)
                    print("[STATE] SL-Cooling wiederhergestellt: " + sym +
                          " noch " + str(mins_left) + "min")

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
                        # Clear transient runtime flags that must not survive a restart
                        pos.pop("btc_crash_mode", None)   # BTC crash may have resolved
                        valid[sym] = pos
                if valid:
                    with self.positions_lock:
                        self.positions = valid
                    for sym, pos in valid.items():
                        spike_tag = " [SPIKE]" if pos.get("spike") else (" [WHALE]" if pos.get("whale") else "")
                        entry = pos["entry"]
                        # Use more decimal places for sub-cent coins (SHIB, PEPE, etc.)
                        entry_str = ("{:.8f}".format(entry).rstrip("0") if entry < 0.01
                                     else str(round(entry, 4)))
                        print("[STATE] Position wiederhergestellt: " + sym +
                              " " + str(round(pos["shares"], 6)) +
                              " @ $" + entry_str +
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
            # Only persist cooldowns that are still active (< 5400s = 1.5h)
            now = time.time()
            active_cooldowns = {sym: ts for sym, ts in self._sl_cooldown.items()
                                if now - ts < 5400}
            st = {
                "balance":           round(bal, 2),
                "day_start_balance": round(start, 2),
                "day_date":          datetime.now().strftime("%Y-%m-%d"),
                "positions":         positions,     # full position dicts, restored on startup
                "sl_cooldown":       active_cooldowns,  # persisted SL cooling periods
            }
            with open(STATE_PATH, "w") as f:
                json.dump(st, f)
            os.chmod(STATE_PATH, 0o600)   # owner read/write only — API keys adjacent
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
            url    = ALPACA_DATA_URL + "/v1beta3/crypto/us/bars"
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

            # 24h price change (hourly bars: index -25 ≈ 24h ago)
            if len(closes) >= 25:
                change_24h = (closes[-1] - closes[-25]) / closes[-25] * 100
                self._price_changes[symbol] = round(change_24h, 2)
            elif len(closes) >= 2:
                change_24h = (closes[-1] - closes[0]) / closes[0] * 100
                self._price_changes[symbol] = round(change_24h, 2)

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
                "psar":        round(psar_val, 8),   # 8 decimals for micro-prices (SHIB/PEPE/BONK)
                "psar_ok":     psar_ok,
                "tenkan":      round(tenkan, 8),
                "kijun":       round(kijun, 8),
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
        """Pre-populate per-minute volume baselines — runs in background thread
        so a hanging Alpaca bar-fetch never blocks the main loop."""
        def _run():
            for symbol in CRYPTO_MAIN + CRYPTO_MEME:
                cached = self.avg_vol.get(symbol)
                if cached and time.time() - cached[1] < 3600:
                    continue
                try:
                    bars = self._fetch_bars(symbol)
                    if bars and len(bars) >= 20:
                        avg_per_min = sum(b["v"] for b in bars[-20:]) / 20 / 60
                        self.avg_vol[symbol] = (avg_per_min, time.time())
                except Exception:
                    pass
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        # Don't join — fire-and-forget; cache is updated in background

    def _watchdog_run(self):
        """Daemon thread — kills process if main loop hasn't updated heartbeat in 5 min.
        Monitor agent detects the dead screen session and restarts the bot within 60s."""
        TIMEOUT = 300   # 5 minutes
        while True:
            time.sleep(60)
            age = time.time() - self._last_heartbeat
            if age > TIMEOUT:
                print("[WATCHDOG] Hauptloop haengt seit {:.0f}s — erzwinge Neustart".format(age))
                os._exit(1)

    def _get_vol_regime(self):
        """Calculate BTC 7-day annualized realized volatility from hourly bars.
        Returns (regime_name, size_mult):
          LOW      vol < 50%  → 1.2× size  (calm crypto market)
          NORMAL   vol 50-80% → 1.0× size  (standard)
          HIGH     vol 80-120%→ 0.5× size  (very volatile, reduce exposure)
          EXTREME  vol > 120% → 0.3× size  (crash/mania, tiny positions only)
        Cached 30 min. Returns NORMAL on error (never blocks trades).
        """
        cached = self._vol_cache
        if cached and time.time() - cached[1] < 1800:
            return cached[0]
        try:
            bars = self._fetch_bars("BTC/USD")
            if not bars or len(bars) < 100:
                return ("NORMAL", 1.0)

            closes  = [b["c"] for b in bars[-168:]]   # up to 7 days hourly
            returns = [(closes[i] - closes[i-1]) / closes[i-1]
                       for i in range(1, len(closes)) if closes[i-1] > 0]
            if len(returns) < 24:
                return ("NORMAL", 1.0)

            variance    = sum(r * r for r in returns) / len(returns)
            vol_hourly  = variance ** 0.5
            vol_annual  = vol_hourly * (8760 ** 0.5) * 100   # annualised %

            if vol_annual < 50:
                result = ("LOW",     1.2)
            elif vol_annual < 80:
                result = ("NORMAL",  1.0)
            elif vol_annual < 120:
                result = ("HIGH",    0.5)
            else:
                result = ("EXTREME", 0.3)

            self._vol_cache = (result, time.time())
            print("[VOL] BTC Ann.Vol={:.0f}% → {} (size×{})".format(
                  vol_annual, result[0], result[1]))
            return result
        except Exception as e:
            print("[VOL] Fehler: " + str(e) + " → NORMAL")
            return ("NORMAL", 1.0)

    def _btc_crash_check(self, price):
        """Called on every BTC WebSocket tick (WS thread).
        Two jobs:
          1. Crash detection: BTC -2% in 5 min → set btc_crash_mode=True on all positions,
             send Telegram alert, block new entries in trade().
          2. 10-min reference: updated every 600s for the trend filter in trade().
        Fully lock-free except for the brief positions_lock when setting crash mode.
        """
        now = time.time()

        # ── 1. Rolling 5-min window for crash detection ───────────────────────
        self._btc_5min_window.append((price, now))
        # Prune entries older than 5 min
        cutoff = now - 300
        self._btc_5min_window = [(p, t) for p, t in self._btc_5min_window if t >= cutoff]
        # Hard cap to prevent unbounded growth on very active ticks
        if len(self._btc_5min_window) > 600:
            self._btc_5min_window = self._btc_5min_window[-300:]

        if len(self._btc_5min_window) >= 3:
            peak_5min = max(p for p, _ in self._btc_5min_window)
            drop_pct  = (peak_5min - price) / peak_5min * 100

            if drop_pct >= 2.0 and not self._btc_crash_mode:
                # BTC just crashed — tighten all open positions
                self._btc_crash_mode = True
                with self.positions_lock:
                    affected = list(self.positions.keys())
                    for sym in affected:
                        if sym in self.positions:
                            self.positions[sym]["btc_crash_mode"] = True
                n = len(affected)
                print("[BTC-GUARD] BTC -{:.1f}% in 5min — Crash-Stop auf {} Positionen".format(
                      drop_pct, n))
                if n > 0:
                    self.send("🚨 <b>BTC CRASH: -{:.1f}% in 5min</b>\n"
                              "Tight-Stop (1.5% Trailing) auf {} offene Positionen angezogen\n"
                              "Neue Käufe bis zur Erholung blockiert".format(drop_pct, n))

            elif drop_pct < 0.5 and self._btc_crash_mode:
                # BTC recovered — lift crash mode
                self._btc_crash_mode = False
                with self.positions_lock:
                    for sym in self.positions:
                        self.positions[sym].pop("btc_crash_mode", None)
                print("[BTC-GUARD] BTC erholt (Rückgang nur {:.1f}%) — Crash-Schutz aufgehoben".format(
                      drop_pct))

        # ── 2. Update 10-min reference for trend filter in trade() ────────────
        if now - self._btc_10min_time >= 600:
            self._btc_10min_ref  = price
            self._btc_10min_time = now

    def _onchain_refresh_run(self):
        """Background thread: refreshes on-chain scores every 120s independently.
        Prevents blockchain.info / Etherscan calls from blocking the main loop."""
        while self.running:
            try:
                new_scores = self.fetch_onchain()
                with self._onchain_lock:
                    self._onchain_scores = new_scores
            except Exception as e:
                print("[ONCHAIN-BG] " + str(e))
            time.sleep(120)

    def _get_avg_vol(self, symbol):
        """Non-blocking lookup for the WS thread. Returns None if not yet cached."""
        cached = self.avg_vol.get(symbol)
        return cached[0] if cached else None

    # ── Whale Alert fast-path ─────────────────────────────────────────────────

    def _whale_fast_path_run(self):
        """Background thread: polls Whale Alert every 60s.
        On a mega-transfer (≥$100M FROM exchange → bullish, ≥$200M TO exchange → bearish),
        fires an immediate buy/sell decision without waiting for the 2-min analyze() cycle.

        Free tier delay: ~1-5 min after on-chain confirmation.
        Typical lead time over market reaction: 5-20 min → exploitable edge.
        """
        WA_KEY = config.get("whale_alert_key", "")
        if not WA_KEY:
            return   # silently exit — no key configured

        SYMBOL_MAP = {
            "btc":  "BTC/USD",  "eth":  "ETH/USD",  "sol":  "SOL/USD",
            "xrp":  "XRP/USD",  "avax": "AVAX/USD", "link": "LINK/USD",
            "ltc":  "LTC/USD",  "doge": "DOGE/USD", "shib": "SHIB/USD",
            "pepe": "PEPE/USD", "wif":  "WIF/USD",
        }
        WHALE_BUY_THRESHOLD  = 100_000_000   # $100M from exchange → likely accumulation
        WHALE_SELL_THRESHOLD = 200_000_000   # $200M to exchange   → likely distribution
        WHALE_POS_SIZE       = 0.06          # 6% of balance per whale buy
        WHALE_SL             = 2.0           # 2% stop-loss
        WHALE_TP             = 8.0           # 8% take-profit (same as normal)
        ALERT_TTL            = 3600          # reset per-symbol cooldown every hour

        print("[WHALE-FP] Fast-Path Thread gestartet (Poll alle 60s, Schwelle: $100M)")

        last_alert_reset = time.time()

        while self.running:
            try:
                # Reset per-symbol cooldown every hour to allow fresh signals
                if time.time() - last_alert_reset > ALERT_TTL:
                    self._whale_alerted.clear()
                    last_alert_reset = time.time()

                start = int(time.time()) - 90   # last 90s (overlap so we don't miss anything)
                r = requests.get(
                    "https://api.whale-alert.io/v1/transactions",
                    params={"api_key": WA_KEY, "min_value": WHALE_BUY_THRESHOLD,
                            "start": start, "limit": 50},
                    timeout=10,
                )
                if r.status_code != 200:
                    time.sleep(60)
                    continue

                txs = r.json().get("transactions", [])
                for tx in txs:
                    tx_id     = str(tx.get("id", ""))
                    sym_key   = tx.get("symbol", "").lower()
                    symbol    = SYMBOL_MAP.get(sym_key)
                    amount_usd = float(tx.get("amount_usd", 0))

                    if not symbol or tx_id in self._whale_seen:
                        continue
                    self._whale_seen.add(tx_id)
                    # Keep seen-set bounded
                    if len(self._whale_seen) > 500:
                        self._whale_seen.clear()

                    to_type   = tx.get("to",   {}).get("owner_type", "unknown")
                    from_type = tx.get("from", {}).get("owner_type", "unknown")

                    # ── BUY trigger: large outflow from exchange (accumulation) ──
                    if (from_type == "exchange"
                            and amount_usd >= WHALE_BUY_THRESHOLD
                            and symbol not in self._whale_alerted):

                        self._whale_alerted.add(symbol)
                        usd_m = round(amount_usd / 1_000_000)
                        owner = tx.get("from", {}).get("owner", "exchange")

                        with self.positions_lock:
                            already_in = symbol in self.positions
                            pos_full   = len(self.positions) >= self.max_pos
                            bal        = self.balance

                        if already_in or pos_full or self.tg_paused:
                            print("[WHALE-FP] SIGNAL {}: ${:,}M von {} — Pos voll/pausiert, kein Kauf".format(
                                symbol, usd_m, owner))
                            continue

                        price = self.ws_prices.get(symbol)
                        if not price:
                            continue

                        size   = WHALE_POS_SIZE
                        shares = round((bal * size) / price, 6)
                        cost   = round(shares * price, 2)

                        if shares <= 0 or cost > bal * 0.95:
                            continue

                        print("[WHALE-FP] BUY {} ${:,}M Abfluss von {} → sofortiger Kauf".format(
                            symbol, usd_m, owner))

                        ok = self.place_order(symbol, shares, "buy")
                        if ok:
                            with self.positions_lock:
                                self.balance -= cost
                                self.positions[symbol] = {
                                    "shares":      shares,
                                    "entry":       price,
                                    "highest":     price,
                                    "time":        datetime.now().strftime("%Y-%m-%d %H:%M"),
                                    "stop_loss":   WHALE_SL,
                                    "take_profit": WHALE_TP,
                                    "whale":       True,
                                    "whale_usd_m": usd_m,
                                }
                            self._save_state()
                            self.send("🐋 <b>WHALE BUY {}</b> ${:,}M Abfluss von {}\n"
                                      "Kauf {} @ ${} | SL {}% TP {}%".format(
                                symbol, usd_m, owner,
                                shares, round(price, 4),
                                WHALE_SL, WHALE_TP))

                    # ── ALERT trigger: massive inflow to exchange (distribution) ──
                    elif (to_type == "exchange"
                            and amount_usd >= WHALE_SELL_THRESHOLD
                            and symbol not in self._whale_alerted):

                        self._whale_alerted.add(symbol)
                        usd_m = round(amount_usd / 1_000_000)
                        owner = tx.get("to", {}).get("owner", "exchange")

                        with self.positions_lock:
                            has_pos = symbol in self.positions

                        msg = "🐋⚠️ <b>WHALE SELL-SIGNAL {}</b>\n${:,}M Zufluss zu {}\n".format(
                            symbol, usd_m, owner)
                        if has_pos:
                            msg += "⚡ Position vorhanden — Stop auf 0.5% gezogen"
                            # Tighten stop on existing position
                            with self.positions_lock:
                                if symbol in self.positions:
                                    current = self.ws_prices.get(symbol,
                                        self.positions[symbol]["entry"])
                                    self.positions[symbol]["stop_loss"] = 0.5
                                    self.positions[symbol]["psar_stop"] = current * 0.995
                        else:
                            msg += "Keine offene Position — Kauf blockiert"
                        self.send(msg)
                        print("[WHALE-FP] SELL-SIGNAL {}: ${:,}M zu {}".format(
                            symbol, usd_m, owner))

            except Exception as e:
                print("[WHALE-FP] Fehler: " + str(e))

            time.sleep(60)

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
                        # BTC crash detection runs on every BTC tick,
                        # even when BTC is not in self.positions
                        if symbol == "BTC/USD":
                            self._btc_crash_check(price)
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

    def _exit_trigger(self, pos, price, ws=True):
        """
        Tiered profit-protection exit logic — uses live WebSocket prices.

        Zones (based on best P&L ever seen for this position):
          ≥ tp%   → classic 1.5% trailing stop from peak
          ≥ 6%    → lock minimum (peak − 2%) — trail 2% behind best gain
          ≥ 4%    → lock minimum +2%
          ≥ 2%    → break-even stop (never lose on a winning trade)
          < 2%    → standard hard stop-loss

        PSAR dynamic stop always checked first (highest priority).
        Returns trigger string or None.
        """
        entry    = pos["entry"]
        highest  = pos.get("highest", entry)
        pnl_pct  = ((price - entry) / entry) * 100
        best_pnl = ((highest - entry) / entry) * 100
        trailing = ((highest - price) / highest) * 100
        psar_stop = pos.get("psar_stop")
        sl = pos.get("stop_loss", self.stop_loss)
        tp = pos.get("take_profit", self.take_profit)
        pfx = "WS-" if ws else ""

        # 1. PSAR dynamic stop — only active once position is in profit (≥+1.5%)
        # Below that threshold PSAR is too noisy on 1h bars and stops out early
        if psar_stop is not None and price < psar_stop and pnl_pct >= 1.5:
            return pfx + "PSAR-STOP"

        # 1b. BTC crash mode — tighter 1.5% trailing + tighter hard stop
        if pos.get("btc_crash_mode"):
            if trailing >= 1.5:
                return pfx + "BTC-CRASH-STOP"
            if pnl_pct <= -1.5:
                return pfx + "BTC-CRASH-STOP"

        # 2. Take-profit zone — classic trailing
        if best_pnl >= tp:
            if trailing >= 1.5:
                return pfx + "TRAIL-STOP"

        # 3. Deep profit zone (≥6%) — trail 2% behind personal best
        elif best_pnl >= 6.0:
            if pnl_pct < best_pnl - 2.0:
                return pfx + "PROFIT-LOCK"

        # 4. Good profit zone (≥4%) — protect minimum +2%
        elif best_pnl >= 4.0:
            if pnl_pct < 2.0:
                return pfx + "PROFIT-LOCK"

        # 5. Break-even zone (≥2%) — never lose on a trade that was winning
        elif best_pnl >= 2.0:
            if pnl_pct < 0.0:
                return pfx + "BREAKEVEN"

        # 6. Standard hard stop — position never reached +2%
        else:
            if pnl_pct <= -sl:
                return pfx + "STOP-LOSS"

        return None

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

            # Track intraday high for trailing stop
            if price > pos.get("highest", pos["entry"]):
                pos["highest"] = price

            pnl_pct = ((price - pos["entry"]) / pos["entry"]) * 100
            trigger = self._exit_trigger(pos, price, ws=True)
            if trigger is None:
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
            "https://news.google.com/rss/search?q=cardano+ADA+crypto&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=polkadot+DOT+crypto&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=uniswap+UNI+defi&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=aave+defi+lending+crypto&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=arbitrum+ARB+layer2&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=polygon+POL+MATIC+crypto&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=render+network+RNDR+AI+crypto&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=bonk+coin+solana+meme&hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/search?q=trump+coin+crypto+maga&hl=en-US&gl=US&ceid=US:en",
        ]
        articles = []

        def _fetch_feed(url):
            try:
                r    = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                feed = feedparser.parse(r.content)
                return [entry.title + " " + getattr(entry, "summary", "")
                        for entry in feed.entries[:10]]
            except Exception:
                return []

        # Fetch all feeds in parallel — worst case 10s instead of 22×10s=220s
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(_fetch_feed, url): url for url in feeds}
            for fut in as_completed(futures, timeout=15):
                try:
                    articles.extend(fut.result())
                except Exception:
                    pass

        print("[NEWS] " + str(len(articles)) + " Artikel via RSS")
        return articles

    # ── On-Chain Exchange Wallet Tracker ─────────────────────────────────────
    #
    # Tracks balance changes in the ACTUAL exchange cold/hot wallets on-chain.
    # When coins leave these wallets → accumulation (bullish).
    # When coins flow IN  → distribution / sell pressure (bearish).
    #
    # This is as close to "insider trading detection" as free data allows:
    # large coordinated outflows from exchange wallets often precede price pumps
    # by 15-60 minutes as OTC deals and large off-exchange buys settle.
    #
    # Data sources:
    #   BTC  — blockchain.info balance API   (no key needed)
    #   ETH  — Etherscan V2 balance API      (free key: etherscan.io)

    # Known exchange cold/hot wallets
    _BTC_EXCHANGE_WALLETS = {
        "Binance":  "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo",
        "Bitfinex": "3JZq4atUahhuA9rLhXLMhhTo133J9rq97E",
    }
    _ETH_EXCHANGE_WALLETS = {
        "Binance1": "0xBE0eB53F46Cd790Cd13851d5EFf43D12404d33E8",
        "Binance2": "0xF977814e90dA44bFA03b6295A0616a897441aceC",
        "Coinbase": "0x71660c4005BA85c37ccec55d0C4493E66Fe775d3",
        "Kraken":   "0x2910543Af39abA0Cd09dBb2D50200b3E800A63D2",
    }
    # Insider-signal thresholds
    _BTC_ALERT_LARGE   = 2000    # BTC leaving in 1h → Telegram alert + strong buy
    _BTC_SIGNAL_SMALL  = 500     # BTC leaving in 1h → moderate buy signal
    _ETH_ALERT_LARGE   = 20_000  # ETH leaving in 1h → alert
    _ETH_SIGNAL_SMALL  = 5_000   # ETH leaving in 1h → moderate signal

    def _onchain_btc_balance(self):
        """Sum BTC balance across tracked exchange wallets. Returns dict {name: btc}."""
        balances = {}
        for name, addr in self._BTC_EXCHANGE_WALLETS.items():
            try:
                r = requests.get(
                    "https://blockchain.info/balance",
                    params={"active": addr},
                    timeout=10,
                )
                if r.status_code == 200:
                    data = r.json()
                    btc = data[addr]["final_balance"] / 1e8
                    balances[name] = btc
            except Exception as e:
                print("[ONCHAIN] BTC {}: {}".format(name, e))
            time.sleep(1)   # be polite to blockchain.info
        return balances

    def _onchain_erc20_flows(self, es_key):
        """Track ERC-20 token flows for LINK, SHIB, PEPE via Etherscan.
        Detects large transfers FROM known exchange wallets (insider accumulation).
        Small coins move faster — even $1M outflow can trigger 50-500% pump.
        """
        TOKEN_CONTRACTS = {
            # symbol         contract                                       decimals  min_tokens (≈$1M worth)
            "LINK/USD":   ("0x514910771AF9Ca656af840dff83E8264EcF986CA", 18,      50_000),
            "AAVE/USD":   ("0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9", 18,      10_000),
            "UNI/USD":    ("0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984", 18,     200_000),
            "ARB/USD":    ("0xB50721BCf8d664c30412Cfbc6cf7a15145234ad1", 18,   1_000_000),
            "POL/USD":    ("0x455e53CBB86018Ac2B8092FdCd39d8444aFFC3F6", 18,   5_000_000),
            "RENDER/USD": ("0x6De037ef9aD2725EB40118Bb1702EBb27e4Aeb24", 18,      50_000),
            "SHIB/USD":   ("0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE", 18, 50_000_000_000_000),
            "PEPE/USD":   ("0x6982508145454Ce325dDbE47a25d4ec3d2311933", 18,  5_000_000_000_000),
        }
        EXCHANGE_ADDRS = {a.lower() for a in self._ETH_EXCHANGE_WALLETS.values()}
        scores = {}

        try:
            rb = requests.get(
                "https://api.etherscan.io/v2/api",
                params={"chainid": "1", "module": "proxy",
                        "action": "eth_blockNumber", "apikey": es_key},
                timeout=8,
            )
            if rb.status_code != 200:
                return scores
            current_block = int(rb.json()["result"], 16)
            start_block   = current_block - 300   # ≈ last 1 hour (12s/block)
        except Exception as e:
            print("[ONCHAIN-ERC20] Block lookup: " + str(e))
            return scores

        for symbol, (contract, decimals, min_tokens) in TOKEN_CONTRACTS.items():
            try:
                time.sleep(0.25)
                r = requests.get(
                    "https://api.etherscan.io/v2/api",
                    params={
                        "chainid": "1", "module": "account", "action": "tokentx",
                        "contractaddress": contract,
                        "startblock": start_block, "endblock": "latest",
                        "sort": "desc", "apikey": es_key,
                        "offset": 100, "page": 1,
                    },
                    timeout=10,
                )
                if r.status_code != 200 or r.json()["status"] != "1":
                    continue

                outflow = 0.0
                inflow  = 0.0
                for tx in r.json()["result"]:
                    amount  = int(tx["value"]) / (10 ** decimals)
                    from_ex = tx["from"].lower() in EXCHANGE_ADDRS
                    to_ex   = tx["to"].lower()   in EXCHANGE_ADDRS
                    if from_ex:
                        outflow += amount
                    elif to_ex:
                        inflow  += amount

                ticker = symbol.split("/")[0]
                if outflow >= min_tokens:
                    factor = outflow / min_tokens
                    score  = min(factor * 0.8, 3.0)
                    scores[symbol] = scores.get(symbol, 0) + score
                    print("[ONCHAIN-ERC20] {} Abfluss {:,.0f} ({}×) → +{:.1f}".format(
                        ticker, outflow, round(factor, 1), score))
                    if outflow >= min_tokens * 5:
                        self.send("🚨 <b>ONCHAIN INSIDER SIGNAL — {}</b>\n"
                                  "{:,.0f} Token verlassen Exchange ({}×)\n"
                                  "→ Insider-Akkumulation vor möglichem Pump!".format(
                            ticker, outflow, round(factor, 1)))
                if inflow >= min_tokens:
                    score = min((inflow / min_tokens) * 0.5, 2.0)
                    scores[symbol] = scores.get(symbol, 0) - score
                    print("[ONCHAIN-ERC20] {} Zufluss {:,.0f} → -{:.1f}".format(
                        ticker, inflow, score))

            except Exception as e:
                print("[ONCHAIN-ERC20] {}: {}".format(symbol, e))

        return scores

    def _onchain_eth_balance(self, es_key):
        """Sum ETH balance across tracked exchange wallets (Etherscan API)."""
        balances = {}
        addrs = ",".join(self._ETH_EXCHANGE_WALLETS.values())
        names = list(self._ETH_EXCHANGE_WALLETS.keys())
        try:
            r = requests.get(
                "https://api.etherscan.io/v2/api",
                params={"chainid": "1", "module": "account", "action": "balancemulti",
                        "address": addrs, "tag": "latest", "apikey": es_key},
                timeout=10,
            )
            if r.status_code == 200 and r.json()["status"] == "1":
                for item in r.json()["result"]:
                    addr  = item["account"].lower()
                    eth   = int(item["balance"]) / 1e18
                    # find name for this address
                    for name, a in self._ETH_EXCHANGE_WALLETS.items():
                        if a.lower() == addr:
                            balances[name] = eth
                            break
        except Exception as e:
            print("[ONCHAIN] ETH Etherscan: {}".format(e))
        return balances


    def fetch_onchain(self):
        """Main on-chain call — runs in analyze() cycle every ~2 min.
        Returns score dict for BTC/ETH/LTC based on exchange wallet flows.
        Sends Telegram alert on insider-scale movements (>BTC_ALERT_LARGE in 1h).
        """
        scores = {s: 0.0 for s in CRYPTO_MAIN + CRYPTO_MEME}
        now    = time.time()

        ES_KEY = config.get("etherscan_api_key", "")

        # ── 1. BTC exchange wallet balances (blockchain.info, always free) ──
        btc_now = self._onchain_btc_balance()
        if btc_now:
            # Compare to 1-hour-ago snapshot
            prev = getattr(self, "_onchain_btc_prev", {})
            prev_time = getattr(self, "_onchain_btc_prev_time", 0)

            if prev and (now - prev_time) >= 3500:   # ~1h window
                for name, bal_now in btc_now.items():
                    bal_prev = prev.get(name, bal_now)
                    delta = bal_prev - bal_now   # positive = coins LEAVING (bullish)
                    if abs(delta) > 50:
                        direction = "⬇️ Abfluss" if delta > 0 else "⬆️ Zufluss"
                        print("[ONCHAIN] BTC {} {}: {:+.0f} BTC in 1h".format(
                            name, direction, delta))
                        if delta > self._BTC_ALERT_LARGE:
                            scores["BTC/USD"] += 3.0
                            self.send("🚨 <b>ONCHAIN INSIDER SIGNAL</b>\n"
                                      "BTC: {:+.0f} verlassen {} in 1h\n"
                                      "→ Grosse Akkumulation — möglicher Insider-Kauf!".format(delta, name))
                        elif delta > self._BTC_SIGNAL_SMALL:
                            scores["BTC/USD"] += 1.5
                        elif delta < -self._BTC_SIGNAL_SMALL:
                            scores["BTC/USD"] -= 1.0

                # Reset 1h window
                self._onchain_btc_prev      = btc_now
                self._onchain_btc_prev_time = now
            elif not prev:
                # First run — store baseline
                self._onchain_btc_prev      = btc_now
                self._onchain_btc_prev_time = now
                total = sum(btc_now.values())
                print("[ONCHAIN] BTC Baseline: {:.0f} BTC in {} Exchange-Wallets".format(
                    total, len(btc_now)))

        # ── 2. ERC-20 token flows: LINK, SHIB, PEPE (Etherscan) ─────────────
        if ES_KEY:
            for sym, val in self._onchain_erc20_flows(ES_KEY).items():
                scores[sym] = scores.get(sym, 0) + val

        # ── 3. ETH exchange wallet balances (Etherscan) ─────────────────────
        if ES_KEY:
            eth_now = self._onchain_eth_balance(ES_KEY)
            if eth_now:
                prev_eth  = getattr(self, "_onchain_eth_prev", {})
                prev_time = getattr(self, "_onchain_eth_prev_time", 0)

                if prev_eth and (now - prev_time) >= 3500:
                    total_delta = sum(
                        prev_eth.get(n, b) - b for n, b in eth_now.items()
                    )
                    if total_delta > self._ETH_ALERT_LARGE:
                        scores["ETH/USD"] += 3.0
                        self.send("🚨 <b>ONCHAIN INSIDER SIGNAL</b>\n"
                                  "ETH: {:+.0f} verlassen Exchanges in 1h\n"
                                  "→ Grosse Akkumulation!".format(total_delta))
                    elif total_delta > self._ETH_SIGNAL_SMALL:
                        scores["ETH/USD"] += 1.5
                    elif total_delta < -self._ETH_SIGNAL_SMALL:
                        scores["ETH/USD"] -= 1.0
                    if abs(total_delta) > 1000:
                        print("[ONCHAIN] ETH Δ {:+.0f} ETH in 1h ({})".format(
                            total_delta, "Abfluss=bullish" if total_delta > 0 else "Zufluss=bearish"))
                    self._onchain_eth_prev      = eth_now
                    self._onchain_eth_prev_time = now
                elif not prev_eth:
                    self._onchain_eth_prev      = eth_now
                    self._onchain_eth_prev_time = now
                    print("[ONCHAIN] ETH Baseline: {:.0f} ETH total in {} Wallets".format(
                        sum(eth_now.values()), len(eth_now)))
        else:
            print("[ONCHAIN] Etherscan übersprungen (etherscan_api_key in config.py)")


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

    def fetch_whale_alerts(self):
        """Whale Alert REST API (free tier) — replaces dead Nitter RSS.
        Free key: https://whale-alert.io  →  add 'whale_alert_key' to config.py
        Without a key the function returns neutral scores (silent skip).
        """
        scores = {s: 0.0 for s in CRYPTO_MAIN + CRYPTO_MEME}
        WA_KEY = config.get("whale_alert_key", "")
        if not WA_KEY:
            print("[WHALE] Kein API-Key — übersprungen (whale_alert_key in config.py setzen)")
            return scores

        # Map Whale Alert symbol names → our internal symbols
        SYMBOL_MAP = {
            "btc":  "BTC/USD",  "eth":  "ETH/USD",  "sol":  "SOL/USD",
            "xrp":  "XRP/USD",  "avax": "AVAX/USD", "link": "LINK/USD",
            "ltc":  "LTC/USD",  "doge": "DOGE/USD", "shib": "SHIB/USD",
            "pepe": "PEPE/USD", "wif":  "WIF/USD",
        }
        try:
            start = int(time.time()) - 3600   # last 1 h (free-tier max lookback)
            r = requests.get(
                "https://api.whale-alert.io/v1/transactions",
                params={"api_key": WA_KEY, "min_value": 10_000_000,
                        "start": start, "limit": 100},
                timeout=10,
            )
            if r.status_code != 200:
                print("[WHALE] API Fehler: " + str(r.status_code))
                return scores
            txs   = r.json().get("transactions", [])
            count = 0
            for tx in txs:
                sym_key = tx.get("symbol", "").lower()
                symbol  = SYMBOL_MAP.get(sym_key)
                if not symbol:
                    continue
                to_type   = tx.get("to",   {}).get("owner_type", "unknown")
                from_type = tx.get("from", {}).get("owner_type", "unknown")
                if to_type == "exchange":
                    scores[symbol] -= 0.4    # bearish: coins flowing to exchange (sell pressure)
                elif from_type == "exchange":
                    scores[symbol] += 0.4    # bullish: coins leaving exchange (accumulation)
                else:
                    scores[symbol] += 0.15   # neutral: wallet-to-wallet move
                count += 1
            print("[WHALE] " + str(count) + " grosse Transfers ($10M+) via Whale Alert API")
        except Exception as e:
            print("[WHALE] " + str(e))
        return scores

    def _reddit_token(self):
        """OAuth2 client-credentials token for Reddit API (100 req/min).
        Register a free 'script' app at reddit.com/prefs/apps, then add to config.py:
            "reddit_client_id":     "...",
            "reddit_client_secret": "...",
        """
        cid = config.get("reddit_client_id", "")
        sec = config.get("reddit_client_secret", "")
        if not cid or not sec:
            return None
        try:
            r = requests.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=(cid, sec),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": "TradingBot/2.0"},
                timeout=10,
            )
            if r.status_code == 200:
                return r.json().get("access_token")
            print("[REDDIT] Token Fehler: HTTP " + str(r.status_code))
        except Exception as e:
            print("[REDDIT] Token: " + str(e))
        return None

    def fetch_reddit(self):
        """Reddit OAuth API — public JSON is IP-blocked (429). Needs free OAuth app.
        Without credentials → silently skipped; other 13 crypto feeds still active.
        """
        scores = {s: 0.0 for s in CRYPTO_MAIN + CRYPTO_MEME}
        token = self._reddit_token()
        if not token:
            print("[REDDIT] Kein OAuth-Key — übersprungen (reddit_client_id/secret in config.py)")
            return scores

        subs = [
            ("CryptoCurrency", "hot", 25, 1.0),
            ("CryptoCurrency", "new", 15, 0.7),
            ("Bitcoin",        "hot", 25, 1.3),
            ("Bitcoin",        "new", 15, 0.9),
            ("ethereum",       "hot", 25, 1.3),
            ("ethereum",       "new", 15, 0.9),
            ("solana",         "hot", 20, 1.1),
            ("dogecoin",       "hot", 20, 1.1),
        ]
        headers = {
            "Authorization": "bearer " + token,
            "User-Agent":    "TradingBot/2.0",
        }
        total = 0
        for sub, sort, limit, weight in subs:
            try:
                url = "https://oauth.reddit.com/r/{}/{}?limit={}".format(sub, sort, limit)
                r   = requests.get(url, timeout=10, headers=headers)
                if r.status_code != 200:
                    print("[REDDIT] {}/{} → HTTP {}".format(sub, sort, r.status_code))
                    continue
                posts = r.json().get("data", {}).get("children", [])
                for post in posts:
                    d    = post.get("data", {})
                    raw  = d.get("title", "") + " " + d.get("selftext", "")
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

    def check_stuck_positions(self):
        """Time-based exit for positions that are blocking slots without going anywhere.

        Rules:
        - Spike trade  open > 12h  → always exit (spikes must resolve fast)
        - Normal trade open > 72h  AND best P&L never reached +4% → TIME-EXIT
        - Any trade    open > 120h → hard exit regardless (free up capital)
        """
        SPIKE_MAX_H  = 12    # spike trades must close within 12h
        STUCK_H      = 72    # normal trades: stuck threshold
        STUCK_PEAK   = 4.0   # only 'stuck' if best P&L was never above this %
        HARD_MAX_H   = 120   # 5 days — absolute maximum for any position

        with self.positions_lock:
            symbols = list(self.positions.keys())

        for symbol in symbols:
            try:
                price = self.get_price(symbol)
                if not price or price <= 0:
                    continue

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

                age_h    = (datetime.now() - entry_dt).total_seconds() / 3600
                pnl_pct  = ((price - pos["entry"]) / pos["entry"]) * 100
                best_pnl = ((pos.get("highest", pos["entry"]) - pos["entry"]) / pos["entry"]) * 100
                is_spike = pos.get("spike", False)

                reason = None
                if is_spike and age_h >= SPIKE_MAX_H:
                    reason = "TIME-EXIT-SPIKE"
                elif age_h >= HARD_MAX_H:
                    reason = "TIME-EXIT-MAX"
                elif age_h >= STUCK_H and best_pnl < STUCK_PEAK:
                    reason = "TIME-EXIT-STUCK"

                if reason:
                    print("[TIME-EXIT] {} nach {:.0f}h | P&L: {:.1f}% | Grund: {}".format(
                        symbol, age_h, pnl_pct, reason))
                    self.send("⏰ <b>TIME-EXIT</b>: {} nach <b>{:.0f}h</b>\n"
                              "P&amp;L: {:.1f}% | Best: {:.1f}% | {}".format(
                              symbol, age_h, pnl_pct, best_pnl, reason))
                    self.close_position(symbol, price, reason, pnl_pct)

            except Exception as e:
                print("[TIME-EXIT] Fehler bei {}: {}".format(symbol, e))

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

        # On-chain exchange wallet tracker — read cached scores (updated by background thread)
        with self._onchain_lock:
            onchain_snap = dict(self._onchain_scores)
        for sym, val in onchain_snap.items():
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
                pos = self.positions[symbol]
                if price > pos.get("highest", pos["entry"]):
                    pos["highest"] = price
                pnl_pct = ((price - pos["entry"]) / pos["entry"]) * 100
                trigger = self._exit_trigger(pos, price, ws=False)
                if trigger is None:
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
            "symbol":    symbol,
            "profit":    round(profit, 2),
            "pct":       round(pnl_pct, 1),
            "reason":    reason,
            "time":      datetime.now().strftime("%Y-%m-%d %H:%M"),
            "spike":     pos.get("spike", False),
            "whale":     pos.get("whale", False),
            "whale_usd_m": pos.get("whale_usd_m", 0),
        }
        with self.positions_lock:
            self.trades.append(trade_record)

        trades_path = "/home/trading2025/trading_bot/crypto/trades_history.json"
        with open(trades_path, "w") as f:
            json.dump(self.trades, f)

        self._save_state()   # persist balance after every close

        # 1.5h cooling period after hard stop-loss — prevents re-buying into downtrend
        if reason in ("WS-STOP-LOSS", "STOP-LOSS"):
            self._sl_cooldown[symbol] = time.time()
            print("[COOLING] " + symbol + " — 1.5h Sperre nach Hard-Stop")

        msg = ("CRYPTO " + reason + ": " + symbol + " " +
               str(round(pnl_pct, 1)) + "% | P&L: $" + str(round(profit, 0)))
        print(msg)
        self.send(msg)

    # ── Trade entry ────────────────────────────────────────────────────────

    def _get_drawdown_mult(self):
        """Gradual position-size scaling based on today's P&L.
        Returns (size_mult, zone, allow_meme).

        HEALTHY  > -3%        → 1.0×  alle Trades erlaubt
        CAUTION  -3% to -6%   → 0.7×  -30% Grösse, Telegram-Warnung
        WARNING  -6% to -9%   → 0.4×  -60% Grösse, keine Meme-Coins
        DANGER   < -9%        → 0.0×  keine neuen Käufe
        """
        if self.start_balance <= 0:
            return 1.0, "HEALTHY", True
        day_pct = (self.balance - self.start_balance) / self.start_balance * 100
        if day_pct > -3.0:
            return 1.0, "HEALTHY", True
        elif day_pct > -6.0:
            if not getattr(self, "_dd_caution_sent", False):
                self.send("⚠️ Drawdown CAUTION: {:.1f}% heute — Positionsgrösse -30%".format(day_pct))
                self._dd_caution_sent = True
            return 0.7, "CAUTION", True
        elif day_pct > -9.0:
            if not getattr(self, "_dd_warning_sent", False):
                self.send("🔴 Drawdown WARNING: {:.1f}% heute — -60% Grösse, keine Meme-Coins".format(day_pct))
                self._dd_warning_sent = True
            return 0.4, "WARNING", False
        else:
            if not getattr(self, "_dd_danger_sent", False):
                self.send("🚨 Drawdown DANGER: {:.1f}% heute — keine neuen Trades!".format(day_pct))
                self._dd_danger_sent = True
            return 0.0, "DANGER", False

    def trade(self, scores):
        if self.tg_paused:
            print("[TRADE] Pausiert (via Telegram /stop)")
            return

        # Gradual drawdown protection
        dd_mult, dd_zone, dd_allow_meme = self._get_drawdown_mult()
        if dd_mult == 0.0:
            print("[TRADE] DD=" + dd_zone + " — keine neuen Käufe")
            return
        if dd_zone == "HEALTHY":
            self._dd_caution_sent = False
            self._dd_warning_sent = False
            self._dd_danger_sent  = False

        # ── BTC Lead Indicator — trade filter ────────────────────────────────
        # Block all new buys during an active BTC crash (already tightened stops)
        if self._btc_crash_mode:
            print("[TRADE] BTC-CRASH aktiv — keine neuen Käufe")
            return
        # Soft filter: BTC trending down >1% over last 10 min → wait for stabilisation
        btc_now = self.ws_prices.get("BTC/USD")
        if btc_now and self._btc_10min_ref and self._btc_10min_ref > 0:
            btc_10m_chg = (btc_now - self._btc_10min_ref) / self._btc_10min_ref * 100
            if btc_10m_chg < -1.0:
                print("[TRADE] BTC-TREND {:.1f}% (10min) — keine neuen Käufe".format(btc_10m_chg))
                return

        ranked = sorted(scores.items(), key=lambda x: abs(x[1]), reverse=True)
        for symbol, score in ranked:
            if score <= 0.1:
                continue

            # Quick check before doing slow indicator fetch
            with self.positions_lock:
                if symbol in self.positions or len(self.positions) >= self.max_pos:
                    continue

            # 1.5h cooling period after hard stop-loss — no re-entry into downtrend
            sl_age = time.time() - self._sl_cooldown.get(symbol, 0)
            if sl_age < 5400:
                mins_left = int((5400 - sl_age) / 60)
                print("[SKIP] " + symbol + " SL-COOLING " + str(mins_left) + "min")
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

            # ── BTC Realized Volatility Regime — multiplied on top of ADX ─────
            vol_regime, vol_mult = self._get_vol_regime()
            size_mult = round(size_mult * vol_mult * dd_mult, 2)

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

            is_meme   = symbol in CRYPTO_MEME
            # Block meme coins in WARNING/DANGER drawdown zones
            if not dd_allow_meme and is_meme:
                print("[SKIP] " + symbol + " DD=" + dd_zone + " — keine Meme-Coins in dieser Zone")
                continue
            # Extreme-volatile meme coins get wider stop (5%) — BONK/TRUMP can drop 5% intraday
            WILD_MEME = {"BONK/USD", "TRUMP/USD", "PEPE/USD", "WIF/USD"}
            meme_sl   = 5.0 if symbol in WILD_MEME else self.stop_loss
            size      = self.meme_size if is_meme else self.pos_size

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
                pos_entry = {
                    "shares":    shares,
                    "entry":     price,
                    "time":      datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "highest":   price,
                    "psar_stop": ind.get("psar"),   # dynamic stop — updated each cycle
                }
                # Wild meme coins get a wider per-position stop (5%) stored explicitly
                # so _ws_check_price and check_stops both use it via pos.get("stop_loss")
                if symbol in WILD_MEME:
                    pos_entry["stop_loss"] = meme_sl
                self.positions[symbol] = pos_entry

            if not self.demo and self.exchange_ok:
                self.place_order(symbol, shares, "buy")
                self._sync_balance()

            self._save_state()   # persist balance after buy

            msg = ("CRYPTO BUY " + symbol + " $" + str(round(price, 4)) +
                   " [" + regime + " ADX=" + str(adx) +
                   " VOL=" + vol_regime +
                   " DD=" + dd_zone +
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
            entry = pos["entry"]
            pnl_pct = ((curr - entry) / entry) * 100 if entry else 0
            pnl_usd = pos["shares"] * (curr - entry)
            # Use 8 decimal places so micro-prices (SHIB 0.000005, PEPE 0.0000001)
            # are not truncated to 0.0 by round(..., 4)
            positions_data[sym] = {
                "shares":        round(pos["shares"], 6),
                "entry":         round(entry, 8),
                "current_price": round(curr, 8),
                "pnl_pct":       round(pnl_pct, 1),
                "pnl_usd":       round(pnl_usd, 2),
            }

        total_pnl = (sum(t["profit"] for t in trades_snap) +
                     sum(v.get("pnl_usd", 0) for v in positions_data.values()))

        mode_str = ("DEMO" if self.demo else "LIVE") + " | " + EXCHANGE.upper()
        if self.ws_connected:
            mode_str += " | WS✓"

        data = {
            "time":          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode":          mode_str,
            "balance":       round(balance_snap, 2),
            "positions":     positions_data,
            "scores":        {k: round(v, 2) for k, v in scores.items()},
            "price_changes": dict(self._price_changes),
            "trades":        trades_snap[-20:],
            "total_pnl":     round(total_pnl, 0),
            "total_trades":  len(trades_snap),
            "running":       self.running,
            "fear_greed":    self.last_fg,
            "skips":         skips_snap,
            "ws_connected":  self.ws_connected,
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

        # Start Whale Alert fast-path thread (fires buys on $100M+ exchange outflows)
        wt = threading.Thread(target=self._whale_fast_path_run, daemon=True, name="whale-fast-path")
        wt.start()

        # Watchdog thread — kills process if main loop hangs > 5 min (monitor restarts)
        wd = threading.Thread(target=self._watchdog_run, daemon=True, name="watchdog")
        wd.start()

        # On-chain background thread — updates scores every 120s without blocking main loop
        oc = threading.Thread(target=self._onchain_refresh_run, daemon=True, name="onchain-bg")
        oc.start()

        print("[WATCHDOG] Aktiv — Neustart wenn Hauptloop > 5 min haengt")

        while self.running:
            try:
                self._last_heartbeat = time.time()   # watchdog: main loop alive
                self.check_control()
                self.check_day_loss()
                scores = self.analyze()
                self.trade(scores)
                self._update_psar_stops()
                self.check_stuck_positions()
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
                    self._last_heartbeat = time.time()   # watchdog: inner loop alive
                    self.check_control()      # allow close_all to fire mid-cycle
                    if not self.running:
                        break
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
