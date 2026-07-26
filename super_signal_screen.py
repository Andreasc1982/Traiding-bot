#!/usr/bin/env python3
"""Signal-Screening: welche Kennzahl hat ueberhaupt Querschnitts-Vorhersagekraft?

Nachdem der eigene Indikator-Score im Querschnitt nichts vorhersagt, wird hier
systematisch gesucht statt geraten. Gleiche Maschinerie, viele Kandidaten:
klassische Anomalien (Momentum, Reversal, Low-Vol, 52W-Hoch) UND die
Einzelbausteine unseres eigenen Scores — um zu sehen, ob die Aggregation das
Signal zerstoert oder ob nie eins da war.

Panel wird beim ersten Lauf geladen und gecacht -> weitere Laeufe in Sekunden.

    python3 super_signal_screen.py [anzahl_titel] [jahre] [--refresh]
"""
import sys, os, json, time, math, pickle, urllib.request, collections
import statistics as st
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, "/home/trading2025/trading_bot")
sys.path.insert(0, "/home/trading2025/trading_bot/agents")
from config import config

CACHE = None   # wird nach dem Parsen der Argumente gesetzt (je Groesse/Zeitraum eigener Cache)
N_SYMS = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 400
YEARS = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 3
REFRESH = "--refresh" in sys.argv
NONOVER = "--nonoverlap" in sys.argv   # nur jeder h-te Tag -> keine ueberlappenden Fenster
CACHE = "/home/trading2025/trading_bot/agents/panel_%dx%dy.pkl" % (N_SYMS, YEARS)
CHUNK, WARMUP = 40, 260
HORIZONS = [1, 5, 20]
MIN_DOLLAR_VOL = 5e6


# ── Panel laden ──────────────────────────────────────────────────────────────
def universe(n):
    req = urllib.request.Request(
        "https://paper-api.alpaca.markets/v2/assets?status=active&asset_class=us_equity",
        headers={"APCA-API-KEY-ID": config.get("alpaca_api_key"),
                 "APCA-API-SECRET-KEY": config.get("alpaca_secret_key")})
    with urllib.request.urlopen(req, timeout=60) as r:
        assets = json.loads(r.read().decode())
    syms = sorted(a["symbol"] for a in assets
                  if a.get("tradable") and a.get("exchange") in ("NYSE", "NASDAQ")
                  and a.get("symbol", "").isalpha() and len(a.get("symbol", "")) <= 4
                  and not a.get("symbol", "").endswith("W"))
    step = max(len(syms) // n, 1)
    return syms[::step][:n]


def load_panel():
    if os.path.exists(CACHE) and not REFRESH:
        with open(CACHE, "rb") as f:
            d = pickle.load(f)
        print("Panel aus Cache: %d Titel\n" % len(d))
        return d
    import yfinance as yf
    syms = universe(N_SYMS)
    print("Lade %d Titel, %d Jahre..." % (len(syms), YEARS), flush=True)
    out = {}
    for i in range(0, len(syms), CHUNK):
        part = syms[i:i + CHUNK]
        try:
            df = yf.download(part, period="%dy" % YEARS, interval="1d",
                             progress=False, auto_adjust=True, threads=True,
                             group_by="ticker")
        except Exception:
            continue
        for s in part:
            try:
                sub = df[s].dropna()
                if len(sub) < WARMUP + 120:
                    continue
                cl = [float(x) for x in sub["Close"].values]
                vo = [float(x) for x in sub["Volume"].values]
                if st.median([c * v for c, v in zip(cl[-60:], vo[-60:])]) < MIN_DOLLAR_VOL:
                    continue
                out[s] = {"dates": [d.strftime("%Y-%m-%d") for d in sub.index],
                          "highs": [float(x) for x in sub["High"].values],
                          "lows": [float(x) for x in sub["Low"].values],
                          "closes": cl, "volumes": vo}
            except Exception:
                continue
        print("  %d/%d -> %d brauchbar" % (min(i + CHUNK, len(syms)), len(syms),
                                           len(out)), flush=True)
        time.sleep(0.4)
    with open(CACHE, "wb") as f:
        pickle.dump(out, f)
    print("\nPanel gecacht: %d Titel\n" % len(out))
    return out


# ── Kandidaten-Signale (alle: hoeher = erwartet besser) ──────────────────────
def build_signals(bars):
    c, h, l, v = bars["closes"], bars["highs"], bars["lows"], bars["volumes"]
    n = len(c)
    sig = collections.defaultdict(lambda: [None] * n)
    for i in range(WARMUP, n):
        w20 = c[i - 20:i + 1]
        w60 = c[i - 60:i + 1]
        r = [c[j] / c[j - 1] - 1 for j in range(i - 59, i + 1)]
        vol60 = st.pstdev(r) if len(r) > 2 else None
        # klassische Anomalien
        sig["mom_12_1"][i] = c[i - 21] / c[i - 252] - 1 if i >= 252 else None
        sig["mom_6m"][i] = c[i] / c[i - 126] - 1 if i >= 126 else None
        sig["reversal_5d"][i] = -(c[i] / c[i - 5] - 1)
        sig["reversal_1m"][i] = -(c[i] / c[i - 21] - 1)
        sig["low_vol"][i] = -vol60 if vol60 else None
        sig["dist_52w_hoch"][i] = c[i] / max(c[max(0, i - 252):i + 1]) - 1
        sig["vol_schub"][i] = (st.mean(v[i - 4:i + 1]) / st.mean(v[i - 60:i + 1]) - 1
                               if st.mean(v[i - 60:i + 1]) > 0 else None)
        # Bausteine unseres eigenen Scores
        sig["ma20_abstand"][i] = c[i] / st.mean(w20) - 1
        sig["ma60_abstand"][i] = c[i] / st.mean(w60) - 1
        gains = [max(c[j] - c[j - 1], 0) for j in range(i - 13, i + 1)]
        losses = [max(c[j - 1] - c[j], 0) for j in range(i - 13, i + 1)]
        ag, al = st.mean(gains), st.mean(losses)
        rsi = 100 - 100 / (1 + ag / al) if al > 0 else 100.0
        sig["rsi_niedrig"][i] = -rsi
        mfm = []
        for j in range(i - 19, i + 1):
            rng = h[j] - l[j]
            mfm.append(((2 * c[j] - h[j] - l[j]) / rng * v[j]) if rng > 0 else 0.0)
        sv = sum(v[i - 19:i + 1])
        sig["cmf"][i] = sum(mfm) / sv if sv > 0 else None
    return sig


def spearman(a, b):
    def rk(x):
        o = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        for p, i in enumerate(o):
            r[i] = p
        return r
    ra, rb = rk(a), rk(b)
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return num / (da * db) if da and db else 0.0


def main():
    data = load_panel()
    if len(data) < 30:
        print("Panel zu klein.")
        return
    print("Berechne Kandidaten-Signale...", flush=True)
    sigs, closes, dates_of = {}, {}, {}
    for s, bars in data.items():
        try:
            sigs[s] = build_signals(bars)
            closes[s] = bars["closes"]
            dates_of[s] = bars["dates"]
        except Exception:
            continue
    names = sorted({k for s in sigs for k in sigs[s]})
    by_date = collections.defaultdict(list)
    for s in sigs:
        for i, d in enumerate(dates_of[s]):
            by_date[d].append((s, i))
    dates = sorted(d for d in by_date if len(by_date[d]) >= 30)
    print("%d Titel, %d Handelstage\n" % (len(sigs), len(dates)), flush=True)

    for h in HORIZONS:
        print("=== Horizont +%d Handelstage%s ===" % (h, " (ueberlappungsfrei)" if NONOVER else ""))
        print("%-16s %8s %14s %9s %10s %11s" % ("Signal", "Tage", "Dezil-Spanne",
                                                "t-Wert", "positiv", "Rang-Korr."))
        rows = []
        use_dates = dates[::h] if NONOVER else dates
        for name in names:
            spreads, ics = [], []
            for d in use_dates:
                xs, ys = [], []
                for s, i in by_date[d]:
                    val = sigs[s][name][i] if i < len(sigs[s][name]) else None
                    cl = closes[s]
                    if val is None or i + h >= len(cl) or cl[i] <= 0:
                        continue
                    xs.append(val)
                    ys.append((cl[i + h] / cl[i] - 1) * 100)
                if len(xs) < 30:
                    continue
                order = sorted(range(len(xs)), key=lambda j: xs[j])
                k = max(len(order) // 10, 3)
                spreads.append(st.mean([ys[j] for j in order[-k:]])
                               - st.mean([ys[j] for j in order[:k]]))
                ics.append(spearman(xs, ys))
            if len(spreads) < 20:
                continue
            m, sd = st.mean(spreads), st.pstdev(spreads)
            t = m / (sd / math.sqrt(len(spreads))) if sd else 0
            rows.append((abs(t), name, len(spreads), m, t,
                         100 * sum(1 for x in spreads if x > 0) / len(spreads),
                         st.mean(ics)))
        for _, name, n, m, t, pos, ic in sorted(rows, reverse=True):
            mark = "  <<<" if abs(t) >= 2 and m > 0.04 else ""
            print("%-16s %8d %13.4f%% %9.2f %9.1f%% %11.4f%s"
                  % (name, n, m, t, pos, ic, mark))
        print()
    print("<<< = statistisch belastbar UND ueber der Kostenschwelle (0,04%).")
    print("Survivorship-Bias schoent nach oben — Negatives ist belastbarer.")


main()
