#!/usr/bin/env python3
"""Prueft, wie stark der ADS-Einheitenfehler die Insider-Auswertung trifft.

Hintergrund: bei ADR/ADS-Emittenten zaehlt TRANS_SHARES Stammaktien, waehrend
TRANS_PRICEPERSHARE den Preis **je ADS** nennt. `shares * preis` ist dann um
das Hinterlegungsverhaeltnis zu hoch (SVRE: Faktor 43.200). Die bisherige
Pruefung ueber "Kauf > 50x Tagesumsatz" findet nur grobe Faelle — ein
Verhaeltnis von 1:2 oder 1:10 bleibt darunter unsichtbar.

Hier wird das Verhaeltnis direkt aus FOOTNOTES.tsv gelesen, also aus der
Quelle statt aus einer Auffaelligkeit. Ausgabe: welche Ticker betroffen sind,
welche davon im Panel liegen und welche die $5M-ADV-Schwelle passieren —
denn nur die erreichen die Auswertung.

    python3 sec_ads_audit.py            # Bericht
    python3 sec_ads_audit.py --korrigiere <ziel.csv>   # + korrigierter Datensatz
"""
import os, sys, csv, io, re, json, zipfile, collections, pickle, statistics

BASE = "/home/trading2025/trading_bot/sec"
PANEL = "/home/trading2025/trading_bot/agents/panel_ins_2500x8y.pkl"
Y0, Y1 = 2018, 2026

ZAHLWORT = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "fifteen": 15, "twenty": 20, "twenty-five": 25,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "hundred": 100,
    "one hundred": 100, "two hundred": 200, "five hundred": 500,
    "thousand": 1000, "one thousand": 1000,
}

# "One ADS represents four Class A Ordinary Shares."
# "Each ADS represents 43,200 ordinary shares"
# "Each American Depositary Share represents 10 common shares"
RE_ADS_ZU_SHARES = re.compile(
    r"(?:one|each|1)\s+(?:ADS|ADR|American\s+Depositary\s+(?:Share|Receipt))s?\s+"
    r"(?:\(\"?ADSs?\"?\)\s+)?"
    r"(?:represents?|equals?|is\s+equivalent\s+to|=)\s+"
    r"([\d,\.]+|[a-z\-]+(?:\s+hundred|\s+thousand)?)\s+"
    r"(?:[\w\-]+\s+){0,4}?(?:ordinary|common|class\s+[ab])\s*(?:share|stock)",
    re.I)

# Umkehrung: "Every 10 ordinary shares represent one ADS"
RE_SHARES_ZU_ADS = re.compile(
    r"(?:every|each)\s+([\d,\.]+|[a-z\-]+)\s+"
    r"(?:[\w\-]+\s+){0,3}?(?:ordinary|common)\s*(?:share|stock)s?\s+"
    r"(?:represents?|equals?|=)\s+(?:one|1|a)\s+"
    r"(?:ADS|ADR|American\s+Depositary)",
    re.I)

# Implizit ueber zwei Zahlen, haeufigste ungefasste Form (1.394 Fussnoten):
# "The 70,584 ordinary shares reported in Column 5 are represented by
#  11,764 ADSs."  -> 70.584 / 11.764 = 6
RE_IMPLIZIT = re.compile(
    r"([\d,]+)\s+(?:[\w\-]+\s+){0,4}?(?:ordinary|common|class\s+[ab])\s*"
    r"(?:share|stock)s?\b[^.]{0,80}?represented\s+by\s+([\d,]+)\s+ADSs?",
    re.I)


def zahl(s):
    s = s.strip().lower().rstrip(".")
    try:
        return float(s.replace(",", ""))
    except ValueError:
        pass
    return ZAHLWORT.get(s)


def ratio_aus_text(t):
    """-> Stammaktien je ADS, oder None."""
    for rx in (RE_ADS_ZU_SHARES, RE_SHARES_ZU_ADS):
        m = rx.search(t)
        if m:
            n = zahl(m.group(1))
            if n and n > 1:            # 1:1 ist kein Fehler
                return n
    m = RE_IMPLIZIT.search(t)
    if m:
        a, b = zahl(m.group(1)), zahl(m.group(2))
        if a and b and b > 0:
            v = a / b
            # nur runde, plausible Hinterlegungsverhaeltnisse akzeptieren
            if v > 1.5 and abs(v - round(v)) < 0.01:
                return round(v)
    return None


def sammle():
    """-> ratios {accession: n}, ads_erwaehnungen, unparsed[], alle_acc

    `alle_acc` sind ALLE Filings mit irgendeiner ADS/ADR-Erwaehnung — auch
    ohne auslesbares Verhaeltnis. Nur so ist die Kandidatenliste unabhaengig
    davon, was der Parser fasst; fuer die wenigen Treffer im $5M-Band laesst
    sich das Verhaeltnis dann gezielt nachschlagen.
    """
    ratios, ads_gesamt, unparsed, alle_acc = {}, 0, [], set()
    for y in range(Y0, Y1 + 1):
        for q in (1, 2, 3, 4):
            p = os.path.join(BASE, "%dq%d.zip" % (y, q))
            if not os.path.exists(p):
                continue
            try:
                z = zipfile.ZipFile(p)
            except Exception:
                continue
            if "FOOTNOTES.tsv" not in z.namelist():
                z.close()
                continue
            with z.open("FOOTNOTES.tsv") as f:
                rd = csv.DictReader(io.TextIOWrapper(f, "utf-8",
                                                     errors="replace"),
                                    delimiter="\t")
                for r in rd:
                    t = r.get("FOOTNOTE_TXT") or ""
                    if "ADS" not in t and "ADR" not in t and \
                            "American Depositary" not in t:
                        continue
                    ads_gesamt += 1
                    n = ratio_aus_text(t)
                    acc = r.get("ACCESSION_NUMBER")
                    alle_acc.add(acc)
                    if n:
                        # groesstes gefundenes Verhaeltnis je Filing gewinnt
                        ratios[acc] = max(ratios.get(acc, 0), n)
                    elif ("represent" in t.lower() and
                          ("ordinary" in t.lower() or "common" in t.lower())):
                        unparsed.append(t[:120])
            z.close()
    return ratios, ads_gesamt, unparsed, alle_acc


def filings_index():
    """accession -> (ticker, filing_date) — wie im Bulk-Fetcher."""
    sub = {}
    for y in range(Y0, Y1 + 1):
        for q in (1, 2, 3, 4):
            p = os.path.join(BASE, "%dq%d.zip" % (y, q))
            if not os.path.exists(p):
                continue
            try:
                z = zipfile.ZipFile(p)
            except Exception:
                continue
            with z.open("SUBMISSION.tsv") as f:
                rd = csv.DictReader(io.TextIOWrapper(f, "utf-8",
                                                     errors="replace"),
                                    delimiter="\t")
                for r in rd:
                    if r.get("DOCUMENT_TYPE") != "4":
                        continue
                    tic = (r.get("ISSUERTRADINGSYMBOL") or "").strip().upper()
                    if tic:
                        sub[r["ACCESSION_NUMBER"]] = tic
            z.close()
    return sub


def main():
    print("Lese Fussnoten aus den Quartals-ZIPs ...", flush=True)
    ratios, ads_gesamt, unparsed, alle_acc = sammle()
    print("  %d Fussnoten erwaehnen ADS/ADR" % ads_gesamt)
    print("  %d Filings mit auslesbarem Verhaeltnis (>1:1)" % len(ratios))
    print("  %d Fussnoten nennen ein Verhaeltnis, das der Parser NICHT fasst"
          % len(unparsed))
    for t in unparsed[:5]:
        print("      ungelesen: %s" % t)

    print("\nOrdne Filings den Tickern zu ...", flush=True)
    sub = filings_index()
    je_ticker = collections.defaultdict(set)
    for acc, n in ratios.items():
        tic = sub.get(acc)
        if tic:
            je_ticker[tic].add(n)
    print("  %d Ticker betroffen" % len(je_ticker))

    panel = pickle.load(open(PANEL, "rb"))
    adv = {}
    for s, b in panel.items():
        dv = [c * v for c, v in zip(b["closes"], b["volumes"]) if c and v]
        if dv:
            adv[s] = statistics.median(dv)

    im_panel = sorted(t for t in je_ticker if t in adv)
    im_band = sorted(t for t in im_panel if adv[t] >= 5e6)
    print("  davon im Panel (1.432 Titel): %d" % len(im_panel))
    print("  davon ueber der $5M-ADV-Schwelle: %d" % len(im_band))

    if im_band:
        print("\n  DIESE erreichen die Auswertung im $5M-Band:")
        for t in im_band:
            print("    %-6s Verhaeltnis %s | ADV $%.0f"
                  % (t, sorted(je_ticker[t]), adv[t]))
    if im_panel:
        print("\n  im Panel, aber unter $5M ADV (fallen im Band ohnehin raus):")
        print("    " + " ".join("%s(%.0fx)" % (t, max(je_ticker[t]))
                                for t in im_panel if t not in im_band))

    # Gegenprobe ohne Parser: ALLE Ticker mit ADS-Erwaehnung
    alle_tic = set(sub.get(a) for a in alle_acc) - set([None])
    kand = sorted(t for t in alle_tic if t in adv and adv[t] >= 5e6)
    print("\nGegenprobe (unabhaengig vom Parser):")
    print("  %d Ticker erwaehnen ADS/ADR irgendwo, %d davon im $5M-Band:"
          % (len(alle_tic), len(kand)))
    print("    " + " ".join("%s%s" % (t, "*" if t in im_band else "")
                            for t in kand))
    print("    (* = Verhaeltnis ausgelesen; ohne * = ADS erwaehnt, "
          "Verhaeltnis unklar -> pruefen)")

    json.dump({t: max(je_ticker[t]) for t in je_ticker},
              open(os.path.join(BASE, "ads_ratios.json"), "w"))
    print("\nVerhaeltnisse je Ticker -> sec/ads_ratios.json")
    return ratios, sub


main()
