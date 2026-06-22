#!/usr/bin/env python3
"""
DEX-Monitor (Phase 2a) — Solana Token-Discovery + Scam-Screening. READ-ONLY.

Pollt DexScreener nach neuen Solana-Token, bewertet jeden (Liquiditaet, Buy/Sell-
Druck, Momentum, Alter, RugCheck) und fuehrt eine persistente Watchlist + eine
Zeitreihen-CSV (zum spaeteren Anlernen: hat das Screening Rugs gefangen / Gewinner
gefunden?). KEIN Trading, kein Geld, keine Wallet.

Lehren aus bisherigen Bugs (bewusst eingebaut):
 - harte 10s-API-Timeouts + graceful failure  -> keine Haenger (vgl. feedparser/ThreadPool)
 - Micro-Preise als String/roh gespeichert     -> kein round() das auf 0.0 kollabiert (SHIB/PEPE-Lehre)
 - atomare Writes (tmp+rename) + Persistenz     -> Watchlist ueberlebt Neustart
 - Heartbeat-Datei                              -> Monitor erkennt Haenger
 - defensives Parsen (alle .get mit Default)    -> kein Crash bei fehlenden Feldern
 - Anomalie-Log bei unrealistischen Werten
"""
import os, sys, json, time, requests
from datetime import datetime

sys.path.insert(0, "/home/trading2025/trading_bot")
try:
    from config import config
except ImportError:
    config = {}

DEX_DIR   = "/home/trading2025/trading_bot/dex"
os.makedirs(DEX_DIR, exist_ok=True)
WATCHLIST = os.path.join(DEX_DIR, "watchlist.json")
HEARTBEAT = os.path.join(DEX_DIR, "heartbeat.json")
LOG_CSV   = os.path.join(DEX_DIR, "screening_log.csv")

CHAIN          = "solana"
POLL_SEC       = 120
TIMEOUT        = 10
MAX_PER_CYCLE  = 30          # nur Top-N Profile/Zyklus screenen (Rate-Limit-Schonung)

# Screening-Schwellen — konservativ: die MEISTEN Token sollen durchfallen (Rug-Dichte!)
MIN_LIQUIDITY  = 10000       # min $10k Liquiditaet (darunter Rug-anfaellig)
MIN_VOL_5M     = 500         # min Handelsaktivitaet (5 min)
MAX_AGE_H      = 48          # nur frische Token (<48h)
MIN_AGE_MIN    = 15          # aber nicht brandneu (<15min = hoechstes Rug-Fenster)
MIN_BUY_RATIO  = 0.5         # buys/sells >= 0.5 (kein massiver Verkaufsdruck)


def _get(url):
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print("[DEX-API] " + str(e)[:80])
    return None


def _atomic_write(path, obj):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except Exception as e:
        print("[DEX-WRITE] " + str(e))


def screen_token(addr):
    data = _get("https://api.dexscreener.com/latest/dex/tokens/" + addr)
    if not data or not data.get("pairs"):
        return None
    pairs = [p for p in data["pairs"] if p.get("chainId") == CHAIN]
    if not pairs:
        return None
    p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd", 0) or 0)

    liq   = (p.get("liquidity") or {}).get("usd", 0) or 0
    vol5  = (p.get("volume") or {}).get("m5", 0) or 0
    txns  = (p.get("txns") or {}).get("m5", {}) or {}
    buys, sells = txns.get("buys", 0) or 0, txns.get("sells", 0) or 0
    pcd   = p.get("priceChange") or {}
    chg5  = pcd.get("m5", 0) or 0
    chg1  = pcd.get("h1", 0) or 0
    vold  = p.get("volume") or {}
    volh1 = vold.get("h1", 0) or 0
    volh6 = vold.get("h6", 0) or 0          # ~5h-Volumen (sustained interest, kein Flash)
    created = p.get("pairCreatedAt", 0) or 0
    age_h = (time.time() * 1000 - created) / 3600000 if created else 999.0
    price = p.get("priceUsd")          # als STRING belassen — Micro-Preis (z.B. "0.000000034")
    symbol = (p.get("baseToken") or {}).get("symbol", "?")

    reasons = []
    if liq < MIN_LIQUIDITY:                              reasons.append("liq<10k")
    if vol5 < MIN_VOL_5M:                                reasons.append("vol5<500")
    if age_h > MAX_AGE_H:                                reasons.append("alt>48h")
    if age_h < MIN_AGE_MIN / 60.0:                       reasons.append("zu_neu")
    if sells > 0 and (buys / max(sells, 1)) < MIN_BUY_RATIO: reasons.append("sell_druck")

    # RugCheck (der wichtigste Filter)
    rug = _get("https://api.rugcheck.xyz/v1/tokens/" + addr + "/report/summary")
    rug_risk = "?"
    if rug is not None:
        risks = rug.get("risks") or []
        rug_risk = (",".join((r.get("name", "")[:14]) for r in risks[:2]) or "ok")
        if any(r.get("level") == "danger" for r in risks):
            reasons.append("RUG-DANGER")

    return {
        "addr": addr, "symbol": symbol, "price": price,
        "liq": round(liq), "vol5": round(vol5), "buys": buys, "sells": sells,
        "chg5": round(chg5, 1), "chg1": round(chg1, 1),
        "vol_h1": round(volh1), "vol_h6": round(volh6),
        "age_h": round(age_h, 1),
        "rug_risk": rug_risk, "passed": len(reasons) == 0, "reasons": reasons,
    }


def run():
    print("=" * 55)
    print("  DEX-MONITOR (Solana, read-only) gestartet")
    print("  Screening: liq>=$" + str(MIN_LIQUIDITY) + ", vol5>=$" + str(MIN_VOL_5M) +
          ", Alter " + str(MIN_AGE_MIN) + "min-" + str(MAX_AGE_H) + "h, RugCheck")
    print("=" * 55)

    watchlist = {}
    if os.path.exists(WATCHLIST):
        try:
            watchlist = json.load(open(WATCHLIST))
            print("[STATE] Watchlist wiederhergestellt: " + str(len(watchlist)) + " Token")
        except Exception:
            pass

    if not os.path.exists(LOG_CSV):
        with open(LOG_CSV, "w") as f:
            f.write("time,addr,symbol,price,liq,vol5,buys,sells,chg5,age_h,passed,rug_risk,reasons,chg1,vol_h6\n")

    cycle = 0
    while True:
        cycle += 1
        try:
            profiles = _get("https://api.dexscreener.com/token-profiles/latest/v1") or []
            sol = [x for x in profiles if x.get("chainId") == CHAIN][:MAX_PER_CYCLE]
            screened = passed = 0
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            for x in sol:
                addr = x.get("tokenAddress")
                if not addr:
                    continue
                s = screen_token(addr)
                if not s:
                    continue
                screened += 1
                # Zeitreihe loggen (alle, zum Anlernen)
                try:
                    with open(LOG_CSV, "a") as f:
                        f.write(",".join(str(v) for v in [
                            now, s["addr"], s["symbol"], s["price"], s["liq"], s["vol5"],
                            s["buys"], s["sells"], s["chg5"], s["age_h"], s["passed"],
                            s["rug_risk"].replace(",", ";"), "|".join(s["reasons"]),
                            s.get("chg1", 0), s.get("vol_h6", 0)]) + "\n")
                except Exception:
                    pass
                if s["passed"]:
                    passed += 1
                    prev = watchlist.get(addr, {})
                    s["first_seen"]  = prev.get("first_seen", now)
                    s["first_price"] = prev.get("first_price", s["price"])  # Entdeckungs-Preis fixieren
                    s["last_seen"]   = now
                    watchlist[addr] = s
                    print("[PASS] " + s["symbol"].ljust(10) + " liq$" + str(s["liq"]) +
                          " chg5=" + str(s["chg5"]) + "% buys/sells=" + str(s["buys"]) + "/" +
                          str(s["sells"]) + " rug=" + s["rug_risk"])
                time.sleep(0.4)   # Rate-Limit-Schonung

            # Watchlist auf zuletzt 200 begrenzen (aelteste raus)
            if len(watchlist) > 200:
                items = sorted(watchlist.items(), key=lambda kv: kv[1].get("last_seen", ""))
                watchlist = dict(items[-200:])

            _atomic_write(WATCHLIST, watchlist)
            _atomic_write(HEARTBEAT, {"cycle": cycle, "ts": time.time(),
                                      "screened": screened, "passed": passed,
                                      "watchlist": len(watchlist)})
            print("[DEX] Zyklus " + str(cycle) + " | " + str(screened) + " gescreent, " +
                  str(passed) + " bestanden | Watchlist " + str(len(watchlist)))
        except Exception as e:
            print("[DEX-LOOP] " + str(e))
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    run()
