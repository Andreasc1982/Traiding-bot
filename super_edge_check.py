#!/usr/bin/env python3
"""Super-Bot: Kostenanteil + sagt der eigene Score ueberhaupt etwas voraus?

Zwei Fragen auf der bestehenden Historie:
 1) Wie viel des Ergebnisses fressen die Kosten? (Aktien sind kommissionsfrei,
    nur sim_slip 0,02%/Seite -> 4 bp Roundtrip.) Falls vernachlaessigbar, ist
    jedes Ergebnis reine Signalqualitaet — die Kosten-Ausrede entfaellt.
 2) Korreliert score_pct (unser gewichteter Indikator-Score) beim Einstieg mit
    dem tatsaechlichen Ergebnis? Wenn nicht, ist das Herzstueck des Bots blind.

    python3 super_edge_check.py [datei.json ...]
"""
import json, glob, sys, math, statistics as st

SLIP = 0.0002          # je Seite (super_bot sim_slip)
COST_BP = 2 * SLIP * 10000


def tstat(xs):
    if len(xs) < 3:
        return 0.0
    sd = st.pstdev(xs)
    return (st.mean(xs) / (sd / math.sqrt(len(xs)))) if sd else 0.0


def corr(a, b):
    if len(a) < 3:
        return 0.0
    ma, mb = st.mean(a), st.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da and db else 0.0


def main():
    files = sys.argv[1:] or sorted(glob.glob(
        "/home/trading2025/trading_bot/trades_history*.json"))
    trades = []
    for f in files:
        try:
            d = json.load(open(f))
            if isinstance(d, list):
                trades += d
        except Exception:
            pass
    trades = [t for t in trades if t.get("pnl_pct") is not None]
    if not trades:
        print("Keine Trades gefunden.")
        return

    pnl = [float(t["pnl_pct"]) for t in trades]
    print("=== 1) Kostenanteil ===")
    print("Trades: %d | Mittel %+0.3f%% | Median %+0.3f%% | Win-Rate %.1f%% | t=%.2f"
          % (len(pnl), st.mean(pnl), st.median(pnl),
             100 * sum(1 for x in pnl if x > 0) / len(pnl), tstat(pnl)))
    print("Roundtrip-Kosten: %.1f bp = %.3f%% — das sind %.1f%% der mittleren "
          "Bewegung (|%.3f%%|)." % (COST_BP, COST_BP / 100,
                                    100 * (COST_BP / 100) / abs(st.mean(pnl))
                                    if st.mean(pnl) else 0, abs(st.mean(pnl))))
    print("Vergleich: Crypto-Clones 62 bp, dYdX-Taker 10 bp, DEX-Paper 1000 bp.\n")

    reasons = {}
    for t in trades:
        reasons.setdefault(t.get("reason", "?"), []).append(float(t["pnl_pct"]))
    print("Exit-Gruende:")
    for r, xs in sorted(reasons.items(), key=lambda x: -len(x[1])):
        print("  %-20s n=%3d  Mittel %+0.2f%%" % (r, len(xs), st.mean(xs)))

    feat = [t for t in trades if isinstance(t.get("features"), dict)]
    print("\n=== 2) Sagt der eigene Score das Ergebnis voraus? ===")
    if len(feat) < 8:
        print("Nur %d Trades mit Features — zu wenig fuer eine Aussage." % len(feat))
        return
    print("%d Trades mit gespeicherten Einstiegs-Features\n" % len(feat))
    keys = ["score_pct", "adx", "rsi", "cmf", "macd_hist", "stoch_k",
            "ma_dist_pct", "fg_value"]
    print("%-14s %10s %28s" % ("Feature", "Korr.", "oberes vs unteres Drittel"))
    y = [float(t["pnl_pct"]) for t in feat]
    for k in keys:
        try:
            x = [float(t["features"].get(k, 0) or 0) for t in feat]
        except Exception:
            continue
        if len(set(x)) < 3:
            print("%-14s %10s %28s" % (k, "konstant", "-"))
            continue
        c = corr(x, y)
        order = sorted(zip(x, y))
        n3 = max(len(order) // 3, 2)
        lo = [v for _, v in order[:n3]]
        hi = [v for _, v in order[-n3:]]
        print("%-14s %+10.3f   hoch %+0.2f%% vs niedrig %+0.2f%%  (Delta %+0.2f)"
              % (k, c, st.mean(hi), st.mean(lo), st.mean(hi) - st.mean(lo)))
    print("\nKorrelation nahe 0 = das Feature trennt Gewinner nicht von Verlierern.")
    print("Bei n=%d ist |Korr.| unter ~%.2f statistisch bedeutungslos."
          % (len(feat), 2 / math.sqrt(len(feat))))


main()
