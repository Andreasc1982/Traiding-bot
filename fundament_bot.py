#!/usr/bin/env python3
"""Fundament — Stufe 1 der Portfolio-Architektur. Kein Edge noetig, kein Timing.

Haelt feste Zielgewichte ueber echte Anlageklassen und fuehrt monatlich auf die
Zielgewichte zurueck. Keine Stops, keine Prognosen, keine Signale. Genau das ist
der Punkt: unsere eigenen Messungen zeigen, dass wir die Vergleichsbasis mit
Aktivitaet nicht schlagen — also nehmen wir sie.

Warum kurze statt langer Anleihen: TLT hatte 2022 −22,7 % und ueber die Messreihe
−48,4 % groessten Rueckgang. SHY im selben Jahr −12,6 % bei gleichem Ertrag.

Kein echtes Geld. Taeglich per Cron: bewerten, ggf. zurueckfuehren, Dashboard.

    python3 fundament_bot.py [--rebal] [--dry]
"""
import os, sys, csv, json, time
import statistics as st
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings("ignore")

BASE = "/home/trading2025/trading_bot"
DIR = os.path.join(BASE, "fundament")
STATE = os.path.join(DIR, "state.json")
DASH = os.path.join(DIR, "dashboard.json")
HIST = os.path.join(DIR, "equity.csv")

START_KAPITAL = 10000.0
# Zielgewichte — "Wachstum" aus fundament_mix.py:
#   9,54 % p. a. | Vola 10,4 % | groesster Rueckgang −21,4 % | Sharpe 0,92
ZIEL = {"SPY": 0.50,   # Aktien breit — der Ertragsmotor
        "SHY": 0.20,   # kurze Anleihen — der wirklich defensive Teil
        "GLD": 0.15,   # Gold — geringste Korrelation zu Aktien (0,12)
        "DBC": 0.15}   # Rohstoffe
DRIFT = 0.05           # Rueckfuehrung wenn eine Klasse >5 Pp abweicht
KOSTEN_BP = 5          # auf den umgeschichteten Anteil
FORCE = "--rebal" in sys.argv
DRY = "--dry" in sys.argv


def kurse(syms):
    import yfinance as yf
    df = yf.download(sorted(syms), period="5d", interval="1d",
                     progress=False, auto_adjust=True, group_by="ticker")
    out = {}
    for s in sorted(syms):
        try:
            sub = df[s].dropna() if len(syms) > 1 else df.dropna()
            if len(sub):
                out[s] = float(sub["Close"].values[-1])
        except Exception:
            continue
    return out


def load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"cash": START_KAPITAL, "anteile": {}, "trades": [],
                "start": datetime.now().strftime("%Y-%m-%d"),
                "letzte_rueckfuehrung": None, "rueckfuehrungen": 0,
                "kosten_gesamt": 0.0}


def save(o, p):
    t = p + ".tmp"
    json.dump(o, open(t, "w"), indent=1)
    os.replace(t, p)


# ── Bauart-Treue ──────────────────────────────────────────────────────────────
# Ein Mischdepot gegen SPY zu messen ist sinnlos: es haelt nur 50 % Aktien und
# muss im steigenden Markt zurueckbleiben. Die aussagekraeftige Frage lautet,
# ob es liefert, was die Zielgewichte rechnerisch hergeben — und wohin die
# Differenz geht (Handelskosten gegen Rueckfuehrungseffekt).
def bauart_pruefen(start_datum, ist_pct, kosten_gesamt, zeiten):
    try:
        import yfinance as yf
        beg = (datetime.strptime(start_datum, "%Y-%m-%d")
               - timedelta(days=5)).strftime("%Y-%m-%d")
        df = yf.download(list(ZIEL), start=beg, interval="1d", progress=False,
                         auto_adjust=True)["Close"].dropna()
        ab = df[df.index >= start_datum]
        if len(ab) < 2:
            return None
        basis = ab.iloc[0]

        bausteine, mischung = [], 0.0
        for k in sorted(ZIEL, key=lambda x: -ZIEL[x]):
            r = float(ab[k].iloc[-1] / basis[k] - 1) * 100
            beitrag = ZIEL[k] * r
            mischung += beitrag
            bausteine.append({"symbol": k, "ziel_pct": round(ZIEL[k] * 100, 1),
                              "rendite_pct": round(r, 2),
                              "beitrag_pp": round(beitrag, 2)})

        kosten_pp = -kosten_gesamt / START_KAPITAL * 100
        abweichung = ist_pct - mischung

        # Kurve der reinen Mischung je Stichtag, zum Uebereinanderlegen
        verlauf, gesehen = [], set()
        for z in zeiten:
            tag = z[:10]
            if tag in gesehen:
                continue
            bis = ab[ab.index <= tag]
            if len(bis) < 1:
                continue
            gesehen.add(tag)
            faktor = sum(ZIEL[k] * float(bis[k].iloc[-1] / basis[k]) for k in ZIEL)
            verlauf.append({"datum": tag,
                            "mischung": round(START_KAPITAL * faktor, 2)})

        return {"bausteine": bausteine,
                "mischung_pct": round(mischung, 2),
                "ist_pct": round(ist_pct, 2),
                "abweichung_pp": round(abweichung, 2),
                "kosten_pp": round(kosten_pp, 3),
                "rueckfuehrung_pp": round(abweichung - kosten_pp, 2),
                "verlauf": verlauf}
    except Exception as e:
        print("[BAUART] nicht berechenbar: %s" % str(e)[:80])
        return None


def main():
    os.makedirs(DIR, exist_ok=True)
    s = load()
    px = kurse(list(ZIEL))
    fehlend = [k for k in ZIEL if k not in px]
    if fehlend:
        print("[FEHLER] keine Kurse fuer: %s — kein Eingriff." % ", ".join(fehlend))
        return
    heute = datetime.now().strftime("%Y-%m-%d")

    # Bewertung
    werte = {k: s["anteile"].get(k, {}).get("stueck", 0.0) * px[k] for k in ZIEL}
    gesamt = s["cash"] + sum(werte.values())

    erst = not s["anteile"]
    monatswechsel = (s["letzte_rueckfuehrung"] or "")[:7] != heute[:7]
    abweichung = max((abs(werte[k] / gesamt - ZIEL[k]) for k in ZIEL),
                     default=1.0) if gesamt > 0 else 1.0
    faellig = FORCE or erst or (monatswechsel and abweichung > 0.005) \
        or abweichung > DRIFT

    if faellig:
        umschlag = sum(abs(ZIEL[k] * gesamt - werte[k]) for k in ZIEL) / 2.0
        kosten = umschlag * (KOSTEN_BP / 10000.0)
        gesamt -= kosten
        neu = {}
        for k in ZIEL:
            wert = ZIEL[k] * gesamt
            neu[k] = {"stueck": wert / px[k], "kurs": px[k]}
        s["anteile"] = neu
        s["cash"] = 0.0
        s["letzte_rueckfuehrung"] = heute
        s["rueckfuehrungen"] += 1
        s["kosten_gesamt"] = round(s.get("kosten_gesamt", 0.0) + kosten, 2)
        # A1 (25.08.2026): nur entry_ts. einsatz_usd und haltedauer_h gibt es hier
        # bewusst NICHT — dieses Depot haelt SPY/SHY/GLD/DBC dauerhaft und fuehrt
        # nur Gewichte zurueck. Es gibt keinen Ein- und Ausstieg, also auch keine
        # Haltedauer. Die Felder trotzdem zu setzen waere eine erfundene Zahl.
        s["trades"].append({"datum": heute, "umschlag": round(umschlag, 2),
                            "kosten": round(kosten, 2), "wert": round(gesamt, 2),
                            "abweichung_pp": round(abweichung * 100, 2),
                            "entry_ts": time.time()})
        s["trades"] = s["trades"][-30:]
        werte = {k: neu[k]["stueck"] * px[k] for k in ZIEL}
        print("[RUECKFUEHRUNG] Umschlag $%.2f, Kosten $%.2f, Abweichung war %.1f Pp"
              % (umschlag, kosten, abweichung * 100))

    gesamt = s["cash"] + sum(werte.values())
    zeilen = []
    for k in sorted(ZIEL, key=lambda x: -ZIEL[x]):
        ist = werte[k] / gesamt if gesamt else 0
        zeilen.append({"symbol": k, "ziel_pct": round(ZIEL[k] * 100, 1),
                       "ist_pct": round(ist * 100, 2),
                       "abweichung_pp": round((ist - ZIEL[k]) * 100, 2),
                       "wert": round(werte[k], 2), "kurs": round(px[k], 2),
                       "stueck": round(s["anteile"].get(k, {}).get("stueck", 0), 4)})

    zeiten = []
    if os.path.exists(HIST):
        try:
            with open(HIST, encoding="utf-8") as f:
                zeiten = [r["zeit"] for r in csv.DictReader(f)]
        except Exception:
            zeiten = []
    zeiten.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    bauart = bauart_pruefen(s["start"], (gesamt / START_KAPITAL - 1) * 100,
                            s.get("kosten_gesamt", 0.0), zeiten)

    dash = {"zeit": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "bauart": bauart,
            "start": s["start"], "start_kapital": START_KAPITAL,
            "equity": round(gesamt, 2),
            "rendite_pct": round((gesamt / START_KAPITAL - 1) * 100, 2),
            "positionen": zeilen,
            "max_abweichung_pp": round(abweichung * 100, 2),
            "drift_schwelle_pp": DRIFT * 100,
            "letzte_rueckfuehrung": s["letzte_rueckfuehrung"],
            "rueckfuehrungen": s["rueckfuehrungen"],
            "kosten_gesamt": s.get("kosten_gesamt", 0.0),
            "trades": s["trades"][-10:],
            "erwartung": {"cagr": 9.54, "vola": 10.4, "max_dd": -21.4,
                          "sharpe": 0.92, "quelle": "fundament_mix.py, 2014-2026"}}

    if DRY:
        print(json.dumps(dash, indent=1)[:1000])
        return
    save(s, STATE)
    save(dash, DASH)
    neu_datei = not os.path.exists(HIST)
    with open(HIST, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if neu_datei:
            w.writerow(["zeit", "equity"] + sorted(ZIEL))
        w.writerow([dash["zeit"], dash["equity"]] +
                   [round(werte[k], 2) for k in sorted(ZIEL)])
    print("%s | Depot $%.2f (%+.2f%%) | max. Abweichung %.1f Pp | %d Rueckfuehrungen"
          % (dash["zeit"], gesamt, dash["rendite_pct"], abweichung * 100,
             s["rueckfuehrungen"]))


main()
