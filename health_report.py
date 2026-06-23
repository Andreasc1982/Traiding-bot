#!/usr/bin/env python3
"""Health-Report — wertet agents/health_log.csv aus, um Fehlermuster ueber Zeit
sichtbar zu machen (Grundlage fuers autarke Live-Laufen: was haengt/crasht wie oft?).

Aufruf:
    python3 health_report.py            # letzte 7 Tage
    python3 health_report.py 30         # letzte 30 Tage
    python3 health_report.py 7 --tg     # zusaetzlich als Telegram
"""
import sys
import os
import csv
import collections
from datetime import datetime, timedelta

sys.path.insert(0, "/home/trading2025/trading_bot")
try:
    from config import config
except Exception:
    config = {}

CSV_PATH = "/home/trading2025/trading_bot/agents/health_log.csv"
DAYS = next((int(a) for a in sys.argv[1:] if a.isdigit()), 7)
TG = "--tg" in sys.argv


def main():
    if not os.path.exists(CSV_PATH):
        print("kein health_log.csv vorhanden")
        return
    cutoff = datetime.now() - timedelta(days=DAYS)
    rows = []
    with open(CSV_PATH) as f:
        for r in csv.DictReader(f):
            try:
                t = datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            if t >= cutoff:
                rows.append((t, r.get("source", ""), r.get("event", ""), r.get("detail", "")))

    by_event = collections.Counter(e for _, _, e, _ in rows)
    by_source = collections.Counter(s for _, s, _, _ in rows)
    by_day = collections.Counter(t.strftime("%Y-%m-%d") for t, _, _, _ in rows)
    hotspot = collections.Counter(d for _, _, e, d in rows if e in ("CRASH", "RESTART_OK", "WATCHDOG_HANG"))

    L = []
    L.append("HEALTH-REPORT (letzte " + str(DAYS) + " Tage) — " + str(len(rows)) + " Events")
    L.append("")
    L.append("Nach Typ:")
    for e, c in by_event.most_common():
        L.append("  " + e.ljust(18) + str(c))
    L.append("")
    L.append("Nach Quelle:")
    for s, c in by_source.most_common():
        L.append("  " + s.ljust(14) + str(c))
    if hotspot:
        L.append("")
        L.append("Crash/Hang-Hotspots (welcher Dienst):")
        for d, c in hotspot.most_common(6):
            L.append("  " + (d or "?").ljust(24) + str(c))
    L.append("")
    L.append("Pro Tag:")
    for d in sorted(by_day)[-DAYS:]:
        L.append("  " + d + "  " + str(by_day[d]))

    warn = []
    if by_event.get("DUPLICATE_BLOCKED"):
        warn.append("Singleton-Lock hat " + str(by_event["DUPLICATE_BLOCKED"]) + "x Doppelstart verhindert (gut!)")
    if by_event.get("WATCHDOG_HANG"):
        warn.append(str(by_event["WATCHDOG_HANG"]) + "x Watchdog-Hang — ein Bot haengt wiederholt, Ursache pruefen")
    if by_event.get("RESTART_FAIL"):
        warn.append(str(by_event["RESTART_FAIL"]) + "x Restart FEHLGESCHLAGEN — dringend pruefen")
    if warn:
        L.append("")
        L.append("HINWEISE:")
        L += ["  - " + w for w in warn]

    out = "\n".join(L)
    print(out)

    if TG and config.get("telegram_bot_token"):
        import requests
        try:
            requests.post(
                "https://api.telegram.org/bot" + config["telegram_bot_token"] + "/sendMessage",
                data={"chat_id": config.get("telegram_chat_id"), "text": "🩺 " + out[:3800]},
                timeout=10)
        except Exception as e:
            print("[TG] " + str(e))


if __name__ == "__main__":
    main()
