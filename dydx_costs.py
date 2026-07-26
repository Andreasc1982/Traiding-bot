#!/usr/bin/env python3
"""Echte dYdX-Kosten statt Annahmen: Gebuehrenstufen von der Chain + Funding-Raten.

WICHTIG: dYdX v4 handelt PERPETUALS, nicht Spot. Neben Gebuehr+Spread faellt
Funding an (auf v4 stuendlich). Ein Vergleich mit Kraken-Spot ohne Funding
waere unehrlich — genau das rechnet dieses Skript aus.

    python3 dydx_costs.py
"""
import json, time, urllib.request, statistics as st

IDX = "https://indexer.dydx.trade/v4"
NODES = ["https://dydx-rest.publicnode.com",
         "https://dydx-api.lavenderfive.com",
         "https://rest.cosmos.directory/dydx"]
FEE_PATH = "/dydxprotocol/v4/feetiers/perpetual_fee_params"


def get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fee_tiers():
    print("=== 1) Gebuehrenstufen (direkt von der Chain) ===")
    for n in NODES:
        try:
            d = get(n + FEE_PATH)
        except Exception as e:
            print("  %s -> %s" % (n.split("//")[1][:28], str(e)[:45]))
            continue
        tiers = (d.get("params") or {}).get("tiers") or []
        if not tiers:
            print("  %s -> keine Tiers im Response" % n)
            continue
        print("  Quelle: %s\n" % n)
        print("  %-12s %14s %14s %12s %12s" % ("Stufe", "Vol 30d abs", "Vol-Anteil",
                                               "Maker", "Taker"))
        for t in tiers:
            mk = int(t.get("maker_fee_ppm", 0)) / 10000.0
            tk = int(t.get("taker_fee_ppm", 0)) / 10000.0
            print("  %-12s %14s %14s %11.4f%% %11.4f%%" % (
                t.get("name", "?"),
                format(int(t.get("absolute_volume_requirement", 0)) // 1000000, ","),
                t.get("total_volume_share_requirement_ppm", "0"), mk, tk))
        return tiers
    print("  Keine Chain-Quelle erreichbar — Gebuehren bleiben Annahme!")
    return None


def funding(tickers):
    print("\n=== 2) Funding-Raten (echte Kosten des Perp-Haltens) ===")
    print("%-12s %12s %12s %12s %14s" % ("Markt", "aktuell/h", "Median/h",
                                         "pro Tag", "annualisiert"))
    out = {}
    for t in tickers:
        try:
            d = get(IDX + "/historicalFunding/%s?limit=100" % t)
        except Exception as e:
            print("%-12s FEHLER %s" % (t, str(e)[:40]))
            continue
        recs = d.get("historicalFunding") or []
        rates = []
        for r in recs:
            try:
                rates.append(float(r.get("rate")))
            except Exception:
                pass
        if not rates:
            print("%-12s (keine Daten)" % t)
            continue
        cur = rates[0] * 100
        med = st.median(rates) * 100
        out[t] = med
        print("%-12s %11.5f%% %11.5f%% %11.4f%% %13.2f%%" % (
            t, cur, med, med * 24, med * 24 * 365))
        time.sleep(0.25)
    return out


def main():
    fee_tiers()
    tickers = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD", "XMR-USD"]
    med = funding(tickers)

    print("\n=== 3) Ehrlicher Kostenvergleich fuer einen 24h-Trade ===")
    print("Kraken-Spot: 0,26%% Taker je Seite = 0,52%% Roundtrip, KEIN Funding.")
    print("dYdX-Perp:   Gebuehr-Roundtrip + Spread + Funding fuer die Haltedauer.\n")
    print("%-12s %16s %16s" % ("Markt", "Funding 24h (Long)", "Bemerkung"))
    for t, m in med.items():
        d = m * 24
        note = ("Long zahlt" if d > 0 else "Long bekommt") + " %.3f%%/Tag" % abs(d)
        print("%-12s %15.4f%%  %s" % (t, d, note))
    print("\nFunding ist richtungsabhaengig: positiv = Long zahlt Short.")


main()
