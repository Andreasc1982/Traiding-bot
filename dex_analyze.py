#!/usr/bin/env python3
"""Analyse: Was trennt die Gewinner von den Verlierern im DEX Paper-Moonshot?
Joint paper_trades.json (Ergebnis) gegen screening_log.csv (Entry-Charakteristik je Token,
zur Zeit des Kaufs) und sucht trennende Muster: Liquidität, Volumen, Momentum, Alter,
Buy/Sell-Druck. Plus Win-Rate/P&L nach Buckets."""
import json, csv, os, statistics
from datetime import datetime

BASE = "/home/trading2025/trading_bot/dex"
trades = json.load(open(os.path.join(BASE, "paper_trades.json")))

# screening_log: addr -> [(dt, liq, vol5, buys, sells, chg5, age_h, rug_risk)]
by_addr = {}
with open(os.path.join(BASE, "screening_log.csv")) as f:
    rd = csv.reader(f)
    next(rd, None)
    for row in rd:
        if len(row) < 13:
            continue
        try:
            dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M")
            by_addr.setdefault(row[1], []).append(
                (dt, float(row[4]), float(row[5]), int(row[6]), int(row[7]),
                 float(row[8]), float(row[9]), row[11]))
        except Exception:
            continue


def feat(t):
    rows = by_addr.get(t.get("addr"), [])
    if not rows:
        return None
    try:
        op = datetime.strptime(t.get("opened", ""), "%Y-%m-%d %H:%M")
        before = [x for x in rows if x[0] <= op]
        return max(before, key=lambda x: x[0]) if before else \
            min(rows, key=lambda x: abs((x[0] - op).total_seconds()))
    except Exception:
        return rows[0]


win, los = [], []
for t in trades:
    rec = {"t": t, "f": feat(t)}
    (win if t.get("profit", 0) > 0 else los).append(rec)

matched = sum(1 for r in win + los if r["f"])
print("=" * 58)
print("  GEWINNER vs VERLIERER — Entry-Charakteristik")
print("  %d Trades | %d Gewinner / %d Verlierer | %d/%d gematcht"
      % (len(trades), len(win), len(los), matched, len(trades)))
print("=" * 58)


def med(recs, idx):
    v = [r["f"][idx] for r in recs if r["f"]]
    return statistics.median(v) if v else 0


print("\n%-20s %14s %14s" % ("Dimension (Median)", "GEWINNER", "VERLIERER"))
for name, idx in [("Liquidität $", 1), ("Volumen 5m $", 2), ("Momentum 5m %", 5), ("Alter h", 6)]:
    print("%-20s %14.1f %14.1f" % (name, med(win, idx), med(los, idx)))


def bsr(recs):
    v = [r["f"][3] / r["f"][4] for r in recs if r["f"] and r["f"][4] > 0]
    return statistics.median(v) if v else 0


print("%-20s %14.2f %14.2f" % ("Buy/Sell-Ratio", bsr(win), bsr(los)))


def buckets(title, idx, edges, fmt):
    print("\n" + title)
    allr = [r for r in win + los if r["f"]]
    for lo, hi in edges:
        sub = [r for r in allr if lo <= r["f"][idx] < hi]
        if not sub:
            continue
        w = sum(1 for r in sub if r["t"].get("profit", 0) > 0)
        pnl = sum(r["t"].get("profit", 0) for r in sub)
        print("  %-14s %2d Trades | %2d Gew (%3.0f%%) | P&L $%+7.2f"
              % (fmt(lo, hi), len(sub), w, 100 * w / len(sub), pnl))


buckets("== Win-Rate nach Entry-Momentum (chg5) ==", 5,
        [(-1e9, 0), (0, 25), (25, 50), (50, 100), (100, 1e9)],
        lambda lo, hi: ("%d–%d%%" % (lo, hi)) if abs(lo) < 1e8 and hi < 1e8 else
        ("<0%" if lo < -1e8 else ">100%"))
buckets("== Win-Rate nach Liquidität ==", 1,
        [(0, 20000), (20000, 50000), (50000, 1e12)],
        lambda lo, hi: "$%dk–%s" % (lo // 1000, ("%dk" % (hi // 1000)) if hi < 1e11 else "+"))
buckets("== Win-Rate nach Alter ==", 6,
        [(0, 2), (2, 6), (6, 24), (24, 1e9)],
        lambda lo, hi: "%g–%gh" % (lo, hi) if hi < 1e8 else ">24h")

# Exit-Reason-Aufschlüsselung
print("\n== Exit-Gründe (Gewinner / Verlierer) ==")
from collections import Counter
wc = Counter(r["t"].get("reason") for r in win)
lc = Counter(r["t"].get("reason") for r in los)
for reason in set(wc) | set(lc):
    print("  %-12s Gew %2d | Verl %2d" % (reason, wc.get(reason, 0), lc.get(reason, 0)))

# Struktur-Mathe: ab welchem Peak lohnt der 30%-Trail?
print("\n== Struktur: 30%%-Trailing ==")
print("  Trail feuert bei Peak x 0.70. Damit der Exit >= Entry liegt,")
print("  muss der Token mind. +43%% gepumpt haben (1/0.70 - 1).")
print("  Tokens die nur +10-40%% poppen -> Trail-Exit IM MINUS.")
