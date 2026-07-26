#!/usr/bin/env python3
"""Laedt die SEC-Form-4-Bulkdaten und verdichtet sie zu einem Tages-Panel.

Quelle: offizielle "Insider Transactions Data Sets" (ein ZIP je Quartal).
Ergebnis: sec/insider_daily.csv mit je Ticker und FILING-Datum:
    n_kaeufer, kauf_usd, n_verkaeufer, verkauf_usd

WICHTIG — kein Lookahead: aggregiert wird nach **FILING_DATE** (wann die
Information oeffentlich wurde), nicht nach TRANS_DATE (wann gehandelt wurde).
Zwischen beiden liegen bis zu 2 Werktage; nach Transaktionsdatum zu sortieren
wuerde Wissen unterstellen, das damals niemand hatte.

Gewertet werden nur TRANS_CODE 'P' (offener Kauf) und 'S' (offener Verkauf) —
Optionsausuebungen, Schenkungen, Vesting (M/A/G/F...) sind kein Signal.

    python3 sec_insider_fetch.py [startjahr] [endjahr]
"""
import os, sys, csv, io, time, zipfile, collections, urllib.request
from datetime import datetime

BASE = "/home/trading2025/trading_bot/sec"
URL = ("https://www.sec.gov/files/structureddata/data/"
       "insider-transactions-data-sets/%dq%d_form345.zip")
UA = "TradingResearch contact@example.com"
OUT = os.path.join(BASE, "insider_daily.csv")
Y0 = int(sys.argv[1]) if len(sys.argv) > 1 else 2018
Y1 = int(sys.argv[2]) if len(sys.argv) > 2 else 2026


def parse_date(s):
    try:
        return datetime.strptime(s.strip(), "%d-%b-%Y").strftime("%Y-%m-%d")
    except Exception:
        return None


def quarter(year, q, agg):
    url = URL % (year, q)
    path = os.path.join(BASE, "%dq%d.zip" % (year, q))
    if not os.path.exists(path):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) < 10000:
                return 0
            with open(path, "wb") as f:
                f.write(data)
            time.sleep(0.5)
        except Exception as e:
            print("  %dq%d: %s" % (year, q, str(e)[:50]), flush=True)
            return 0
    try:
        zf = zipfile.ZipFile(path)
    except Exception:
        os.remove(path)
        return 0

    # 1) Einreichung -> (Ticker, Filing-Datum)
    sub = {}
    with zf.open("SUBMISSION.tsv") as f:
        rd = csv.DictReader(io.TextIOWrapper(f, "utf-8", errors="replace"),
                            delimiter="\t")
        for r in rd:
            if r.get("DOCUMENT_TYPE") != "4":
                continue
            tic = (r.get("ISSUERTRADINGSYMBOL") or "").strip().upper()
            fd = parse_date(r.get("FILING_DATE") or "")
            if not tic or not fd or not tic.isalpha() or len(tic) > 5:
                continue
            sub[r["ACCESSION_NUMBER"]] = (tic, fd)

    # 2) Transaktionen zuordnen und je (Ticker, Filing-Tag) verdichten
    n = 0
    seen_buyer = collections.defaultdict(set)
    seen_seller = collections.defaultdict(set)
    with zf.open("NONDERIV_TRANS.tsv") as f:
        rd = csv.DictReader(io.TextIOWrapper(f, "utf-8", errors="replace"),
                            delimiter="\t")
        for r in rd:
            acc = r.get("ACCESSION_NUMBER")
            if acc not in sub:
                continue
            code = (r.get("TRANS_CODE") or "").strip().upper()
            if code not in ("P", "S"):
                continue
            try:
                sh = float(r.get("TRANS_SHARES") or 0)
                px = float(r.get("TRANS_PRICEPERSHARE") or 0)
            except Exception:
                continue
            if sh <= 0 or px <= 0:
                continue
            tic, fd = sub[acc]
            key = (tic, fd)
            usd = sh * px
            if code == "P":
                agg[key][1] += usd
                seen_buyer[key].add(acc)
            else:
                agg[key][3] += usd
                seen_seller[key].add(acc)
            n += 1
    for k, v in seen_buyer.items():
        agg[k][0] += len(v)
    for k, v in seen_seller.items():
        agg[k][2] += len(v)
    zf.close()
    return n


def main():
    os.makedirs(BASE, exist_ok=True)
    agg = collections.defaultdict(lambda: [0, 0.0, 0, 0.0])  # nB, kaufUSD, nS, verkUSD
    total = 0
    for y in range(Y0, Y1 + 1):
        for q in (1, 2, 3, 4):
            n = quarter(y, q, agg)
            if n:
                total += n
                print("  %dq%d: %d Transaktionen (P/S), Panel %d Zeilen"
                      % (y, q, n, len(agg)), flush=True)
    if not agg:
        print("Keine Daten geladen.")
        return
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "filing_date", "n_kaeufer", "kauf_usd",
                    "n_verkaeufer", "verkauf_usd"])
        for (tic, fd), v in sorted(agg.items()):
            w.writerow([tic, fd, v[0], round(v[1], 2), v[2], round(v[3], 2)])
    print("\n%d offene Kauf-/Verkaufstransaktionen -> %d Ticker-Tage in %s"
          % (total, len(agg), OUT))


main()
