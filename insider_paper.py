#!/usr/bin/env python3
"""Vorwaerts-Papierdepot fuer das Insider-Signal — der einzige unverzerrte Test.

Jeder weitere Backtest nutzt dieselben survivorship-verzerrten Daten. Deshalb
hier ein Depot, das ab HEUTE nach vorne laeuft: alle REBAL Handelstage die
NPOS Titel mit dem hoechsten `ins_netto_90` (Insider-Netto-Kauf, skaliert am
60-Tage-Durchschnittsumsatz) gleichgewichtet, nur Titel mit ADV >= MIN_ADV.

Kein echtes Geld, keine Orders. Taeglich per Cron:
  1) Kurse der gehaltenen Titel aktualisieren -> Equity
  2) faellige Umschichtung durchfuehren
  3) Dashboard schreiben

    python3 insider_paper.py [--rebal] [--dry]
"""
import os, sys, csv, json, math, collections
import statistics as st
from datetime import datetime
import warnings
warnings.filterwarnings("ignore")

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)

SEC = os.path.join(BASE, "sec")
STATE = os.path.join(SEC, "paper_state.json")
DASH = os.path.join(SEC, "insider_dashboard.json")
HIST = os.path.join(SEC, "paper_equity.csv")

START_CAPITAL = 10000.0
NPOS = 30
REBAL_DAYS = 20
MIN_ADV = 5e6
W = 90
FORCE = "--rebal" in sys.argv
DRY = "--dry" in sys.argv


def load_insider():
    per = collections.defaultdict(dict)
    for path in (os.path.join(SEC, "insider_daily.csv"),
                 os.path.join(SEC, "insider_live.csv")):
        if not os.path.exists(path):
            continue
        for r in csv.DictReader(open(path, encoding="utf-8")):
            try:
                k = r["filing_date"]
                b, s = float(r["kauf_usd"]), float(r["verkauf_usd"])
                cur = per[r["ticker"]].get(k, (0.0, 0.0))
                per[r["ticker"]][k] = (cur[0] + b, cur[1] + s)
            except Exception:
                continue
    return per


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"cash": START_CAPITAL, "positions": {}, "trades": [],
                "last_rebal": None, "start": datetime.now().strftime("%Y-%m-%d"),
                "rebal_count": 0}


def save(obj, path):
    tmp = path + ".tmp"
    json.dump(obj, open(tmp, "w"), indent=1)
    os.replace(tmp, path)


def prices(syms):
    """Aktuelle Kurse + 60-Tage-Durchschnittsumsatz."""
    import yfinance as yf
    out = {}
    syms = sorted(set(syms))
    for i in range(0, len(syms), 50):
        part = syms[i:i + 50]
        try:
            df = yf.download(part, period="4mo", interval="1d", progress=False,
                             auto_adjust=True, threads=True, group_by="ticker")
        except Exception:
            continue
        for s in part:
            try:
                sub = df[s].dropna() if len(part) > 1 else df.dropna()
                if len(sub) < 30:
                    continue
                cl = [float(x) for x in sub["Close"].values]
                vo = [float(x) for x in sub["Volume"].values]
                adv = st.median([c * v for c, v in zip(cl[-60:], vo[-60:])])
                out[s] = {"price": cl[-1], "adv": adv}
            except Exception:
                continue
    return out


def signal_candidates(ins, topn=200):
    """Roh-Rangliste nach Netto-Insiderkauf der letzten W Tage (noch ohne ADV)."""
    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.now() - __import__("datetime").timedelta(days=W)
              ).strftime("%Y-%m-%d")
    raw = {}
    for tic, days in ins.items():
        b = s = 0.0
        for d, (bu, se) in days.items():
            if cutoff <= d <= today:
                b += bu
                s += se
        if b > 0:
            raw[tic] = b - s
    return sorted(raw.items(), key=lambda x: -x[1])[:topn]


def main():
    from datetime import timedelta
    ins = load_insider()
    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")

    # Frische-Wache: nicht auf halb geladenen Daten umschichten
    newest = max((d for days in ins.values() for d in days), default=None)
    stale_days = ((datetime.now() - datetime.strptime(newest, "%Y-%m-%d")).days
                  if newest else 9999)
    data_ok = stale_days <= 10

    due = FORCE or state["last_rebal"] is None
    if not due and state["last_rebal"]:
        d0 = datetime.strptime(state["last_rebal"], "%Y-%m-%d")
        due = (datetime.now() - d0).days >= REBAL_DAYS * 7 / 5.0

    if due and not data_ok:
        print("[WARTE] Insider-Daten nur bis %s (%d Tage alt) — keine Umschichtung."
              % (newest or "-", stale_days))
    due = due and data_ok

    held = list(state["positions"].keys())
    need = held[:]
    cands = []
    if due:
        cands = signal_candidates(ins)
        need += [t for t, _ in cands]
    px = prices(need) if need else {}

    if due and cands and data_ok:
        elig = [(v, t) for t, v in cands
                if t in px and px[t]["adv"] >= MIN_ADV and px[t]["price"] > 1]
        elig.sort(reverse=True)
        picks = [t for _, t in elig[:NPOS]]
        if picks:
            # alles verkaufen, was nicht mehr drin ist
            equity = state["cash"]
            for t, p in list(state["positions"].items()):
                cur = px.get(t, {}).get("price", p["entry"])
                equity += p["shares"] * cur
            newpos, cash = {}, equity
            per = equity / len(picks)
            for t in picks:
                p = px[t]["price"]
                sh = per / p
                newpos[t] = {"shares": sh, "entry": p, "since": today,
                             "adv": round(px[t]["adv"])}
                cash -= sh * p
            sold = [t for t in state["positions"] if t not in newpos]
            bought = [t for t in newpos if t not in state["positions"]]
            state["positions"] = newpos
            state["cash"] = max(cash, 0.0)
            state["last_rebal"] = today
            state["rebal_count"] = state.get("rebal_count", 0) + 1
            state["trades"].append({"date": today, "verkauft": sold,
                                    "gekauft": bought, "equity": round(equity, 2)})
            state["trades"] = state["trades"][-50:]
            print("[REBAL] %d Positionen | %d neu, %d raus | Equity $%.2f"
                  % (len(newpos), len(bought), len(sold), equity))

    # Bewertung
    pos_val = 0.0
    rows = []
    for t, p in state["positions"].items():
        cur = px.get(t, {}).get("price", p["entry"])
        val = p["shares"] * cur
        pos_val += val
        rows.append({"symbol": t, "shares": round(p["shares"], 4),
                     "entry": round(p["entry"], 2), "price": round(cur, 2),
                     "pnl_pct": round((cur / p["entry"] - 1) * 100, 2),
                     "wert": round(val, 2), "seit": p["since"],
                     "adv_mio": round(p.get("adv", 0) / 1e6, 1)})
    equity = state["cash"] + pos_val
    rows.sort(key=lambda r: -r["pnl_pct"])

    dash = {"zeit": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "start": state["start"], "start_kapital": START_CAPITAL,
            "equity": round(equity, 2), "cash": round(state["cash"], 2),
            "rendite_pct": round((equity / START_CAPITAL - 1) * 100, 2),
            "positionen": rows, "n_pos": len(rows),
            "letzte_umschichtung": state["last_rebal"],
            "umschichtungen": state.get("rebal_count", 0),
            "naechste_in_tagen": max(0, REBAL_DAYS - int(
                (datetime.now() - datetime.strptime(
                    state["last_rebal"], "%Y-%m-%d")).days * 5 / 7.0))
            if state["last_rebal"] else 0,
            "trades": state["trades"][-10:],
            "daten_stand": newest, "daten_alter_tage": stale_days,
            "config": {"positionen": NPOS, "rebal_tage": REBAL_DAYS,
                       "min_adv_mio": MIN_ADV / 1e6, "fenster_tage": W}}

    if DRY:
        print(json.dumps(dash, indent=1)[:1200])
        return
    save(state, STATE)
    save(dash, DASH)
    new = not os.path.exists(HIST)
    with open(HIST, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["zeit", "equity", "cash", "n_pos"])
        w.writerow([dash["zeit"], dash["equity"], dash["cash"], len(rows)])
    print("%s | Equity $%.2f (%+.2f%%) | %d Positionen"
          % (dash["zeit"], equity, dash["rendite_pct"], len(rows)))


main()
