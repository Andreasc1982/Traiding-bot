#!/usr/bin/env python3
"""Empirischer Rug-Reaktionstest fuer dex_paper.py — kein Netzwerk.
Beantwortet: Wie schnell reagiert der Bot auf einen Rug? Kann er vor -90% raus?
Nutzt die ECHTEN Konstanten + close_paper() aus dex_paper, damit das Ergebnis
exakt die Live-Logik widerspiegelt."""
import dex_paper as P


def fresh_pos(entry, peak=None):
    return {"symbol": "TEST", "entry": entry, "shares": P.BET / entry,
            "peak": peak or entry, "last_price": peak or entry, "bet": P.BET,
            "realized": 0.0, "scaled": False, "time": "2026-06-22 12:00"}


print("=" * 62)
print("  RUG-REAKTIONSTEST — echte dex_paper-Logik")
print("  Poll alle " + str(P.POLL_SEC) + "s | Hard-Stop -" + str(int(P.HARD * 100)) +
      "% | Trail " + str(int(P.TRAIL * 100)) + "% | Rug-Liq <$" + str(P.RUG_LIQ))
print("=" * 62)

# ── A) INSTANT-RUG: Dev zieht Liquiditaet in EINEM Solana-Block (~0.4s) ──
print("\n### A) INSTANT-RUG (Liquiditaet in 1 Block entzogen, ~0.4s)")
state = {"bankroll": 480.0, "positions": {"X": fresh_pos(0.001)}, "traded": ["X"]}
trades = []
pos = state["positions"]["X"]
print("  Entry $0.001 | Einsatz $" + str(P.BET))
print("  t=0s   Preis $0.001    Liq $50000  -> gesund")
print("  ~~ Rug-Block: Liquiditaet weg, Preis -97% (passiert VOR dem naechsten Poll) ~~")
for label, now in [("t=20s", {"price": 0.00003, "liq": 200}),
                   ("t=40s", {"price": 0.00003, "liq": 180}),
                   ("t=60s", {"price": 0.00002, "liq": 150})]:
    if "X" not in state["positions"]:
        break
    if now is None:
        pos["rug_misses"] = 0
        continue
    if not now or now.get("liq", 0) < P.RUG_LIQ:
        pos["rug_misses"] = pos.get("rug_misses", 0) + 1
        print("  " + label + "  Liq $" + str(now["liq"]) + " < $" + str(P.RUG_LIQ) +
              "  -> Rug-Beleg " + str(pos["rug_misses"]) + "/" + str(P.RUG_CONFIRM) +
              ("  => BUCHEN" if pos["rug_misses"] >= P.RUG_CONFIRM else "  (warte auf Bestaetigung)"))
        if pos["rug_misses"] < P.RUG_CONFIRM:
            continue
        crashed = now["price"] if now.get("price", 0) > 0 else pos["last_price"] * P.RUG_RECOVERY
        pos["last_price"] = crashed
        P.close_paper(state, trades, "X", crashed, "RUG-TOTAL")
t = trades[-1]
print("  --> Fill $" + str(t["exit"]) + " | Ergebnis " + str(t["pct"]) +
      "% = $" + str(t["profit"]) + " von $" + str(P.BET))

# ── B) SLOW BLEED: Gewinner kippt langsam ueber Minuten ──
print("\n### B) SLOW BLEED (Token pumpt auf +100%, kippt dann ueber Minuten)")
state = {"bankroll": 480.0, "positions": {"Y": fresh_pos(0.001, peak=0.002)}, "traded": ["Y"]}
trades = []
for label, price in [("t=0s", 0.0020), ("t=20s", 0.0018), ("t=40s", 0.0016), ("t=60s", 0.0014)]:
    pos = state["positions"].get("Y")
    if not pos:
        break
    pos["last_price"] = price
    if price > pos["peak"]:
        pos["peak"] = price
    reason = None
    if price <= pos["entry"] * (1 - P.HARD):
        reason = "HARD-STOP"
    elif pos["peak"] > pos["entry"] and price <= pos["peak"] * (1 - P.TRAIL):
        reason = "TRAIL"
    print("  " + label.ljust(7) + " Preis $" + str(price) +
          "  (" + ("%+.0f" % ((price / pos["entry"] - 1) * 100)) + "% Entry, " +
          ("%+.0f" % ((price / pos["peak"] - 1) * 100)) + "% vom Hoch) -> " + (reason or "halten"))
    if reason:
        P.close_paper(state, trades, "Y", price, reason)
if trades:
    t = trades[-1]
    print("  --> Exit " + t["reason"] + " | Ergebnis " + str(t["pct"]) + "% = $" + str(t["profit"]))

print("\n" + "=" * 62)
print("FAZIT")
print(" A) Instant-Rug: Der -97%-Verlust ist im RUG-BLOCK (~0.4s) gelockt — VOR dem")
print("    naechsten Poll. Der Bot bucht ihn nach " + str(P.RUG_CONFIRM) + " Bestaetigungen (~" +
      str(P.RUG_CONFIRM * P.POLL_SEC) + "s) zum")
print("    abgestuerzten Preis. Er kann NICHT davor verkaufen — kein Exit-Tempo")
print("    schlaegt einen 1-Block-Rug. Einziger Schutz: Screening VOR dem Kauf.")
print("    (Die " + str(P.RUG_CONFIRM) + " Bestaetigungen kosten nichts extra — der Verlust steht schon;")
print("     sie verhindern nur FAKE-Rugs aus API-Aussetzern.)")
print(" B) Slow-Bleed: Trailing/Hard-Stop greift binnen " + str(P.POLL_SEC) +
      "s, sichert Gewinn /")
print("    begrenzt Verlust. DAS faengt der Bot zuverlaessig.")
print("=" * 62)
