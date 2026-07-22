#!/usr/bin/env python3
"""
dex_bundle_collector.py — VORWAERTS-Sammler fuer den Bundle-Test.

Problem (belegt): bei ALTEN Tokens ist das Launch-Fenster unter 30.000+ Transaktionen
begraben -> nicht guenstig rekonstruierbar, Survivors erreichen es fast nie (Bias).
Loesung: jeden NEUEN Watchlist-Token mitschneiden, SOLANGE er frisch ist (wenige Tx =
Genesis billig erreichbar, kein Bias). Das Label (rug/survivor) kommt spaeter GRATIS aus
der screening_log-Trajektorie, die dex_monitor ohnehin schreibt.

Isoliert: eigener Prozess + eigener Singleton-Lock, read-only auf watchlist.json, schreibt
NUR nach dex/bundle_live/ + dex/bundle_log.csv. Beruehrt dex_monitor / dex_paper nicht.
Wiederverwendet die (RPC-basierten) Fetch-Funktionen aus dex_bundle_probe.py.
"""
import os
import sys
import json
import time
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from config import config
import dex_bundle_probe as _probe
from dex_bundle_probe import early_buyers, funder_of, _atomic_write

# Live-Tuning: frische Tokens erreichen Genesis weit unter 60 Seiten -> Seiten + Kaeufer
# knapper halten (schnellere, guenstigere Zyklen). Die importierten Funktionen lesen diese
# Werte aus dem _probe-Namespace, das Override wirkt also.
_probe.MINT_CAP_PAGES = 20
_probe.EARLY_WINDOW_N = 20

HK = config.get("helius_api_key", "")

DEX_DIR    = os.path.join(REPO_ROOT, "dex")
WATCHLIST  = os.path.join(DEX_DIR, "watchlist.json")
BUNDLE_DIR = os.path.join(DEX_DIR, "bundle_live")            # je Token ein Funding-Graph
BUNDLE_LOG = os.path.join(DEX_DIR, "bundle_log.csv")         # Zeitreihe fuer die spaetere Auswertung
HEARTBEAT  = os.path.join(DEX_DIR, "bundle_collector_hb.json")

POLL_SEC          = 300      # alle 5 Min neue Watchlist-Tokens pruefen
MAX_PER_CYCLE     = 4        # max neue Captures/Zyklus (Helius-Last begrenzen)
CAPTURE_MAX_AGE_H = 6        # nur frische Tokens erfassen (Launch billig + Genesis erreichbar)
SLEEP_BETWEEN     = 2        # Pause zwischen zwei Captures


def capture(addr, tok):
    """Launch-Funding-Graph eines Tokens mitschneiden + loggen. Crasht nie."""
    try:
        buyers, genesis = early_buyers(addr, HK)
        for b in buyers:
            f = funder_of(b["wallet"], b["first_buy_ts"], HK)
            if f:
                b.update(f)
        funders = {}
        for b in buyers:
            if b.get("funder"):
                funders.setdefault(b["funder"], []).append(b)
        max_cluster = max((len(v) for v in funders.values()), default=0)   # groesster geteilter Funder = Bundle-Proxy
        oc = tok.get("onchain") or {}
        graph = {"addr": addr, "symbol": tok.get("symbol", "?"),
                 "first_seen": tok.get("first_seen"), "age_h_at_capture": tok.get("age_h"),
                 "captured": datetime.now().strftime("%Y-%m-%d %H:%M"),
                 "reached_genesis": genesis, "n_buyers": len(buyers),
                 "n_funded": sum(1 for b in buyers if b.get("funder")),
                 "max_cluster": max_cluster,
                 "insiders": oc.get("insiders"), "insider_nets": oc.get("insider_nets"),
                 "buyers": buyers}
        os.makedirs(BUNDLE_DIR, exist_ok=True)
        _atomic_write(os.path.join(BUNDLE_DIR, addr + ".json"), graph)
        _new = not os.path.exists(BUNDLE_LOG)
        with open(BUNDLE_LOG, "a") as f:
            if _new:
                f.write("captured,addr,symbol,first_seen,age_h,n_buyers,n_funded,max_cluster,genesis,insiders,insider_nets\n")
            f.write(",".join(str(x) for x in [graph["captured"], addr, graph["symbol"], graph["first_seen"],
                    graph["age_h_at_capture"], graph["n_buyers"], graph["n_funded"], max_cluster,
                    genesis, graph["insiders"], graph["insider_nets"]]) + "\n")
        print("[CAPTURE] %-10s %s | %d Kaeufer, %d Funder, max-Cluster %d, genesis=%s"
              % (graph["symbol"][:10], addr[:8], graph["n_buyers"], graph["n_funded"], max_cluster, genesis),
              flush=True)
    except Exception as e:
        print("[CAPTURE-ERR] " + addr[:8] + " " + str(e)[:80], flush=True)


def cycle():
    """Ein Durchlauf: neue frische Watchlist-Tokens erfassen. Gibt Anzahl neuer Captures zurueck."""
    try:
        wl = json.load(open(WATCHLIST)) if os.path.exists(WATCHLIST) else {}
    except Exception:
        wl = {}
    done = 0
    for addr, tok in wl.items():
        if done >= MAX_PER_CYCLE:
            break
        path = os.path.join(BUNDLE_DIR, addr + ".json")
        if os.path.exists(path):
            continue                                        # schon erfasst (oder als too_old gestubt)
        age = tok.get("age_h", 999) or 999
        if age > CAPTURE_MAX_AGE_H:
            os.makedirs(BUNDLE_DIR, exist_ok=True)           # Stub -> nicht jeden Zyklus neu pruefen
            _atomic_write(path, {"addr": addr, "symbol": tok.get("symbol", "?"), "skipped": "too_old", "age_h": age})
            continue
        capture(addr, tok)
        done += 1
        time.sleep(SLEEP_BETWEEN)
    try:
        files = [f for f in os.listdir(BUNDLE_DIR) if f.endswith(".json")] if os.path.isdir(BUNDLE_DIR) else []
    except Exception:
        files = []
    _atomic_write(HEARTBEAT, {"time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                              "watchlist": len(wl), "files_total": len(files), "last_cycle_new": done})
    return done


def run(once=False):
    if not HK:
        print("[FATAL] config['helius_api_key'] fehlt.")
        sys.exit(2)
    print("=" * 55)
    print("  DEX BUNDLE-COLLECTOR (vorwaerts, read-only, isoliert)")
    print("  faengt Launch-Funding-Graphen frischer Tokens (Alter <=" + str(CAPTURE_MAX_AGE_H) + "h)")
    print("=" * 55, flush=True)
    while True:
        try:
            n = cycle()
            print("[CYCLE] " + datetime.now().strftime("%H:%M") + " | " + str(n) + " neu erfasst", flush=True)
        except Exception as e:
            print("[CYCLE-ERR] " + str(e)[:80], flush=True)
        if once:
            break
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    once = "--once" in sys.argv
    if not once:
        try:
            import health
            if health.acquire_singleton("dex_bundle_collector") is None:
                health.log("dex_bundle_collector", "DUPLICATE_BLOCKED", "")
                sys.exit(0)
            health.log("dex_bundle_collector", "START", "")
        except Exception:
            pass
    run(once=once)
