#!/usr/bin/env python3
"""Sammelt dYdX-Orderbuch-Imbalance + Mid-Preis fuer den Praediktions-Test.

Read-only, kein Handel, kein Konto. Schreibt alle POLL_SEC eine Zeile je Markt
nach dex/../dydx/imbalance_log.csv. Ausgewertet wird spaeter mit
dydx_imbalance_eval.py (Vorwaertsrendite je Imbalance-Bucket).

Warum sammeln statt backtesten: Orderbuch-Momentaufnahmen sind historisch nicht
abrufbar — Imbalance laesst sich NUR vorwaerts messen.
"""
import os, sys, csv, json, time, urllib.request
from datetime import datetime, timezone

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)

IDX = "https://indexer.dydx.trade/v4"
MARKETS = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD"]
POLL_SEC = 15
OUT_DIR = os.path.join(BASE, "dydx")
LOG = os.path.join(OUT_DIR, "imbalance_log.csv")
HB = os.path.join(OUT_DIR, "heartbeat.json")
COLS = ["time", "market", "mid", "spread_bps",
        "imb1", "imb5", "imb10", "bid_depth10", "ask_depth10"]


def get(path, timeout=10):
    req = urllib.request.Request(IDX + path, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, path)


def notional(levels, n):
    return sum(float(x["price"]) * float(x["size"]) for x in levels[:n])


def snapshot(market):
    ob = get("/orderbooks/perpetualMarket/%s" % market)
    bids, asks = ob.get("bids") or [], ob.get("asks") or []
    if not bids or not asks:
        return None
    bb, ba = float(bids[0]["price"]), float(asks[0]["price"])
    mid = (bb + ba) / 2
    if mid <= 0 or ba < bb:
        return None
    row = {"time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
           "market": market, "mid": "%.8f" % mid,
           "spread_bps": "%.3f" % ((ba - bb) / mid * 10000)}
    for n in (1, 5, 10):
        b, a = notional(bids, n), notional(asks, n)
        row["imb%d" % n] = "%.5f" % ((b - a) / (b + a)) if (b + a) else "0"
    row["bid_depth10"] = "%.2f" % notional(bids, 10)
    row["ask_depth10"] = "%.2f" % notional(asks, 10)
    return row


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    if not os.path.exists(LOG):
        with open(LOG, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(COLS)
    n = 0
    errs = 0
    while True:
        rows = []
        for m in MARKETS:
            try:
                r = snapshot(m)
                if r:
                    rows.append([r[c] for c in COLS])
            except Exception as e:
                errs += 1
                if errs % 20 == 1:
                    print("[DYDX-ERR] %s %s" % (m, str(e)[:70]), flush=True)
            time.sleep(0.3)
        if rows:
            with open(LOG, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows(rows)
            n += len(rows)
        _atomic(HB, json.dumps({"time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "rows": n, "errors": errs,
                                "markets": len(MARKETS)}))
        if n % 100 < len(MARKETS):
            print("[DYDX] %d Zeilen gesammelt, %d Fehler" % (n, errs), flush=True)
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    try:
        import health
        if health.acquire_singleton("dydx_collect") is None:
            print("[SINGLETON] dydx_collect laeuft bereits — Ende.")
            raise SystemExit(0)
        health.log("dydx_collect", "START", "")
    except SystemExit:
        raise
    except Exception as e:
        print("[SINGLETON] health nicht verfuegbar:", e)
    main()
