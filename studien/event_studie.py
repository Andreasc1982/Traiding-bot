#!/usr/bin/env python3
"""
event_studie.py — B3 aus TODO_NEUDENKEN.md

Event-Studie auf historischen Tagesdaten (yfinance) für die beiden ältesten
Einträge der Leads-Liste:

  1. QUARTALSENDE / MONATSWECHSEL ("turn of the quarter"):
     mittlere SPY-Tagesrendite je Handelstag-Offset rund um das Quartalsende
     (T-4 .. T+3) gegen alle übrigen Tage. t-Statistik je Offset.

  2. RUSSELL-REKONSTITUTION (letzter Juni-Freitag, Näherung):
     IWM-minus-SPY-Tagesspread in den 5 Handelstagen vor und nach dem
     Rekonstitutionstag gegen den Rest des Jahres. Misst, ob der viel
     zitierte Rebalancing-Druck für uns handelbar wäre.

Ehrlichkeitsregeln: adjustierte Kurse, t-Werte immer mit ausgegeben,
Kosten-Fußnote (Alpaca ~4 bp Roundtrip), keine Parameter-Suche — die Fenster
sind vorab festgelegt (T-4..T+3 bzw. ±5 Tage), nicht optimiert.

Aufruf: python3 event_studie.py [--md ergebnis.md] [--start 2005-01-01]
"""
import argparse
import math
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf


def tstat(x):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 3 or x.std(ddof=1) == 0:
        return float("nan")
    return x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))


def _load_chart_api(symbol, start):
    """Fallback ohne yfinance: Yahoo-Chart-API direkt (adjustierte Schlusskurse)."""
    import time as _t
    import requests as _rq
    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int(_t.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div%2Csplits")
    j = _rq.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).json()
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    df = pd.DataFrame({"Close": adj},
                      index=pd.to_datetime(ts, unit="s").normalize())
    return df.dropna()


def load(symbol, start):
    df = yf.download(symbol, start=start, interval="1d", auto_adjust=True,
                     progress=False)
    if isinstance(df.columns, pd.MultiIndex):          # bekannte yfinance-Falle
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    if df.empty:                                       # yfinance geblockt/leer → Chart-API
        df = _load_chart_api(symbol, start)
    df["ret"] = df["Close"].pct_change()
    return df.dropna()


def quarter_end_offsets(idx):
    """Handelstag-Offset zum Quartalsende: 0 = letzter Handelstag des Quartals,
    -1 = vorletzter, +1 = erster des Folgequartals usw."""
    q = pd.PeriodIndex(idx, freq="Q")
    offsets = np.full(len(idx), 99, dtype=int)
    # Positionen der letzten Handelstage je Quartal
    last_pos = {}
    for i, (ts, qq) in enumerate(zip(idx, q)):
        last_pos[qq] = i
    for qq, pos in last_pos.items():
        for off in range(-4, 0):                        # T-4 .. T-1
            j = pos + off + 0
            if 0 <= pos + off < len(idx) and q[pos + off] == qq:
                offsets[pos + off] = off
        offsets[pos] = 0                                # T0
        for off in range(1, 4):                         # T+1 .. T+3
            if pos + off < len(idx):
                offsets[pos + off] = off
    return offsets


def last_friday_of_june(year):
    d = date(year, 6, 30)
    while d.weekday() != 4:
        d = d.replace(day=d.day - 1)
    return pd.Timestamp(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="event_studie_ergebnis.md")
    ap.add_argument("--start", default="2005-01-01")
    args = ap.parse_args()

    spy = load("SPY", args.start)
    iwm = load("IWM", args.start)

    lines = [f"# Event-Studie Quartalsende + Russell (B3)\n",
             f"Daten: SPY/IWM adjustiert, {args.start} bis {spy.index[-1].date()}, "
             f"{len(spy)} Handelstage. Fenster vorab festgelegt, nicht optimiert.\n"]

    # ---------- 1. Quartalsende ----------
    off = quarter_end_offsets(spy.index)
    base = spy["ret"].values[off == 99]
    lines.append("\n## 1. Quartalsende (SPY, Tagesrendite je Offset)\n")
    lines.append("| Offset | Ø Rendite bp | t | n | vs. Normaltag bp |")
    lines.append("|---|---|---|---|---|")
    base_mean = np.nanmean(base) * 1e4
    for o in range(-4, 4):
        r = spy["ret"].values[off == o]
        lines.append(f"| T{o:+d} | {np.nanmean(r)*1e4:.1f} | {tstat(r):.2f} | "
                     f"{len(r)} | {np.nanmean(r)*1e4 - base_mean:+.1f} |")
    lines.append(f"| Normaltage | {base_mean:.1f} | {tstat(base):.2f} | {len(base)} | — |")

    # ---------- 2. Russell-Rekonstitution ----------
    both = pd.DataFrame({"spy": spy["ret"], "iwm": iwm["ret"]}).dropna()
    spread = both["iwm"] - both["spy"]
    years = sorted(set(both.index.year))
    pre_all, post_all, per_year = [], [], []
    for y in years:
        recon = last_friday_of_june(y)
        pos = both.index.searchsorted(recon, side="right") - 1
        if pos < 5 or pos + 5 >= len(both):
            continue
        pre = spread.iloc[pos - 4:pos + 1].sum()        # T-4..T0 (inkl. Recon-Tag)
        post = spread.iloc[pos + 1:pos + 6].sum()       # T+1..T+5
        pre_all.append(pre)
        post_all.append(post)
        per_year.append((y, pre * 1e4, post * 1e4))
    rest = spread.values
    lines.append("\n## 2. Russell-Rekonstitution (IWM − SPY, kumulierter 5-Tage-Spread)\n")
    lines.append("| Fenster | Ø kum. Spread bp | t | n Jahre |")
    lines.append("|---|---|---|---|")
    lines.append(f"| T-4..T0 (vor/inkl. Recon-Freitag) | {np.mean(pre_all)*1e4:.0f} | "
                 f"{tstat(pre_all):.2f} | {len(pre_all)} |")
    lines.append(f"| T+1..T+5 (danach) | {np.mean(post_all)*1e4:.0f} | "
                 f"{tstat(post_all):.2f} | {len(post_all)} |")
    lines.append(f"| Referenz: beliebige 5 Tage | {np.nanmean(rest)*5*1e4:.0f} | — | — |")
    lines.append("\n<details><summary>Einzeljahre (bp)</summary>\n")
    lines.append("| Jahr | vor | nach |")
    lines.append("|---|---|---|")
    for y, a, b in per_year:
        lines.append(f"| {y} | {a:+.0f} | {b:+.0f} |")
    lines.append("\n</details>")

    lines.append("\n## Lesehilfe\n")
    lines.append("Handelbar ist ein Effekt erst, wenn |t| ≥ 2 UND der Effekt nach Kosten "
                 "(~4 bp Roundtrip Alpaca) und in einem Vorwärtstest bestehen bleibt. "
                 "Alles darunter ist Beobachtung, kein Signal.\n")

    with open(args.md, "w") as f:
        f.write("\n".join(lines))
    print(f"[EVENT-STUDIE] geschrieben: {args.md}")


if __name__ == "__main__":
    main()
