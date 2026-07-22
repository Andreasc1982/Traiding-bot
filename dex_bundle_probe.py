#!/usr/bin/env python3
"""
dex_bundle_probe.py — Forensik-Prototyp: bringt ein LLM (Fable 5) Bundle-Erkennung,
die die simple "Insider-Anzahl"-Heuristik NICHT abdeckt?

HYPOTHESE (unbelegt, wird hier getestet): Rugs unterscheiden sich von organischen
Token nicht in der ZAHL der Insider-Wallets (Insider-Ø 107 vs 109 = identisch,
schon gemessen), sondern in der BEZIEHUNG zwischen den Wallets — wurden mehrere
"unabhaengige" Kaeufer-Wallets aus derselben Quelle in engem Zeitfenster finanziert
und kaufen dann synchron (= koordinierter Bundle-Kauf statt organischer Nachfrage)?
Das ist Mustererkennung ueber einen Beziehungsgraphen, keine Zaehlung.

DESIGN (bewusst, siehe README-Block unten):
  * Nur Launch-Fenster-Daten. Wir ziehen die FRUEHE, unveraenderliche On-Chain-Tx-
    Historie (Helius) — NICHT den heutigen RugCheck-Report. Ein Report von heute fuer
    einen laengst gerugten Token zeigt den Rug-Status direkt = Data Leakage. Solscan/
    Helius-Tx aus den ersten Minuten sind unveraenderlich und rekonstruierbar.
  * Balanciert: N Rugs / N Non-Rugs (sonst kippt jede Trefferquote durch Klassenverteilung).
  * Baseline zum Vergleich: der simple insider_nets / insiders-Klassifikator aus
    onchain_log.csv (beide zum SCREENING-Zeitpunkt geloggt = auch leakage-frei).
    Bringt Fables Bundle-Flag ZUSAETZLICHE Trennschaerfe oder nur Rauschen?
  * Erfolgskriterium VORHER festgelegt (siehe GATE unten) — kein Nach-hinten-Rationalisieren.
  * Gestaffelt + gecacht: --build-sample und --fetch sind gratis/billig und
    inspizierbar; erst --run kostet echte API-Calls (Fable 5, ~$0.20/Token).

Stufen (einzeln oder via --all):
  --build-sample   paper_trades.json -> bundle_probe/sample.json  (10 Rug / 10 Non-Rug)
  --fetch          je Token: Helius-Funding-Graph -> bundle_probe/cache/<addr>.json  (gratis-ish, inspizierbar)
  --run            je Token: Funding-Graph -> Fable 5 -> results.json  (BEZAHLT, resumierbar)
  --score          Konfusionsmatrix Fable vs Baseline vs Labels + Erfolgs-Gate

read-only fuer die Bot-Daten. Schreibt NUR nach dex/bundle_probe/. Beruehrt keinen Bot.
"""
import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
from datetime import datetime

# ── Config (gleiche Konvention wie die Agenten) ──────────────────────────────
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def load_config(need_anthropic=False):
    """Lazy — damit --help ohne config.py funktioniert. Verlangt den Anthropic-Key
    NUR fuer --run (Fable); --fetch braucht nur Helius (gratis)."""
    try:
        from config import config
    except Exception:
        print("[FATAL] config.py nicht importierbar (liegt im Repo-Root, gitignored).")
        sys.exit(2)
    hk = config.get("helius_api_key", "")
    ak = config.get("anthropic_api_key", "")
    if not hk:
        print("[FATAL] config['helius_api_key'] fehlt — Funding-Graph braucht Helius.")
        sys.exit(2)
    if need_anthropic and not ak:
        print("[FATAL] config['anthropic_api_key'] fehlt. In config.py ergaenzen:")
        print('        "anthropic_api_key": "sk-ant-...",')
        sys.exit(2)
    return hk, ak


# ── Pfade ────────────────────────────────────────────────────────────────────
DEX_DIR      = os.environ.get("DEX_DIR", os.path.join(REPO_ROOT, "dex"))
SCREENING_LOG = os.path.join(DEX_DIR, "screening_log.csv")
ONCHAIN_LOG  = os.path.join(DEX_DIR, "onchain_log.csv")
PROBE_DIR    = os.path.join(DEX_DIR, "bundle_probe")
CACHE_DIR    = os.path.join(PROBE_DIR, "cache")
SAMPLE_JSON  = os.path.join(PROBE_DIR, "sample.json")
RESULTS_JSON = os.path.join(PROBE_DIR, "results.json")
REPORT_JSON  = os.path.join(PROBE_DIR, "report.json")     # Dashboard-Feed (bundle_probe.html)
LIVE_REPORT  = os.path.join(PROBE_DIR, "live_report.json") # Dashboard-Feed (bundle_live.html)
BUNDLE_LIVE  = os.path.join(DEX_DIR, "bundle_live")        # Captures vom dex_bundle_collector

# ── Parameter ────────────────────────────────────────────────────────────────
N_EACH           = 15         # Rugs bzw. Survivors im Sample (balanciert)
EARLY_WINDOW_N   = 25         # frueheste eindeutige Kaeufer-Wallets = "Launch-Fenster"
MINT_CAP_PAGES   = 60         # max getSignaturesForAddress-Seiten (1000/Seite) fuer den Mint bis Genesis
MINT_SIGS        = 150        # aelteste N Mint-Signaturen parsen (= Launch-Transaktionen)
FUNDER_CAP_PAGES = 3          # max Sig-Seiten je Kaeufer-Wallet (fresh Wallets = 1 Seite)
WALLET_SIGS      = 30         # aelteste N Signaturen je Wallet parsen (Funding suchen)
# Graveyard-Labeling aus screening_log-Trajektorie:
GRAVE_PEAK_MIN  = 15000       # min Peak-Liq — echter Launch, kein Dust
GRAVE_PEAK_MAX  = 150000      # max Peak-Liq — darueber zu viel Tx-Historie fuer die Genesis-Rekonstruktion
GRAVE_MIN_OBS   = 3           # min Beobachtungen (Trajektorie vorhanden)
SURVIVE_LIQ     = 10000       # Survivor: Liquiditaet am Ende noch >= das
RUG_LIQ         = 2500        # Rug: Liquiditaet kollabiert unter das (= dex_paper RUG_LIQ)
LIVE_SURVIVOR_AGE_H = 24      # Live-Capture gilt erst nach 24h Ueberleben als Survivor (sonst 'pending')
FABLE_MODEL     = "claude-fable-5"
FALLBACK_MODEL  = "claude-opus-4-8"     # Refusal-Fallback (Fable-Safety-Classifier kann Cyber/Bio ablehnen)
FABLE_EFFORT    = "medium"    # medium reicht fuer Muster ueber ~40 Zeilen; hoeher = laengere Turns/mehr Kosten
HTTP_TIMEOUT    = 300         # Fable-Turns koennen Minuten dauern
# ERFOLGS-GATE (vorher festgelegt): Bundle-Flag muss bei >=7/10 Rugs anschlagen
# UND bei <=2/10 Non-Rugs — sonst ueberinterpretieren wir 20 Datenpunkte.
GATE_MIN_RUG_HITS   = 7
GATE_MAX_NONRUG_HITS = 2


# ── kleine HTTP-Helfer (stdlib, keine neue venv-Dependency — wie der Rest des Repos) ──
def _get_json(url, timeout=30):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "bundle-probe/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print("[HELIUS] HTTP " + str(e.code) + " " + url[:70])
    except Exception as e:
        print("[HELIUS] " + str(e)[:80])
    return None


def _atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)


# ── STUFE 1: Sample bauen ────────────────────────────────────────────────────
def build_sample(n_each):
    """Graveyard-Sampling aus screening_log.csv: rug(tot) vs survivor(lebt) ueber die
    Liquiditaets-Trajektorie. Nur Tokens MIT onchain_log-Baseline (leakage-frei) und in
    einem Peak-Liq-Band (echter Launch, aber nicht so viel Tx-Historie, dass die
    Genesis-Rekonstruktion unmoeglich wird)."""
    import csv
    if not os.path.exists(SCREENING_LOG):
        print("[FATAL] " + SCREENING_LOG + " fehlt — laeuft dex_monitor?")
        sys.exit(2)

    base = {}                                          # addr -> (insiders, insider_nets), frueheste Zeile
    if os.path.exists(ONCHAIN_LOG):
        for row in csv.DictReader(open(ONCHAIN_LOG)):
            a = row.get("addr")
            if a and a not in base:
                def _n(x):
                    try: return float(x)
                    except Exception: return None
                base[a] = (_n(row.get("insiders")), _n(row.get("insider_nets")))
    print("[SAMPLE] Baseline-Tokens (onchain_log): %d" % len(base))

    st = {}                                            # addr -> Trajektorie-Stats
    with open(SCREENING_LOG) as f:
        rd = csv.reader(f); next(rd, None)
        for r in rd:
            if len(r) < 13:
                continue
            a = r[1]
            if a not in base:                          # nur Tokens mit Baseline
                continue
            try: liq = float(r[4])
            except Exception: liq = 0.0
            s = st.get(a)
            if s is None:
                s = st[a] = {"sym": r[2], "n": 0, "peak": 0.0, "last_liq": 0.0,
                             "last_key": "", "vanished": False}
            s["n"] += 1
            if liq > s["peak"]: s["peak"] = liq
            k = str(r[0])
            if k >= s["last_key"]:
                s["last_key"] = k; s["last_liq"] = liq
            if "graveyard_vanished" in r[12]: s["vanished"] = True

    rug, surv = [], []
    for a, s in st.items():
        if s["n"] < GRAVE_MIN_OBS or not (GRAVE_PEAK_MIN <= s["peak"] <= GRAVE_PEAK_MAX):
            continue
        ins, nets = base[a]
        rec = {"addr": a, "symbol": s["sym"], "peak_liq": round(s["peak"]),
               "last_liq": round(s["last_liq"]), "insiders": ins, "insider_nets": nets}
        if s["vanished"] or s["last_liq"] < RUG_LIQ:
            rec["label"], rec["reason"] = "rug", ("vanished" if s["vanished"] else "liq_collapse")
            rug.append(rec)
        elif s["last_liq"] >= SURVIVE_LIQ:
            rec["label"], rec["reason"] = "nonrug", "survivor"
            surv.append(rec)

    rug.sort(key=lambda x: -x["peak_liq"]); surv.sort(key=lambda x: -x["peak_liq"])
    if len(rug) < n_each or len(surv) < n_each:
        print("[WARN] nur %d Rug / %d Survivor im Band (gewuenscht %d je)." % (len(rug), len(surv), n_each))
    r, s = rug[:n_each], surv[:n_each]
    sample = [t for pair in zip(r, s) for t in pair]        # rug/surv abwechselnd -> beide Klassen frueh im Fetch
    sample += r[len(s):] + s[len(r):]                       # Rest falls Klassen ungleich gross

    os.makedirs(PROBE_DIR, exist_ok=True)
    _atomic_write(SAMPLE_JSON, sample)
    print("[SAMPLE] %d Token -> %s (%d Rug / %d Survivor, Peak-Liq $%dk-$%dk)"
          % (len(sample), SAMPLE_JSON, min(len(rug), n_each), min(len(surv), n_each),
             GRAVE_PEAK_MIN // 1000, GRAVE_PEAK_MAX // 1000))
    return sample


# ── STUFE 2: Helius-Funding-Graph (Launch-Fenster, leakage-frei) ─────────────
SOL_RPC = "https://mainnet.helius-rpc.com/?api-key="         # + key (getSignaturesForAddress, 1000/Seite)
ENH_TX  = "https://api.helius.xyz/v0/transactions?api-key="  # + key (parse bis 100 Sigs/Call)
CALL_SLEEP = 0.25


def _rpc(method, params, hk):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for a in range(5):
        try:
            req = urllib.request.Request(SOL_RPC + hk, data=body, headers={"Content-Type": "application/json", "User-Agent": "bundle-probe/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8")).get("result")
        except urllib.error.HTTPError as e:
            if e.code == 429 and a < 4:
                time.sleep(2 ** (a + 1)); continue
            print("[RPC] HTTP %d %s" % (e.code, method)); return None
        except Exception as e:
            print("[RPC] " + str(e)[:70]); time.sleep(1)
    return None


def _oldest_sigs(address, hk, want, cap_pages):
    """getSignaturesForAddress rueckwaerts (1000/Seite) bis Genesis (oder cap); gibt die
    AELTESTEN `want` Signaturen + reached_genesis zurueck."""
    allsigs, before, genesis = [], None, False
    for _ in range(cap_pages):
        params = [address, {"limit": 1000}]
        if before:
            params[1]["before"] = before
        res = _rpc("getSignaturesForAddress", params, hk)
        time.sleep(CALL_SLEEP)
        if not res:
            break
        allsigs.extend(res); before = res[-1]["signature"]
        if len(res) < 1000:
            genesis = True; break
    allsigs.sort(key=lambda s: s.get("blockTime") or 0)     # aelteste zuerst
    return [s["signature"] for s in allsigs[:want]], genesis


def _parse_txns(sigs, hk):
    """Helius-Parse fuer bis zu 100 Signaturen/Call -> Liste geparster Transaktionen."""
    out = []
    for i in range(0, len(sigs), 100):
        body = json.dumps({"transactions": sigs[i:i + 100]}).encode()
        for a in range(5):
            try:
                req = urllib.request.Request(ENH_TX + hk, data=body, headers={"Content-Type": "application/json", "User-Agent": "bundle-probe/1.0"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    got = json.loads(r.read().decode("utf-8"))
                    if isinstance(got, list):
                        out.extend(got)
                    break
            except urllib.error.HTTPError as e:
                if e.code == 429 and a < 4:
                    time.sleep(2 ** (a + 1)); continue
                print("[PARSE] HTTP %d" % e.code); break
            except Exception as e:
                print("[PARSE] " + str(e)[:70]); break
        time.sleep(CALL_SLEEP)
    return out


def early_buyers(mint, hk):
    """Aelteste Mint-Signaturen -> parsen -> die ERSTEN eindeutigen Wallets, die den Mint
    empfangen (= frueheste Kaeufer). reached_genesis sagt, ob wir am Launch waren."""
    sigs, genesis = _oldest_sigs(mint, hk, MINT_SIGS, MINT_CAP_PAGES)
    txns = _parse_txns(sigs, hk)
    txns.sort(key=lambda t: t.get("timestamp") or 0)
    buyers, seen = [], set()
    for tx in txns:
        for tt in tx.get("tokenTransfers", []):
            if tt.get("mint") == mint:
                w = tt.get("toUserAccount")
                if w and w not in seen:
                    seen.add(w)
                    buyers.append({"wallet": w, "first_buy_ts": tx.get("timestamp", 0)})
        if len(buyers) >= EARLY_WINDOW_N:
            break
    return buyers[:EARLY_WINDOW_N], genesis


def funder_of(wallet, before_ts, hk):
    """Erste SOL-Finanzierung INS Wallet vor seinem ersten Kauf (aus den aeltesten Wallet-Txns).
    Teilen sich viele 'unabhaengige' Wallets einen Funder in engem Fenster = Bundle-Fingerabdruck."""
    sigs, _ = _oldest_sigs(wallet, hk, WALLET_SIGS, FUNDER_CAP_PAGES)
    txns = _parse_txns(sigs, hk)
    txns.sort(key=lambda t: t.get("timestamp") or 0)
    for tx in txns:                                          # aelteste zuerst -> erste Finanzierung
        ts = tx.get("timestamp", 0)
        if before_ts and ts > before_ts:
            continue
        for nt in tx.get("nativeTransfers", []):
            if nt.get("toUserAccount") == wallet and (nt.get("amount", 0) or 0) > 0:
                return {"funder": nt.get("fromUserAccount"), "funder_ts": ts,
                        "sol": round((nt.get("amount", 0) or 0) / 1e9, 4),
                        "sec_before_buy": (before_ts - ts) if before_ts else None}
    return None


def fetch_graph(token, hk):
    addr = token["addr"]
    cache_path = os.path.join(CACHE_DIR, addr + ".json")
    if os.path.exists(cache_path):
        return json.load(open(cache_path))
    buyers, reached = early_buyers(addr, hk)
    for b in buyers:
        f = funder_of(b["wallet"], b["first_buy_ts"], hk)
        if f:
            b.update(f)
    graph = {"addr": addr, "n_buyers": len(buyers), "reached_genesis": reached,
             "buyers": buyers, "fetched": datetime.now().strftime("%Y-%m-%d %H:%M")}
    os.makedirs(CACHE_DIR, exist_ok=True)
    _atomic_write(cache_path, graph)
    return graph


def fetch_all(hk):
    sample = json.load(open(SAMPLE_JSON))
    for i, tok in enumerate(sample, 1):
        g = fetch_graph(tok, hk)
        funded = sum(1 for b in g["buyers"] if b.get("funder"))
        print("[FETCH %2d/%d] %-10s %s | %d Kaeufer, %d mit Funder, genesis=%s"
              % (i, len(sample), tok["symbol"][:10], tok["addr"][:8], g["n_buyers"],
                 funded, g["reached_genesis"]), flush=True)


# ── STUFE 3: Fable 5 — Bundle-Urteil aus dem (anonymisierten) Funding-Graph ───
SYSTEM_PROMPT = (
    "You are a Solana on-chain forensics analyst. You receive the EARLY buyer wallets of a "
    "freshly launched token and, for each, where its SOL came from (the funding wallet), when, "
    "and how many seconds before that wallet's first buy of this token. Judge ONLY whether the "
    "early demand looks like a COORDINATED BUNDLE — several nominally-independent wallets funded "
    "from a common source within a tight window, then buying in sync — versus ORGANIC demand from "
    "unrelated wallets funded independently over time. Do NOT try to guess whether the token later "
    "rugged; reason only about wallet-funding relationships in the data you are given."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "bundle_detected": {"type": "boolean"},
        "confidence": {"type": "number"},
        "cluster_size": {"type": "integer"},
        "evidence": {"type": "string"},
    },
    "required": ["bundle_detected", "confidence", "cluster_size", "evidence"],
    "additionalProperties": False,
}


def _anonymize(graph):
    """Symbol + Adresse RAUS (kein name-based prior), Wallets auf w0..wN mappen —
    Fable soll nur die Beziehungsstruktur sehen, nichts wiedererkennen."""
    wmap, out = {}, []

    def alias(w):
        if w not in wmap:
            wmap[w] = "w%d" % len(wmap)
        return wmap[w]

    for b in graph["buyers"]:
        row = {"buyer": alias(b["wallet"]), "buy_ts": b.get("first_buy_ts")}
        if b.get("funder"):
            row["funded_by"] = alias(b["funder"])
            row["funded_sol"] = b.get("sol")
            row["sec_before_buy"] = b.get("sec_before_buy")
        out.append(row)
    return {"n_buyers": graph["n_buyers"], "reached_genesis": graph["reached_genesis"],
            "early_buyers": out}


def fable_verdict(graph, ak):
    payload = _anonymize(graph)
    body = {
        "model": FABLE_MODEL,
        "max_tokens": 8000,
        "system": SYSTEM_PROMPT,
        "fallbacks": [{"model": FALLBACK_MODEL}],
        "output_config": {"effort": FABLE_EFFORT,
                          "format": {"type": "json_schema", "schema": SCHEMA}},
        "messages": [{"role": "user", "content": json.dumps(payload)}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", "x-api-key": ak,
                 "anthropic-version": "2023-06-01",
                 "anthropic-beta": "server-side-fallback-2026-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": "HTTP %d: %s" % (e.code, e.read().decode("utf-8", "ignore")[:200])}
    except Exception as e:
        return {"error": str(e)[:200]}

    if resp.get("stop_reason") == "refusal":
        return {"error": "refusal", "served_by": resp.get("model")}
    # Strukturierte Ausgabe: erster text-Block ist valides JSON. Trotzdem defensiv.
    text = next((b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text"), "")
    try:
        verdict = json.loads(text)
    except Exception:
        import re
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return {"error": "unparsable", "raw": text[:200]}
        verdict = json.loads(m.group(0))
    verdict["served_by"] = resp.get("model")
    return verdict


def run_fable(ak):
    sample = json.load(open(SAMPLE_JSON))
    results = json.load(open(RESULTS_JSON)) if os.path.exists(RESULTS_JSON) else {}
    todo = [t for t in sample if t["addr"] not in results]
    print("[RUN] %d Token offen (von %d), Modell %s, effort %s. Grobkosten ~$%.2f."
          % (len(todo), len(sample), FABLE_MODEL, FABLE_EFFORT, 0.20 * len(todo)))
    for i, tok in enumerate(todo, 1):
        cache_path = os.path.join(CACHE_DIR, tok["addr"] + ".json")
        if not os.path.exists(cache_path):
            print("[RUN %2d] %s — kein Cache, erst --fetch. Uebersprungen." % (i, tok["symbol"]))
            continue
        graph = json.load(open(cache_path))
        v = fable_verdict(graph, ak)
        results[tok["addr"]] = v
        _atomic_write(RESULTS_JSON, results)      # nach JEDEM Token persistieren (resumierbar)
        if "error" in v:
            print("[RUN %2d/%d] %-6s FEHLER: %s" % (i, len(todo), tok["symbol"], v["error"][:60]))
        else:
            print("[RUN %2d/%d] %-6s bundle=%s conf=%.2f cluster=%d (%s)"
                  % (i, len(todo), tok["symbol"], v.get("bundle_detected"),
                     v.get("confidence", 0), v.get("cluster_size", 0), v.get("served_by")))


# ── STUFE 4: Auswerten — Fable vs Baseline vs Labels ─────────────────────────
def _onchain_baseline():
    """addr -> (insiders, insider_nets) aus der FRUEHESTEN onchain_log-Zeile (Screening-Zeitpunkt)."""
    base = {}
    if not os.path.exists(ONCHAIN_LOG):
        return base
    import csv
    with open(ONCHAIN_LOG) as f:
        rd = csv.DictReader(f)
        for row in rd:
            a = row.get("addr")
            if not a or a in base:      # erste (= frueheste) Zeile je Token behalten
                continue

            def num(x):
                try:
                    return float(x)
                except Exception:
                    return None
            base[a] = {"insiders": num(row.get("insiders")),
                       "insider_nets": num(row.get("insider_nets"))}
    return base


def _confusion(preds, labels):
    """preds/labels: addr -> bool (True = 'ist Rug'-Vorhersage / -Label). -> (tp,fp,tn,fn)."""
    tp = fp = tn = fn = 0
    for a, lab in labels.items():
        if a not in preds:
            continue
        p = preds[a]
        if lab and p:
            tp += 1
        elif lab and not p:
            fn += 1
        elif not lab and p:
            fp += 1
        else:
            tn += 1
    return tp, fp, tn, fn


def _method_stats(name, preds, labels):
    tp, fp, tn, fn = _confusion(preds, labels)
    return {"name": name, "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "prec": round(tp / (tp + fp), 3) if (tp + fp) else 0,
            "rec": round(tp / (tp + fn), 3) if (tp + fn) else 0,
            "sep": tp - fp}                              # Trennschaerfe = Treffer minus Fehlalarme


def build_report():
    """Baut die Dashboard-fertige Auswertungs-Struktur (auch schon ohne Fable-Lauf -> 'ausstehend')."""
    sample = json.load(open(SAMPLE_JSON))
    labels = {t["addr"]: (t["label"] == "rug") for t in sample}
    n_rug = sum(1 for v in labels.values() if v)
    n_nonrug = sum(1 for v in labels.values() if not v)

    results = json.load(open(RESULTS_JSON)) if os.path.exists(RESULTS_JSON) else {}
    base = _onchain_baseline()

    fable_pred, errors = {}, 0
    for a, v in results.items():
        if "error" in v:
            errors += 1
        else:
            fable_pred[a] = bool(v.get("bundle_detected"))

    b_nets1 = {a: (base.get(a, {}).get("insider_nets") or 0) >= 1 for a in labels}
    b_nets2 = {a: (base.get(a, {}).get("insider_nets") or 0) >= 2 for a in labels}
    b_ins20 = {a: (base.get(a, {}).get("insiders") or 0) >= 20 for a in labels}

    fable_stats = _method_stats("FABLE Bundle-Flag", fable_pred, labels)
    baselines = [_method_stats("insider_nets >= 1", b_nets1, labels),
                 _method_stats("insider_nets >= 2", b_nets2, labels),
                 _method_stats("insiders >= 20", b_ins20, labels)]
    best_base = max(s["sep"] for s in baselines)

    rows = []
    for t in sample:
        a = t["addr"]
        v = results.get(a, {})
        cp = os.path.join(CACHE_DIR, a + ".json")
        g = json.load(open(cp)) if os.path.exists(cp) else {}
        row = {"symbol": t["symbol"], "addr": a[:8], "label": t["label"],
               "reason": t.get("reason", "?"), "peak_pct": t.get("peak_pct"),
               "peak_liq": t.get("peak_liq"),
               "insiders": base.get(a, {}).get("insiders"),
               "insider_nets": base.get(a, {}).get("insider_nets"),
               "n_buyers": g.get("n_buyers"), "reached_genesis": g.get("reached_genesis")}
        if not v:
            row["fable"] = None                          # noch nicht gelaufen
        elif "error" in v:
            row["fable"] = {"error": str(v["error"])[:120]}
        else:
            row["fable"] = {"bundle_detected": bool(v.get("bundle_detected")),
                            "confidence": v.get("confidence"), "cluster_size": v.get("cluster_size"),
                            "evidence": v.get("evidence"), "served_by": v.get("served_by")}
            row["hit"] = (row["fable"]["bundle_detected"] == (t["label"] == "rug"))
        rows.append(row)

    return {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "model": FABLE_MODEL, "effort": FABLE_EFFORT,
            "n_rug": n_rug, "n_nonrug": n_nonrug, "errors": errors, "ran": len(fable_pred) > 0,
            "gate": {"min_rug_hits": GATE_MIN_RUG_HITS, "max_nonrug_hits": GATE_MAX_NONRUG_HITS,
                     "passed": bool(fable_stats["tp"] >= GATE_MIN_RUG_HITS and
                                    fable_stats["fp"] <= GATE_MAX_NONRUG_HITS),
                     "adds_value": bool(fable_stats["sep"] > best_base),
                     "fable_sep": fable_stats["sep"], "best_baseline_sep": best_base},
            "fable": fable_stats, "baselines": baselines, "rows": rows}


def score():
    r = build_report()
    _atomic_write(REPORT_JSON, r)                         # Dashboard-Feed

    def line(s):
        print("  %-26s Rug-Treffer %d/%d | Non-Rug-Fehlalarm %d/%d | Prec %.2f Rec %.2f"
              % (s["name"], s["tp"], r["n_rug"], s["fp"], r["n_nonrug"], s["prec"], s["rec"]))

    print("=" * 72)
    print("  ERGEBNIS — Bundle-Erkennung vs. simple Insider-Zaehlung")
    print("  Sample: %d Rug / %d Non-Rug | Fable-Fehler/Refusals: %d" % (r["n_rug"], r["n_nonrug"], r["errors"]))
    print("=" * 72)
    print("  (\"Rug-Treffer\" = Flag korrekt bei Rug | \"Non-Rug-Fehlalarm\" = Flag faelschlich bei Non-Rug)\n")
    line(r["fable"])
    print("  ---- Baselines (onchain_log, gratis) ----")
    for s in r["baselines"]:
        line(s)

    print("\n  ERFOLGS-GATE (vorher festgelegt): Fable-Flag bei >=%d/%d Rugs UND <=%d/%d Non-Rugs"
          % (GATE_MIN_RUG_HITS, r["n_rug"], GATE_MAX_NONRUG_HITS, r["n_nonrug"]))
    if not r["ran"]:
        print("  -> KEIN Ergebnis (keine erfolgreichen Fable-Calls). Erst --run.")
        print("  -> report.json geschrieben — Dashboard zeigt 'ausstehend'.")
        return
    g = r["gate"]
    print("  -> GATE: %s (Rug-Treffer %d, Fehlalarm %d)"
          % ("BESTANDEN ✅" if g["passed"] else "NICHT bestanden ❌", r["fable"]["tp"], r["fable"]["fp"]))
    print("  -> Trennung Fable=%d vs. beste Baseline=%d -> Bundle-Flag %s"
          % (g["fable_sep"], g["best_baseline_sep"],
             "bringt Mehrwert" if g["adds_value"] else "bringt KEINEN Mehrwert ueber die Zaehlung"))
    if not (g["passed"] and g["adds_value"]):
        print("\n  FAZIT: Hypothese in diesem Sample NICHT gestuetzt — Bundle-Erkennung ist")
        print("         (noch) nicht der fehlende Hebel. NICHT live in den Screening-Loop bauen.")
    else:
        print("\n  FAZIT: Hypothese gestuetzt — Bundle-Flag trennt besser als die Zaehlung.")
        print("         Naechster Schritt: groesseres Sample, dann evtl. Live-Integration.")
    print("  -> Dashboard-Feed report.json aktualisiert.")


# ── STUFE 5: Live-Auswertung (vom Collector gesammelte Captures) ─────────────
def analyze_live():
    """Joint die Live-Captures (bundle_live/) gegen die Outcomes (screening_log-Trajektorie)
    und misst, ob max_cluster (Bundle-Proxy) Rugs von Survivors trennt — auf SAUBEREN,
    unverzerrten Daten (am echten Launch erfasst). Schreibt live_report.json fuers Dashboard."""
    import csv
    caps = {}
    if os.path.isdir(BUNDLE_LIVE):
        for fn in os.listdir(BUNDLE_LIVE):
            if not fn.endswith(".json"):
                continue
            try:
                g = json.load(open(os.path.join(BUNDLE_LIVE, fn)))
            except Exception:
                continue
            if g.get("skipped") or not g.get("addr"):
                continue                                    # too_old-Stubs ueberspringen
            caps[g["addr"]] = g
    print("[LIVE] Captures geladen: %d" % len(caps))

    st = {}                                                 # addr -> Trajektorie aus screening_log
    if os.path.exists(SCREENING_LOG) and caps:
        with open(SCREENING_LOG) as f:
            rd = csv.reader(f); next(rd, None)
            for r in rd:
                if len(r) < 13:
                    continue
                a = r[1]
                if a not in caps:
                    continue
                try: liq = float(r[4])
                except Exception: liq = 0.0
                s = st.setdefault(a, {"last_liq": 0.0, "last_key": "", "vanished": False, "peak": 0.0})
                if liq > s["peak"]: s["peak"] = liq
                k = str(r[0])
                if k >= s["last_key"]:
                    s["last_key"] = k; s["last_liq"] = liq
                if "graveyard_vanished" in r[12]: s["vanished"] = True

    now = datetime.now()
    rows = []
    for a, g in caps.items():
        s = st.get(a, {})
        outcome = "pending"
        if s.get("vanished") or (s.get("last_liq", 1e9) < RUG_LIQ and s.get("peak", 0) >= 8000):
            outcome = "rug"
        elif s.get("last_liq", 0) >= SURVIVE_LIQ:
            try:
                fs = datetime.strptime(g.get("first_seen", ""), "%Y-%m-%d %H:%M")
                if (now - fs).total_seconds() / 3600 >= LIVE_SURVIVOR_AGE_H:
                    outcome = "survivor"
            except Exception:
                pass
        rows.append({"symbol": g.get("symbol", "?"), "addr": a[:8], "outcome": outcome,
                     "max_cluster": g.get("max_cluster", 0), "genesis": g.get("reached_genesis"),
                     "n_buyers": g.get("n_buyers"), "n_funded": g.get("n_funded"),
                     "insiders": g.get("insiders"), "insider_nets": g.get("insider_nets"),
                     "captured": g.get("captured")})

    rug = [r for r in rows if r["outcome"] == "rug"]
    srv = [r for r in rows if r["outcome"] == "survivor"]

    def method(name, key, thr):
        tp = sum(1 for r in rug if (r[key] or 0) >= thr)
        fp = sum(1 for r in srv if (r[key] or 0) >= thr)
        return {"name": name, "tp": tp, "fp": fp, "sep": tp - fp}

    methods = [method("max_cluster ≥ 2", "max_cluster", 2), method("max_cluster ≥ 3", "max_cluster", 3),
               method("insider_nets ≥ 1", "insider_nets", 1), method("insiders ≥ 20", "insiders", 20)]
    bundle_sep = max((m["sep"] for m in methods[:2]), default=0)
    base_sep = max((m["sep"] for m in methods[2:]), default=0)

    report = {"generated": now.strftime("%Y-%m-%d %H:%M"),
              "n_captured": len(rows), "n_rug": len(rug), "n_survivor": len(srv),
              "n_pending": len(rows) - len(rug) - len(srv),
              "n_genesis": sum(1 for r in rows if r["genesis"]),
              "methods": methods, "bundle_sep": bundle_sep, "baseline_sep": base_sep,
              "enough": bool(len(rug) >= 8 and len(srv) >= 8),
              "rows": sorted(rows, key=lambda r: ({"rug": 0, "survivor": 1, "pending": 2}[r["outcome"]],
                                                  -(r["max_cluster"] or 0)))}
    os.makedirs(PROBE_DIR, exist_ok=True)
    _atomic_write(LIVE_REPORT, report)

    print("=" * 66)
    print("  LIVE-SAMMLUNG — Bundle-Proxy (max_cluster) auf sauberen Daten")
    print("  %d erfasst | %d Rug / %d Survivor / %d pending | genesis %d"
          % (len(rows), len(rug), len(srv), report["n_pending"], report["n_genesis"]))
    print("=" * 66)
    for m in methods:
        print("  %-18s Rug %2d | Survivor-Fehlalarm %2d | Trennung %+d" % (m["name"], m["tp"], m["fp"], m["sep"]))
    if report["enough"]:
        print("\n  -> max_cluster-Trennung %+d vs. beste Baseline %+d -> Bundle-Signal %s"
              % (bundle_sep, base_sep, "traegt" if bundle_sep > base_sep else "traegt NICHT besser als die Zaehlung"))
    else:
        print("\n  -> noch zu wenig aufgeloest (brauche >=8 Rug UND >=8 Survivor). Weiter sammeln.")
    print("  -> live_report.json aktualisiert (Dashboard).")
    return report


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Forensik-Prototyp: LLM-Bundle-Erkennung vs Insider-Zaehlung.")
    ap.add_argument("--build-sample", action="store_true", help="paper_trades -> balanciertes Sample")
    ap.add_argument("--fetch", action="store_true", help="Helius-Funding-Graphen holen (gratis-ish)")
    ap.add_argument("--run", action="store_true", help="Fable 5 aufrufen (BEZAHLT, resumierbar)")
    ap.add_argument("--score", action="store_true", help="auswerten gegen Baseline + Gate")
    ap.add_argument("--analyze-live", action="store_true", help="Collector-Captures gegen Outcomes auswerten (Live-Dashboard)")
    ap.add_argument("--all", action="store_true", help="alle vier Stufen nacheinander")
    ap.add_argument("--n", type=int, default=N_EACH, help="Rugs bzw. Non-Rugs im Sample (default %d)" % N_EACH)
    args = ap.parse_args()

    if not any([args.build_sample, args.fetch, args.run, args.score, args.analyze_live, args.all]):
        ap.print_help()
        return

    if args.build_sample or args.all:
        build_sample(args.n)
    if args.fetch or args.all:
        hk, _ = load_config()
        fetch_all(hk)
    if args.run or args.all:
        _, ak = load_config(need_anthropic=True)
        run_fable(ak)
    if args.score or args.all:
        score()
    if args.analyze_live:
        analyze_live()


if __name__ == "__main__":
    main()
