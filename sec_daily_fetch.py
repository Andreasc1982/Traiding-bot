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
import urllib.request, urllib.error
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sec_clean, health

BASE = "/home/trading2025/trading_bot/sec"
OUT = os.path.join(BASE, "insider_live.csv")
STATE = os.path.join(BASE, "live_state.json")
UA = "TradingResearch contact@example.com"
PAUSE = 0.13                      # SEC erlaubt ~10 Anfragen/s
START_DEFAULT = "2026-07-01"      # Bulkdaten enden mit 2026q2


def get(url, timeout=30, versuche=4):
    """Holt eine URL. 404 kommt sofort durch (Datei existiert nicht),
    alles andere wird wiederholt.

    403/429 heisst bei EDGAR **Drosselung**, nicht "verboten" — dagegen hilft
    nur deutlich laenger warten. Mit den kurzen Netzwerk-Backoffs (2/4/6s)
    lief der Neuaufbau am 03.07. in genau diese Wand.
    """
    letzte = None
    for i in range(versuche):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise                            # kein Index fuer diesen Tag
            letzte = e
            time.sleep(30 * (i + 1) if e.code in (403, 429) else 2 * (i + 1))
        except Exception as e:
            letzte = e
            time.sleep(2 * (i + 1))
    raise letzte


def parse_filing(txt):
    """-> (ticker, [(code, shares, price), ...]) oder None."""
    m = re.search(r"<ownershipDocument>.*?</ownershipDocument>", txt, re.S)
    if not m:
        return None
    try:
        root = ET.fromstring(m.group(0))
    except Exception:
        return None
    tic = sec_clean.ticker_gueltig(root.findtext(".//issuer/issuerTradingSymbol"))
    if not tic:
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
    out, verworfen = sec_clean.filter_ausreisser(out)
    return (tic, out, verworfen) if out else None


def day(dstr):
    """-> (n_transaktionen, tages_agg, ok).

    ok=False heisst: der Tag konnte NICHT vollstaendig geholt werden
    (Netzwerk/SEC-Problem). Der Aufrufer darf den Zeiger dann nicht
    weiterschieben, sonst faellt der Tag dauerhaft aus den Daten.
    """
    d = datetime.strptime(dstr, "%Y-%m-%d")
    q = (d.month - 1) // 3 + 1
    url = ("https://www.sec.gov/Archives/edgar/daily-index/%d/QTR%d/form.%s.idx"
           % (d.year, q, d.strftime("%Y%m%d")))
    try:
        idx = get(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 0, {}, True                    # Feiertag: kein Index
        print("  %s: Index-Abruf fehlgeschlagen (%s)" % (dstr, e), flush=True)
        return 0, {}, False
    except Exception as e:
        print("  %s: Index-Abruf fehlgeschlagen (%s)" % (dstr, e), flush=True)
        return 0, {}, False
    # Ein Filing mit mehreren Reporting Owners steht im Tagesindex EINMAL PRO
    # OWNER (bis 8x) — jeweils unter dessen CIK-Pfad, aber mit derselben
    # Accession-Nummer im Dateinamen. Ohne Dedup wird jede solche Meldung
    # mehrfach gezaehlt: ~52% der Index-Zeilen sind Wiederholungen, und es
    # trifft systematisch Gruppen-Insider (Fonds, Familienholdings, 10%-Eigner).
    paths, gesehen = [], set()
    for line in idx.splitlines():
        if not line.startswith("4 "):
            continue
        mm = re.search(r"(edgar/data/\S+\.txt)", line)
        if not mm:
            continue
        p = mm.group(1)
        acc = p.rsplit("/", 1)[1]                 # 0001193125-26-318541.txt
        if acc in gesehen:
            continue
        gesehen.add(acc)
        paths.append(p)
    if not paths:
        return 0, {}, True
    agg = collections.defaultdict(lambda: [0, 0.0, 0, 0.0])
    buyers = collections.defaultdict(set)
    sellers = collections.defaultdict(set)
    n, fehler, verworfen = 0, 0, 0
    for p in paths:
        try:
            txt = get("https://www.sec.gov/Archives/" + p)
        except Exception:
            fehler += 1
            time.sleep(PAUSE)
            continue
        res = parse_filing(txt)
        time.sleep(PAUSE)
        if not res:
            continue
        tic, trans, weg = res
        verworfen += weg
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
    ok = fehler <= max(2, len(paths) // 50)       # bis 2% Ausfall tolerierbar
    print("  %s: %d Meldungen, %d P/S-Transaktionen, %d Kaeufer-Ticker%s%s"
          % (dstr, len(paths), n, len(buyers),
             ", %d Ausreisser verworfen" % verworfen if verworfen else "",
             "" if ok else "  -> %d Ausfaelle, Tag wird wiederholt" % fehler),
          flush=True)
    return n, agg, ok


def main():
    # Zwei gleichzeitige Laeufe holen dieselben Tage, haengen beide ans CSV an
    # (Duplikate) und provozieren EDGAR-Drosselung. Realistisch, sobald ein
    # langer Nachlauf in den 22:30-Cron laeuft.
    if health.acquire_singleton("sec_daily_fetch") is None:
        print("Ein anderer Lauf ist aktiv — Abbruch.")
        sys.exit(0)
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
    # Nur abgeschlossene Tage: EDGAR nimmt Form 4 bis 22:00 ET an, der Cron
    # laeuft 22:30 MESZ (= 16:30 ET). Wuerde man den laufenden Tag mitnehmen,
    # bekaeme man einen halben Index und der Zeiger stuende danach trotzdem
    # dahinter -> der Rest des Tages fiele dauerhaft weg.
    end = datetime.now() - timedelta(days=1)
    agg = collections.defaultdict(lambda: [0, 0.0, 0, 0.0])
    total, last_ok, abbruch = 0, state.get("last"), None
    while d <= end:
        ds = d.strftime("%Y-%m-%d")
        if d.weekday() < 5:
            n, tag_agg, ok = day(ds)
            if not ok:
                abbruch = ds                      # Zeiger bleibt davor stehen
                break
            for k, v in tag_agg.items():
                z = agg[k]
                z[0] += v[0]; z[1] += v[1]; z[2] += v[2]; z[3] += v[3]
            total += n
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
    if abbruch:
        print("ABBRUCH bei %s — Tag nicht vollstaendig abrufbar, "
              "naechster Lauf holt ihn nach." % abbruch)
        sys.exit(1)


main()
