#!/usr/bin/env python3
"""Auswertung des Telegram-Dumps: was ist fuer Crypto/Aktien verwertbar?

    python3 tg_eval.py [tg/scan_all.csv]

Prueft je Kanal/Thema: Volumen, Zeitraum, Taktung, wer postet, und ob
handelbare Anker vorkommen (Contract-Adressen, Cashtags, Ticker, Coins)
sowie markt-relevante Ereignis-Stichworte (Oel/Ruestung/Makro).
"""
import sys, csv, re, collections
from datetime import datetime

PATH = sys.argv[1] if len(sys.argv) > 1 else "/home/trading2025/trading_bot/tg/scan_all.csv"
csv.field_size_limit(10_000_000)

SOL_ADDR = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
EVM_ADDR = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
CASHTAG = re.compile(r"\$([A-Za-z]{2,10})\b")

ETFS = ["XLE", "XOP", "XLI", "SLX", "ITA", "XLF", "XLK", "GLD", "PAVE", "IBIT"]
STOCKS = ["AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN", "GOOG", "LMT", "RTX",
          "NOC", "BA", "XOM", "CVX", "COP", "OXY", "JPM", "GS", "BAC"]
COINS = ["BTC", "BITCOIN", "ETH", "ETHEREUM", "SOL", "SOLANA", "XRP", "DOGE",
         "NAKMAK", "ADA", "LINK", "AVAX", "BNB"]

# Ereignisse mit direkter Wirkung auf Oel (XLE/XOP) und Ruestung (ITA)
OIL = ["hormuz", "hormus", "tanker", "opec", "oil", "öl", "crude", "refinery",
       "raffinerie", "pipeline", "aramco", "barrel"]
WAR = ["strike", "airstrike", "missile", "rakete", "angriff", "attack", "war",
       "krieg", "iran", "israel", "houthi", "hisbollah", "hezbollah",
       "ceasefire", "waffenruhe", "mobilization", "nuclear", "atom"]
MACRO = ["fed", "ezb", "ecb", "zins", "rate hike", "inflation", "cpi", "tariff",
         "zoll", "sanction", "sanktion", "recession", "rezession"]

BREAKING = ["breaking", "eilmeldung", "urgent", "❗", "🚨", "⚡"]


def bucket(rows, keyfn):
    d = collections.defaultdict(list)
    for r in rows:
        d[keyfn(r)].append(r)
    return d


def hits(text, words):
    t = text.lower()
    return sum(1 for w in words if w in t)


def main():
    rows = list(csv.DictReader(open(PATH, encoding="utf-8")))
    print("Nachrichten gesamt: %d\n" % len(rows))

    for chat, msgs in sorted(bucket(rows, lambda r: r["chat"]).items(),
                             key=lambda x: -len(x[1])):
        dates = sorted(m["date"][:10] for m in msgs if m["date"])
        if not dates:
            continue
        d0 = datetime.fromisoformat(dates[0])
        d1 = datetime.fromisoformat(dates[-1])
        span = max((d1 - d0).days, 1)
        print("=" * 78)
        print("%s   %d Msgs | %s .. %s | %.1f/Tag" % (chat, len(msgs), dates[0],
                                                      dates[-1], len(msgs) / span))

        topics = bucket(msgs, lambda r: r["topic"] or "")
        if len(topics) > 1:
            print("  Themen:")
            for t, tm in sorted(topics.items(), key=lambda x: -len(x[1]))[:12]:
                print("    %-46s %5d" % ((t or "(ohne Thema)")[:46], len(tm)))

        senders = collections.Counter(m["sender"] for m in msgs if m["sender"])
        print("  Top-Absender: " + ", ".join("%s (%d)" % (s, c)
                                             for s, c in senders.most_common(5)))
        fwds = collections.Counter(m["fwd_from"] for m in msgs if m["fwd_from"])
        if fwds:
            print("  Weitergeleitet von: " + ", ".join("%s (%d)" % (s, c)
                                                       for s, c in fwds.most_common(4)))

        sol = collections.Counter()
        evm = collections.Counter()
        cash = collections.Counter()
        tick = collections.Counter()
        coin = collections.Counter()
        n_oil = n_war = n_macro = n_break = 0
        for m in msgs:
            t = m["text"] or ""
            if not t:
                continue
            for a in SOL_ADDR.findall(t):
                if not a.isalpha() or not a.isupper():
                    sol[a] += 1
            for a in EVM_ADDR.findall(t):
                evm[a] += 1
            for c in CASHTAG.findall(t):
                cash[c.upper()] += 1
            up = set(re.findall(r"\b[A-Z]{2,6}\b", t))
            for s in ETFS + STOCKS:
                if s in up:
                    tick[s] += 1
            tl = t.upper()
            for c in COINS:
                if re.search(r"\b%s\b" % c, tl):
                    coin[c] += 1
            n_oil += 1 if hits(t, OIL) else 0
            n_war += 1 if hits(t, WAR) else 0
            n_macro += 1 if hits(t, MACRO) else 0
            n_break += 1 if hits(t, BREAKING) else 0

        print("  HANDELBARE ANKER:")
        print("    Solana-Adressen : %d Treffer, %d eindeutig" % (sum(sol.values()), len(sol)))
        print("    EVM-Adressen    : %d Treffer, %d eindeutig" % (sum(evm.values()), len(evm)))
        print("    Cashtags        : %d Treffer, %d eindeutig  %s" % (
            sum(cash.values()), len(cash),
            ", ".join("$%s(%d)" % (k, v) for k, v in cash.most_common(8))))
        print("    ETF/Aktien      : %s" % (", ".join("%s(%d)" % (k, v)
              for k, v in tick.most_common(10)) or "keine"))
        print("    Coins           : %s" % (", ".join("%s(%d)" % (k, v)
              for k, v in coin.most_common(8)) or "keine"))
        print("  MARKT-EREIGNISSE (Nachrichten mit Treffer):")
        print("    Oel %d (%.1f%%) | Krieg/Geopolitik %d (%.1f%%) | Makro %d (%.1f%%) | 'Breaking' %d" % (
            n_oil, 100 * n_oil / len(msgs), n_war, 100 * n_war / len(msgs),
            n_macro, 100 * n_macro / len(msgs), n_break))
        print()


main()
