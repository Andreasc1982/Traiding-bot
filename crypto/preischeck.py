#!/usr/bin/env python3
"""Abgleich: gemeldeter Kaufpreis im Telegram-Feed gegen den echten Marktkurs
derselben Minute (Alpaca-Bars). Faengt Fehl-Ticks beim Einstieg."""
import sys, datetime as dt
sys.path.insert(0, "/home/trading2025/trading_bot/crypto")
from exit_sim import lade_entries, lade_bars

entries = lade_entries()
cache = {}
treffer = []
for e in entries:
    s = e["sym"]
    if s not in cache: cache[s] = lade_bars(s)
    bars = cache[s]
    if not bars: continue
    nah = [b for b in bars if abs((b["t"] - e["zeit"]).total_seconds()) <= 300]
    if not nah: continue
    markt = sum(b["c"] for b in nah) / len(nah)
    abw = (e["preis"] - markt) / markt * 100
    treffer.append((abw, e, markt))

treffer.sort(key=lambda x: -abs(x[0]))
print("Geprüfte Einstiege: %d" % len(treffer))
print("Abweichung Kaufpreis ↔ Marktkurs:")
for grenze in (0.5, 1, 3, 10):
    n = sum(1 for t in treffer if abs(t[0]) > grenze)
    print("   > %4.1f %%: %3d" % (grenze, n))
print("\nGrösste Abweichungen:")
print("%-10s %-16s %12s %12s %9s %8s" % ("Symbol","Einstieg","gemeldet","Markt","Abw.","Einsatz"))
for abw, e, markt in treffer[:12]:
    print("%-10s %-16s %12.4f %12.4f %8.1f%% %8.0f" % (
        e["sym"], e["zeit"].strftime("%d.%m %H:%M"), e["preis"], markt, abw, e["einsatz"]))
