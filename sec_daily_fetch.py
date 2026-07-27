#!/usr/bin/env python3
"""Holt taeglich neue Form-4-Meldungen von EDGAR — Live-Quelle fuer den Vorwaertstest.

Die Quartals-Bulkdateien erscheinen nur alle 3 Monate; fuer einen laufenden Test
braucht es den EDGAR-Tagesindex. Fuer jeden Handelstag: Index holen, Form-4-
Eintraege filtern, jede Meldung laden und die offenen Kaeufe/Verkaeufe (Code P/S)
herausziehen. Verdichtet auf (Ticker, Filing-Datum) — gleiches Format wie
sec/insider_daily.csv, damit beide Quellen zusammen ausgewertet werden koennen.

    python3 sec_daily_fetch.py            # alles seit dem letzten Lauf
    python3 sec_daily_fetch.py 2026-07-01 # ab Datum nachholen
"""
import os, sys, csv, json, time, re, collections
import urllib.request
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

BASE = "/home/trading2025/trading_bot/sec"
OUT = os.path.join(BASE, "insider_live.csv")
STATE = os.path.join(BASE, "live_state.json")
UA = "TradingResearch contact@example.com"
PAUSE = 0.13                      # SEC erlaubt ~10 Anfragen/s
START_DEFAULT = "2026-07-01"      # Bulkdaten enden mit 2026q2


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_filing(txt):
    """-> (ticker, [(code, shares, price), ...]) oder None."""
    m = re.search(r"<ownershipDocument>.*?</ownershipDocument>", txt, re.S)
    if not m:
        return None
    try:
        root = ET.fromstring(m.group(0))
    except Exception:
        return None
    tic = root.findtext(".//issuer/issuerTradingSymbol") or ""
    tic = tic.strip().upper()
    if not tic or not tic.isalpha() or len(tic) > 5:
        return None
    out = []
    for tr in root.findall(".//nonDerivativeTransaction"):
        code = tr.findtext(".//transactionCoding/transactionCode") or ""
        if code.strip().upper() not in ("P", "S"):
            continue
        try:
            sh = float(tr.findtext(".//transactionAmounts/transactionShares/value"))
            px = float(tr.findtext(
                ".//transactionAmounts/transactionPricePerShare/value"))
        except Exception:
            continue
        if sh > 0 and px > 0:
            out.append((code.strip().upper(), sh, px))
    return (tic, out) if out else None


def day(dstr, agg):
    d = datetime.strptime(dstr, "%Y-%m-%d")
    q = (d.month - 1) // 3 + 1
    url = ("https://www.sec.gov/Archives/edgar/daily-index/%d/QTR%d/form.%s.idx"
           % (d.year, q, d.strftime("%Y%m%d")))
    try:
        idx = get(url)
    except Exception:
        return 0                                  # Wochenende/Feiertag
    paths = []
    for line in idx.splitlines():
        if not line.startswith("4 "):
            continue
        mm = re.search(r"(edgar/data/\S+\.txt)", line)
        if mm:
            paths.append(mm.group(1))
    if not paths:
        return 0
    buyers = collections.defaultdict(set)
    sellers = collections.defaultdict(set)
    n = 0
    for p in paths:
        try:
            txt = get("https://www.sec.gov/Archives/" + p)
        except Exception:
            time.sleep(PAUSE)
            continue
        res = parse_filing(txt)
        time.sleep(PAUSE)
        if not res:
            continue
        tic, trans = res
        key = (tic, dstr)
        for code, sh, px in trans:
            if code == "P":
                agg[key][1] += sh * px
                buyers[key].add(p)
            else:
                agg[key][3] += sh * px
                sellers[key].add(p)
            n += 1
    for k, v in buyers.items():
        agg[k][0] += len(v)
    for k, v in sellers.items():
        agg[k][2] += len(v)
    print("  %s: %d Meldungen, %d P/S-Transaktionen, %d Kaeufer-Ticker"
          % (dstr, len(paths), n, len(buyers)), flush=True)
    return n


def main():
    os.makedirs(BASE, exist_ok=True)
    try:
        state = json.load(open(STATE))
    except Exception:
        state = {"last": None}
    start = sys.argv[1] if len(sys.argv) > 1 else (
        state.get("last") or START_DEFAULT)
    d = datetime.strptime(start, "%Y-%m-%d")
    if state.get("last") and len(sys.argv) == 1:
        d += timedelta(days=1)
    end = datetime.now()
    agg = collections.defaultdict(lambda: [0, 0.0, 0, 0.0])
    total, last_ok = 0, state.get("last")
    while d <= end:
        ds = d.strftime("%Y-%m-%d")
        if d.weekday() < 5:
            total += day(ds, agg)
            last_ok = ds
        d += timedelta(days=1)
    if agg:
        exists = os.path.exists(OUT)
        with open(OUT, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(["ticker", "filing_date", "n_kaeufer", "kauf_usd",
                            "n_verkaeufer", "verkauf_usd"])
            for (tic, fd), v in sorted(agg.items()):
                w.writerow([tic, fd, v[0], round(v[1], 2), v[2], round(v[3], 2)])
    state["last"] = last_ok
    json.dump(state, open(STATE, "w"))
    print("\n%d Transaktionen ergaenzt, Stand: %s" % (total, last_ok))


main()
