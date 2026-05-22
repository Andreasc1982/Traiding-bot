# Trading Bot System — Architecture Reference

## Directory Layout

```
/home/trading2025/trading_bot/
├── super_bot.py              # Stock ETF bot
├── config.py                 # All secrets and switches (not in git)
├── dashboard.json            # Live JSON feed for super_bot dashboard
├── dashboard_super.html      # Super bot web dashboard
├── trades_history.json       # Persistent trade log (super_bot)
├── super_state.json          # Persisted balance + daily-loss baseline (survives restarts)
├── bot_control.json          # Pause/stop control for super_bot (written by telegram_router)
├── telegram_router.py        # Single Telegram getUpdates poller — routes commands to both bots
├── start_all.sh              # Launches all 9 screen sessions (called by systemd)
├── .gitignore                # Excludes config.*, state files, live feeds, logs
│
├── crypto/
│   ├── crypto_bot.py         # Crypto bot
│   ├── crypto_dashboard.json # Live JSON feed for crypto dashboard
│   ├── dashboard_crypto.html # Crypto bot web dashboard
│   ├── crypto_control.json   # Pause/stop control for crypto_bot (written by telegram_router)
│   ├── crypto_state.json     # Persisted balance + daily-loss baseline (survives restarts)
│   └── trades_history.json   # Persistent trade log (crypto_bot)
│
└── agents/
    ├── monitor_agent.py       # Watchdog: restarts crashed bots, daily Telegram report
    ├── risk_agent.py          # Portfolio risk guard: halts bots on loss/drawdown limits
    ├── backtest_agent.py      # 2024 historical backtest for both bots
    ├── optimize_agent.py      # Weekly parameter optimizer (runs every Sunday 00:00)
    ├── risk_halt.json         # Written by risk_agent when halted; read by monitor_agent
    ├── risk_log.json          # Persisted risk state + event history
    ├── backtest_results.json  # Full backtest output (machine-readable)
    ├── backtest_report.txt    # Human-readable backtest summary
    ├── optimize_results.json  # Weekly optimization output (machine-readable)
    ├── optimize_log.txt       # Timestamped optimization run log
    └── github_backup.py       # Nightly git commit + push at 02:00 (screen: backup)
```

Local copies (Windows, for editing):
- `C:\Users\Jennifer\super_bot_new.py`
- `C:\Users\Jennifer\crypto_bot_new.py`
- `C:\Users\Jennifer\dashboard_super.html`
- `C:\Users\Jennifer\dashboard_crypto.html`

---

## Starting and Stopping the Bots

### Start everything

```bash
# Kill existing screen sessions first
screen -S trading  -X quit 2>/dev/null
screen -S crypto   -X quit 2>/dev/null
screen -S dashboard -X quit 2>/dev/null
screen -S optimize -X quit 2>/dev/null
sleep 1

# Super bot
screen -dmS trading bash -c '
  cd /home/trading2025/trading_bot &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u super_bot.py > /tmp/super_bot.log 2>&1'

# Crypto bot
screen -dmS crypto bash -c '
  cd /home/trading2025/trading_bot/crypto &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u crypto_bot.py > /tmp/crypto_bot.log 2>&1'

# HTTP server for both dashboards
screen -dmS dashboard bash -c '
  cd /home/trading2025/trading_bot &&
  python3 -m http.server 8080'

screen -list
```

### Stop a bot

```bash
# Graceful — bot checks this file every cycle
echo '{"command":"stop"}' > /home/trading2025/trading_bot/bot_control.json

# Hard kill
screen -S trading  -X quit
screen -S crypto   -X quit
screen -S dashboard -X quit
```

### View live logs

```bash
tail -f /tmp/super_bot.log
tail -f /tmp/crypto_bot.log
```

### Attach to screen session (interactive)

```bash
screen -r trading
screen -r crypto
# Detach: Ctrl+A  D
```

### Systemd autostart (runs on every Pi reboot)

The service `trading-bots.service` starts all nine screen sessions automatically after the network is up.

```bash
# Service control
sudo systemctl start   trading-bots   # start all sessions now
sudo systemctl stop    trading-bots   # gracefully kill all sessions
sudo systemctl restart trading-bots   # full stop + start cycle
sudo systemctl status  trading-bots   # show active/inactive + last log lines

# Enable / disable autostart on boot
sudo systemctl enable  trading-bots   # already enabled — symlink in multi-user.target.wants
sudo systemctl disable trading-bots   # remove autostart

# Reload after editing the service file
sudo systemctl daemon-reload
```

**Key files:**

| File | Purpose |
|------|---------|
| `/etc/systemd/system/trading-bots.service` | Systemd unit (`Type=oneshot`, `RemainAfterExit=yes`) |
| `/home/trading2025/trading_bot/start_all.sh` | Startup script called by the service — launches all 9 screen sessions |

**Service design notes:**
- `After=network-online.target` — waits for network before starting (Alpaca/Kraken API needs it)
- `Type=oneshot` + `RemainAfterExit=yes` — script exits after launching screens; service stays `active (exited)`; all bot processes remain alive under systemd's cgroup
- `ExecStop` — `systemctl stop` sends `screen -X quit` to all eight sessions cleanly
- The old `@reboot` crontab entries have been removed; systemd is the only autostart mechanism

---

### Deploy updated code from Windows

```bash
# Syntax check before deploy
scp super_bot_new.py trading2025@trading:/tmp/sb_check.py
ssh trading2025@trading "python3 -c 'import ast; ast.parse(open(\"/tmp/sb_check.py\").read()); print(\"OK\")'"

# Deploy
scp super_bot_new.py  trading2025@trading:/home/trading2025/trading_bot/super_bot.py
scp crypto_bot_new.py trading2025@trading:/home/trading2025/trading_bot/crypto/crypto_bot.py
```

---

## Dashboard URLs

| Dashboard      | URL                                          | JSON feed                       | Screen session     |
|----------------|----------------------------------------------|---------------------------------|--------------------|
| Super Bot      | `http://<server>:8080/dashboard_super.html`  | `dashboard.json`                | `dashboard`        |
| Crypto Bot     | `http://<server>:8081/dashboard_crypto.html` | `crypto/crypto_dashboard.json`  | `dashboard_crypto` |

Each dashboard has its own HTTP server. `dashboard` serves the `trading_bot/` root on port 8080; `dashboard_crypto` serves the `trading_bot/crypto/` subdirectory on port 8081. Both auto-refresh every 30 seconds via a countdown timer. Both servers are watched by the monitor agent and restarted automatically on crash.

---

## config.py (server-side only — never commit)

```python
config = {
    "newsapi_key":        "",                    # NewsAPI.org key (optional)
    "telegram_bot_token": "...",                 # Telegram bot token
    "telegram_chat_id":   "...",                 # Your Telegram chat ID

    # Alpaca — always paper trading (paper-api.alpaca.markets)
    "alpaca_api_key":     "PKXXFFESIDJBEOR7SDRYTNIARS",
    "alpaca_secret_key":  "2VQXHnoqQ3VEncMUUaFBKau7F2Q69h2SPrd6RAHR4rU7",

    # Kraken — live trading when exchange="kraken" and demo_mode=False
    "kraken_api_key":     "",
    "kraken_secret_key":  "",

    # Switch exchange for crypto_bot only
    "exchange":   "alpaca",   # "alpaca" | "kraken"

    # False = LIVE real money (Kraken only). Alpaca is always paper.
    "demo_mode":  True,
}
```

---

## Super Bot Architecture (`super_bot.py`)

### Overview
Trades 10 sector ETFs using NLP sentiment from news/Twitter/SEC/Fed/Congress feeds plus 7 technical indicators. Runs a 10-minute main cycle. Includes real-time WebSocket price stream from Alpaca IEX for instant stop-loss/take-profit.

### Universe — Sector ETFs

| Sector   | ETF  |
|----------|------|
| energy   | XLE  |
| oil      | XOP  |
| industry | XLI  |
| steel    | SLX  |
| defense  | ITA  |
| finance  | XLF  |
| tech     | XLK  |
| gold     | GLD  |
| infra    | PAVE |
| crypto   | IBIT |

### Key Parameters

| Parameter       | Value   | Notes                          |
|-----------------|---------|--------------------------------|
| `stop_loss`     | 3.0%    | Hard stop, fires via WS or poll |
| `take_profit`   | 15.0%   | Minimum gain before trailing   |
| `trailing_stop` | 3.0%    | Pullback from peak to trigger exit |
| `max_pos`       | 15      | Max concurrent positions       |
| `pos_size`      | 5%      | Per-trade allocation of balance |
| `max_day_loss`  | 10%     | Pause new trades; process stays alive (no restart loop) |
| Cycle interval  | 600s    | Full sentiment re-analysis every 10 min |
| Intra-cycle     | every 120s | Momentum check + stop poll (if WS down) |

### Balance persistence (`super_state.json`)

Alpaca paper-trading `cash` always returns ~$100k (no real orders placed in demo). In demo mode, balance is tracked in-memory and lost on restart. Fix: `_save_state()` writes `super_state.json` after every buy, every sell, and every intra-cycle checkpoint. On startup, `_load_state()` restores the saved balance (demo only) and the day's loss baseline (all modes, date-checked so a restart doesn't carry yesterday's drawdown into today).

**State file**: `super_state.json`
```json
{"balance": 97500.0, "day_start_balance": 100000.0, "day_date": "2026-05-19"}
```

**Daily-loss halt**: when `check_day_loss()` fires, `running` is set to `False`. The main loop handles this without exiting (`if not self.running: sleep(30); continue`) so the monitor agent never sees a crash and never restarts the bot. The bot resumes automatically when `/start` is issued via Telegram.

### Exchange — Alpaca (stocks, always paper)
- REST: `https://paper-api.alpaca.markets`
- Data: `https://data.alpaca.markets`
- WebSocket: `wss://stream.data.alpaca.markets/v2/iex` (free IEX feed)
- Orders: market orders, `time_in_force: day`
- Balance: synced from `/v2/account` after each order

### Main Loop Flow

```
run()
 ├─ start_websocket()          → daemon thread, subscribes all 10 ETF tickers
 └─ while True:
     ├─ check_control()        → reads bot_control.json
     ├─ check_day_loss()       → halts if down >10%
     ├─ fetch_twitter()        → fast-path trade on hot tweets
     ├─ check_stops()          → polling fallback ONLY when ws_connected=False
     ├─ analyze()              → full sentiment cycle
     │   ├─ fetch_news()       → 17 RSS feeds
     │   ├─ fetch_twitter()    → Nitter scrape
     │   ├─ fetch_congress()   → UnusualWhales RSS + Google News
     │   └─ fetch_fear_greed() → api.alternative.me
     ├─ trade(scores)          → buy if signal strong + all 7 indicators pass
     ├─ dashboard(scores)      → print to console
     ├─ save_dashboard(scores) → write dashboard.json
     └─ for _ in range(5):     → intra-cycle (every 2 min)
         ├─ fetch_prices()     → 5-min bar momentum check
         ├─ trade(pscore)      → momentum trades
         └─ check_stops()      → only if ws_connected=False
```

### WebSocket Thread (super_bot)

```
_ws_run() [daemon thread]
 └─ WebSocketApp(wss://stream.data.alpaca.markets/v2/iex)
     ├─ on_open  → auth with Alpaca key/secret
     ├─ on_message:
     │   ├─ T=authenticated → subscribe trades: all 10 ETF tickers
     │   ├─ T=t (trade tick) → update ws_prices[symbol]
     │   │                   → call _ws_check_price(symbol, price)
     │   └─ T=error → log
     ├─ on_error → ws_connected = False
     └─ on_close → ws_connected = False, reconnect in 5s
```

---

## Crypto Bot Architecture (`crypto_bot.py`)

### Overview
Trades 11 cryptocurrencies (7 main + 4 meme) using sentiment from crypto RSS, Reddit, Whale Alert, and Fear & Greed. 2-minute polling cycle. WebSocket real-time stream when using Alpaca; REST polling when using Kraken.

### Universe

**Main** (8% position size): BTC/USD, ETH/USD, SOL/USD, XRP/USD, AVAX/USD, LINK/USD, LTC/USD  
**Meme** (3% position size): DOGE/USD, SHIB/USD, PEPE/USD, WIF/USD

### Key Parameters

| Parameter       | Value  | Notes                           |
|-----------------|--------|---------------------------------|
| `stop_loss`     | 4.0%   | Higher than stocks (crypto volatile) |
| `take_profit`   | 10.0%  | Min gain before trailing        |
| `trailing_stop` | 2.0%   | Pullback from peak to trigger   |
| `max_pos`       | 6      | Max concurrent positions        |
| `pos_size`      | 8%     | Main coins per trade            |
| `meme_size`     | 3%     | Meme coins per trade            |
| `max_day_loss`  | 10%    | Daily drawdown limit — bot sleeps until 00:30, then auto-resumes |
| Cycle interval  | ~120s  | 4 × 30s checks per full cycle   |

### Balance persistence (`crypto_state.json`)

Solves two problems unique to demo/paper mode:

1. **Balance reset on restart**: Alpaca paper-trading `cash` is always ~$100k (no real orders placed). In demo mode the bot tracks balance in-memory — after a restart this in-memory state is lost. Fix: `_save_state()` writes `crypto_state.json` after every buy, sell, and every 30s cycle. On startup, `_load_state()` restores the saved balance (demo only; live modes read from the exchange API).

2. **Crash/restart loop on daily loss**: Previously `check_day_loss()` set `running=False`, the process exited, and the monitor restarted it within 60s — creating an infinite restart loop on the same depleted balance. Fix: the bot now calls `_sleep_until_tomorrow()` which keeps the process alive (monitor sees no crash) and sleeps in 60s increments until 00:30 next day, still honouring `/stop` commands. On wake-up, `start_balance` resets to the current balance so the new day's loss counter starts fresh.

**State file**: `crypto/crypto_state.json`
```json
{"balance": 95000.0, "day_start_balance": 97000.0, "day_date": "2026-05-19"}
```

### Exchange — Alpaca (crypto paper)
- REST: `https://paper-api.alpaca.markets`
- Data: `https://data.alpaca.markets/v1beta3/crypto/us`
- WebSocket: `wss://stream.data.alpaca.markets/v1beta3/crypto/us`
- Symbol format: `BTC/USD` (with slash)
- Order symbol: `BTCUSD` (slash stripped)
- Bars: 1-hour candles, 7 days lookback

### Exchange — Kraken (live trading)
- REST: `https://api.kraken.com`
- Auth: HMAC-SHA512 (see below)
- Symbol map: `BTC/USD` → `XBTUSD`, `ETH/USD` → `ETHUSD`, etc.
- Balance key: `ZUSD` (not "USD")
- Bars: `/0/public/OHLC` with `interval=60` (minutes), drop last bar (incomplete)
- Min order quantities enforced per coin (e.g. BTC min 0.0001)
- No sandbox — preflight check with 10s countdown runs before first cycle

### Kraken Authentication

```python
def _kraken_sign(urlpath, data):
    postdata = urllib.parse.urlencode(data)
    encoded  = (str(data["nonce"]) + postdata).encode()
    message  = urlpath.encode() + hashlib.sha256(encoded).digest()
    mac      = hmac.new(base64.b64decode(KRAKEN_SECRET), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()

# nonce = str(int(time.time_ns() // 1_000_000))   # milliseconds
# Headers: "API-Key" + "API-Sign"
```

### Main Loop Flow

```
run()
 ├─ start_websocket()       → daemon thread (Alpaca only; skipped for Kraken)
 └─ while running:
     ├─ check_day_loss()
     ├─ analyze()
     │   ├─ fetch_news()        → 13 RSS feeds (CoinDesk, CoinTelegraph, Decrypt, etc.)
     │   ├─ fetch_reddit()      → r/CryptoCurrency, r/Bitcoin, r/ethereum, r/solana, r/dogecoin
     │   ├─ fetch_whale_alerts()→ Whale Alert Nitter RSS, filters $10M+ transfers
     │   └─ fetch_fear_greed()  → api.alternative.me/fng
     ├─ trade(scores)
     └─ for _ in range(4):      → every 30s
         ├─ check_stops()       → only if ws_connected=False
         └─ save_dashboard()
```

### WebSocket Thread (crypto_bot)

```
_ws_run() [daemon thread — Alpaca only]
 └─ WebSocketApp(wss://stream.data.alpaca.markets/v1beta3/crypto/us)
     ├─ on_open  → auth with Alpaca key/secret
     ├─ on_message:
     │   ├─ T=authenticated → subscribe trades: all 11 crypto symbols
     │   ├─ T=t (trade tick) → update ws_prices[symbol]
     │   │                   → call _ws_check_price(symbol, price)
     │   └─ T=error → log
     ├─ on_error → ws_connected = False
     └─ on_close → ws_connected = False, reconnect in 5s
```

---

## ADX Market Regime Detection + Weighted Scoring

Added to both bots in `get_indicators()` and `trade()`. Replaces the old binary AND-gate (all-7-must-pass) with a regime-aware weighted scoring system.

### ADX — Average Directional Index (Wilder, period=14)

Computed inside `get_indicators()` using the same `trs` (true range) already calculated for ATR:

```
+DM[i] = max(high[i] - high[i-1], 0)  if +DM > -DM  else 0
-DM[i] = max(low[i-1] - low[i],  0)   if -DM > +DM  else 0

Wilder-smoothed: TR, +DM, -DM  (initial = sum of first 14; each step = prev*(13/14) + curr)
+DI[i] = 100 * smooth_+DM[i] / smooth_TR[i]   → 0–100
-DI[i] = 100 * smooth_-DM[i] / smooth_TR[i]   → 0–100
DX[i]  = 100 * |+DI - -DI| / (+DI + -DI)      → 0–100
ADX    = Wilder MA of DX (initial = average of first 14 DX values; step = (prev*13 + dx)/14)
```

**NOTE**: ATR/+DM/-DM use `initial = sum` (Wilder's original — the factor-of-14 cancels in +DI/-DI ratio). ADX uses `initial = average` (different formula to keep ADX in 0–100 range).

Returns `"adx"` in the indicator dict.

### Market Regime Detection

Runs at the top of the buy-gate block in `trade()`:

| ADX value | Regime       | Score threshold | Position size multiplier |
|-----------|-------------|-----------------|--------------------------|
| ≥ 25      | TRENDING    | 75% of max score | 1.0× (full size)        |
| 20–24     | TRANSITIONAL | 60% of max score | 0.6× (reduced size)     |
| < 20      | RANGING     | 45% of max score | 0.4× (minimal size)     |

### Weighted Indicator Score

Replaces the binary AND-gate. Gates are weighted by trend-signal strength:

```
gate_score = RSI_ok×1.5 + MACD_ok×1.5 + ST_ok×1.5 + ICHI_ok×1.2 + MA_ok×1.0 + OBV_ok×0.8
score_pct  = gate_score / 7.5    # normalised 0–100%
```

If `score_pct < threshold` → skip (logged with regime, ADX, score%). PSAR is not a buy gate — still used as dynamic stop only.

Position size: `shares = balance × pos_size × size_mult / price` (super_bot)  
or: `shares = balance × size × size_mult / price` (crypto_bot, where `size` = `pos_size` or `meme_size`)

### Log format

```
[SKIP] XLK [TRENDING ADX=38.2 score=53%<75%] RSI=61.2 MA=above MACD=bull ST=bear OBV=down ICHI=below PSAR=bear
BUY XLK (tech) 18 @ $235.10 [TRENDING ADX=38.2 score=80% x1.0] RSI=61.2 ...
```

---

## 7 Technical Indicators

All indicators are computed from OHLCV bars (daily for super_bot, hourly for crypto_bot).  
Gates are now evaluated as a **weighted score** against an ADX regime threshold (see above) — not a binary AND-gate.

### 1. RSI — Relative Strength Index
- Period: 14 bars
- **Buy gate**: RSI < 70 (not overbought)
- Formula: `RSI = 100 - 100 / (1 + avg_gain / avg_loss)` over 14 periods
- Dashboard: shown as `RSI=xx.x` in skip log

### 2. MA20 — 20-period Simple Moving Average
- **Buy gate**: current price > MA20 (uptrend confirmation)
- Used as dynamic support level

### 3. MACD — Moving Average Convergence/Divergence
- EMA(12) − EMA(26) = MACD line
- EMA(9) of MACD = signal line
- Histogram = MACD − signal
- **Buy gate**: MACD line > signal line (bullish crossover)

### 4. Supertrend
- Period: 7 bars, multiplier: 3.0
- Uses ATR(7) to compute upper/lower bands
- Tracks trend direction: +1 = bullish, -1 = bearish
- **Buy gate**: supertrend == 1

### 5. OBV — On-Balance Volume
- Cumulative: +volume when price rises, −volume when price falls
- **Buy gate**: `obv[-1] > obv[-11]` (rising over last 10 bars)  
  OR `current_volume > avg_volume_20 × 0.5` (volume spike fallback)
- The fallback prevents false negatives from OBV drift on low-volume days

### 6. Parabolic SAR
- Acceleration factor: 0.02 start, 0.20 max
- **Buy gate**: `closes[-1] > psar` (price above SAR = bullish)
- **Dynamic stop-loss**: replaces fixed % stop for normal positions. `psar_stop` stored in position dict at entry, updated each main cycle by `_update_psar_stops()` — ratchets upward as price rises
- WS thread reads `pos["psar_stop"]` directly; closes with trigger `WS-PSAR-STOP` / `PSAR-STOP`
- Spike positions use fixed 1.5% stop instead (no `psar_stop` key)

### 7. Ichimoku Cloud
- Tenkan-sen (Conversion): `(max_high_9 + min_low_9) / 2`
- Kijun-sen (Base): `(max_high_26 + min_low_26) / 2`
- Senkou Span A (current cloud): `(Tenkan[-26] + Kijun[-26]) / 2` — calculated 26 bars ago
- Senkou Span B (current cloud): `(max_high_52[-26] + min_low_52[-26]) / 2` — 52-bar range ending 26 bars ago
- **Buy gate**: `closes[-1] > max(Span A, Span B)` — price above the cloud
- Requires **78+ bars** (52 lookback + 26 displacement). Bar fetch limits updated: super_bot daily limit 50→100, crypto_bot hourly lookback 7→14 days

---

### Computed Values (not buy gates)

#### Bollinger Bands (computed alongside MA20)
- Upper: MA20 + 2 × std20
- Lower: MA20 - 2 × std20
- Informational only — not used as a gate

#### ATR — Average True Range
- Period: 14 bars
- Formula: `TR = max(high−low, |high−prev_close|, |low−prev_close|)`
- **Used for**: Supertrend band calculation; position sizing context (shown in logs)
- Not a gate by itself

---

## Signal Sources

### Super Bot

| Source          | Feed/URL                                        | Weight  |
|-----------------|-------------------------------------------------|---------|
| BBC Business    | `feeds.bbci.co.uk/news/business/rss.xml`        | 1.0     |
| MarketWatch     | `feeds.marketwatch.com/marketwatch/topstories/` | 1.0     |
| Yahoo Finance   | `finance.yahoo.com/news/rssindex`               | 1.0     |
| CNBC            | `cnbc.com/id/100003114/device/rss/rss.html`     | 1.0     |
| WSJ Markets     | `feeds.a.dj.com/rss/RSSMarketsMain.xml`         | 1.0     |
| Bloomberg       | `feeds.bloomberg.com/markets/news.rss`          | 1.0     |
| Google News     | `news.google.com/rss/search?q=stocks+economy`  | 1.0     |
| Fed Press       | `federalreserve.gov/feeds/press_all.xml`        | 1.5×    |
| Fed Speeches    | `federalreserve.gov/feeds/speeches.xml`         | 1.5×    |
| Fed Monetary    | `federalreserve.gov/feeds/press_monetary.xml`   | 1.5×    |
| Fed Google News | `...q=federal+reserve+interest+rate`            | 1.5×    |
| SEC Form 4      | `sec.gov/cgi-bin/browse-edgar?type=4&output=atom` | 1.5×  |
| SEC Google News | `...q=SEC+insider+filing+executive+purchase`    | 1.5×    |
| UnusualWhales   | `unusualwhales.com/rss/congress`                | congress score |
| UnusualWhales   | `unusualwhales.com/rss/political`               | congress score |
| Congress Google | `...q=congress+stock+trade+disclosure`          | congress score |
| Twitter/Nitter  | realDonaldTrump, elonmusk, POTUS (Nitter scrape) | 1.5×   |
| Fear & Greed    | `api.alternative.me/fng`                        | multiplier |

**Key figures that boost score 1.3×**: Trump, Musk, Powell, Yellen, Buffett, BlackRock, Goldman, JPMorgan, Citadel, Pelosi, Dalio, Soros, Bezos, Zuckerberg, Fink, Dimon, Griffin, Icahn, Ackman, Nvidia, Microsoft, Amazon, Apple, Tesla, Vanguard, Berkshire, OpenAI, Mnuchin

**Congress VIP boost 1.8×** (vs 1.0× for unknown members): pelosi, tuberville, ossoff, collins, warren, ocasio, mcconnell, schumer, johnson, jeffries

### Crypto Bot

| Source         | Feed/URL                                          | Weight  |
|----------------|---------------------------------------------------|---------|
| CoinDesk       | `feeds.feedburner.com/CoinDesk`                   | 1.0     |
| CoinTelegraph  | `cointelegraph.com/rss`                           | 1.0     |
| Decrypt        | `decrypt.co/feed`                                 | 1.0     |
| CryptoPanic    | `cryptopanic.com/news/rss/`                       | 1.0     |
| UnusualWhales  | `unusualwhales.com/rss/congress`                  | 1.0     |
| Google BTC     | `...q=bitcoin+BTC`                                | 1.0     |
| Google ETH     | `...q=ethereum+ETH`                               | 1.0     |
| Google SOL     | `...q=solana+SOL`                                 | 1.0     |
| Google XRP     | `...q=ripple+XRP`                                 | 1.0     |
| Google DOGE    | `...q=dogecoin+DOGE`                              | 1.0     |
| Google Whale   | `...q=crypto+whale+bitcoin`                       | 1.0     |
| Google SEC     | `...q=crypto+SEC+regulation`                      | 1.0     |
| Google IBIT    | `...q=bitcoin+blackrock+etf`                      | 1.0     |
| Reddit r/CC    | hot + new                                         | 1.0/0.7 |
| Reddit r/BTC   | hot + new                                         | 1.3/0.9 |
| Reddit r/ETH   | hot + new                                         | 1.3/0.9 |
| Reddit r/SOL   | hot                                               | 1.1     |
| Reddit r/DOGE  | hot                                               | 1.1     |
| Whale Alert    | Nitter RSS — filters >$10M transfers              | ±0.4    |
| Fear & Greed   | `api.alternative.me/fng`                          | multiplier |

**Whale Alert logic**:
- `to exchange` (Coinbase/Binance/Kraken/OKX/Bybit): −0.4 (bearish, sell pressure)
- `from exchange`: +0.4 (bullish, accumulation)
- unknown wallet-to-wallet: +0.15 (weak bullish)

### Fear & Greed Multiplier (both bots)

| F&G Value | Label         | Score multiplier |
|-----------|---------------|-----------------|
| 0–25      | Extreme Fear  | 1.3× (contrarian buy) |
| 26–45     | Fear          | 1.1×            |
| 46–55     | Neutral       | 1.0×            |
| 56–75     | Greed         | 0.8×            |
| 76–100    | Extreme Greed | 0.5×            |

---

## Thread Safety Architecture

Both bots use the same pattern for concurrent WebSocket thread + main loop:

```python
self.positions_lock = threading.RLock()   # RLock not Lock — allows re-entry
```

**RLock** is required because `_ws_check_price` → `close_position` can re-enter the lock from the same WebSocket thread.

### Atomic position claiming (prevents double-close)

```python
def close_position(self, symbol, price, reason, pnl_pct):
    with self.positions_lock:
        pos = self.positions.pop(symbol, None)   # atomic — only one caller gets the position
    if pos is None:
        return   # already closed by the other thread — no-op
    # ... network calls outside the lock ...
```

### Double-checked locking on buy

```python
# Quick check (no API call)
with self.positions_lock:
    if symbol in self.positions or len(self.positions) >= self.max_pos:
        continue

ind = self.get_indicators(symbol)   # slow — outside lock

# Re-check after slow op, then commit
with self.positions_lock:
    if symbol in self.positions or len(self.positions) >= self.max_pos:
        continue
    self.positions[symbol] = { ... }
```

### Polling fallback pattern

```python
# Only run slow REST polling when WebSocket is down
if not self.ws_connected:
    self.check_stops()
```

---

## Dashboard JSON Schema

### `dashboard.json` (super_bot)

```json
{
  "time":         "2026-01-01 12:00:00",
  "mode":         "DEMO | WS✓",
  "balance":      100000.00,
  "positions": {
    "XLK": {
      "shares": 42, "entry": 230.50, "current_price": 235.10,
      "pnl_pct": 1.9, "pnl_usd": 193.0, "sector": "tech", "time": "2026-01-01 11:00"
    }
  },
  "scores":       {"energy": 1.2, "tech": 3.4, ...},
  "trades":       [{"symbol":"XLE","profit":250,"pnl_pct":2.1,"reason":"TRAIL-STOP","time":"...","sector":"energy"}],
  "total_pnl":    1340.0,
  "wins":         7,
  "total_trades": 12,
  "running":      true,
  "fear_greed":   {"value": 42, "label": "Fear"},
  "skips":        [{"symbol":"XLF","time":"11:30","rsi":72.1,"rsi_ok":false,"ma_ok":true,"macd_ok":true,"st_ok":true,"obv_ok":true,"psar_ok":true,"ichi_ok":true}],
  "congress":     {"tech": 1.2, "finance": -0.6},
  "ws_connected": true,
  "earnings":     {"XLK": {"stock": "MSFT", "date": "2026-01-28"}}
}
```

### `crypto/crypto_dashboard.json` (crypto_bot)

Same structure, with differences:
- No `wins` or `congress` fields
- `scores` keys are full symbols: `{"BTC/USD": 2.1, "ETH/USD": 0.8, ...}`
- `positions.shares` is float (crypto fractional)
- `mode`: `"DEMO | ALPACA | WS✓"` or `"LIVE | KRAKEN"`

---

## Required Python Packages

```bash
pip install requests feedparser textblob python-telegram-bot websocket-client yfinance beautifulsoup4
python -m textblob.download_corpora
```

---

## Spike Trading Strategy (crypto_bot only)

Fires an immediate buy from inside the WebSocket thread — no indicator gate, no analyze() cycle delay. Designed for millisecond reaction to sudden volume explosions.

### How it works

1. Every trade tick (`T="t"`) carries `s` = trade size. The WS message handler accumulates these into a **rolling 60-second volume window** per symbol.
2. After ≥ 10 seconds of data, `_ws_spike_check(symbol, price)` runs on every tick.
3. Accumulated volume is extrapolated to a 60s rate and compared to the **20-bar hourly average per-minute baseline** (`avg_vol_20 / 60`).
4. If `vol_rate ≥ 10× baseline` (1000% spike), a buy fires immediately inside the WS thread.
5. The window resets to zero on trigger to prevent re-firing on the same spike.

### Parameters

| Parameter     | Value | Notes                                       |
|---------------|-------|---------------------------------------------|
| `spike_size`  | 4%    | Smaller than normal trades (riskier entry)  |
| `stop_loss`   | 1.5%  | Tight — spike can reverse fast              |
| `take_profit` | 3.0%  | Quick target — 2:1 risk/reward              |
| Threshold     | 10.0× | 1000% above 20-bar avg per-minute volume    |
| Min window    | 10s   | Won't fire on <10s of accumulated data      |
| Window length | 60s   | Rolling window, resets after 60s or trigger |

### Volume baseline refresh

`_refresh_avg_vols()` runs at the start of each `analyze()` cycle (every ~10 min, main thread). Fetches 1H OHLCV for all 11 symbols, computes `avg_vol_20 / 60`, caches with 1-hour TTL. `_get_avg_vol(symbol)` is the non-blocking WS-thread lookup — returns `None` if not yet cached (spike silently skipped until first analyze completes).

### Per-position stop/take overrides

Both `_ws_check_price` and `check_stops` use:
```python
sl = pos.get("stop_loss", self.stop_loss)     # 1.5% spike / 4.0% normal
tp = pos.get("take_profit", self.take_profit) # 3.0% spike / 10.0% normal
```

Spike positions carry `"stop_loss": 1.5`, `"take_profit": 3.0`, `"spike": True` in the position dict. Normal positions carry none of these keys.

### Dashboard / logs

- Console: `SPIKE-BUY BTC/USD $104200.1 vol=4.7x avg SL=1.5% TP=3% | Bal: $9580`
- Trade history: `reason` = `WS-STOP-LOSS` or `WS-TRAIL-STOP`; `"spike": true` in JSON distinguishes from normal closes

### Limitations

- **Alpaca only** — dead code when `EXCHANGE="kraken"` (WS thread doesn't start; Kraken uses REST polling)
- **No indicator gate** — bypasses all 7 indicator gates; tight 1.5% stop is the only protection
- **Illiquid hours** — overnight/weekend tick volume is lower, making threshold easier to hit; the 1H bar baseline accounts for this

---

## Earnings Calendar (super_bot only)

Prevents buying ETF positions when a major constituent stock has an earnings announcement due within the next 2 days, or was announced yesterday (the day-after gap-risk window).

### Constituent map (`ETF_CONSTITUENTS`)

| ETF  | Top-5 constituents tracked |
|------|---------------------------|
| XLE  | XOM, CVX, COP, EOG, SLB |
| XOP  | DVN, MRO, APA, OXY, FANG |
| XLI  | GE, RTX, UNP, HON, ETN |
| SLX  | NUE, STLD, RS, CMC, X |
| ITA  | LMT, RTX, NOC, GD, BA |
| XLF  | JPM, BAC, WFC, GS, MS |
| XLK  | MSFT, AAPL, NVDA, AVGO, META |
| GLD  | *(gold bullion trust — no constituent earnings)* |
| PAVE | VMC, MLM, PWR, CARR, JCI |
| IBIT | *(Bitcoin ETF trust — no constituent earnings)* |

### How it works

1. **`_fetch_earnings()`** — runs at the start of each 10-minute outer cycle. Queries `yfinance.Ticker(stock).calendar` for all unique constituent stocks (~30 stocks). Result is a `dict[stock → date]` cached for the rest of the calendar day. On a new day the cache and alert set both reset. Defensive parsing handles both the dict and legacy DataFrame formats yfinance may return.

2. **`_get_earnings_window(etf_symbol)`** — returns `(blocked, stock, date_str)`. Blocked = True if any constituent has `−1 ≤ (earnings_date − today).days ≤ +2`.

3. **Buy gate in `trade()`** — inserted after the quick position-count check and *before* the expensive `get_indicators()` call. Logs `[SKIP] XLK Earnings MSFT 2026-01-28` and skips to next sector.

4. **`_check_held_earnings()`** — scans open positions at cycle start. If a held ETF enters the earnings window, sends a one-time Telegram alert: `⚠️ EARNINGS: XLK — Konstituent MSFT Earnings 2026-01-28 | Position gehalten (kein Autoverkauf)`. The alert fires once per position per calendar day (`_earnings_alerted` set, reset daily).

5. **Dashboard** — `save_dashboard()` adds an `"earnings"` field: a dict of ETF → `{"stock": "MSFT", "date": "2026-01-28"}` for any ETF currently in a blocked window. Empty dict when no earnings nearby.

### Notes

- **No auto-close** — existing positions are never closed due to earnings. The Telegram alert is informational only; the operator decides whether to close manually.
- **yfinance dependency** — if `yfinance` is not installed, `_fetch_earnings()` prints a warning and leaves the cache empty (all `_get_earnings_window` calls return `False` — no blocking, no alerts).
- **Performance** — the fetch runs ~30 sequential HTTP calls to Yahoo Finance. Typically completes in 10–30 seconds on a good connection. Only runs once per day (first cycle after midnight); all subsequent cycles use the in-memory cache instantly.

---

## Monitor Agent (`agents/monitor_agent.py`)

Runs as its own `monitor` screen session. Checks all three screen sessions every 60 seconds, restarts crashed bots, monitors system health, and sends a daily Telegram performance report.

### Start the monitor

```bash
screen -dmS monitor bash -c '
  cd /home/trading2025/trading_bot/agents &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u monitor_agent.py > /tmp/monitor.log 2>&1'
```

### View monitor log

```bash
tail -f /tmp/monitor.log
screen -r monitor   # attach; Ctrl+A D to detach
```

### What it watches

| Screen session     | Service                     | Risk-halt protected | Restart notes |
|--------------------|-----------------------------|---------------------|---------------|
| `trading`          | Super Bot                   | ✅ skipped on halt  | Exact CLAUDE.md cmd |
| `crypto`           | Crypto Bot                  | ✅ skipped on halt  | Exact CLAUDE.md cmd |
| `dashboard`        | HTTP server :8080           | ❌ always restarts  | `fuser -k 8080/tcp` first |
| `dashboard_crypto` | Crypto HTTP server :8081    | ❌ always restarts  | `fuser -k 8081/tcp` first |
| `risk`             | Risk Agent                  | ❌ always restarts  | `agents/risk_agent.py` |
| `optimize`         | Optimization Agent          | ❌ always restarts  | `agents/optimize_agent.py` |
| `tgrouter`         | Telegram Router             | ❌ always restarts  | `telegram_router.py` |
| `backup`           | GitHub Backup Agent         | ❌ always restarts  | `agents/github_backup.py` |

**Risk halt integration**: before restarting a crashed session, `check_bots()` checks whether `agents/risk_halt.json` exists. Sessions with `trading_only=True` (`trading`, `crypto`) are skipped — the risk agent owns those during a halt. All infrastructure sessions (`dashboard`, `dashboard_crypto`, `risk`, `optimize`, `tgrouter`, `monitor` itself) always restart regardless.

### Crash + restart flow

1. `screen -ls` checked every 60s — session missing → crash detected
2. Telegram: `🚨 CRASH: Super Bot (screen:trading) ist ausgefallen!`
3. 3s wait, then `screen -dmS trading bash -c '...'`
4. 5s wait, then verify session alive
5. Telegram: `✅ RESTART OK` or `❌ RESTART FEHLGESCHLAGEN`
6. `_crash_alerted` flag prevents duplicate crash alerts while bot is still down

### Stale dashboard alert

If either dashboard JSON is not updated in >15 minutes (bot alive but hung), sends:
`⚠️ Super Bot Dashboard seit 16 min nicht aktualisiert — Bot evtl. hängend?`

### System health thresholds

| Metric | Alert threshold | Cooldown |
|--------|-----------------|----------|
| CPU    | >85%            | 1 hour   |
| RAM    | >85%            | 1 hour   |
| Disk   | >85%            | 1 hour   |

CPU is measured with a real 0.5s sample from `/proc/stat` (not load average). RAM from `/proc/meminfo`. Disk from `df -h /`.

### Daily report (08:00)

Fires once per day at 08:00. Telegram message includes:
- Super Bot: balance, total P&L, trade count + win rate, open positions with P&L %, F&G value, JSON age
- Crypto Bot: same fields, spike positions flagged `[SPIKE]`
- System: CPU%, RAM%, disk% + free space
- Screen session status for all eight sessions (`trading`, `crypto`, `dashboard`, `dashboard_crypto`, `monitor`, `risk`, `optimize`, `tgrouter`)

### Config keys used

```python
config["telegram_bot_token"]   # same token as bots
config["telegram_chat_id"]     # same chat ID
```

No other config keys needed — reads dashboard JSON directly from disk.

---

## Risk Agent (`agents/risk_agent.py`)

Runs as its own `risk` screen session. Reads both dashboard JSONs every 30 seconds and halts both bots if combined portfolio risk exceeds configured thresholds. Resumes automatically next day.

### Start the risk agent

```bash
screen -dmS risk bash -c '
  cd /home/trading2025/trading_bot/agents &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u risk_agent.py > /tmp/risk.log 2>&1'
```

### View risk log

```bash
tail -f /tmp/risk.log
screen -r risk   # attach; Ctrl+A D to detach
```

### Thresholds

| Trigger               | Threshold | Scope                                    |
|-----------------------|-----------|------------------------------------------|
| Daily loss            | −5%       | Combined portfolio (both bots), resets midnight |
| Drawdown from peak    | −15%      | Combined all-time high, never resets     |

### Halt sequence (when threshold breached)

1. Writes `agents/risk_halt.json` → monitor_agent sees this and skips bot restarts
2. Kills `screen:crypto` immediately (hard stop)
3. Writes `{"command":"stop"}` to `bot_control.json` → super_bot graceful exit
4. Hard-kills `screen:trading` after 15 seconds if still alive
5. Sends Telegram alert with portfolio value, daily P&L %, drawdown %, peak value, resume time

### Resume (automatic, next day at 09:30 local time)

1. Deletes `risk_halt.json`
2. monitor_agent detects sessions dead on next 60s cycle and restarts both bots normally
3. Daily P&L counter resets; all-time peak preserved
4. Sends Telegram confirmation

### State files

| File                    | Purpose                                                      |
|-------------------------|--------------------------------------------------------------|
| `agents/risk_halt.json` | Exists while halted; deleted on resume. Read by monitor_agent. |
| `agents/risk_log.json`  | Persisted state: peak value, day-start value, full event history (capped 500 entries). Survives restarts. |

### Event types logged to `risk_log.json`

| Type        | When                                             |
|-------------|--------------------------------------------------|
| `START`     | Agent process starts                             |
| `DAY_START` | Midnight rollover — new day-start value recorded |
| `HALT`      | Threshold breached — bots stopped                |
| `RESUME`    | Resume time reached — halt file removed          |

### Config keys used

```python
config["telegram_bot_token"]
config["telegram_chat_id"]
```

Portfolio values read directly from `dashboard.json` and `crypto/crypto_dashboard.json`.

---

## Telegram Router (`telegram_router.py`)

Single standalone process that is the **only** caller of `getUpdates`. Previously both bots had an independent `TelegramCommands` daemon thread — because Telegram delivers each update to whichever caller wins the race, only one bot ever responded to commands. The router fixes this by centralising all polling and communicating with bots via JSON control files.

### Architecture

```
Telegram API
    │  getUpdates (single long-poll, 30s timeout)
    ▼
telegram_router.py  (screen: tgrouter)
    ├─ reads  dashboard.json              → /status, /positions, /risk
    ├─ reads  crypto/crypto_dashboard.json
    ├─ reads  agents/risk_log.json
    ├─ writes bot_control.json            → super_bot reads {"paused": true/false}
    └─ writes crypto/crypto_control.json  → crypto_bot reads {"paused": true/false}

super_bot.py    → check_control() every cycle  → reads bot_control.json
crypto_bot.py   → check_control() every cycle  → reads crypto/crypto_control.json
```

### Commands

| Command        | Action |
|----------------|--------|
| `/status`      | Both bots: balance, P&L, trades, win rate, positions count, F&G, WS status, pause state |
| `/positions`   | All open positions (Super + Crypto combined) with entry→current price and P&L |
| `/risk`        | Daily P&L %, all-time drawdown %, peak equity, halt status from `risk_log.json` |
| `/stop`        | Pause new trades on BOTH bots (writes `{"paused":true}` to both control files) |
| `/start`       | Resume new trades on BOTH bots |
| `/stop_super`  | Pause Super Bot only |
| `/start_super` | Resume Super Bot only |
| `/stop_crypto` | Pause Crypto Bot only |
| `/start_crypto`| Resume Crypto Bot only |
| `/apply`       | Show pending optimisation suggestions from `agents/optimize_results.json` — diffs current vs best params, lists expected improvement, warns about open positions |
| `/confirm`     | Apply the shown suggestions: regex-patches both bot source files in-place, restarts `trading` + `crypto` screen sessions, confirms new values. Expires after 5 min. |
| `/help`        | Show command list |

### `/apply` + `/confirm` — parameter update flow

```
/apply
 ├─ loads agents/optimize_results.json → grid_search.super/crypto.best_params
 ├─ reads current params from super_bot.py + crypto/crypto_bot.py via regex
 │    stop_loss   → self.stop_loss = X.X
 │    take_profit → self.take_profit = X.X
 │    rsi_threshold → rsi_ok = ind["rsi"] < XX
 │    st_mult     → b_ub = hl2 + X.X * st_atr[i]
 ├─ computes diff — only params with |Δ| > 0.01 are shown
 ├─ warns if open positions exist (will lose tracking after restart)
 └─ stores {ts, super:{…}, crypto:{…}} in _pending_apply (5-min TTL)

/confirm
 ├─ checks _pending_apply exists and not expired
 ├─ _apply_params_to_file() — re.sub on super_bot.py + crypto_bot.py
 ├─ restarts screen sessions: trading + crypto
 ├─ waits 10s, checks screen -list for both sessions
 └─ reports new active values + session health
```

**What is and isn't patched**: `stop_loss`, `take_profit`, `rsi_threshold`, `st_mult`. `trailing_stop` is intentionally excluded (changes exit behaviour too drastically to auto-apply).

### Control file IPC

`bot_control.json` and `crypto/crypto_control.json` are the IPC mechanism. The router reads the existing file before writing so it preserves any other fields (e.g. `{"command":"stop"}`).

Both bots call `self.check_control()` at the top of each main loop iteration:
- `"paused": true` → sets `tg_paused = True` — blocks `trade()` entry scanning; stop-loss and take-profit still fire via WebSocket and REST polling.
- `"paused": false` → clears `tg_paused`.
- `"command": "stop"` → sets `running = False` (hard stop, existing behaviour).

### Start the router

```bash
screen -dmS tgrouter bash -c '
  cd /home/trading2025/trading_bot &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u telegram_router.py > /tmp/tgrouter.log 2>&1'
```

### View log

```bash
tail -f /tmp/tgrouter.log
screen -r tgrouter   # attach; Ctrl+A D to detach
```

### Log output on startup

```
[2026-05-18 23:38:17] Telegram Router gestartet
[2026-05-18 23:38:17] Chat-ID  : 5696707457
[2026-05-18 23:38:17] Long-polling gestartet (einziger getUpdates-Aufrufer)
```

### Implementation notes

- Handles `/command@botname` format by splitting on `@` before lookup.
- `_dash_age_min(dash)` computes dashboard staleness from the `time` field — `/status` warns if >10 min old.
- `send()` chunks messages at 3800 characters for Telegram's 4096-char limit.
- All messages use HTML parse mode; `&` encoded as `&amp;`.
- Unknown commands silently ignored; messages from other `chat_id`s silently dropped.

---

## Optimization Agent (`agents/optimize_agent.py`)

Runs as its own `optimize` screen session. Wakes up every Sunday at 00:00, analyzes both bots' trade history and current skip-log snapshot, runs an 81-combo parameter grid search on recent Alpaca data, generates suggestions, sends a Telegram report, and saves results to `optimize_results.json`.

### Start the agent

```bash
screen -dmS optimize bash -c '
  cd /home/trading2025/trading_bot/agents &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u optimize_agent.py > /tmp/optimize.log 2>&1'
```

### Manual run (immediate, no Sunday wait)

```bash
cd /home/trading2025/trading_bot/agents
source /home/trading2025/trading_bot_env/bin/activate
python3 optimize_agent.py --now
```

### View log

```bash
tail -f /tmp/optimize.log
cat agents/optimize_log.txt     # full history across restarts
screen -r optimize              # attach; Ctrl+A D to detach
```

### Four analysis phases

| Phase | Description | Data source |
|-------|-------------|-------------|
| 1. Trade audit | Win rate, P&L, exit-reason breakdown per symbol | `trades_history.json` (both bots) |
| 2. Indicator block audit | Which gates block the most entries, avg RSI at skip | `dashboard.json` skip log (live snapshot) |
| 3. False-signal audit | STOP-LOSS rate per symbol (proxy for bad-entry rate) | Same trade history |
| 4. Grid search | 81-combo parameter sweep on recent market data | Alpaca daily bars (live fetch) |

### Parameter grid (81 combos per bot)

| Parameter | Super Bot values | Crypto Bot values |
|-----------|-----------------|-------------------|
| RSI threshold | 65, 70, 75 | 65, 70, 75 |
| Supertrend mult | 3.0, 3.5, 4.0 | 3.0, 3.5, 4.0 |
| Stop-loss % | 2.0, 3.0, 4.0 | 3.0, 4.0, 5.0 |
| Take-profit % | 12.0, 15.0, 20.0 | 8.0, 10.0, 15.0 |

Trailing-stop stays fixed. Scores each combo as `(avg_return×0.35 + avg_win_rate×0.45 − avg_drawdown×0.20) × trade_count_penalty`.

### Data window

- **Super Bot**: last 275 calendar days of daily ETF bars (≈189 trading days) via Alpaca IEX — all 10 ETFs fetched in one call
- **Crypto Bot**: last 220 calendar days of daily crypto bars (≈221 bars; crypto trades 7d/week) — all 9 liquid symbols
- **Warmup**: first 100 bars per symbol for indicator stabilisation; Ichimoku requires minimum 78 bars
- Data is fetched fresh each Sunday — no caching between runs

### Efficiency

All indicators pre-computed once per symbol per run (RSI, MA20, MACD, OBV, Ichimoku, PSAR, Supertrend × 3 mult values). The 81-combo grid runs in < 2 seconds for each bot (no repeated API calls during grid iteration).

### Scoring and suggestions

Best params = highest composite score across all symbols. Suggestions are generated when:
- Any grid parameter differs from current baseline by a significant margin (≥0.5% SL, ≥1.5% TP, ≥0.4 ST mult, ≥5 RSI)
- Stop-loss exit rate exceeds 35% (indicator system letting through bad entries)
- Any single indicator blocks >55% of recent skip-log entries (possible over-restriction)
- RSI at skips averages within 65–75 (threshold is borderline — raise to 75 to reduce blocking)
- Individual symbols show ≥50% stop-loss exit rate across ≥2 trades

### Output files

| File | Content |
|------|---------|
| `agents/optimize_results.json` | Full results: trade analysis, indicator block rates, grid top-5, suggestions, timestamp |
| `agents/optimize_log.txt` | Timestamped run history (appended each week) |

### Schedule

Runs at Sunday 00:00 local time (weekday == 6, hour == 0). Scheduler checks once per hour; sleeps 55 minutes between checks. If the process restarts mid-week, it recalculates time-to-next-Sunday and sleeps accordingly. The `last_run_date` guard prevents double-firing within the same Sunday.

### Config keys used

```python
config["telegram_bot_token"]
config["telegram_chat_id"]
config["alpaca_api_key"]      # needed for grid search bar fetch
config["alpaca_secret_key"]   # grid search skipped gracefully if absent
```

---

## GitHub Backup Agent (`agents/github_backup.py`)

Runs as its own `backup` screen session. Commits all source changes to a GitHub repository every night at 02:00 and sends a Telegram confirmation.

### Start the agent

```bash
screen -dmS backup bash -c '
  cd /home/trading2025/trading_bot/agents &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u github_backup.py > /tmp/backup.log 2>&1'
```

### View log

```bash
tail -f /tmp/backup.log
screen -r backup   # attach; Ctrl+A D to detach
```

### Setup — one-time steps

1. **Create a GitHub repo** (private recommended) and generate a personal access token with `repo` scope.

2. **Add to `config.py`** on the server (token embedded in URL — no SSH key needed):
   ```python
   "github_repo": "https://<token>@github.com/<user>/<repo>.git",
   ```

3. The agent reads `github_repo` from `config.py` at each 02:00 run and calls `git remote set-url origin` automatically — rotate tokens by editing `config.py` alone, no git commands needed.

4. **First push** — on the first night with `github_repo` set, the agent will push the existing initial commit plus all accumulated changes since setup.

### What is committed / excluded

| Committed | Excluded (`.gitignore`) |
|-----------|------------------------|
| All `.py` source files | `config.*` (all variants — API keys) |
| `*.html` dashboards | `super_state.json`, `crypto/crypto_state.json` |
| `start_all.sh`, `.gitignore`, `CLAUDE.md` | `bot_control.json`, `crypto/crypto_control.json` |
| `trades_history.json` (both bots) | `dashboard.json`, `crypto/crypto_dashboard.json` |
| `agents/backtest_report.txt` + `backtest_results.json` | `agents/risk_halt.json` |
| `agents/optimize_log.txt` + `optimize_results.json` | `*.log`, `*.save`, `*.swp`, `__pycache__/` |
| `agents/risk_log.json` | |

### Behaviour

- **No changes**: if `git status --porcelain` is empty, no commit is created (silent skip).
- **Push skipped**: if `github_repo` is not yet in `config.py`, the agent commits locally but skips the push and logs a reminder.
- **Branch**: `main` (renamed from `master` on initialisation).
- **Telegram**: `✅ GitHub Backup OK — 2026-05-20 02:00` on success; `❌ GitHub Backup FEHLER` with details on any failure.

### Git repo state

```
/home/trading2025/trading_bot/.git   # initialised 2026-05-19
Branch: main
Initial commit: 37d16a7
```

---

## Backtest Agent (`agents/backtest_agent.py`)

Downloads full-year 2024 historical data from Alpaca and simulates both bots with current indicator settings. Tests indicator gates in isolation (sentiment assumed bullish).

### Run the backtest

```bash
cd /home/trading2025/trading_bot/agents
source /home/trading2025/trading_bot_env/bin/activate

python3 backtest_agent.py           # full year 2024 (~3 min)
python3 backtest_agent.py --quick   # Q1 2024 only (fast sanity check)
```

### 2024 full-year results (last run)

| | Super Bot (ETFs) | Crypto Bot |
|---|---|---|
| **Return** | +18.51% | +279.98% |
| **Win rate** | 91.5% | 58.3% |
| **Max drawdown** | −0.55% | −2.23% |
| **Profit factor** | 12.22 | 5.38 |
| **Total trades** | 152 | 300 |

**Combined:** $110,000 → $156,511 (+42.3%) across 452 trades at 69.5% win rate.

Note: PEPE/USD and WIF/USD had no Alpaca data for 2024. Sentiment assumed bullish — live results will differ.

Output files: `agents/backtest_results.json` (full data) · `agents/backtest_report.txt` (readable summary)

---

## TODO / Planned Improvements

- [x] **Backtesting Agent** — `agents/backtest_agent.py` — 2024 full-year results: +18.5% ETFs, +280% crypto
- [x] **Risk Agent** — `agents/risk_agent.py` — daily −5% / drawdown −15% halt, auto-resume 09:30
- [x] **Optimierung Agent** — `agents/optimize_agent.py` — 81-combo weekly grid search (RSI · ST-mult · SL · TP) on live Alpaca data; indicator block analysis; Telegram report every Sunday 00:00
- [x] **Kraken WebSocket** (`wss://ws.kraken.com`) — `_kraken_ws_run/on_open/on_message()` daemon thread; public trade channel (no auth); `KRAKEN_WS_PAIR_MAP` maps internal symbols to WS pair names (BTC/USD→XBT/USD etc.); `KRAKEN_WS_REVERSE` for reverse lookup; `start_websocket()` now branches on EXCHANGE: alpaca→Alpaca WS, kraken→Kraken WS; trade ticks update `ws_prices` and call `_ws_check_price()` same as Alpaca; spike detection disabled for Kraken (volume format incompatible); activates automatically when `"exchange": "kraken"` set in config.py
- [x] **GitHub Backup** — `agents/github_backup.py` nightly at 02:00; git repo initialised on server (branch `main`); `.gitignore` excludes all secrets (`config.*`), state files, live feeds; push activates when `"github_repo"` key is added to `config.py`
- [x] **Telegram Steuerung** — `telegram_router.py` standalone router (single `getUpdates` caller) fixes race condition where two bots polled the same token; communicates via `bot_control.json` / `crypto/crypto_control.json`; adds `/stop_super`, `/stop_crypto`, `/start_super`, `/start_crypto` per-bot controls
- [x] **Telegram /apply + /confirm** — reads `optimize_results.json`, diffs current vs recommended params, patches both bot source files in-place via regex (`stop_loss`, `take_profit`, `rsi_threshold`, `st_mult`), restarts bots; 5-minute confirmation timeout; warns if open positions exist
- [x] **Earnings Calendar** — `ETF_CONSTITUENTS` dict maps each ETF to top-5 constituent stocks; `_fetch_earnings()` fetches yfinance `.calendar` daily (cached); buy gate skips ETF if any constituent has earnings within −1/+2 days; `_check_held_earnings()` sends one-time Telegram alert per held position; `earnings` field added to `dashboard.json`
- [x] **ADX Market Regime Detection + Weighted Scoring** — ADX(14) added to `get_indicators()` both bots; `trade()` replaces binary AND-gate with regime-aware weighted score (RSI×1.5 + MACD×1.5 + ST×1.5 + ICHI×1.2 + MA×1.0 + OBV×0.8 = max 7.5); TRENDING(ADX≥25)→75% threshold + 1.0× size, TRANSITIONAL(20-24)→60% + 0.6×, RANGING(<20)→45% + 0.4×; BUY/SKIP logs show regime+ADX+score
- [x] **ATR-basiertes Position Sizing** — `trade()` both bots: `shares = min(risk_budget/atr_risk, max_pos_cap)` where `risk_budget = balance × 1%` and `atr_risk = ATR × 2`; keeps dollar-risk per trade constant at ~1% of capital regardless of volatility; capped by `pos_size × size_mult × balance`; BUY log shows `risk=$X` (actual $ at risk)
- [x] **VADER Sentiment** — replaces TextBlob in both bots; module-level `_sentiment(text)` helper tries `vaderSentiment.SentimentIntensityAnalyzer` first (compound score), falls back to `TextBlob.sentiment.polarity` if not installed; both return [-1,+1]; VADER is tuned for short financial text (handles caps, negations, punctuation, booster words better than TextBlob); install: `pip install vaderSentiment`; startup log: `[SENTIMENT] VADER geladen`
- [x] **Multi-Timeframe HTF Filter** — `_get_htf_trend(symbol)` method on both bots; super_bot: Alpaca weekly bars, price > MA10(weekly) = bullish; crypto_bot: Alpaca daily bars, price > MA20(daily) = bullish; cached 30 min (super) / 10 min (crypto); called in `trade()` after `get_indicators()`, before scoring; HTF bearish → hard skip `[SKIP] XLK HTF=bear`; neutral (True) on API error or insufficient data so trades aren't blocked by connectivity issues
- [x] **CMF (Chaikin Money Flow)** — replaces OBV as the volume gate in both bots; computed in `get_indicators()` from existing OHLCV: `MFM=(2C−H−L)/(H−L)`, `CMF=Σ(MFM×V,20)/Σ(V,20)`; bounded [−1,+1], gate: `cmf_ok = cmf > 0`; OBV still computed (kept for reference) but `cmf_ok×0.8` replaces `obv_ok×0.8` in weighted gate score; `"cmf"` added to indicator dict and shown in BUY/SKIP logs
- [x] **Korrelations-Management** — `_pearson(a, b)` static method computes Pearson correlation of daily/hourly returns; `_check_correlation(symbol)` compares candidate vs all open positions using `_bar_cache` (last 20 closes cached by `get_indicators()` — zero extra API calls); in `trade()` after HTF check: if max correlation > 0.85 → skip with `[SKIP] XOP Korrelation=0.92 zu XLE`; applies to both bots; threshold 0.85 allows moderate correlation (e.g. BTC+ETH≈0.80) but blocks near-duplicate exposures (e.g. XLE+XOP≈0.95)

---

## Known Gotchas

**Kraken symbol format**: BTC is `XBTUSD` not `BTCUSD`. Response key may be long-form (`XXBTZUSD`). Use `next(v for k, v in result.items() if k != "last")` to extract OHLC data.

**Kraken balance key**: USD balance is stored as `ZUSD` in the API response, not `USD`.

**Kraken OHLC last bar**: The last bar in the response is always incomplete (current candle). Always slice `raw[:-1]` before computing indicators.

**Alpaca paper URL is permanent**: `ALPACA_BASE_URL = "https://paper-api.alpaca.markets"` — hardcoded, never changes. `demo_mode=False` only affects Kraken.

**WebSocket auth 402 in demo**: Expected if Alpaca keys are absent or wrong tier. Bot logs `[WS] Error: ...` and retries every 5s. Main loop is unblocked — not a fatal error.

**`pkill -f super_bot.py` kills SSH session**: Kills the entire process group including the terminal. Use `screen -S trading -X quit` instead.

**Python stdout buffering**: Always launch with `PYTHONUNBUFFERED=1 python3 -u` inside screen or log files will appear empty.

**OBV bounds guard**: `obv[-11]` will crash if bars < 12. Guard: `(len(obv) > 11 and obv[-1] > obv[-11]) or volumes[-1] > avg_vol_20 * 0.5`
