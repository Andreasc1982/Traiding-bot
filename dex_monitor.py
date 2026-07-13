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
ONCHAIN_LOG = os.path.join(DEX_DIR, "onchain_log.csv")   # log-only: erste On-Chain-Signalspur, aendert Screening NICHT
SOL_RPC   = "https://api.mainnet-beta.solana.com"        # Public-RPC-Fallback (getAccountInfo ok; Holder-Calls rate-limited)
HELIUS_KEY  = config.get("helius_api_key", "")
ONCHAIN_RPC = ("https://mainnet.helius-rpc.com/?api-key=" + HELIUS_KEY) if HELIUS_KEY else SOL_RPC
onchain_cache = {}   # addr -> {"freeze","conc","top10"} : 1-Call-Cache je Token UND Quelle fuers Dashboard
GRAVEYARD = os.path.join(DEX_DIR, "graveyard.json")
GRAVE_H          = 36   # aus Watchlist entfernte Token noch so lange weiterloggen (Post-Exit-Trajektorie)
GRAVE_MAX        = 60   # max Grab-Groesse (= 2 Batch-Calls) — aelteste fliegen zuerst
GRAVE_VANISH_MAX = 3    # nach N BESTAETIGTEN Vanishes (leere OK-Antwort, kein API-Fehler) endgueltig raus

CHAIN          = "solana"
POLL_SEC       = 60          # 120->60: dank Batch-Call + Lazy-RugCheck (1 statt ~30 DexScreener-Calls/Zyklus)
TIMEOUT        = 10
MAX_PER_CYCLE  = 30          # nur Top-N Profile/Zyklus screenen (= 1 Batch-Call, DexScreener-Limit 30 Adressen)

# Screening-Schwellen — konservativ: die MEISTEN Token sollen durchfallen (Rug-Dichte!)
MIN_LIQUIDITY  = 10000       # min $10k Liquiditaet (darunter Rug-anfaellig)
MIN_VOL_5M     = 500         # min Handelsaktivitaet (5 min)
MAX_AGE_H      = 48          # nur frische Token (<48h)
MIN_AGE_MIN    = 15          # aber nicht brandneu (<15min = hoechstes Rug-Fenster)
MIN_BUY_RATIO  = 0.5         # buys/sells >= 0.5 (kein massiver Verkaufsdruck)


def _rpc(method, params):
    """Ein Solana-RPC-Call (Helius wenn Key, sonst Public). Returns result oder None (nie Crash)."""
    try:
        r = requests.post(ONCHAIN_RPC, timeout=TIMEOUT, headers={"Content-Type": "application/json"},
                          json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if r.status_code != 200:
            return None
        d = r.json() or {}
        if "error" in d:
            return None
        return d.get("result")
    except Exception as e:
        print("[ONCHAIN] " + method + ": " + str(e)[:50])
        return None


def onchain_signals(addr):
    """On-Chain-DNA: Authority (Rug) + Holder-Konzentration (Insider-Dump-Risiko).
    Alles optional -> Teil-Fehler = None, nie Crash. Gibt IMMER ein dict zurueck.
    Heuristik: Top-Konto ist meist Bonding-Curve/LP -> top10_ex1 (Holder 2-11) = Insider-Proxy."""
    out = {"mint_auth": None, "freeze_auth": None,
           "top1": None, "top5": None, "top10": None, "top10_ex1": None}
    supply = None
    info = _rpc("getAccountInfo", [addr, {"encoding": "jsonParsed"}])
    try:
        pi = (((info or {}).get("value") or {}).get("data") or {})
        pi = (pi.get("parsed") or {}).get("info") if isinstance(pi, dict) else None
        if pi:
            out["mint_auth"]   = bool(pi.get("mintAuthority"))
            out["freeze_auth"] = bool(pi.get("freezeAuthority"))
            dec = int(pi.get("decimals", 0) or 0)
            supply = float(pi.get("supply", 0) or 0) / (10 ** dec)
    except Exception as e:
        print("[ONCHAIN] parse-auth: " + str(e)[:40])
    la = _rpc("getTokenLargestAccounts", [addr])
    try:
        if la and supply and supply > 0:
            amts = sorted([float(a.get("uiAmount") or 0) for a in la.get("value", [])], reverse=True)
            if amts:
                pc = lambda n: round(sum(amts[:n]) / supply * 100, 1)
                out["top1"], out["top5"], out["top10"] = pc(1), pc(5), pc(10)
                out["top10_ex1"] = round(sum(amts[1:11]) / supply * 100, 1)  # Holder 2-11 (Curve/LP raus)
    except Exception as e:
        print("[ONCHAIN] parse-holders: " + str(e)[:40])
    return out


def ensure_onchain(addr, symbol, now):
    """Holt On-Chain-DNA EINMAL je Token (Cache), loggt sie, gibt kompaktes dict fuers Dashboard.
    Log-only — aendert das Screening nicht. Rate-sicher (1x je Token)."""
    if addr in onchain_cache:
        return onchain_cache[addr]
    oc = onchain_signals(addr)
    try:
        _new = not os.path.exists(ONCHAIN_LOG)
        with open(ONCHAIN_LOG, "a") as f:
            if _new:
                f.write("time,addr,symbol,mint_auth,freeze_auth,top1,top5,top10,top10_ex1\n")
            f.write(",".join(str(v) for v in [now, addr, symbol, oc["mint_auth"], oc["freeze_auth"],
                    oc["top1"], oc["top5"], oc["top10"], oc["top10_ex1"]]) + "\n")
    except Exception as _we:
        print("[ONCHAIN-LOG] " + str(_we)[:50])
    if oc.get("freeze_auth"):
        print("[ONCHAIN] ⚠️ " + symbol + " FREEZE-AUTHORITY gesetzt (nicht verkaufbar!)")
    elif oc.get("top10_ex1") is not None and oc["top10_ex1"] > 40:
        print("[ONCHAIN] ⚠️ " + symbol + " Insider-Konzentration hoch: Top2-11 = " + str(oc["top10_ex1"]) + "%")
    elif oc.get("top10") is not None:
        print("[ONCHAIN] " + symbol + " Holder Top10=" + str(oc["top10"]) + "% (ex-LP " + str(oc["top10_ex1"]) + "%)")
    compact = {"freeze": oc.get("freeze_auth"), "conc": oc.get("top10_ex1"), "top10": oc.get("top10")}
    onchain_cache[addr] = compact
    if len(onchain_cache) > 400:                       # Cache begrenzen (aelteste raus)
        for _k in list(onchain_cache.keys())[:100]:
            onchain_cache.pop(_k, None)
    return compact


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


def _best_pair(pairs, addr):
    """Liquidestes Solana-Pair fuer eine Adresse aus einer gemischten Batch-Pair-Liste."""
    cand = [p for p in pairs if p.get("chainId") == CHAIN
            and (p.get("baseToken") or {}).get("address") == addr]
    if not cand:
        return None
    return max(cand, key=lambda x: (x.get("liquidity") or {}).get("usd", 0) or 0)


def screen_pair(p, addr):
    """Billiges Screening aus einem bereits geholten Pair — KEIN RugCheck (kommt lazy)."""
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
    if liq < MIN_LIQUIDITY:                                   reasons.append("liq<10k")
    if vol5 < MIN_VOL_5M:                                     reasons.append("vol5<500")
    if age_h > MAX_AGE_H:                                     reasons.append("alt>48h")
    if age_h < MIN_AGE_MIN / 60.0:                            reasons.append("zu_neu")
    if sells > 0 and (buys / max(sells, 1)) < MIN_BUY_RATIO:  reasons.append("sell_druck")

    return {
        "addr": addr, "symbol": symbol, "price": price,
        "liq": round(liq), "vol5": round(vol5), "buys": buys, "sells": sells,
        "chg5": round(chg5, 1), "chg1": round(chg1, 1),
        "vol_h1": round(volh1), "vol_h6": round(volh6),
        "age_h": round(age_h, 1),
        "rug_risk": "?", "passed": False, "reasons": reasons,
    }


def rugcheck(addr):
    """RugCheck-Status — lazy, nur fuer Cheap-Passer aufgerufen. -> (label, is_danger)."""
    rug = _get("https://api.rugcheck.xyz/v1/tokens/" + addr + "/report/summary")
    if rug is None:
        return "?", False
    risks = rug.get("risks") or []
    label = (",".join((r.get("name", "")[:14]) for r in risks[:2]) or "ok")
    return label, any(r.get("level") == "danger" for r in risks)


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

    graveyard = {}
    if os.path.exists(GRAVEYARD):
        try:
            graveyard = json.load(open(GRAVEYARD))
            print("[STATE] Graveyard wiederhergestellt: " + str(len(graveyard)) + " Token")
        except Exception as e:
            print("[GRAVE] Restore-Fehler (starte leer): " + str(e))

    if not os.path.exists(LOG_CSV):
        with open(LOG_CSV, "w") as f:
            f.write("time,addr,symbol,price,liq,vol5,buys,sells,chg5,age_h,passed,rug_risk,reasons,chg1,vol_h6\n")

    cycle = 0
    while True:
        cycle += 1
        try:
            profiles = _get("https://api.dexscreener.com/token-profiles/latest/v1") or []
            sol = [x for x in profiles if x.get("chainId") == CHAIN][:MAX_PER_CYCLE]
            addrs = [x.get("tokenAddress") for x in sol if x.get("tokenAddress")]
            # EIN Batch-Call fuer ALLE Token-Daten (DexScreener: bis 30 Adressen/Call)
            batch = _get("https://api.dexscreener.com/latest/dex/tokens/" + ",".join(addrs[:30]))
            all_pairs = (batch or {}).get("pairs") or []
            screened = passed = 0
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            for addr in addrs:
                p = _best_pair(all_pairs, addr)
                if not p:
                    continue
                s = screen_pair(p, addr)
                # Lazy RugCheck — nur fuer Tokens die die billigen Filter schon bestehen
                if not s["reasons"]:
                    label, danger = rugcheck(addr)
                    s["rug_risk"] = label
                    if danger:
                        s["reasons"].append("RUG-DANGER")
                    time.sleep(0.3)   # RugCheck-Schonung (nur fuer die wenigen Passer)
                s["passed"] = len(s["reasons"]) == 0
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
                    s["onchain"]     = ensure_onchain(addr, s["symbol"], now)   # DNA fuers Dashboard (log-only)
                    watchlist[addr] = s
                    print("[PASS] " + s["symbol"].ljust(10) + " liq$" + str(s["liq"]) +
                          " chg5=" + str(s["chg5"]) + "% buys/sells=" + str(s["buys"]) + "/" +
                          str(s["sells"]) + " rug=" + s["rug_risk"])

            # ── Watchlist-Refresh: bestehende Eintraege auf LIVE-Daten bringen ──
            # Behebt das Stale-Problem: sonst friert chg1/chg5/liq/price beim Entdecken ein
            # (Median-Alter war ~26h -> jetzt <~1min). Tote/verschwundene/illiquide fliegen raus.
            refreshed = removed = 0
            fresh_set = set(addrs)   # in diesem Zyklus schon frisch gescreent -> nicht doppelt holen
            refresh_addrs = [a for a in list(watchlist.keys()) if a not in fresh_set]
            for i in range(0, len(refresh_addrs), 30):
                chunk = refresh_addrs[i:i + 30]
                rb = _get("https://api.dexscreener.com/latest/dex/tokens/" + ",".join(chunk))
                if rb is None:
                    continue          # API-Ausfall -> Chunk ueberspringen, NICHTS loeschen (transient)
                rpairs = rb.get("pairs") or []
                for a in chunk:
                    p = _best_pair(rpairs, a)
                    if p is None:                       # aus API verschwunden -> geruggt/delisted -> raus
                        _g = watchlist.pop(a, None); removed += 1
                        if _g: graveyard[a] = {"symbol": _g.get("symbol", "?"), "since": time.time(), "vanish": 0}
                        continue
                    fs = screen_pair(p, a)              # FRISCHE Werte + neu bewertete reasons
                    if fs["reasons"]:                   # Basis-Screen nicht mehr erfuellt -> raus
                        _g = watchlist.pop(a, None); removed += 1
                        if _g: graveyard[a] = {"symbol": _g.get("symbol", "?"), "since": time.time(), "vanish": 0}
                        continue
                    prev = watchlist.get(a, {})
                    fs["first_seen"]  = prev.get("first_seen", now)
                    fs["first_price"] = prev.get("first_price", fs["price"])
                    fs["last_seen"]   = now             # JETZT frisch gesehen
                    fs["rug_risk"]    = prev.get("rug_risk", "ok")   # RugCheck-Label vom Erst-Screen behalten
                    fs["passed"]      = True
                    fs["onchain"]     = ensure_onchain(a, fs["symbol"], now)   # auch Restart-restaurierte Token bekommen DNA
                    watchlist[a] = fs
                    refreshed += 1
                time.sleep(0.3)                          # DexScreener-Schonung zwischen Chunks

            # Watchlist auf zuletzt 200 begrenzen (aelteste raus -> auch ins Grab, Trajektorie weiterloggen)
            if len(watchlist) > 200:
                items = sorted(watchlist.items(), key=lambda kv: kv[1].get("last_seen", ""))
                for _a, _v in items[:-200]:
                    graveyard[_a] = {"symbol": _v.get("symbol", "?"), "since": time.time(), "vanish": 0}
                watchlist = dict(items[-200:])

            # ── Graveyard-Watch: entfernte Token GRAVE_H weiterloggen (Post-Exit-Trajektorie) ──
            # Schliesst die groesste Analyse-Luecke: Retro-Sims mussten das Trajektorien-Ende als
            # Unbekannte behandeln (optimistisch/pessimistisch-Schranken). Lehren eingebaut:
            # API-Ausfall (None) zaehlt NICHT als Vanish; Rows gehen NUR ins LOG_CSV
            # (reasons="graveyard*", passed=False) — nie in die Watchlist, nie in screened/passed.
            gy_logged = 0
            try:
                _tnow = time.time()
                graveyard = {a: g for a, g in graveyard.items()
                             if (_tnow - g.get("since", _tnow)) / 3600 < GRAVE_H and a not in watchlist}
                if len(graveyard) > GRAVE_MAX:
                    _gitems = sorted(graveyard.items(), key=lambda kv: kv[1].get("since", 0))
                    graveyard = dict(_gitems[-GRAVE_MAX:])
                gaddrs = list(graveyard.keys())
                for gi in range(0, len(gaddrs), 30):
                    gchunk = gaddrs[gi:gi + 30]
                    gb = _get("https://api.dexscreener.com/latest/dex/tokens/" + ",".join(gchunk))
                    if gb is None:
                        continue          # API-Ausfall -> kein Vanish-Beleg, nichts loggen (transient)
                    gpairs = gb.get("pairs") or []
                    for a in gchunk:
                        g = graveyard.get(a) or {}
                        gp = _best_pair(gpairs, a)
                        if gp is None:    # bestaetigt weg (OK-Antwort ohne den Token)
                            g["vanish"] = g.get("vanish", 0) + 1
                            _row = [now, a, g.get("symbol", "?"), 0, 0, 0, 0, 0, 0, 0,
                                    False, "?", "graveyard_vanished", 0, 0]
                            if g["vanish"] >= GRAVE_VANISH_MAX:
                                graveyard.pop(a, None)    # endgueltig tot -> nicht weiter pollen
                        else:
                            g["vanish"] = 0
                            gs = screen_pair(gp, a)
                            _row = [now, a, gs["symbol"], gs["price"], gs["liq"], gs["vol5"],
                                    gs["buys"], gs["sells"], gs["chg5"], gs["age_h"],
                                    False, "?", "graveyard", gs.get("chg1", 0), gs.get("vol_h6", 0)]
                        try:
                            with open(LOG_CSV, "a") as f:
                                f.write(",".join(str(v) for v in _row) + "\n")
                            gy_logged += 1
                        except Exception as _we:
                            print("[GRAVE-LOG] " + str(_we))
                    time.sleep(0.3)
                _atomic_write(GRAVEYARD, graveyard)
            except Exception as e:
                print("[GRAVE] " + str(e))

            # Vollstaendige On-Chain-Abdeckung: JEDER Watchlist-Token bekommt DNA — auch die,
            # die durch Screen/Refresh-Ritzen fielen (discovered, aber nicht im Batch). Cached -> billig.
            for _a, _v in list(watchlist.items()):
                if not _v.get("onchain"):
                    _v["onchain"] = ensure_onchain(_a, _v.get("symbol", "?"), now)

            _atomic_write(WATCHLIST, watchlist)
            _atomic_write(HEARTBEAT, {"cycle": cycle, "ts": time.time(),
                                      "screened": screened, "passed": passed,
                                      "refreshed": refreshed, "removed": removed,
                                      "watchlist": len(watchlist), "graveyard": len(graveyard)})
            print("[DEX] Zyklus " + str(cycle) + " | " + str(screened) + " gescreent, " +
                  str(passed) + " neu | refresh " + str(refreshed) + " / raus " + str(removed) +
                  " | Watchlist " + str(len(watchlist)) + " | Grab " + str(len(graveyard)) +
                  ("(" + str(gy_logged) + " Rows)" if gy_logged else ""))
        except Exception as e:
            print("[DEX-LOOP] " + str(e))
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    try:
        import health
        if health.acquire_singleton("dex_monitor") is None:
            health.log("dex_monitor", "DUPLICATE_BLOCKED", "")
            print("[SINGLETON] dex_monitor laeuft bereits — Instanz beendet sich.")
            raise SystemExit(0)
        health.log("dex_monitor", "START", "")
    except SystemExit:
        raise
    except Exception as _e:
        print("[SINGLETON] health n/a: " + str(_e))
    run()
