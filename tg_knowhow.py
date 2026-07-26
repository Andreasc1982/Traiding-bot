#!/usr/bin/env python3
"""Wissens-Extraktion aus dem Telegram-Dump: was ist technisch brauchbar?

Nicht Signale, sondern Verfahren/Werkzeuge — DEX-Mechanik, Ausfuehrung, MEV,
Wallets, Privacy, Infrastruktur. Bewertet jede Nachricht nach Fachbegriffs-
Dichte und gibt die ergiebigsten je Thema aus.

    python3 tg_knowhow.py            # Uebersicht + Top je Thema
    python3 tg_knowhow.py <thema>    # alles zu einem Thema
"""
import sys, csv, re, collections

CSVP = "/home/trading2025/trading_bot/tg/scan_all.csv"
csv.field_size_limit(10_000_000)

THEMES = {
    "ausfuehrung": ["jupiter", "raydium", "orca", "slippage", "price impact",
                    "preisauswirkung", "limit order", "swap", "routing", "aggregator",
                    "pump.fun", "pumpfun", "meteora", "liquidity pool", "lp ",
                    "priority fee", "prioritygebühr", "gebühren", "transaktionsgebühr"],
    "mev_rpc": ["mev", "jito", "validator", "rpc", "node", "sandwich", "frontrun",
                "front-run", "bundle", "slot", "blockhash", "confirmed", "finalized",
                "helius", "quicknode", "tps"],
    "wallet_sicherheit": ["seed", "seedphrase", "recovery phrase", "hardware wallet",
                          "cold wallet", "ledger", "trezor", "phantom", "solflare",
                          "exodus", "backup", "private key", "burner", "multisig"],
    "onchain_analyse": ["dexscreener", "birdeye", "solscan", "rugcheck", "holder",
                        "mint authority", "freeze authority", "honeypot", "rug",
                        "bundler", "sniper", "insider", "bubblemap", "wallet cluster",
                        "on-chain", "onchain", "explorer"],
    "privacy_kyc": ["kyc", "no-kyc", "monero", "xmr", "vpn", "tor", "atomic swap",
                    "bisq", "haveno", "peer-to-peer", "p2p", "mixer", "anonym",
                    "datenschutz", "jurisdiktion"],
    "steuer_recht": ["steuer", "haltefrist", "spekulationsfrist", "finanzamt",
                     "mwst", "einkommensteuer", "verlustverrechnung", "mica",
                     "regulierung", "meldepflicht"],
    "staking_defi": ["staking", "stake", "apy", "apr", "yield", "farming", "lending",
                     "airdrop", "vesting", "unlock", "emission", "burn", "tokenomics"],
    "automatisierung": ["bot", "api", "webhook", "script", "automat", "telegram bot",
                        "trading bot", "sniper bot", "copy trading", "wallet tracker",
                        "alert"],
}


def load():
    rows = []
    for r in csv.DictReader(open(CSVP, encoding="utf-8")):
        t = (r["text"] or "").strip()
        if len(t) < 60:
            continue
        rows.append(r)
    return rows


def score(text, words):
    tl = text.lower()
    return sum(1 for w in words if w in tl)


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    rows = load()
    print("Nachrichten mit Substanz (>60 Zeichen): %d\n" % len(rows))

    per_theme = {}
    for th, words in THEMES.items():
        scored = []
        for r in rows:
            s = score(r["text"], words)
            if s >= 2:
                scored.append((s, len(r["text"]), r))
        scored.sort(key=lambda x: (-x[0], -x[1]))
        per_theme[th] = scored

    print("%-20s %8s  %s" % ("Thema", "Treffer", "Kanaele"))
    for th, sc in per_theme.items():
        chats = collections.Counter(r["chat"].split(" ")[0] for _, _, r in sc)
        print("%-20s %8d  %s" % (th, len(sc),
                                 ", ".join("%s(%d)" % (c, n) for c, n in chats.most_common(3))))
    print()

    targets = [only] if only else list(THEMES)
    lim = 25 if only else 6
    cut = 1500 if only else 500
    for th in targets:
        sc = per_theme.get(th, [])
        if not sc:
            continue
        print("=" * 78)
        print("THEMA: %s   (%d Treffer, zeige %d)" % (th.upper(), len(sc), min(lim, len(sc))))
        print("=" * 78)
        seen = set()
        shown = 0
        for s, _, r in sc:
            key = (r["text"] or "")[:80]
            if key in seen:
                continue
            seen.add(key)
            print("\n[%d Begriffe] %s | %s | %s" % (s, r["date"][:10],
                                                   (r["sender"] or "?")[:16],
                                                   (r["topic"] or r["chat"])[:34]))
            print(r["text"][:cut])
            shown += 1
            if shown >= lim:
                break
        print()


main()
