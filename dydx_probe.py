#!/usr/bin/env python3
"""dYdX v4 Public-Indexer-Test: erreichbar? welche Maerkte? wie teuer real?

Misst was sofort messbar ist: Erreichbarkeit/Latenz, Marktliste mit Volumen,
Spread und Orderbuch-Tiefe. Daraus die EHRLICHEN Roundtrip-Kosten
(Spread + Gebuehren) im Vergleich zu unserer Kraken-Annahme 0,26%/Seite.

    python3 dydx_probe.py [anzahl_maerkte]
"""
import sys, json, time, urllib.request

BASE = "https://indexer.dydx.trade/v4"
# dYdX v4 Basis-Gebuehrenstufe (offizielle Schedule, hier als Annahme markiert)
MAKER_BPS = 1.0     # 0.010%
TAKER_BPS = 5.0     # 0.050%
KRAKEN_TAKER_PCT = 0.26


def get(path, timeout=15):
    t0 = time.time()
    req = urllib.request.Request(BASE + path,
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    return data, (time.time() - t0) * 1000


def main():
    topn = int(sys.argv[1]) if len(sys.argv) > 1 else 12

    print("=== 1) Erreichbarkeit ===")
    try:
        mk, ms = get("/perpetualMarkets")
    except Exception as e:
        print("NICHT ERREICHBAR:", str(e)[:120])
        return
    markets = mk.get("markets", {})
    print("OK — %d Maerkte, Antwortzeit %.0f ms" % (len(markets), ms))

    rows = []
    for t, m in markets.items():
        try:
            vol = float(m.get("volume24H") or 0)
        except Exception:
            vol = 0
        rows.append((vol, t, m))
    rows.sort(reverse=True)

    print("\n=== 2) Top-Maerkte nach 24h-Volumen ===")
    print("%-16s %16s %14s %12s" % ("Markt", "Volumen 24h", "Open Interest", "Preis"))
    for vol, t, m in rows[:topn]:
        print("%-16s %16s %14s %12s" % (
            t, format(int(vol), ","),
            format(int(float(m.get("openInterest") or 0)), ","),
            m.get("oraclePrice", "?")))

    print("\n=== 3) Orderbuch: Spread + Tiefe + Imbalance ===")
    print("%-14s %10s %9s %11s %11s  %s" % (
        "Markt", "Mid", "Spread", "Bid-Tiefe", "Ask-Tiefe", "Imbalance"))
    lat = []
    for vol, t, m in rows[:topn]:
        try:
            ob, ims = get("/orderbooks/perpetualMarket/%s" % t)
            lat.append(ims)
        except Exception as e:
            print("%-14s FEHLER %s" % (t, str(e)[:40]))
            continue
        bids = ob.get("bids") or []
        asks = ob.get("asks") or []
        if not bids or not asks:
            print("%-14s (leeres Buch)" % t)
            continue
        bb = float(bids[0]["price"])
        ba = float(asks[0]["price"])
        mid = (bb + ba) / 2
        spread_bps = (ba - bb) / mid * 10000
        # Tiefe: Notional der ersten 10 Level je Seite
        bd = sum(float(x["price"]) * float(x["size"]) for x in bids[:10])
        ad = sum(float(x["price"]) * float(x["size"]) for x in asks[:10])
        imb = (bd - ad) / (bd + ad) if (bd + ad) else 0
        print("%-14s %10.4f %8.2fbp %11s %11s  %+.3f" % (
            t, mid, spread_bps, "$" + format(int(bd), ","),
            "$" + format(int(ad), ","), imb))
        time.sleep(0.25)

    if lat:
        print("\nOrderbuch-Latenz: min %.0f / median %.0f / max %.0f ms"
              % (min(lat), sorted(lat)[len(lat) // 2], max(lat)))

    print("\n=== 4) Was kostet ein Roundtrip WIRKLICH ===")
    print("Annahme dYdX-Basisstufe: Maker %.3f%% / Taker %.3f%% je Seite"
          % (MAKER_BPS / 100, TAKER_BPS / 100))
    print("%-14s %14s %14s %16s" % ("Markt", "Taker-Roundtrip", "Maker-Roundtrip",
                                    "Kraken-Vergleich"))
    for vol, t, m in rows[:min(topn, 8)]:
        try:
            ob, _ = get("/orderbooks/perpetualMarket/%s" % t)
            bids, asks = ob.get("bids") or [], ob.get("asks") or []
            if not bids or not asks:
                continue
            bb, ba = float(bids[0]["price"]), float(asks[0]["price"])
            sp_pct = (ba - bb) / ((bb + ba) / 2) * 100
        except Exception:
            continue
        taker_rt = 2 * TAKER_BPS / 100 + sp_pct        # 2x Gebuehr + 1x Spread
        maker_rt = 2 * MAKER_BPS / 100                 # Maker zahlt keinen Spread
        kraken_rt = 2 * KRAKEN_TAKER_PCT + sp_pct
        print("%-14s %13.3f%% %13.3f%% %15.3f%%" % (t, taker_rt, maker_rt, kraken_rt))
        time.sleep(0.25)
    print("\n(Maker-Roundtrip setzt voraus, dass beide Seiten als Limit-Order "
          "gefuellt werden — nicht garantiert.)")


main()
