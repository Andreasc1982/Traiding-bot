#!/usr/bin/env python3
"""
momentum_backtest.py — B1 aus TODO_NEUDENKEN.md

Fee-aware Backtest des geplanten Super-Bot-Umbaus:
  12-1-Monats-Momentum + 200-Tage-Trendfilter, monatliches Rebalancing.

Regeln (vorab festgelegt, keine Parameter-Suche):
  - Universum: 28 ETFs (Sektoren, Regionen, Anleihen, Rohstoffe, Gold) —
    ETFs statt Einzelaktien, um Survivorship-Bias im Backtest zu vermeiden;
    Einzelaktien kommen erst im Vorwärtstest über den Funnel dazu.
  - Am Monatsende: 12-1-Momentum = Schluss[m−1] / Schluss[m−13] − 1
    (letzter Monat übersprungen — Standard gegen Short-Term-Reversal).
  - Nur Kandidaten über ihrer eigenen 200-Tage-Linie (Trendfilter).
  - Top 5 gleichgewichtet; weniger als 5 Kandidaten → Rest bleibt Cash (0 %).
  - Kosten: 5 bp je Seite auf den Umschlag (konservativer als Alpaca-Ist ~2 bp).

Vergleich: SPY Buy&Hold und gleichgewichtetes Universum, gleiche Datenbasis.
Ausgabe: momentum_backtest_ergebnis.md

Aufruf: python3 momentum_backtest.py [--start 2006-01-01] [--top 5]
"""
import argparse
import math
import time

import numpy as np
import pandas as pd
import requests

UNIVERSE = [
    # US-Sektoren
    "XLK", "XLE", "XLF", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB",
    # Breit / Regionen / Größe
    "SPY", "QQQ", "IWM", "EFA", "EEM",
    # Anleihen
    "TLT", "IEF", "SHY", "LQD", "HYG",
    # Sachwerte / Rohstoffe
    "GLD", "SLV", "DBC", "USO", "VNQ",
    # Themen (spätere Auflage — steigen ein, sobald Daten da sind)
    "XLRE", "XLC", "ITA", "PAVE",
]
COST_PER_SIDE = 0.0005          # 5 bp je Seite auf Umschlag
TIMEOUT = 30


def load_close(symbol, start):
    """Adjustierte Tages-Schlusskurse. Erst yfinance, sonst Yahoo-Chart-API."""
    try:
        import yfinance as yf
        df = yf.download(symbol, start=start, interval="1d", auto_adjust=True,
                         progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if not df.empty:
            return df["Close"].dropna()
    except Exception:
        pass
    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div%2Csplits")
    j = requests.get(url, timeout=TIMEOUT,
                     headers={"User-Agent": "Mozilla/5.0"}).json()
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    s = pd.Series(adj, index=pd.to_datetime(ts, unit="s").normalize(),
                  name=symbol)
    return s.dropna()


def stats(returns, freq=12):
    r = pd.Series(returns).dropna()
    eq = (1 + r).cumprod()
    years = len(r) / freq
    cagr = eq.iloc[-1] ** (1 / years) - 1
    vol = r.std(ddof=1) * math.sqrt(freq)
    dd = (eq / eq.cummax() - 1).min()
    sharpe = (r.mean() * freq) / vol if vol > 0 else float("nan")
    return cagr, vol, dd, sharpe, eq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2006-01-01")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--md", default="momentum_backtest_ergebnis.md")
    args = ap.parse_args()

    closes = {}
    for sym in UNIVERSE:
        try:
            closes[sym] = load_close(sym, args.start)
            print(f"  {sym}: {len(closes[sym])} Tage ab {closes[sym].index[0].date()}")
        except Exception as e:
            print(f"  [WARN] {sym}: {e}")
        time.sleep(0.2)

    px = pd.DataFrame(closes).sort_index()
    sma200 = px.rolling(200).mean()
    m_px = px.resample("ME").last()
    m_sma = sma200.resample("ME").last()

    mom = m_px.shift(1) / m_px.shift(13) - 1            # 12-1
    trend_ok = m_px > m_sma                              # über 200-Tage-Linie
    fwd_ret = m_px.pct_change().shift(-1)                # Rendite des Folgemonats

    months = m_px.index
    weights_prev = pd.Series(0.0, index=px.columns)
    strat_rets, dates, turnover_hist, ncand_hist = [], [], [], []

    for i, m in enumerate(months[:-1]):
        mo = mom.loc[m].dropna()
        ok = trend_ok.loc[m]
        cand = [s for s in mo.index if ok.get(s, False)]
        top = mo[cand].sort_values(ascending=False).head(args.top).index.tolist()
        w = pd.Series(0.0, index=px.columns)
        if top:
            w[top] = 1.0 / args.top                      # Rest implizit Cash
        turnover = (w - weights_prev).abs().sum()
        cost = turnover * COST_PER_SIDE
        gross = (w * fwd_ret.loc[m].fillna(0.0)).sum()
        strat_rets.append(gross - cost)
        dates.append(months[i + 1])
        turnover_hist.append(turnover)
        ncand_hist.append(len(cand))
        weights_prev = w

    strat = pd.Series(strat_rets, index=dates).dropna()
    # Warmup abschneiden: erst ab dem Monat, ab dem mom überhaupt existiert
    first_valid = mom.dropna(how="all").index[0]
    strat = strat[strat.index > first_valid]

    spy_m = m_px["SPY"].pct_change()
    spy = spy_m[strat.index]
    ew_shift = m_px.pct_change().mean(axis=1)[strat.index]   # gleichgew. Universum

    c1, v1, d1, s1, eq1 = stats(strat)
    c2, v2, d2, s2, eq2 = stats(spy)
    c3, v3, d3, s3, _ = stats(ew_shift)

    diff = (strat - spy).dropna()
    t_alpha = diff.mean() / (diff.std(ddof=1) / math.sqrt(len(diff)))

    lines = []
    lines.append("# Momentum-Backtest — Ergebnis (B1)\n")
    lines.append(f"Zeitraum: {strat.index[0].date()} bis {strat.index[-1].date()} "
                 f"({len(strat)} Monate). Regeln siehe Skriptkopf — vorab festgelegt, "
                 f"keine Parameter-Suche. Kosten {COST_PER_SIDE*1e4:.0f} bp/Seite "
                 f"auf Umschlag (Ø Umschlag {np.mean(turnover_hist):.2f}/Monat, "
                 f"Ø Kandidaten {np.mean(ncand_hist):.1f}).\n")
    lines.append("| | CAGR | Vola p.a. | max. Rückgang | Sharpe |")
    lines.append("|---|---|---|---|---|")
    lines.append(f"| **Momentum Top {args.top} (netto)** | {c1*100:.1f} % | "
                 f"{v1*100:.1f} % | {d1*100:.1f} % | {s1:.2f} |")
    lines.append(f"| SPY Buy&Hold | {c2*100:.1f} % | {v2*100:.1f} % | "
                 f"{d2*100:.1f} % | {s2:.2f} |")
    lines.append(f"| Universum gleichgewichtet | {c3*100:.1f} % | {v3*100:.1f} % | "
                 f"{d3*100:.1f} % | {s3:.2f} |")
    lines.append(f"\nMonats-Differenz Strategie − SPY: Ø {diff.mean()*1e4:.0f} bp, "
                 f"**t = {t_alpha:.2f}** (n = {len(diff)}).\n")

    # Jahresrenditen
    yr = (1 + strat).groupby(strat.index.year).prod() - 1
    yr_spy = (1 + spy).groupby(spy.index.year).prod() - 1
    lines.append("<details><summary>Jahresrenditen</summary>\n")
    lines.append("| Jahr | Strategie | SPY |")
    lines.append("|---|---|---|")
    for y in yr.index:
        lines.append(f"| {y} | {yr[y]*100:+.1f} % | {yr_spy.get(y, float('nan'))*100:+.1f} % |")
    lines.append("\n</details>\n")

    lines.append("## Ehrliche Einordnung\n")
    lines.append("Backtest, kein Nachweis: Aufnahme in Stufe 2 erst nach 3 Monaten "
                 "unverzerrtem Vorwärtstest (Portfolio-Architektur-Regel). ETF-Universum "
                 "vermeidet Survivorship-Bias, deckelt aber die Auflösung — Einzelaktien "
                 "erst im Vorwärtstest über den Funnel. Spätere ETF-Auflagen (XLRE, XLC, "
                 "PAVE) steigen erst ab Datenbeginn ein — das ist korrekt, kein Leck. "
                 "Der Drawdown zeigt, was auszuhalten wäre; der Trendfilter senkt ihn, "
                 "kostet aber in V-Erholungen Rendite.\n")

    with open(args.md, "w") as f:
        f.write("\n".join(lines))
    print(f"[BACKTEST] geschrieben: {args.md}")


if __name__ == "__main__":
    main()
