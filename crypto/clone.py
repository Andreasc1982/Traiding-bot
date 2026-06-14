#!/usr/bin/env python3
"""
Clone-Bot — duenne Strategie-Variante, liest ALLE Marktdaten aus dem Gateway
(/dev/shm/crypto_gw) statt selbst zu Alpaca zu verbinden. Alle Clones sehen
identische Daten -> fairer Vergleich. Demo only (in-memory Balance, keine
echten Orders), eigene State/Dashboard/Trades-Dateien, Telegram aus.

Varianten:
  A_baseline     : Momentum, MIT (Gateway-)Spikes, Memes, normale Schwelle
  B_nospikes     : Momentum, OHNE Spikes
  C_conservative : Momentum, OHNE Spikes, OHNE Memes, strenger Einstieg
  D_contrarian   : Mean-Reversion — kauft oversold (RSI<35 + am unteren BB) in Angst

Usage: python3 clone.py <A_baseline|B_nospikes|C_conservative|D_contrarian>
"""
import os, sys, json, time, threading
from datetime import datetime

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "crypto"))

import crypto_bot
from crypto_bot import CryptoBot, CRYPTO_MAIN, CRYPTO_MEME

SHM       = "/dev/shm/crypto_gw"
CLONE_DIR = os.path.join(BASE, "crypto", "clones")
os.makedirs(CLONE_DIR, exist_ok=True)

START_BALANCE = 5000.0    # entspricht dem echten Kapital-Maximum -> realistische Zahlen
                          # (alle Clones gleich -> fairer %-Vergleich bleibt erhalten)

VARIANTS = {
    "A_baseline":     {"spikes": True,  "memes": True,  "contrarian": False, "score_min": 0.1, "port": 8092},
    "B_nospikes":     {"spikes": False, "memes": True,  "contrarian": False, "score_min": 0.1, "port": 8093},
    "C_conservative": {"spikes": False, "memes": False, "contrarian": False, "score_min": 0.5, "port": 8094},
    "D_contrarian":   {"spikes": False, "memes": True,  "contrarian": True,  "score_min": 0.1, "port": 8095},
}


def _read_shm(name, default=None):
    try:
        with open(os.path.join(SHM, name)) as f:
            return json.load(f)
    except Exception:
        return default


class CloneBot(CryptoBot):
    def __init__(self, variant):
        if variant not in VARIANTS:
            raise SystemExit("Unbekannte Variante: " + variant)
        self.variant = variant
        cfg = VARIANTS[variant]
        self.cfg = cfg
        state_p = os.path.join(CLONE_DIR, variant + "_state.json")
        had_state = os.path.exists(state_p)
        super().__init__(
            state_path  =state_p,
            dash_path   =os.path.join(CLONE_DIR, variant + "_dashboard.json"),
            trades_path =os.path.join(CLONE_DIR, variant + "_trades.json"),
            control_path=os.path.join(CLONE_DIR, variant + "_control.json"),
        )
        # Fresh clone (no prior state) starts at the fixed equal balance
        if not had_state:
            self.balance = START_BALANCE
            self.start_balance = START_BALANCE
        # Variant tuning ------------------------------------------------------
        if not cfg["memes"]:
            self.excluded_symbols = set(self.excluded_symbols) | set(CRYPTO_MEME)
        self._entry_score_min = cfg["score_min"]
        self._consumed_spikes = set()
        print("[CLONE-" + variant + "] init | spikes=" + str(cfg["spikes"]) +
              " memes=" + str(cfg["memes"]) + " contrarian=" + str(cfg["contrarian"]) +
              " score_min=" + str(cfg["score_min"]))

    # ── Telegram aus ─────────────────────────────────────────────────────────
    def send(self, msg):
        print("[CLONE-" + self.variant + "][TG] " + msg)

    # ── Marktdaten aus dem Gateway statt eigenem WS ──────────────────────────
    def start_websocket(self):
        threading.Thread(target=self._shm_reader, daemon=True, name="shm-reader").start()
        print("[CLONE-" + self.variant + "] liest Marktdaten aus " + SHM)

    def _shm_reader(self):
        """Replaces the WS thread: pull prices from gateway every 1s, run stop
        checks on held positions, and (variant A) consume spike signals."""
        while self.running:
            try:
                prices = _read_shm("prices.json", {})
                if prices:
                    self.ws_prices.update({k: float(v) for k, v in prices.items()})
                    self.ws_connected = True
                    with self.positions_lock:
                        held = list(self.positions.keys())
                    for sym in held:
                        p = self.ws_prices.get(sym)
                        if p:
                            self._ws_check_price(sym, p)
                    if self.cfg["spikes"]:
                        self._consume_spikes()
                else:
                    self.ws_connected = False
            except Exception as e:
                print("[CLONE-READER] " + str(e))
            time.sleep(1)

    # gateway has no WS in REST mode -> spikes.json absent -> no-op (A==B until WS)
    def _consume_spikes(self):
        spikes = _read_shm("spikes.json", {})
        if not spikes:
            return
        for sym, ev in spikes.items():
            key = sym + ":" + str(ev.get("ts"))
            if key in self._consumed_spikes:
                continue
            self._consumed_spikes.add(key)
            if time.time() - ev.get("ts", 0) > 30:    # only fresh spikes
                continue
            if sym in self.excluded_symbols:
                continue
            price = self.ws_prices.get(sym) or ev.get("price")
            if price:
                self._spike_buy(sym, float(price), ev.get("ratio", 0))

    def _spike_buy(self, symbol, price, ratio):
        """Mirror of base spike buy (fee-aware demo) — clone has no tick stream,
        so the gateway signals the spike and the clone executes it."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self._spike_count_date != today:
            self._spike_count_date = today
            self._spike_count = 0
        if self._spike_count >= self.spike_max_day:
            return
        if time.time() - self._spike_last.get(symbol, 0) < self.spike_cooldown:
            return
        with self.positions_lock:
            if symbol in self.positions or len(self.positions) >= self.max_pos:
                return
            bal    = self.balance
            shares = (bal * self.spike_size) / price
            if shares * price < 1:
                return
            fill   = price * (1 + self.sim_slip) if self.demo else price
            fee_in = shares * fill * self.sim_fee if self.demo else 0.0
            self.balance -= shares * fill + fee_in
            self._spike_count += 1
            self._spike_last[symbol] = time.time()
            self.positions[symbol] = {
                "shares": shares, "entry": fill, "fee_in": round(fee_in, 6),
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"), "highest": fill,
                "stop_loss": 1.5, "take_profit": 3.0, "spike": True,
            }
        self._save_state()
        print("[CLONE-" + self.variant + "] SPIKE-BUY " + symbol + " $" + str(round(price, 4)) +
              " vol=" + str(round(ratio, 1)) + "x | Bal $" + str(round(self.balance, 0)))

    # ── Sentiment-Scores + F&G aus dem Gateway ───────────────────────────────
    def analyze(self):
        scores = _read_shm("scores.json", {s: 0.0 for s in CRYPTO_MAIN + CRYPTO_MEME})
        fg = _read_shm("fear_greed.json", None)
        if fg:
            self.last_fg = fg
        return scores

    # ── Indikatoren aus dem Gateway ──────────────────────────────────────────
    def get_indicators(self, symbol):
        inds = _read_shm("indicators.json", {})
        return inds.get(symbol)

    # ── HTF/Korrelation: Gateway liefert keine Bar-Historie -> neutral ───────
    # (alle Clones gleich -> Vergleich bleibt fair; Korrelations-Filter aus)
    def _get_htf_trend(self, symbol):
        return True

    def _check_correlation(self, symbol):
        return 0.0, None

    # ── Entscheidung: Momentum (Basis) ODER Contrarian ───────────────────────
    def trade(self, scores):
        if self.cfg["contrarian"]:
            self._contrarian_trade(scores)
        else:
            super().trade(scores)

    def _contrarian_trade(self, scores):
        """Mean-Reversion: kauft die am staerksten ueberverkauften Coins
        (RSI<35, Preis am/unter unterem Bollinger-Band) in Angst-Phasen."""
        if self.tg_paused:
            return
        fg = self.last_fg.get("value", 50)
        if fg > 55:                       # nur in Angst/Neutral kaufen, nicht in Gier
            print("[CLONE-D] F&G=" + str(fg) + " > 55 (Gier) — Contrarian wartet")
            return
        dd_mult, dd_zone, dd_allow_meme = self._get_drawdown_mult()
        if dd_mult == 0.0 or self._btc_crash_mode:
            return

        universe = list(CRYPTO_MAIN) + (list(CRYPTO_MEME) if dd_allow_meme else [])
        candidates = []
        for sym in universe:
            if sym in self.excluded_symbols:
                continue
            with self.positions_lock:
                if sym in self.positions or len(self.positions) >= self.max_pos:
                    continue
            if time.time() - self._sl_cooldown.get(sym, 0) < 5400:
                continue
            ind = self.get_indicators(sym)
            if not ind:
                continue
            rsi      = ind.get("rsi", 50)
            price    = ind.get("price") or self.ws_prices.get(sym)
            bb_lower = ind.get("bb_lower")
            if price and bb_lower and rsi < 35 and price <= bb_lower * 1.02:
                candidates.append((sym, rsi, ind, float(price)))

        candidates.sort(key=lambda x: x[1])     # most oversold first
        for sym, rsi, ind, price in candidates[:3]:
            with self.positions_lock:
                if sym in self.positions or len(self.positions) >= self.max_pos:
                    continue
                is_meme = sym in CRYPTO_MEME
                size    = self.meme_size if is_meme else self.pos_size
                atr     = ind.get("atr", 0) or (price * 0.02)
                risk_budget = self.balance * 0.01
                atr_shares  = risk_budget / (atr * 2) if atr > 0 else 0
                max_shares  = (self.balance * size * dd_mult) / price
                shares = min(atr_shares, max_shares) if atr_shares > 0 else max_shares
                if shares * price < 1:
                    continue
                fill   = price * (1 + self.sim_slip) if self.demo else price
                fee_in = shares * fill * self.sim_fee if self.demo else 0.0
                self.balance -= shares * fill + fee_in
                self.positions[sym] = {
                    "shares": shares, "entry": fill, "fee_in": round(fee_in, 6),
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M"), "highest": fill,
                    "stop_loss": self.stop_loss, "take_profit": 6.0,   # wider TP for mean-reversion
                    "contrarian": True,
                }
            self._save_state()
            print("[CLONE-D] CONTRARIAN-BUY " + sym + " RSI=" + str(rsi) +
                  " $" + str(round(price, 6)) + " | Bal $" + str(round(self.balance, 0)))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python3 clone.py <variant>")
    CloneBot(sys.argv[1]).run()
