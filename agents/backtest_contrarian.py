#!/usr/bin/env python3
"""
10-JAHRES-BACKTEST — antizyklischer Mean-Reversion-Modus fuer den Super Bot.

Frage: Traegt "in der Angst oversold ETFs kaufen" historisch nach Kosten —
und UEBERLEBT es die Baeren (2018Q4, 2020-Crash, 2022)?

EHRLICHKEIT (Bias-Kontrollen):
 - Entry/Exit-Signal auf close[i], FILL auf open[i+1]  -> kein Same-Bar-Lookahead
 - Kosten pro Seite (Slippage), Stocks kommissionsfrei
 - 10 Jahre inkl. aller Baerenmaerkte als Stresstest
 - Kein Curve-Fit: mehrere Schwellen/Varianten, Spannweite berichtet
 - Baeren-Aufschluesselung getrennt -> zeigt wo Dip-Buying versagt
 - VIX als Angst-Trigger (real-time verfuegbar, kein Lookahead)
 - Connors-Kern getestet: Dip-Kauf NUR im Aufwaertstrend (>MA200)

Kernhypothese (a priori): pure Dip-Buys ohne Regime-Filter sterben in Baeren;
mit >MA200-Filter (Connors) sollte es tragen. Der Backtest entscheidet.
"""
import sys
import yfinance as yf

ETFS = ["XLE", "XOP", "XLI", "SLX", "ITA", "XLF", "XLK", "GLD", "PAVE", "IBIT"]
COST = 0.0003          # 0.03% Slippage pro Seite (konservativ; Aktien kommissionsfrei)

# Baeren-Fenster (Entry-Datum faellt hinein -> separat ausgewertet)
BEARS = {
    "2018Q4":     ("2018-10-01", "2018-12-31"),
    "2020-COVID": ("2020-02-15", "2020-04-30"),
    "2022-Bear":  ("2022-01-01", "2022-10-31"),
}


def _col(df, name):
    """yfinance multi-level-column-sicher."""
    s = df[name]
    try:
        vals = s.values.tolist()
        return [float(x[0]) if isinstance(x, (list, tuple)) else float(x) for x in vals]
    except Exception:
        return [float(x) for x in s.iloc[:, 0].values.tolist()]


def fetch(sym, period="10y"):
    try:
        df = yf.download(sym, period=period, interval="1d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        dates = [str(d)[:10] for d in df.index]
        return {"dates": dates, "open": _col(df, "Open"),
                "high": _col(df, "High"), "low": _col(df, "Low"), "close": _col(df, "Close")}
    except Exception as e:
        print("[FETCH] " + sym + ": " + str(e)[:80])
        return None


def rsi(closes, period):
    n = len(closes)
    out = [None] * n
    if n < period + 1:
        return out
    gains, losses = [], []
    for i in range(1, period + 1):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0)); losses.append(max(-ch, 0.0))
    ag = sum(gains) / period; al = sum(losses) / period
    out[period] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(period + 1, n):
        ch = closes[i] - closes[i - 1]
        g = max(ch, 0.0); l = max(-ch, 0.0)
        ag = (ag * (period - 1) + g) / period
        al = (al * (period - 1) + l) / period
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def sma(closes, period):
    n = len(closes); out = [None] * n
    run = 0.0
    for i in range(n):
        run += closes[i]
        if i >= period:
            run -= closes[i - period]
        if i >= period - 1:
            out[i] = run / period
    return out


def lower_bb(closes, period=20, mult=2.0):
    n = len(closes); out = [None] * n
    for i in range(period - 1, n):
        w = closes[i - period + 1:i + 1]
        m = sum(w) / period
        var = sum((x - m) ** 2 for x in w) / period
        out[i] = m - mult * (var ** 0.5)
    return out


def precompute(d):
    c = d["close"]
    return {
        **d,
        "rsi2": rsi(c, 2), "rsi14": rsi(c, 14),
        "ma5": sma(c, 5), "ma20": sma(c, 20), "ma200": sma(c, 200),
        "lbb": lower_bb(c, 20, 2.0),
    }


VARIANTS = [
    {"name": "A_pure_rsi2<10",          "rsi_p": 2,  "rsi_entry": 10, "regime": None,        "fear": None,         "exit": "ma5",  "stop": 0.08, "maxhold": 10},
    {"name": "B_Connors_rsi2<10+MA200", "rsi_p": 2,  "rsi_entry": 10, "regime": "etf_ma200", "fear": None,         "exit": "ma5",  "stop": 0.08, "maxhold": 10},
    {"name": "C_Connors_rsi2<5+MA200",  "rsi_p": 2,  "rsi_entry": 5,  "regime": "etf_ma200", "fear": None,         "exit": "ma5",  "stop": 0.08, "maxhold": 10},
    {"name": "D_Connors+VIX>28",        "rsi_p": 2,  "rsi_entry": 10, "regime": "etf_ma200", "fear": ("vix", 28), "exit": "ma5",  "stop": 0.08, "maxhold": 10},
    {"name": "E_RSI14<30+lowBB+MA200",  "rsi_p": 14, "rsi_entry": 30, "regime": "etf_ma200", "fear": None,         "exit": "ma20", "stop": 0.10, "maxhold": 15, "bb": True},
    {"name": "F_SPY_regime_rsi2<10",    "rsi_p": 2,  "rsi_entry": 10, "regime": "spy_ma200", "fear": None,         "exit": "ma5",  "stop": 0.08, "maxhold": 10},
    {"name": "G_Connors_NO_stop",       "rsi_p": 2,  "rsi_entry": 10, "regime": "etf_ma200", "fear": None,         "exit": "ma5",  "stop": None, "maxhold": 10},
    {"name": "H_fear_only_VIX>30",      "rsi_p": 2,  "rsi_entry": 10, "regime": None,        "fear": ("vix", 30), "exit": "ma5",  "stop": 0.08, "maxhold": 10},
    {"name": "I_deepfear_RSI14<25+VIX30","rsi_p": 14,"rsi_entry": 25, "regime": None,        "fear": ("vix", 30), "exit": "ma20", "stop": 0.12, "maxhold": 20},
]


def in_bear(date):
    for lo, hi in BEARS.values():
        if lo <= date <= hi:
            return True
    return False


def bear_name(date):
    for nm, (lo, hi) in BEARS.items():
        if lo <= date <= hi:
            return nm
    return None


def simulate(pc, V, vix, spy_ma200):
    """Liefert Liste von Trades: (entry_date, net_return, hold_days)."""
    c, o = pc["close"], pc["open"]
    dates = pc["dates"]
    rsi_arr = pc["rsi2"] if V["rsi_p"] == 2 else pc["rsi14"]
    ma5, ma20, ma200, lbb = pc["ma5"], pc["ma20"], pc["ma200"], pc["lbb"]
    exit_ma = ma5 if V["exit"] == "ma5" else ma20
    trades = []
    n = len(c)
    i = 0
    while i < n - 1:
        # --- Entry-Bedingung auf close[i] ---
        if rsi_arr[i] is None or ma200[i] is None or exit_ma[i] is None:
            i += 1; continue
        ok = rsi_arr[i] < V["rsi_entry"]
        if ok and V.get("bb"):
            ok = lbb[i] is not None and c[i] < lbb[i]
        if ok and V["regime"] == "etf_ma200":
            ok = c[i] > ma200[i]
        if ok and V["regime"] == "spy_ma200":
            sm = spy_ma200.get(dates[i]); ok = sm is not None and spy_ma200.get("_spy_" + dates[i], 0) > sm
        if ok and V["fear"] and V["fear"][0] == "vix":
            vv = vix.get(dates[i]); ok = vv is not None and vv > V["fear"][1]
        if not ok:
            i += 1; continue
        # --- Fill zum NAECHSTEN Open ---
        entry = o[i + 1]
        if entry <= 0:
            i += 1; continue
        entry_date = dates[i + 1]
        stop_lvl = entry * (1 - V["stop"]) if V["stop"] else None
        # --- Halten bis Exit ---
        j = i + 1
        exit_price = None
        while j < n - 1:
            # Exit-Signal auf close[j], Fill open[j+1]
            held = j - (i + 1)
            hit_stop = stop_lvl is not None and c[j] <= stop_lvl
            hit_target = exit_ma[j] is not None and c[j] > exit_ma[j]
            hit_time = held >= V["maxhold"]
            if hit_stop or hit_target or hit_time:
                exit_price = o[j + 1]
                break
            j += 1
        if exit_price is None:           # bis Datenende gehalten
            exit_price = c[-1]; j = n - 1
        net = (exit_price / entry - 1) - 2 * COST
        trades.append((entry_date, net, j - (i + 1)))
        i = j + 1                        # nach Exit weiter
    return trades


def stats(trades):
    if not trades:
        return None
    rets = [t[1] for t in trades]
    wins = [r for r in rets if r > 0]
    return {
        "n": len(trades),
        "win": 100 * len(wins) / len(trades),
        "avg": 100 * sum(rets) / len(rets),          # Expectancy pro Trade (%)
        "med": 100 * sorted(rets)[len(rets) // 2],
        "best": 100 * max(rets),
        "worst": 100 * min(rets),
        "avg_hold": sum(t[2] for t in trades) / len(trades),
        "sum": 100 * sum(rets),                       # Summe aller Trade-%-Returns
    }


def equity_curve(trades, max_concurrent=5):
    """Grobe Portfolio-Naeherung: chronologisch, bis N gleichzeitige Slots, je 1/N Equity."""
    if not trades:
        return 0.0, 0.0
    ts = sorted(trades, key=lambda t: t[0])
    eq = 1.0; peak = 1.0; maxdd = 0.0
    frac = 1.0 / max_concurrent
    for _, net, _ in ts:                  # sequentiell (konservativ: keine Ueberlappung kompoundiert)
        eq *= (1 + net * frac)
        peak = max(peak, eq)
        maxdd = max(maxdd, (peak - eq) / peak)
    return (eq - 1) * 100, maxdd * 100


def main():
    print("=" * 72)
    print("  ANTIZYKLISCHER MEAN-REVERSION BACKTEST — 10 Jahre, fee-aware, kein Lookahead")
    print("=" * 72)
    print("Lade Daten (10 ETFs + SPY + ^VIX)...")
    data = {}
    for s in ETFS:
        d = fetch(s)
        if d:
            data[s] = precompute(d)
        print("  " + s + (": " + str(len(d["close"])) + " Bars" if d else ": KEINE DATEN"))
    spy = fetch("SPY")
    vixd = fetch("^VIX")
    if not spy or not vixd:
        print("FEHLER: SPY oder VIX nicht ladbar"); return
    spy_ma200_arr = sma(spy["close"], 200)
    spy_ma200 = {}
    for k, dt in enumerate(spy["dates"]):
        spy_ma200[dt] = spy_ma200_arr[k]
        spy_ma200["_spy_" + dt] = spy["close"][k]
    vix = {dt: vixd["close"][k] for k, dt in enumerate(vixd["dates"])}
    print("  SPY: " + str(len(spy["close"])) + " | VIX: " + str(len(vixd["close"])) + " Bars")
    print()

    hdr = "%-26s %5s %6s %7s %7s %8s %7s %7s %6s" % (
        "Variante", "N", "Win%", "Exp%", "Med%", "Worst%", "Hold", "Ret%", "MaxDD")
    print(hdr); print("-" * len(hdr))
    results = {}
    for V in VARIANTS:
        all_tr = []
        for s in data:
            all_tr += simulate(data[s], V, vix, spy_ma200)
        st = stats(all_tr)
        if not st:
            print("%-26s  (keine Trades)" % V["name"]); continue
        ret, dd = equity_curve(all_tr)
        results[V["name"]] = (st, all_tr)
        print("%-26s %5d %5.0f%% %+6.2f %+6.2f %+7.1f %6.1f %+6.0f %5.0f%%" % (
            V["name"], st["n"], st["win"], st["avg"], st["med"], st["worst"],
            st["avg_hold"], ret, dd))

    # --- BAEREN-AUFSCHLUESSELUNG: der ehrliche Test ---
    print()
    print("=" * 72)
    print("  BAEREN-TEST — Expectancy (avg %/Trade) bei Entry IN einem Baerenmarkt")
    print("=" * 72)
    print("%-26s %14s %14s %18s" % ("Variante", "Normal", "Baeren", "Baeren-Win%"))
    for name, (st, trs) in results.items():
        bear = [t for t in trs if in_bear(t[0])]
        norm = [t for t in trs if not in_bear(t[0])]
        bs = stats(bear); ns = stats(norm)
        bexp = ("%+.2f%% (%d)" % (bs["avg"], bs["n"])) if bs else "-"
        nexp = ("%+.2f%% (%d)" % (ns["avg"], ns["n"])) if ns else "-"
        bwin = ("%.0f%%" % bs["win"]) if bs else "-"
        print("%-26s %14s %14s %18s" % (name, nexp, bexp, bwin))

    print()
    print("LEGENDE: Exp% = Expectancy (avg Netto-Return pro Trade nach Kosten) — DIE Kennzahl.")
    print("         Ret%/MaxDD = grobe Portfolio-Naeherung (5 Slots, sequentiell).")
    print("         Baeren-Spalte zeigt, ob Dip-Buying im Crash ueberlebt.")


def robustness_check(data, vix, spy_ma200):
    """
    1) VIX-Threshold-Sweep: Variant-D-Konfiguration, nur VIX-Schwelle variiert 20-36
    2) Per-Crash-Aufschluesselung fuer Variant D (Trade-Klumpung)
    """
    D_BASE = {"rsi_p": 2, "rsi_entry": 10, "regime": "etf_ma200",
              "exit": "ma5", "stop": 0.08, "maxhold": 10}

    print()
    print("=" * 72)
    print("  ROBUSTHEIT 1 — VIX-Schwellen-Sweep (sonst identisch zu Variant D)")
    print("=" * 72)
    print("  Zeigt: Ist VIX>28 curve-fit, oder traegt ein breiter Bereich?")
    print()
    hdr2 = "%-8s %5s %6s %7s %10s %6s %5s" % (
        "VIX>", "N", "Win%", "Exp%", "Baer-Exp%", "MaxDD", "Baer-N")
    print(hdr2)
    print("-" * len(hdr2))

    for thresh in [20, 22, 24, 25, 26, 27, 28, 29, 30, 31, 32, 34, 36]:
        V = dict(D_BASE, fear=("vix", thresh))
        all_tr = []
        for s in data:
            all_tr += simulate(data[s], V, vix, spy_ma200)
        st = stats(all_tr)
        if not st:
            print("%-8s  (keine Trades)" % (">" + str(thresh)))
            continue
        bear_tr = [t for t in all_tr if in_bear(t[0])]
        bs = stats(bear_tr)
        _, dd = equity_curve(all_tr)
        marker = "  <-- D (Basis)" if thresh == 28 else ""
        bexp = ("%+.2f" % bs["avg"]) if bs else "    -"
        bn   = str(bs["n"]) if bs else "-"
        print("%-8s %5d %5.0f%% %+6.2f %10s %5.0f%% %5s%s" % (
            ">" + str(thresh), st["n"], st["win"], st["avg"], bexp, dd, bn, marker))

    print()
    print("=" * 72)
    print("  ROBUSTHEIT 2 — Variant D: Trades je Crash (Klumpungs-Test)")
    print("=" * 72)
    print("  Zeigt: Kommt die Performance aus einem einzigen Crash-Event?")
    print()
    V_D = dict(D_BASE, fear=("vix", 28))
    d_trades = []
    for s in data:
        for t in simulate(data[s], V_D, vix, spy_ma200):
            d_trades.append((s,) + t)

    for bname, (lo, hi) in BEARS.items():
        crash = [(s, dt, r, h) for s, dt, r, h in d_trades if lo <= dt <= hi]
        if not crash:
            print("  %-20s: 0 Trades" % bname)
            continue
        avg_r = sum(r for _, _, r, _ in crash) / len(crash)
        wins  = sum(1 for _, _, r, _ in crash if r > 0)
        print("  %-20s: %2d Trades, %d%% Win, Exp %+.2f%%" % (
            bname, len(crash), 100 * wins // len(crash), avg_r * 100))
        for s, dt, r, h in sorted(crash, key=lambda x: x[1]):
            print("    %s  %-6s  %+.1f%%  %dd" % (dt, s, r * 100, h))

    non_bear = [(s, dt, r, h) for s, dt, r, h in d_trades if not in_bear(dt)]
    if non_bear:
        avg_nb = sum(r for _, _, r, _ in non_bear) / len(non_bear)
        wins_nb = sum(1 for _, _, r, _ in non_bear if r > 0)
        print()
        print("  %-20s: %2d Trades, %d%% Win, Exp %+.2f%%" % (
            "Normal (kein Crash)", len(non_bear),
            100 * wins_nb // len(non_bear), avg_nb * 100))

    print()
    print("FAZIT-GUIDE:")
    print("  VIX-Sweep: Wenn Exp% monoton faellt mit steigendem VIX → kein Curve-Fit,")
    print("             Bereich traegt. Wenn nur VIX>28 gut → verdaechtig.")
    print("  Klumpung:  Wenn >50% der Performance aus einem Crash → zu wenig Stichproben.")


if __name__ == "__main__":
    main()
    print()
    print("Starte Robustheitspruefung (gleiche Daten, kein zweiter Download)...")
    # Daten fuer Robustheit neu laden (main() gibt sie nicht zurueck)
    data_r = {}
    for s in ETFS:
        d = fetch(s)
        if d:
            data_r[s] = precompute(d)
    spy_r  = fetch("SPY")
    vixd_r = fetch("^VIX")
    if spy_r and vixd_r:
        sm_r = sma(spy_r["close"], 200)
        spy_ma_r = {}
        for k, dt in enumerate(spy_r["dates"]):
            spy_ma_r[dt] = sm_r[k]
            spy_ma_r["_spy_" + dt] = spy_r["close"][k]
        vix_r = {dt: vixd_r["close"][k] for k, dt in enumerate(vixd_r["dates"])}
        robustness_check(data_r, vix_r, spy_ma_r)
