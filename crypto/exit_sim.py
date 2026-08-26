#!/usr/bin/env python3
"""Retro-Simulation der Ausstiegsregeln des Krypto-Bots.

Frage (Andreas, 25.08.2026): Der Bot verkauft mit kleinem Gewinn und kauft
dasselbe Asset Minuten spaeter zurueck — 38 % aller Verkaeufe. Liegt das an
zu empfindlichen Exit-Regeln, und welche Variante waere besser gewesen?

Vorgehen: echte Einstiege aus dem Telegram-Feed (Zeit, Preis, Einsatz),
1-Minuten-Bars von Alpaca, dann jede Exit-Variante auf denselben Einstiegen
durchgerechnet. Die Entry-Logik bleibt damit konstant — verglichen wird
ausschliesslich der Ausstieg.

Aufruf:  python3 exit_sim.py [feed.json]
"""
import os, sys, json, re
from datetime import datetime, timedelta, timezone

BASE  = "/home/trading2025/trading_bot"
DATA   = os.environ.get("SIM_DATA_MIN", os.path.join(BASE, "crypto", "exit_sim_data"))
DATA_H = os.environ.get("SIM_DATA_H",   os.path.join(BASE, "crypto", "exit_sim_data"))
FEED  = sys.argv[1] if len(sys.argv) > 1 else "/tmp/feed.json"

FEE, SLIP = 0.0026, 0.0005          # je Seite, wie im Bot (sim_fee/sim_slip)
KOSTEN    = (FEE + SLIP) * 2        # Round-Trip 0,62 %
FENSTER_H = 120                     # HARD_MAX_H des Bots

# ── Einstiege aus dem Feed ────────────────────────────────────────────────
def zahl(s):
    return float(s.replace("−", "-").replace(".", "").replace(",", "."))

def lade_entries():
    msgs = sorted(json.load(open(FEED)), key=lambda m: m["date"])
    out = []
    for m in msgs:
        kopf = m["text"].split("\n")[0]
        if "VERKAUF" in kopf or "KAUF" not in kopf:
            continue
        sym = re.search(r"KAUF\s*·\s*([A-Za-z0-9/\.\-]+)", kopf)
        pr  = re.search(r"([\d\.,]+)\s*Stück zu\s*([\d\.,]+)\s*\$\s*=\s*([\d\.,]+)\s*\$", m["text"])
        if not (sym and pr):
            continue
        s = sym.group(1).replace("/USD", "").upper()
        out.append({"sym": s + "/USD",
                    "zeit": datetime.fromisoformat(m["date"]).astimezone(timezone.utc).replace(tzinfo=None),
                    "preis": zahl(pr.group(2)), "einsatz": zahl(pr.group(3)),
                    "spike": "Spike" in m["text"]})
    return out

def filter_fehlpreise(entries, cache, grenze=10.0):
    """Wirft Einstiege raus, deren gemeldeter Preis mehr als `grenze` % neben dem
    Marktkurs derselben Minute liegt. Betrifft im Zeitraum genau einen Fall
    (SOL 13.08.: 187,44 $ gemeldet, Markt 76,29 $ — die Meldung war falsch, der
    Handel selbst lief korrekt). Unbereinigt haengt an diesem einen Datenpunkt
    ein Scheinverlust von 207 $."""
    ok, raus = [], 0
    for e in entries:
        c = cache.get(e["sym"])
        if not c: continue
        nah = [b for b in c[0] if abs((b["t"] - e["zeit"]).total_seconds()) <= 300]
        if nah:
            markt = sum(b["c"] for b in nah) / len(nah)
            if abs((e["preis"] - markt) / markt * 100) > grenze:
                raus += 1; continue
        ok.append(e)
    if raus: print("Wegen Fehlpreis ausgeschlossen: %d Einstieg(e)" % raus)
    return ok

# ── Bars ──────────────────────────────────────────────────────────────────
def lade_bars(sym, tf="1Min"):
    p = os.path.join(DATA if tf == "1Min" else DATA_H, sym.replace("/", "") + "_" + tf + ".json")
    if not os.path.exists(p):
        return None
    raw = json.load(open(p))
    bars = [{"t": datetime.fromisoformat(b["t"].replace("Z", "+00:00")).replace(tzinfo=None),
             "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"]} for b in raw]
    return saeubern(bars)

def saeubern(bars, grenze=0.08):
    """Alpaca-Minutenbars enthalten vereinzelt Fehl-Prints (ein Tick 60 % neben dem
    Markt). Unbereinigt loesen die in der Simulation Stops aus, die es real nie gab —
    ein einziger solcher Bar hat SOL mit −60 % statt −2,3 % in die Rechnung gebracht.
    Docht wird deshalb auf 8 % gegen den Vorschlusskurs gekappt, der Koerper (o/c)
    bleibt unangetastet."""
    weg = 0
    for i, b in enumerate(bars):
        ref = bars[i-1]["c"] if i else b["o"]
        hi, lo = ref * (1 + grenze), ref * (1 - grenze)
        if b["h"] > hi: b["h"] = max(b["o"], b["c"], min(b["h"], hi)); weg += 1
        if b["l"] < lo: b["l"] = min(b["o"], b["c"], max(b["l"], lo)); weg += 1
    return bars

def stunden_bars(bars):
    """1-Min → 1h aggregieren (Rueckfall, wenn keine echten 1h-Bars vorliegen)."""
    out, cur, key = [], None, None
    for b in bars:
        k = b["t"].replace(minute=0, second=0, microsecond=0)
        if k != key:
            if cur: out.append(cur)
            cur = {"t": k, "h": b["h"], "l": b["l"], "c": b["c"]}
            key = k
        else:
            cur["h"] = max(cur["h"], b["h"]); cur["l"] = min(cur["l"], b["l"]); cur["c"] = b["c"]
    if cur: out.append(cur)
    return out

def lade_stunden(sym):
    """Echte 1h-Bars mit 45 Tagen Vorlauf — der Bot rechnet PSAR auf 14 Tagen
    Stundenhistorie, aus 14 Tagen Minutendaten aggregiert waere der Vorlauf zu kurz."""
    b = lade_bars(sym, "1Hour")
    return b

def calc_psar(hs, ls, af0=0.02, af_max=0.2):
    """Wortgleich aus crypto_bot.py uebernommen — sonst simuliert man etwas anderes."""
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

def psar_serie(hbars):
    """PSAR-Wert je Stundenschluss, expandierendes Fenster wie im Bot (max 336 Bars)."""
    out = {}
    hs = [b["h"] for b in hbars]; ls = [b["l"] for b in hbars]
    for i in range(len(hbars)):
        if i < 30:
            out[hbars[i]["t"]] = None; continue
        a = max(0, i - 335)
        out[hbars[i]["t"]] = calc_psar(hs[a:i+1], ls[a:i+1])[0]
    return out

def atr_serie(hbars, n=14):
    """ATR in % vom Kurs, je Stundenschluss."""
    out, trs = {}, []
    for i, b in enumerate(hbars):
        prev_c = hbars[i-1]["c"] if i else b["c"]
        trs.append(max(b["h"] - b["l"], abs(b["h"] - prev_c), abs(b["l"] - prev_c)))
        out[b["t"]] = (sum(trs[-n:]) / min(len(trs), n)) / b["c"] * 100 if i >= n else None
    return out

# ── Exit-Regeln ───────────────────────────────────────────────────────────
def trigger(v, entry, highest, price, sl, tp, psar, atr_pct):
    """Gibt (Grund, Stop-Niveau) zurueck. Das Niveau ist der Preis, zu dem live
    tatsaechlich ausgefuehrt wird — der erste Tick unter der Schwelle liegt an der
    Schwelle, nicht am Minutentief. Ohne diese Unterscheidung rechnet sich die
    Simulation um rund 0,7 % je Trade zu schlecht."""
    pnl  = (price - entry) / entry * 100
    best = (highest - entry) / entry * 100
    trail_pct = v.get("trail", 1.5)
    if v.get("atr_trail") and atr_pct:
        trail_pct = min(max(v["atr_mult"] * atr_pct, v["atr_min"]), v["atr_max"])
    trailing = (highest - price) / highest * 100

    if v.get("nur_sl"):                      # Referenz: nur harter Stop-Loss, kein Nachziehen
        if pnl <= -sl:
            return "STOP-LOSS", entry * (1 - sl / 100)
        return None, None
    if not v.get("psar_aus") and psar is not None and price < psar and pnl >= v.get("psar_ab", 1.5):
        return "PSAR-STOP", psar
    if best >= tp:
        if trailing >= trail_pct:
            return "TRAIL-STOP", highest * (1 - trail_pct / 100)
    elif best >= 6.0:
        if pnl < best - v.get("lock_tief", 2.0):
            return "PROFIT-LOCK", entry * (1 + (best - v.get("lock_tief", 2.0)) / 100)
    elif best >= 4.0:
        if pnl < v.get("lock_min", 2.0):
            return "PROFIT-LOCK", entry * (1 + v.get("lock_min", 2.0) / 100)
    elif best >= v.get("be_ab", 2.0):
        if pnl < v.get("be_bei", 0.0):
            return "BREAKEVEN", entry * (1 + v.get("be_bei", 0.0) / 100)
    else:
        if pnl <= -sl:
            return "STOP-LOSS", entry * (1 - sl / 100)
    return None, None

def simuliere(e, bars, hpsar, hatr, v):
    """Eine Position, eine Variante → (netto_pct, grund, dauer_h, offen)."""
    entry = e["preis"]; highest = entry
    sl = 1.5 if e["spike"] else 2.5
    tp = 3.0 if e["spike"] else 5.0
    start = e["zeit"]
    ende  = start + timedelta(hours=FENSTER_H)
    letzte_std = None; psar = None; atr = None
    for b in bars:
        if b["t"] <= start: 
            letzte_std = b["t"].replace(minute=0); continue
        if b["t"] > ende: break
        std = b["t"].replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        psar = hpsar.get(std, psar); atr = hatr.get(std, atr)
        if v["modus"] == "close":
            preise = [b["c"]]
        else:                                   # intrabar: erst Hoch, dann Tief (heutiges Tick-Verhalten)
            preise = [b["h"], b["l"]]
        for p in preise:
            if p > highest: highest = p
            g, level = trigger(v, entry, highest, p, sl, tp, psar, atr)
            if g:
                if v["modus"] == "close":
                    fill = b["c"]                     # nur Schlusskurs geprueft → dort auch gefuellt
                else:
                    fill = min(max(level, b["l"]), b["h"])   # Ausfuehrung am Stop-Niveau
                dauer = (b["t"] - start).total_seconds() / 3600
                return (fill - entry) / entry * 100 - KOSTEN * 100, g, dauer, False
        # Zeit-Exits
        alter = (b["t"] - start).total_seconds() / 3600
        best  = (highest - entry) / entry * 100
        if (e["spike"] and alter >= 12) or alter >= 120 or (alter >= 72 and best < 4.0):
            return (b["c"] - entry) / entry * 100 - KOSTEN * 100, "TIME-EXIT", alter, False
    if not bars: return None
    letzter = min(bars[-1], key=lambda x: 0) if False else bars[-1]
    return (letzter["c"] - entry) / entry * 100 - KOSTEN * 100, "OFFEN", \
           (letzter["t"] - start).total_seconds() / 3600, True

# ── Varianten ─────────────────────────────────────────────────────────────
VARIANTEN = [
    ("V0 heute",                    {"modus": "intra"}),
    ("W2 Trailing 2,5 %",           {"modus": "intra", "trail": 2.5}),
    ("W3 Trailing 3,5 %",           {"modus": "intra", "trail": 3.5}),
    ("W8 Breakeven aus",            {"modus": "intra", "be_ab": 99.0}),
    ("K1 Trail 2,5 + BE aus",       {"modus": "intra", "trail": 2.5, "be_ab": 99.0}),
    ("K2 K1 + Lock 3 %",            {"modus": "intra", "trail": 2.5, "be_ab": 99.0,
                                     "lock_tief": 3.0, "lock_min": 1.0}),
    ("K3 Trail 3,5 + BE aus",       {"modus": "intra", "trail": 3.5, "be_ab": 99.0}),
    ("VH nur halten (Referenz)",    {"modus": "close", "halten": True}),
]

def main():
    entries = lade_entries()
    cache = {}
    for e in entries:
        if e["sym"] not in cache:
            b = lade_bars(e["sym"])
            h = lade_stunden(e["sym"]) or (stunden_bars(b) if b else None)
            cache[e["sym"]] = (b, psar_serie(h), atr_serie(h)) if b else None
    entries = filter_fehlpreise([e for e in entries if cache.get(e["sym"])], cache)
    print("Einstiege in der Simulation: %d  (%s → %s)" % (
        len(entries), entries[0]["zeit"].strftime("%d.%m %H:%M"), entries[-1]["zeit"].strftime("%d.%m %H:%M")))
    print("Kosten je Runde: %.2f %%   Fenster: %d h\n" % (KOSTEN * 100, FENSTER_H))

    print("%-28s %8s %8s %8s %7s %7s %6s  %s" % (
        "Variante", "Summe$", "Ø%", "Median%", "Treffer", "Ø Std.", "offen", "häufigster Grund"))
    ergebnisse = {}
    for name, v in VARIANTEN:
        res = []
        for e in entries:
            bars, hp, ha = cache[e["sym"]]
            if v.get("halten"):
                nach = [b for b in bars if b["t"] > e["zeit"]]
                nach = [b for b in nach if b["t"] <= e["zeit"] + timedelta(hours=FENSTER_H)]
                if not nach: continue
                r = ((nach[-1]["c"] - e["preis"]) / e["preis"] * 100 - KOSTEN * 100,
                     "HALTEN", (nach[-1]["t"] - e["zeit"]).total_seconds() / 3600, False)
            else:
                r = simuliere(e, bars, hp, ha, v)
            if r: res.append((r, e))
        if not res: continue
        pcts = [r[0][0] for r in res]
        dollar = sum(r[0][0] / 100 * r[1]["einsatz"] for r in res)
        gruende = {}
        for r in res: gruende[r[0][1]] = gruende.get(r[0][1], 0) + 1
        top = sorted(gruende.items(), key=lambda x: -x[1])[:2]
        pcts_s = sorted(pcts)
        print("%-28s %8.0f %8.2f %8.2f %6.0f%% %7.1f %6d  %s" % (
            name, dollar, sum(pcts) / len(pcts), pcts_s[len(pcts_s)//2],
            sum(1 for p in pcts if p > 0) / len(pcts) * 100,
            sum(r[0][2] for r in res) / len(res),
            sum(1 for r in res if r[0][3]),
            ", ".join("%s %d" % (g, n) for g, n in top)))
        ergebnisse[name] = res
    return ergebnisse

if __name__ == "__main__":
    main()
