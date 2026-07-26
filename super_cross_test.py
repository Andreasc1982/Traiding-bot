#!/usr/bin/env python3
"""Hat unser Indikator-Score QUERSCHNITTS-Vorhersagekraft? — sofort, nicht in einem Jahr.

Der Trick: der gewichtete Indikator-Score ist DETERMINISTISCH aus Kursdaten
berechenbar. Man muss ihn also nicht vorwaerts sammeln — er laesst sich fuer
Hunderte Aktien ueber Jahre rueckwirkend rekonstruieren. Damit wird aus einem
Test, der mit 10 ETFs ein halbes Jahr braucht, eine Rechnung von Minuten.

Getestet wird genau das, was der Bot entscheidet: je Handelstag alle Titel nach
Score sortieren und messen, ob das obere Dezil das untere schlaegt.

NICHT enthalten: die Sentiment-Schicht (News/Congress/VIP) — die ist nur live
messbar und laeuft ueber super_score_log.py weiter.

    python3 super_cross_test.py [anzahl_titel] [jahre]
"""
import sys, json, time, math, urllib.request, collections, statistics as st
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, "/home/trading2025/trading_bot")
sys.path.insert(0, "/home/trading2025/trading_bot/agents")
from config import config
from backtest_super_strictness import precompute            # exakte Score-Bausteine

N_SYMS = int(sys.argv[1]) if len(sys.argv) > 1 else 400
YEARS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
CHUNK = 40
WARMUP = 100
HORIZONS = [1, 5, 20]           # Handelstage
MIN_DOLLAR_VOL = 5e6
COST_PCT = 0.04                 # Roundtrip in % (4 bp)


def universe(n):
    """Aktive, handelbare US-Aktien von NYSE/NASDAQ ueber Alpaca."""
    key, sec = config.get("alpaca_api_key"), config.get("alpaca_secret_key")
    req = urllib.request.Request(
        "https://paper-api.alpaca.markets/v2/assets?status=active&asset_class=us_equity",
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
    with urllib.request.urlopen(req, timeout=60) as r:
        assets = json.loads(r.read().decode())
    syms = [a["symbol"] for a in assets
            if a.get("tradable") and a.get("exchange") in ("NYSE", "NASDAQ")
            and a.get("symbol", "").isalpha() and len(a.get("symbol", "")) <= 4
            and not a.get("symbol", "").endswith("W")]
    syms.sort()
    step = max(len(syms) // n, 1)
    return syms[::step][:n], len(syms)


def download(syms, years):
    import yfinance as yf
    out = {}
    for i in range(0, len(syms), CHUNK):
        part = syms[i:i + CHUNK]
        try:
            df = yf.download(part, period="%dy" % years, interval="1d",
                             progress=False, auto_adjust=True, threads=True,
                             group_by="ticker")
        except Exception as e:
            print("  Chunk-Fehler:", str(e)[:60], flush=True)
            continue
        for s in part:
            try:
                sub = df[s].dropna()
                if len(sub) < WARMUP + 120:
                    continue
                closes = [float(x) for x in sub["Close"].values]
                vols = [float(x) for x in sub["Volume"].values]
                dv = st.median([c * v for c, v in zip(closes[-60:], vols[-60:])])
                if dv < MIN_DOLLAR_VOL:
                    continue
                out[s] = {"dates": [d.strftime("%Y-%m-%d") for d in sub.index],
                          "highs": [float(x) for x in sub["High"].values],
                          "lows": [float(x) for x in sub["Low"].values],
                          "closes": closes, "volumes": vols}
            except Exception:
                continue
        print("  %d/%d geladen, %d brauchbar" % (min(i + CHUNK, len(syms)),
                                                 len(syms), len(out)), flush=True)
        time.sleep(0.5)
    return out


def scores_for(bars):
    """score_pct je Tag — exakt die Live-Formel (VWAP im Tagesmodell neutral)."""
    pc = precompute(bars)
    n = pc["n"]
    c, rsi, ma20 = pc["closes"], pc["rsi"], pc["ma20"]
    macd_ok, stt, ichi_ok = pc["macd_ok"], pc["st"], pc["ichi_ok"]
    cmf, stoch_ok = pc["cmf"], pc["stoch_ok"]
    out = [None] * n
    for i in range(WARMUP, n):
        if ma20[i] is None or rsi[i] is None or cmf[i] is None:
            continue
        s = ((rsi[i] < 75) * 1.5 + macd_ok[i] * 1.5 + (stt[i] == 1) * 1.5 +
             ichi_ok[i] * 1.2 + (c[i] > ma20[i]) * 1.0 + (cmf[i] > 0) * 0.8 +
             stoch_ok[i] * 0.5 + 1 * 0.5)
        out[i] = s / 8.5
    return out


def spearman(a, b):
    def rank(x):
        order = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        for pos, i in enumerate(order):
            r[i] = pos
        return r
    ra, rb = rank(a), rank(b)
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return num / (da * db) if da and db else 0.0


def main():
    syms, total = universe(N_SYMS)
    print("Universum: %d von %d handelbaren US-Aktien (gleichmaessige Stichprobe)\n"
          % (len(syms), total), flush=True)
    print("Lade %d Jahre Tagesdaten..." % YEARS, flush=True)
    data = download(syms, YEARS)
    if len(data) < 30:
        print("Zu wenige Titel mit Daten (%d)." % len(data))
        return
    print("\n%d Titel mit ausreichender Historie und Liquiditaet\n" % len(data), flush=True)

    print("Berechne Scores...", flush=True)
    panel = collections.defaultdict(dict)     # datum -> sym -> (score, close_idx)
    series = {}
    for s, bars in data.items():
        try:
            sc = scores_for(bars)
        except Exception:
            continue
        series[s] = bars["closes"]
        for i, d in enumerate(bars["dates"]):
            if sc[i] is not None:
                panel[d][s] = (sc[i], i)

    dates = sorted(panel)
    print("%d Handelstage im Panel, im Mittel %.0f Titel je Tag\n"
          % (len(dates), st.mean([len(panel[d]) for d in dates])), flush=True)

    print("=== Querschnitts-Test: oberes Dezil minus unteres Dezil ===")
    print("%-8s %8s %14s %10s %10s %12s" % ("Horizont", "Tage", "Spanne/Trade",
                                            "t-Wert", "positiv", "Rang-Korr."))
    for h in HORIZONS:
        spreads, ics = [], []
        for d in dates:
            row = panel[d]
            if len(row) < 30:
                continue
            items, rets = [], []
            for s, (sc, i) in row.items():
                cl = series[s]
                if i + h >= len(cl) or cl[i] <= 0:
                    continue
                items.append((sc, s))
                rets.append((cl[i + h] / cl[i] - 1) * 100)
            if len(items) < 30:
                continue
            order = sorted(range(len(items)), key=lambda j: items[j][0])
            k = max(len(order) // 10, 3)
            lo = st.mean([rets[j] for j in order[:k]])
            hi = st.mean([rets[j] for j in order[-k:]])
            spreads.append(hi - lo)
            ics.append(spearman([items[j][0] for j in range(len(items))], rets))
        if len(spreads) < 20:
            print("%-8s zu wenige Tage (%d)" % ("+%dT" % h, len(spreads)))
            continue
        m, sd = st.mean(spreads), st.pstdev(spreads)
        t = m / (sd / math.sqrt(len(spreads))) if sd else 0
        print("%-8s %8d %13.4f%% %10.2f %9.1f%% %12.4f"
              % ("+%dT" % h, len(spreads), m, t,
                 100 * sum(1 for x in spreads if x > 0) / len(spreads), st.mean(ics)))

    print("\nKosten-Massstab: %.2f%% Roundtrip. Handelbar waere eine Spanne klar" % COST_PCT)
    print("darueber mit |t| >= 2. Rang-Korrelation (IC) ueber 0,02 gilt in der")
    print("Praxis bereits als brauchbar, ueber 0,05 als gut.")
    print("\nWARNUNG Survivorship-Bias: das Universum sind HEUTE handelbare Titel.")
    print("Das schoent das Ergebnis nach oben — ein negatives Resultat ist damit")
    print("umso belastbarer, ein knapp positives mit Vorsicht zu geniessen.")


main()
