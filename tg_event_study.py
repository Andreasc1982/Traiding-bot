#!/usr/bin/env python3
"""Event-Study: sagt die Meldungsdichte eines Telegram-Kanals ETF-Renditen voraus?

Idee: pro Tag zaehlen, wie viele Nachrichten markt-relevante Stichworte treffen
(Oel / Krieg-Geopolitik). Dann pruefen, ob Tage mit ungewoehnlich hoher Dichte
eine ueberdurchschnittliche Rendite am selben oder am naechsten Handelstag haben.

    python3 tg_event_study.py "Middle East Spectator" XLE XOP ITA GLD SPY

Ohne Vorhersagekraft ist der Kanal als Signalquelle wertlos — genau das soll
der Test ehrlich zeigen koennen.
"""
import sys, csv, re, collections, statistics as st
from datetime import datetime, timedelta

CSVP = "/home/trading2025/trading_bot/tg/scan_all.csv"
csv.field_size_limit(10_000_000)

OIL = ["hormuz", "tanker", "opec", "oil", "crude", "refinery", "pipeline",
       "aramco", "barrel", "lng", "gas field"]
WAR = ["strike", "airstrike", "missile", "attack", "war", "iran", "israel",
       "houthi", "hezbollah", "ceasefire", "nuclear", "drone", "escalat"]


def load_counts(chat_sub):
    per_day = collections.Counter()
    hot_day = collections.Counter()
    for r in csv.DictReader(open(CSVP, encoding="utf-8")):
        if chat_sub.lower() not in r["chat"].lower():
            continue
        d = r["date"][:10]
        per_day[d] += 1
        t = (r["text"] or "").lower()
        if any(w in t for w in OIL) or any(w in t for w in WAR):
            hot_day[d] += 1
    return per_day, hot_day


def bars(sym, start, end):
    import yfinance as yf
    df = yf.download(sym, start=start, end=end, interval="1d",
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        return {}
    col = ("Close", sym) if ("Close", sym) in df.columns else "Close"
    import math
    out = {}
    prev = None
    for idx, val in df[col].items():
        v = float(val)
        if not math.isfinite(v) or v <= 0:
            continue
        day = idx.strftime("%Y-%m-%d")
        if prev is not None:
            r = (v / prev - 1) * 100
            if math.isfinite(r):
                out[day] = r
        prev = v
    return out


def stats(name, xs):
    if not xs:
        return "%-28s (keine Daten)" % name
    pos = sum(1 for x in xs if x > 0)
    return "%-28s n=%4d  Mittel %+6.3f%%  Median %+6.3f%%  positiv %4.1f%%" % (
        name, len(xs), sum(xs) / len(xs), st.median(xs), 100 * pos / len(xs))


def main():
    chat = sys.argv[1]
    syms = sys.argv[2:] or ["XLE", "XOP", "ITA", "SPY"]
    per_day, hot_day = load_counts(chat)
    if not per_day:
        print("Kein Kanal passend zu '%s'." % chat)
        return
    days = sorted(per_day)
    print("Kanal '%s': %d Tage, %s .. %s" % (chat, len(days), days[0], days[-1]))
    vals = sorted(hot_day.get(d, 0) for d in days)
    q90 = vals[int(len(vals) * 0.90)]
    q50 = vals[int(len(vals) * 0.50)]
    print("Markt-relevante Meldungen/Tag: Median %d, 90%%-Quantil %d, Max %d\n"
          % (q50, q90, vals[-1]))

    start = (datetime.fromisoformat(days[0]) - timedelta(days=5)).strftime("%Y-%m-%d")
    end = (datetime.fromisoformat(days[-1]) + timedelta(days=5)).strftime("%Y-%m-%d")

    for sym in syms:
        rets = bars(sym, start, end)
        if not rets:
            print("%s: keine Kursdaten" % sym)
            continue
        tdays = sorted(rets)
        idx = {d: i for i, d in enumerate(tdays)}
        same_hot, next_hot, base = [], [], []
        for d in tdays:
            h = hot_day.get(d, 0)
            base.append(rets[d])
            if h >= q90 and q90 > 0:
                same_hot.append(rets[d])
                i = idx[d]
                if i + 1 < len(tdays):
                    next_hot.append(rets[tdays[i + 1]])
        print("--- %s ---" % sym)
        print("  " + stats("alle Handelstage", base))
        print("  " + stats("Tage mit Meldungsspitze", same_hot))
        print("  " + stats("Folgetag nach Spitze", next_hot))
        if same_hot and base:
            print("  Differenz Spitze vs. Basis: %+0.3f Prozentpunkte (selber Tag), "
                  "%+0.3f (Folgetag)" % (
                      sum(same_hot) / len(same_hot) - sum(base) / len(base),
                      (sum(next_hot) / len(next_hot) - sum(base) / len(base))
                      if next_hot else float("nan")))
        print()


main()
