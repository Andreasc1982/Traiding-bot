#!/usr/bin/env python3
"""
Moonshot-Parameter-Backtest.

Kernfrage: Dreht die RICHTIGE Exit-Logik das Vorzeichen?
  - ALT (kaputt):  TP +3% / SL -1.5%  -> deckelt Gewinner, behaelt volle Verluste
  - MOONSHOT:      harter Stop -H%, dann Trailing-Stop T% vom Hoch, KEIN TP-Deckel
                   -> kleine Verluste, Gewinner duerfen explodieren (positive Schiefe)

Entry (beide gleich): 20-Tage-Hoch-Breakout (Momentum-Zuendung) — der klassische
Ausbruch, der Explosionen am Anfang faengt. Universe: volatile Crypto (laengste
verfuegbare yfinance-Historie pro Coin). Fee-aware (Crypto 0.31%/Seite).

Schluessel-Metriken: Win-Rate, Ø-Gewinn vs Ø-Verlust (SCHIEFE!), groesster Treffer,
Gesamt-Rendite (sequentielle Voll-Position je Coin), Max-Drawdown.
"""
import sys
sys.path.insert(0, "/home/trading2025/trading_bot/agents")
import yfinance as yf

# yfinance Crypto-Tickers (USD). Memes haben kuerzere Historie -> wird geloggt.
COINS = ["BTC-USD", "ETH-USD", "SOL-USD", "DOGE-USD", "SHIB-USD", "AVAX-USD",
         "LINK-USD", "ADA-USD", "DOT-USD", "XRP-USD", "PEPE-USD", "WIF-USD"]

BREAKOUT = 20            # Entry: neues 20-Tage-Hoch
COST     = 0.0031 * 2    # 0.26% Fee + 0.05% Slippage pro Seite
WARMUP   = 25

# Strategien: (name, hard_stop, trail)  trail=None -> altes Fix-TP/SL
STRATS = [
    ("ALT TP3/SL1.5", None, None),   # Sonderfall: fixes TP 3% / SL 1.5%
    ("Trail 15% (Stop -15%)", 0.15, 0.15),
    ("Trail 25% (Stop -15%)", 0.15, 0.25),
    ("Trail 35% (Stop -20%)", 0.20, 0.35),
    ("Trail 50% (Stop -25%)", 0.25, 0.50),
]


def fetch(sym):
    try:
        df = yf.download(sym, period="10y", interval="1d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        try:
            return [float(x) for x in df["Close"].values.flatten()]
        except Exception:
            return [float(x) for x in df[("Close", sym)].values.flatten()]
    except Exception:
        return None


def simulate(closes, hard, trail):
    """Gibt Liste der Trade-Renditen (netto) zurueck."""
    n = len(closes); trades = []; pos = None
    for i in range(WARMUP, n):
        price = closes[i]
        if pos is not None:
            if price > pos["peak"]:
                pos["peak"] = price
            exit_now = False
            if trail is None:
                # ALT: TP 3% / SL 1.5%
                pnl = (price - pos["entry"]) / pos["entry"]
                if pnl <= -0.015 or pnl >= 0.03:
                    exit_now = True
            else:
                # MOONSHOT: harter Stop ODER Trailing vom Hoch
                if price <= pos["entry"] * (1 - hard):
                    exit_now = True
                elif pos["peak"] > pos["entry"] and price <= pos["peak"] * (1 - trail):
                    exit_now = True
            if exit_now:
                trades.append((price - pos["entry"]) / pos["entry"] - COST)
                pos = None
            continue
        # Entry: neues BREAKOUT-Tage-Hoch
        if closes[i] > max(closes[i - BREAKOUT:i]):
            pos = {"entry": price, "peak": price}
    if pos is not None:
        trades.append((closes[-1] - pos["entry"]) / pos["entry"] - COST)
    return trades


def stats(trades):
    if not trades:
        return None
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    eq, peak, mdd = 1.0, 1.0, 0.0
    for t in trades:
        eq *= (1 + t); peak = max(peak, eq); mdd = max(mdd, (peak - eq) / peak)
    avg_w = sum(wins) / len(wins) * 100 if wins else 0
    avg_l = sum(losses) / len(losses) * 100 if losses else 0
    return {
        "ret": (eq - 1) * 100, "n": len(trades),
        "wr": len(wins) / len(trades) * 100,
        "avg_w": avg_w, "avg_l": avg_l,
        "max_w": max(trades) * 100,
        "skew": (avg_w / abs(avg_l)) if avg_l < 0 else 99.9,
        "mdd": mdd * 100,
    }


def main():
    print("Lade Crypto-Historie...")
    data = {}
    for c in COINS:
        cl = fetch(c)
        if cl and len(cl) > WARMUP + 30:
            data[c] = cl
            yrs = len(cl) / 365.0
            print("  " + c + ": " + str(len(cl)) + " Tage (~" + str(round(yrs, 1)) + "J)")
    print()
    print("=" * 92)
    print("  MOONSHOT-PARAMETER-BACKTEST  (" + str(len(data)) + " Coins, fee-aware, 20T-Breakout-Entry)")
    print("=" * 92)
    print("{:<24} | {:>9} | {:>6} | {:>7} | {:>7} | {:>7} | {:>6} | {:>7}".format(
        "Strategie", "Ø Return", "WR", "Ø-Gew", "Ø-Verl", "Max-Gew", "Schiefe", "Ø-MaxDD"))
    print("-" * 92)
    for name, hard, trail in STRATS:
        ss = []
        for cl in data.values():
            s = stats(simulate(cl, hard, trail))
            if s:
                ss.append(s)
        if not ss:
            continue
        avg = lambda k: sum(s[k] for s in ss) / len(ss)
        tot_n = sum(s["n"] for s in ss)
        max_w = max(s["max_w"] for s in ss)
        print("{:<24} | {:>+8.0f}% | {:>5.0f}% | {:>+6.1f}% | {:>+6.1f}% | {:>+6.0f}% | {:>6.2f} | {:>6.1f}%".format(
            name, avg("ret"), avg("wr"), avg("avg_w"), avg("avg_l"), max_w, avg("skew"), avg("mdd")))
    print("=" * 92)
    print("Lesart: Ø Return = mittlere Coin-Rendite (sequentiell, Voll-Position).")
    print("        Schiefe = Ø-Gewinn / Ø-Verlust. >1 = Gewinner groesser als Verlierer (gut).")
    print("        Max-Gew = groesster Einzeltreffer ueber alle Coins (der 'fette Schwanz').")
    print("        ALT deckelt bei +3% -> Max-Gew kann nie gross werden = Moonshot-Killer.")


if __name__ == "__main__":
    main()
