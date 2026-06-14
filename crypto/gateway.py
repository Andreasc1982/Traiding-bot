#!/usr/bin/env python3
"""
Market-Data Gateway — EINE Datenquelle fuer alle Clone-Bots.

Reuses the existing CryptoBot data pipeline (WebSocket prices + sentiment
scores + indicators) and publishes everything to /dev/shm/crypto_gw/ as
atomic JSON files. The clone bots READ from there instead of each opening
their own Alpaca connection — that solves the WS connection-limit problem
and guarantees every clone sees IDENTICAL data (fair comparison).

The gateway does NOT trade, does NOT touch the live bots' state/dashboards.

Account:
  - If config has alpaca_gw_api_key / alpaca_gw_secret_key  -> use that
    (a SEPARATE Alpaca paper account, so the live super/crypto bots keep
     their own WS on the main account untouched).
  - Otherwise falls back to the main account in REST-only plumbing mode
    (for testing the /dev/shm pipe without a WS conflict).
"""
import os, sys, json, time, threading

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "crypto"))

import crypto_bot
from crypto_bot import CryptoBot, CRYPTO_MAIN, CRYPTO_MEME

try:
    from config import config
except ImportError:
    config = {}

SHM = "/dev/shm/crypto_gw"
os.makedirs(SHM, exist_ok=True)

ALL_SYMBOLS = CRYPTO_MAIN + CRYPTO_MEME

# ── Separate gateway account (keeps live bots' WS untouched) ──────────────────
GW_KEY    = config.get("alpaca_gw_api_key", "")
GW_SECRET = config.get("alpaca_gw_secret_key", "")
USE_WS    = bool(GW_KEY and GW_SECRET)
if USE_WS:
    # Patch module globals BEFORE instantiating so the WS auth + REST headers
    # use the gateway account, not the main one.
    crypto_bot.ALPACA_API_KEY    = GW_KEY
    crypto_bot.ALPACA_SECRET_KEY = GW_SECRET


def _publish(name, obj):
    """Atomic write to /dev/shm (tmp + rename) so readers never see a half file."""
    tmp = os.path.join(SHM, name + ".tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(obj, f)
        os.replace(tmp, os.path.join(SHM, name))
    except Exception as e:
        print("[GW-PUBLISH] " + name + ": " + str(e))


class Gateway(CryptoBot):
    """A CryptoBot that publishes its data pipeline instead of trading."""

    def __init__(self):
        super().__init__()
        # Gateway uses the patched (gateway) account credentials already.
        self.alpaca_headers = {
            "APCA-API-KEY-ID":     crypto_bot.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": crypto_bot.ALPACA_SECRET_KEY,
        }

    def _publish_prices_loop(self):
        """Push the latest WS prices every second (high frequency, small file)."""
        while True:
            try:
                _publish("prices.json", dict(self.ws_prices))
            except Exception as e:
                print("[GW-PRICES] " + str(e))
            time.sleep(1)

    def _rest_price_poll_loop(self):
        """Plumbing-test fallback: poll a few prices via REST when no WS account.
        Slow on purpose (REST rate limits) — proves the pipe, not for production."""
        while True:
            prices = {}
            for sym in ALL_SYMBOLS:
                p = self.get_price(sym)
                if p:
                    prices[sym] = p
            self.ws_prices.update(prices)
            _publish("prices.json", dict(self.ws_prices))
            print("[GW-REST] " + str(len(prices)) + " Preise gepollt (Plumbing-Modus)")
            time.sleep(15)

    def run(self):
        mode = "WS (eigenes Konto)" if USE_WS else "REST-Plumbing (Hauptkonto)"
        print("=" * 55)
        print("  MARKET-DATA GATEWAY gestartet")
        print("  Modus     : " + mode)
        print("  Publiziert: " + SHM + "/{prices,scores,indicators,fear_greed}.json")
        print("  Symbole   : " + str(len(ALL_SYMBOLS)))
        print("=" * 55)
        _publish("status.json", {"mode": mode, "started": time.time(), "symbols": ALL_SYMBOLS})

        if USE_WS:
            self.start_websocket()                       # the ONE WS connection
            threading.Thread(target=self._publish_prices_loop,
                             daemon=True, name="gw-prices").start()
        else:
            threading.Thread(target=self._rest_price_poll_loop,
                             daemon=True, name="gw-rest").start()

        # On-chain background scores (same as the live bot)
        threading.Thread(target=self._onchain_refresh_run,
                         daemon=True, name="gw-onchain").start()

        # Main loop: heavy shared work ONCE — sentiment scores + indicators
        cycle = 0
        while True:
            try:
                cycle += 1
                scores = self.analyze()                  # news/reddit/whale/onchain/F&G
                _publish("scores.json", scores)
                _publish("fear_greed.json", self.last_fg)

                inds = {}
                for sym in ALL_SYMBOLS:
                    try:
                        ind = self.get_indicators(sym)   # bars + indicators
                        if ind:
                            inds[sym] = ind
                    except Exception as e:
                        print("[GW-IND] " + sym + ": " + str(e))
                _publish("indicators.json", inds)
                _publish("heartbeat.json", {"cycle": cycle, "ts": time.time(),
                                            "ws": self.ws_connected,
                                            "prices": len(self.ws_prices),
                                            "indicators": len(inds)})
                print("[GW] Zyklus " + str(cycle) + " | Scores+Indikatoren publiziert | "
                      + str(len(inds)) + " Indikatoren | WS=" + str(self.ws_connected))
                time.sleep(120)
            except Exception as e:
                print("[GW-LOOP] " + str(e))
                time.sleep(30)


if __name__ == "__main__":
    Gateway().run()
