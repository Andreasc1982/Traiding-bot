#!/usr/bin/env python3
"""
Vergleichs-Report fuer das Clone-Experiment.
Findet Varianten DYNAMISCH ueber clones/*_dashboard.json (die alte hardcodierte
A-E-Liste hat F/G/H/G_big verschluckt), rechnet Equity, Netto-Rendite, Win-Rate,
Expectancy, und gibt eine sortierte Tabelle aus + Telegram-Snapshot.

Usage:
  python3 compare_clones.py          # Tabelle ausgeben
  python3 compare_clones.py --tg     # zusaetzlich Telegram-Report senden
"""
import glob, json, os, sys

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)
try:
    from config import config
except ImportError:
    config = {}

CLONE_DIR = os.path.join(BASE, "crypto", "clones")
START = 5000.0
LABELS = {
    "A_baseline":         "A · Baseline (Momentum+Spikes)",
    "B_nospikes":         "B · No-Spikes (Momentum)",
    "C_conservative":     "C · Conservative (streng)",
    "D_contrarian":       "D · Contrarian (Oversold)",
    "E_moonshot":         "E · Moonshot (Lotterie/Trailing)",
    "F_contrarian_vix28": "F · Deep-Fear (RSI<20+F&G<25)",
    "G_core":             "G · Mid-Cap Core (Kraken-Kosten)",
    "H_contra_refined":   "H · Refined Contra (ST-bestät.)",
    "G_big":              "G_big · MEXC 2× Einsatz",
    "G_mexc":             "G_mexc · Core auf MEXC ask/bid",
    "I_wide":             "I · MEXC + weites Universum",
}


def discover_variants():
    """Nur AKTIVE Clones (Dashboard <24h frisch) — gestoppte (F/H/G_big 24.07.) sollen
    weder Report noch Telegram-Feed fuellen; ihre Dateien bleiben als Archiv liegen."""
    import time
    out = []
    for p in sorted(glob.glob(os.path.join(CLONE_DIR, "*_dashboard.json"))):
        if time.time() - os.path.getmtime(p) < 24 * 3600:
            out.append(os.path.basename(p)[:-len("_dashboard.json")])
    return out


def _load(variant):
    dpath = os.path.join(CLONE_DIR, variant + "_dashboard.json")
    tpath = os.path.join(CLONE_DIR, variant + "_trades.json")
    try:
        dash = json.load(open(dpath))
    except Exception:
        return None
    try:
        trades = json.load(open(tpath))
    except Exception:
        trades = []
    pos = dash.get("positions", {})
    open_val = sum(p.get("shares", 0) * p.get("current_price", p.get("entry", 0))
                   for p in pos.values())
    equity = dash.get("balance", 0) + open_val
    wins = sum(1 for t in trades if t.get("profit", 0) > 0)
    wr = round(wins / len(trades) * 100) if trades else None
    closed_pnl = sum(t.get("profit", 0) for t in trades)
    expectancy = closed_pnl / len(trades) if trades else None
    return {
        "exp": expectancy,
        "variant": variant,
        "equity":  equity,
        "ret":     (equity - START) / START * 100,
        "cash":    dash.get("balance", 0),
        "open":    len(pos),
        "trades":  len(trades),
        "wins":    wins,
        "wr":      wr,
        "closed_pnl": closed_pnl,
        "ws":      dash.get("ws_connected", False),
        "time":    dash.get("time", "?"),
    }


def main():
    rows = []
    for v in discover_variants():
        r = _load(v)
        if r:
            rows.append(r)
    if not rows:
        print("Keine Clone-Daten gefunden.")
        return

    rows.sort(key=lambda r: -r["ret"])
    labels = {v: LABELS.get(v, v) for v in [r["variant"] for r in rows]}

    # ── Konsolen-Tabelle ──────────────────────────────────────────────────────
    print("=" * 82)
    print("  CLONE-EXPERIMENT VERGLEICH  (Start je $" + "{:,.0f}".format(START) + ")")
    print("=" * 82)
    hdr = "{:<32} {:>9} {:>8} {:>6} {:>7} {:>5} {:>8}".format(
        "Variante", "Equity", "Rendite", "Pos", "Trades", "WR", "Exp/Tr")
    print(hdr)
    print("-" * 82)
    for i, r in enumerate(rows):
        crown = " <" if i == 0 else "  "
        print("{:<32} {:>9} {:>7}% {:>6} {:>7} {:>5} {:>8}{}".format(
            labels[r["variant"]][:32],
            "${:,.0f}".format(r["equity"]),
            ("+" if r["ret"] >= 0 else "") + "{:.2f}".format(r["ret"]),
            str(r["open"]) + "/8",
            r["trades"],
            (str(r["wr"]) + "%") if r["wr"] is not None else "–",
            ("{:+.2f}$".format(r["exp"])) if r["exp"] is not None else "–",
            crown))
    print("=" * 82)

    # ── Telegram-Report ───────────────────────────────────────────────────────
    if "--tg" in sys.argv:
        tok = config.get("telegram_bot_token", "")
        cid = config.get("telegram_chat_id", "")
        if tok and cid:
            lines = ["\U0001F9EC <b>Clone-Experiment</b> (Start je $5.000)"]
            medals = ["\U0001F947", "\U0001F948", "\U0001F949", "  "]
            for i, r in enumerate(rows):
                arrow = "\U0001F4C8" if r["ret"] >= 0 else "\U0001F4C9"
                lines.append(
                    medals[min(i, len(medals) - 1)] + " <b>" + labels[r["variant"]].split(" · ")[0] + "</b> " +
                    arrow + " " + ("+" if r["ret"] >= 0 else "") + "{:.2f}".format(r["ret"]) + "%" +
                    "  ($" + "{:,.0f}".format(r["equity"]) + ")")
                lines.append("    " + str(r["open"]) + " Pos · " + str(r["trades"]) +
                             " Trades · WR " + ((str(r["wr"]) + "%") if r["wr"] is not None else "–"))
            import requests
            try:
                requests.post("https://api.telegram.org/bot" + tok + "/sendMessage",
                              json={"chat_id": cid, "text": "\n".join(lines), "parse_mode": "HTML"},
                              timeout=10)
                print("[TG] Report gesendet")
            except Exception as e:
                print("[TG] Fehler: " + str(e))


if __name__ == "__main__":
    main()
