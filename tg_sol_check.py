#!/usr/bin/env python3
"""Alle im Telegram-Dump erwaehnten Solana-Adressen gegen DexScreener pruefen:
was war das, lebt es noch, und wer hat es wann gepostet?

    python3 tg_sol_check.py [Kanal-Teilstring]
"""
import sys, csv, re, json, time, urllib.request, collections

CSVP = "/home/trading2025/trading_bot/tg/scan_all.csv"
csv.field_size_limit(10_000_000)
SOL = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
API = "https://api.dexscreener.com/tokens/v1/solana/%s"

# Base58-Strings, die keine Token-Adressen sind (Wallets, Signaturen, Zufall)
SKIP_WORDS = {"http", "https", "www"}


def fetch(addrs):
    try:
        req = urllib.request.Request(API % ",".join(addrs),
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print("  API-Fehler:", str(e)[:70])
        return []


def main():
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    first = {}
    who = {}
    chat_of = {}
    for r in csv.DictReader(open(CSVP, encoding="utf-8")):
        if sub and sub.lower() not in r["chat"].lower():
            continue
        for a in SOL.findall(r["text"] or ""):
            if a.lower() in SKIP_WORDS:
                continue
            if a not in first or r["date"] < first[a]:
                first[a] = r["date"]
                who[a] = r["sender"]
                chat_of[a] = r["chat"]
    print("%d eindeutige Solana-Kandidaten\n" % len(first))

    found = {}
    addrs = list(first)
    for i in range(0, len(addrs), 25):
        batch = addrs[i:i + 25]
        for p in fetch(batch) or []:
            bt = (p.get("baseToken") or {})
            ad = bt.get("address")
            if not ad:
                continue
            cur = found.get(ad)
            liq = (p.get("liquidity") or {}).get("usd", 0) or 0
            if cur is None or liq > cur["liq"]:
                found[ad] = {"sym": bt.get("symbol", "?"),
                             "name": (bt.get("name") or "")[:28],
                             "liq": liq,
                             "fdv": p.get("fdv") or 0,
                             "price": p.get("priceUsd") or "?",
                             "chg24": ((p.get("priceChange") or {}).get("h24"))}
        time.sleep(1.2)

    print("%-44s %-10s %12s %12s  %s" % ("Adresse", "Symbol", "Liquiditaet",
                                         "FDV", "erste Erwaehnung / von"))
    for a in sorted(first, key=lambda x: first[x]):
        f = found.get(a)
        if not f:
            continue
        print("%-44s %-10s %12s %12s  %s / %s" % (
            a[:44], f["sym"][:10], ("$%s" % format(int(f["liq"]),",")) if f["liq"] else "-",
            ("$%s" % format(int(f["fdv"]),",")) if f["fdv"] else "-",
            first[a][:10], (who[a] or "?")[:18]))
    print("\n%d von %d Adressen sind echte Solana-Token (Rest = Wallets/Signaturen/Zufall)."
          % (len(found), len(first)))
    tot = collections.Counter(found[a]["sym"] for a in found)
    print("Symbole:", ", ".join("%s(%d)" % (s, c) for s, c in tot.most_common(15)))


main()
