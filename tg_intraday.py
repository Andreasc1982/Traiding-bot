#!/usr/bin/env python3
"""Latenz-Test: laufen Meldungen des Kanals der Kursbewegung VORAUS oder hinterher?

Tagesbars koennen das nicht beantworten (Meldung und Bewegung fallen auf denselben
Tag). Hier auf Stundenbasis: fuer jede Boersenstunde zaehlen, wie viele
markt-relevante Meldungen in DIESER Stunde kamen, und dann die Rendite der
FOLGENDEN Stunde messen. Nur wenn die Folgestunde systematisch steigt, ist der
Kanal handelbar — sonst ist er nur Begleitmusik zur schon gelaufenen Bewegung.

    python3 tg_intraday.py XOP XLE ITA
"""
import sys, csv, math, collections, statistics as st
from datetime import datetime, timedelta, timezone

CSVP = "/home/trading2025/trading_bot/tg/scan_all.csv"
csv.field_size_limit(10_000_000)
CHAT = "Middle East"

OIL = ["hormuz", "tanker", "opec", "oil", "crude", "refinery", "pipeline",
       "aramco", "barrel"]
WAR = ["strike", "airstrike", "missile", "attack", "war", "iran", "israel",
       "houthi", "hezbollah", "ceasefire", "nuclear", "drone", "escalat"]


def load_hourly(cutoff):
    """Zeitstempel aller markt-relevanten Meldungen im Fenster (UTC, sortiert)."""
    stamps = []
    for r in csv.DictReader(open(CSVP, encoding="utf-8")):
        if CHAT.lower() not in r["chat"].lower():
            continue
        try:
            dt = datetime.fromisoformat(r["date"])
        except Exception:
            continue
        if dt < cutoff:
            continue
        t = (r["text"] or "").lower()
        if any(w in t for w in OIL) or any(w in t for w in WAR):
            stamps.append(dt.astimezone(timezone.utc))
    stamps.sort()
    return stamps


def count_between(stamps, t0, t1):
    import bisect
    return bisect.bisect_left(stamps, t1) - bisect.bisect_left(stamps, t0)


def main():
    syms = sys.argv[1:] or ["XOP", "XLE", "ITA"]
    import yfinance as yf
    import warnings
    warnings.filterwarnings("ignore")

    cutoff = datetime.now(timezone.utc) - timedelta(days=59)
    stamps = load_hourly(cutoff)
    if not stamps:
        print("Keine Nachrichten im 60-Tage-Fenster.")
        return
    print("Fenster: letzte 59 Tage | %d markt-relevante Meldungen\n" % len(stamps))

    for sym in syms:
        df = yf.download(sym, period="59d", interval="60m",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            print("%s: keine Daten" % sym)
            continue
        col = ("Close", sym) if ("Close", sym) in df.columns else "Close"
        ser = [(idx.to_pydatetime().astimezone(timezone.utc), float(v))
               for idx, v in df[col].items() if math.isfinite(float(v))]
        rows = []
        for i in range(len(ser) - 1):
            t0, p0 = ser[i]
            t1, p1 = ser[i + 1]
            if (t1 - t0) > timedelta(hours=2):
                continue                      # Tageswechsel ueberspringen
            n = count_between(stamps, t0, t1)  # Meldungen WAEHREND dieser Bar
            rows.append((n, (p1 / p0 - 1) * 100))
        if not rows:
            print("%s: keine Bars\n" % sym)
            continue
        counts = sorted(r[0] for r in rows)
        q80 = counts[int(len(counts) * 0.80)]
        hot = [r for n, r in rows if n >= max(q80, 1)]
        base = [r for _, r in rows]
        print("  (Meldungen je Boersenstunde: Median %d, 80%%-Quantil %d, Max %d)"
              % (st.median(counts), q80, counts[-1]))

        def line(name, xs):
            if not xs:
                return "%-30s (keine)" % name
            return ("%-30s n=%4d  Mittel %+6.3f%%  Median %+6.3f%%  positiv %4.1f%%"
                    % (name, len(xs), sum(xs) / len(xs), st.median(xs),
                       100 * sum(1 for x in xs if x > 0) / len(xs)))

        print("--- %s (Rendite der FOLGE-Stunde) ---" % sym)
        print("  " + line("alle Boersenstunden", base))
        print("  " + line("nach Meldungs-Spitzenstunde", hot))
        if hot and base:
            print("  Differenz: %+0.3f Prozentpunkte" % (
                sum(hot) / len(hot) - sum(base) / len(base)))
        print()


main()
