#!/usr/bin/env python3
"""Reicht die Stichprobe? Trennschaerfe-Rechnung fuer den Score-Test.

10 Sektor-ETFs sind KEINE 10 unabhaengigen Beobachtungen — sie haengen alle am
selben Markt. Dieses Skript misst die tatsaechliche Querschnitts-Korrelation aus
echten Kursdaten, leitet die effektive Stichprobengroesse ab und rechnet aus,
welchen Effekt wir nach X Wochen ueberhaupt nachweisen koennten.

    python3 power_check.py
"""
import math, statistics as st
import warnings
warnings.filterwarnings("ignore")

ETFS = ["XLE", "XOP", "XLI", "SLX", "ITA", "XLF", "XLK", "GLD", "PAVE", "IBIT"]
HOURS_PER_DAY = 7           # US-Handelsstunden je Tag (stuendlicher Log)


def returns():
    import yfinance as yf
    df = yf.download(ETFS, period="1y", interval="1d",
                     progress=False, auto_adjust=True)["Close"]
    out = {}
    for s in ETFS:
        try:
            ser = df[s].dropna()
        except Exception:
            continue
        r = [(ser.iloc[i] / ser.iloc[i - 1] - 1) for i in range(1, len(ser))]
        out[s] = [float(x) for x in r if math.isfinite(float(x))]
    n = min(len(v) for v in out.values())
    return {k: v[-n:] for k, v in out.items()}, n


def corr(a, b):
    ma, mb = st.mean(a), st.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da and db else 0.0


def main():
    rets, n = returns()
    syms = sorted(rets)
    print("=== 1) Wie unabhaengig sind die 10 ETFs wirklich? ===")
    print("Datenbasis: %d Handelstage\n" % n)
    pairs = []
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            pairs.append(corr(rets[syms[i]], rets[syms[j]]))
    rbar = st.mean(pairs)
    k = len(syms)
    # effektive Anzahl unabhaengiger Einheiten bei gleichfoermiger Korrelation
    k_eff = k / (1 + (k - 1) * rbar) if (1 + (k - 1) * rbar) > 0 else 1
    print("Mittlere paarweise Korrelation: %.3f (min %.3f / max %.3f)"
          % (rbar, min(pairs), max(pairs)))
    print("-> aus %d ETFs werden effektiv **%.1f unabhaengige Einheiten**\n" % (k, k_eff))

    print("Staerkste Paare (fast Dubletten):")
    tri = []
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            tri.append((corr(rets[syms[i]], rets[syms[j]]), syms[i], syms[j]))
    for c, a, b in sorted(tri, reverse=True)[:4]:
        print("   %s / %s  %.3f" % (a, b, c))
    print("Schwaechste (echte Diversifikation):")
    for c, a, b in sorted(tri)[:3]:
        print("   %s / %s  %.3f" % (a, b, c))

    print("\n=== 2) Was koennen wir nach X Wochen nachweisen? ===")
    print("Faustformel Trennschaerfe 80%%, Signifikanz 5%%:  n_eff ~ 8 / r^2")
    print("Serielle Abhaengigkeit: stuendliche Punkte eines langsam laufenden")
    print("Scores zaehlen nicht voll — konservativ 1 unabhaengiger Punkt je Tag.\n")
    print("%-10s %12s %14s %22s" % ("Zeitraum", "Rohpunkte", "n_eff (Tage x k_eff)",
                                    "kleinster Effekt r"))
    for weeks in (1, 2, 4, 8, 12, 26, 52):
        days = weeks * 5
        raw = days * HOURS_PER_DAY * k
        neff = days * k_eff
        rmin = math.sqrt(8 / neff) if neff > 0 else 9
        print("%-10s %12s %14.0f %21.2f" % (
            "%d Wochen" % weeks, format(raw, ","), neff,
            rmin if rmin <= 1 else float("nan")))

    print("\nZum Einordnen: reale Sentiment-/News-Signale liegen bei r = 0,02-0,10.")
    print("Ein r von 0,3+ waere aussergewoehnlich; r ueber 0,5 waere unglaubwuerdig")
    print("und eher ein Hinweis auf einen Fehler (z.B. Lookahead).")

    print("\n=== 3) Der Ausweg: Querschnitts-Test statt Niveau-Test ===")
    print("Der Bot entscheidet nicht 'steigt der Markt', sondern 'welcher Sektor ist")
    print("der beste'. Genau so muss getestet werden: je Zeitpunkt nach Score sortieren")
    print("und Bestes-minus-Schlechtestes messen. Das rechnet den gemeinsamen Markt-")
    print("faktor heraus. Sauber gezaehlt bleiben dann rund k-1 unabhaengige Einheiten")
    print("je Tag (ein Freiheitsgrad geht fuer den Marktfaktor drauf), nicht 2,8.")
    print("Konservativ rechne ich zusaetzlich mit Rest-Faktoren (Sektor/Stil) und")
    print("setze k_eff = k/5 fuer grosse Universen.\n")
    print("%-22s %10s %12s %14s" % ("Test", "Zeitraum", "n_eff", "kleinster Effekt r"))
    scen = [("10 ETFs, gepoolt", 10, k_eff),
            ("10 ETFs, Querschnitt", 10, k - 1),
            ("200 Aktien, Querschnitt", 200, 200 / 5.0),
            ("500 Aktien, Querschnitt", 500, 500 / 5.0)]
    for label, _, ke in scen:
        for weeks in (4, 12, 26):
            ne = weeks * 5 * ke
            print("%-22s %8dW %12.0f %14.3f" % (label, weeks, ne, math.sqrt(8 / ne)))
        print()
    print("Realistische Signalstaerke liegt bei r = 0,02-0,10.")
    print("-> 10 ETFs gepoolt: chancenlos. 10 ETFs im Querschnitt: erst ab ~6 Monaten")
    print("   im interessanten Bereich. Breites Aktienuniversum im Querschnitt:")
    print("   erreicht den Bereich in 1-3 Monaten.")
    print("-> Die Ausweitung auf viele Einzelaktien ist damit auch eine MESS-")
    print("   entscheidung, nicht nur eine Handelsentscheidung.")


main()
