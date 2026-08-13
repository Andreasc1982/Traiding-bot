#!/usr/bin/env python3
"""Wochenbericht — was ist in den letzten 7 Tagen passiert.

Baut eine HTML-Seite (wochenbericht.html im Repo-Wurzelverzeichnis, ausgeliefert
ueber Port 8080) und schickt eine Kurzfassung per Telegram.

Bewusst ohne Bewertung "gut/schlecht": es zeigt Staende, Veraenderung und
Stoerungen. Ob eine Woche etwas bedeutet, entscheidet nicht der Bericht —
7 Tage sind statistisch nichts.

Aufruf:
    python3 wochenbericht.py            # 7 Tage, HTML + Telegram
    python3 wochenbericht.py 30         # anderer Zeitraum
    python3 wochenbericht.py --kein-tg  # nur HTML
"""
import csv
import json
import os
import sys
from datetime import datetime, timedelta
import urllib.request

BASE = "/home/trading2025/trading_bot"
sys.path.insert(0, BASE)

try:
    from config import config
except Exception:
    config = {}

TELEGRAM_TOKEN   = config.get("telegram_bot_token", "")
TELEGRAM_CHAT_ID = config.get("telegram_chat_id", "")

TAGE   = next((int(a) for a in sys.argv[1:] if a.isdigit()), 7)
KEINTG = "--kein-tg" in sys.argv
ZIEL   = os.path.join(BASE, "wochenbericht.html")
LINK   = "http://trading2025.fritz.box:8080/wochenbericht.html"

JETZT   = datetime.now()
SEIT    = JETZT - timedelta(days=TAGE)


def tg(msg):
    if KEINTG or not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": msg,
                           "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(
            "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage",
            data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print("[TG] Fehler:", e)


def zeit(s):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except Exception:
            continue
    return None


def csv_zeilen(pfad):
    p = os.path.join(BASE, pfad)
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return list(csv.DictReader(f))


def verlauf(pfad, zeit_feld, wert_feld):
    """[(datetime, float)] aufsteigend."""
    raus = []
    for r in csv_zeilen(pfad):
        t = zeit(r.get(zeit_feld, ""))
        try:
            v = float(r.get(wert_feld, ""))
        except Exception:
            continue
        if t:
            raus.append((t, v))
    return sorted(raus)


def depot(name, reihe, hinweis=""):
    """Stand heute, Stand vor N Tagen, Veraenderung."""
    if not reihe:
        return {"name": name, "jetzt": None, "hinweis": "keine Daten"}
    jetzt_wert = reihe[-1][1]
    davor = [v for t, v in reihe if t <= SEIT]
    start = davor[-1] if davor else reihe[0][1]
    seit_start = reihe[0][1]
    return {
        "name": name,
        "jetzt": jetzt_wert,
        "start": start,
        "delta": jetzt_wert - start,
        "delta_pct": (jetzt_wert / start - 1) * 100 if start else 0,
        "gesamt_pct": (jetzt_wert / seit_start - 1) * 100 if seit_start else 0,
        "stand": reihe[-1][0].strftime("%d.%m. %H:%M"),
        "hinweis": hinweis,
    }


def trades(pfad, pct_feld):
    p = os.path.join(BASE, pfad)
    if not os.path.exists(p):
        return []
    try:
        with open(p) as f:
            alle = json.load(f)
    except Exception:
        return []
    raus = []
    for t in alle if isinstance(alle, list) else []:
        ts = zeit(t.get("time", ""))
        if ts and ts >= SEIT:
            raus.append({
                "zeit": ts,
                "symbol": t.get("symbol", "?"),
                "profit": float(t.get("profit", 0) or 0),
                "pct": float(t.get(pct_feld, 0) or 0),
                "grund": t.get("reason", ""),
            })
    return sorted(raus, key=lambda x: x["zeit"])


def stoerungen():
    raus = []
    for r in csv_zeilen("agents/health_log.csv"):
        t = zeit(r.get("time", ""))
        if t and t >= SEIT and r.get("event", "") not in ("START",):
            raus.append((t, r.get("source", ""), r.get("event", ""), r.get("detail", "")[:120]))
    return sorted(raus)


def pruefungen():
    raus = []
    for r in csv_zeilen("agents/funktionspruefung_log.csv"):
        t = zeit(r.get("zeit", ""))
        if t and t >= SEIT:
            raus.append((t, int(r.get("abweichungen", 0) or 0), r.get("details", "")))
    return sorted(raus)


def eur(x, stellen=2):
    return "{:,.{}f}".format(x, stellen).replace(",", " ")


def vz(x, stellen=2, einheit=""):
    return ("+" if x >= 0 else "−") + eur(abs(x), stellen) + einheit


def html_bauen(depots, tr_super, tr_crypto, stoer, pruef):
    def karte(d):
        if d.get("jetzt") is None:
            return ('<div class="karte"><h3>%s</h3><p class="leer">%s</p></div>'
                    % (d["name"], d.get("hinweis", "keine Daten")))
        richtung = "hoch" if d["delta"] >= 0 else "runter"
        return """<div class="karte">
      <h3>%s</h3>
      <div class="wert">$%s</div>
      <div class="delta %s">%s $ &nbsp;(%s %%) &nbsp;in %d Tagen</div>
      <div class="fuss">seit Start %s %% &middot; Stand %s</div>
    </div>""" % (d["name"], eur(d["jetzt"]), richtung, vz(d["delta"]),
                 vz(d["delta_pct"], 2), TAGE, vz(d["gesamt_pct"], 2), d["stand"])

    def trade_tabelle(liste, titel):
        if not liste:
            return "<h2>%s</h2><p class='leer'>keine Trades in diesem Zeitraum</p>" % titel
        summe = sum(t["profit"] for t in liste)
        gewinner = sum(1 for t in liste if t["profit"] > 0)
        zeilen = "".join(
            "<tr><td>%s</td><td>%s</td><td class='%s'>%s $</td><td class='%s'>%s %%</td><td>%s</td></tr>"
            % (t["zeit"].strftime("%d.%m. %H:%M"), t["symbol"],
               "hoch" if t["profit"] >= 0 else "runter", vz(t["profit"]),
               "hoch" if t["pct"] >= 0 else "runter", vz(t["pct"], 1), t["grund"])
            for t in reversed(liste))
        return """<h2>%s</h2>
    <p class="zusammen">%d Trades &middot; %d Gewinner (%d %%) &middot; Ergebnis <span class="%s">%s $</span></p>
    <div class="tabellenrahmen"><table>
      <thead><tr><th>Zeit</th><th>Titel</th><th>Ergebnis</th><th>%%</th><th>Grund</th></tr></thead>
      <tbody>%s</tbody></table></div>""" % (
            titel, len(liste), gewinner, round(gewinner / len(liste) * 100),
            "hoch" if summe >= 0 else "runter", vz(summe), zeilen)

    if stoer:
        stoer_html = "<div class='tabellenrahmen'><table><thead><tr><th>Zeit</th><th>Quelle</th><th>Ereignis</th><th>Detail</th></tr></thead><tbody>" + "".join(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (t.strftime("%d.%m. %H:%M"), q, e, d) for t, q, e, d in reversed(stoer)
        ) + "</tbody></table></div>"
    else:
        stoer_html = "<p class='leer'>keine Stoerungen protokolliert</p>"

    if pruef:
        auffaellig = [p for p in pruef if p[1] > 0]
        pruef_html = ("<p class='zusammen'>%d Pruefungen &middot; %s</p>"
                      % (len(pruef),
                         "alle ohne Befund" if not auffaellig
                         else "%d mit Abweichung" % len(auffaellig)))
        if auffaellig:
            pruef_html += "<ul class='liste'>" + "".join(
                "<li><b>%s</b> — %s</li>" % (t.strftime("%d.%m. %H:%M"), d)
                for t, n, d in reversed(auffaellig)) + "</ul>"
    else:
        pruef_html = "<p class='leer'>noch keine Pruefungen protokolliert</p>"

    return """<!doctype html>
<html lang="de"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wochenbericht</title>
<style>
  :root {
    --grund: #f6f6f4; --flaeche: #fff; --linie: #e2e2dd; --text: #1c1c1a;
    --leise: #6f6f68; --hoch: #1a7f4b; --runter: #b3261e;
  }
  @media (prefers-color-scheme: dark) {
    :root { --grund:#14151a; --flaeche:#1c1e25; --linie:#2c2f38; --text:#e9e9e6;
            --leise:#9a9a94; --hoch:#4ac07e; --runter:#ef6b60; }
  }
  * { box-sizing: border-box; }
  body { margin:0; padding:24px 16px 64px; background:var(--grund); color:var(--text);
         font:16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  .huelle { max-width: 940px; margin: 0 auto; }
  h1 { font-size: 1.6rem; margin: 0 0 4px; }
  h2 { font-size: 1.12rem; margin: 36px 0 10px; }
  .kopfzeile { color: var(--leise); font-size: .9rem; margin-bottom: 26px; }
  .karten { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); }
  .karte { background: var(--flaeche); border: 1px solid var(--linie); border-radius: 12px; padding: 16px; }
  .karte h3 { margin: 0 0 8px; font-size: .82rem; text-transform: uppercase;
              letter-spacing: .06em; color: var(--leise); font-weight: 600; }
  .wert { font-size: 1.6rem; font-weight: 600; font-variant-numeric: tabular-nums; }
  .delta { font-size: .95rem; margin-top: 4px; font-variant-numeric: tabular-nums; }
  .fuss { color: var(--leise); font-size: .8rem; margin-top: 8px; }
  .hoch { color: var(--hoch); } .runter { color: var(--runter); }
  .leer { color: var(--leise); font-style: italic; }
  .zusammen { color: var(--leise); font-size: .92rem; margin: 6px 0 12px; }
  .tabellenrahmen { overflow-x: auto; border: 1px solid var(--linie);
                    border-radius: 12px; background: var(--flaeche); }
  table { border-collapse: collapse; width: 100%%; font-size: .9rem; }
  th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--linie);
           white-space: nowrap; font-variant-numeric: tabular-nums; }
  th { color: var(--leise); font-weight: 600; font-size: .78rem;
       text-transform: uppercase; letter-spacing: .05em; }
  tr:last-child td { border-bottom: none; }
  .liste { padding-left: 20px; } .liste li { margin: 5px 0; font-size: .92rem; }
  .hinweis { margin-top: 44px; padding: 14px 16px; border-left: 3px solid var(--linie);
             color: var(--leise); font-size: .88rem; }
</style></head>
<body><div class="huelle">
  <h1>Wochenbericht</h1>
  <div class="kopfzeile">%s &ndash; %s &middot; erstellt %s</div>

  <div class="karten">%s</div>

  %s
  %s

  <h2>Funktionspruefungen</h2>
  %s

  <h2>Stoerungen im Betrieb</h2>
  %s

  <div class="hinweis">
    Sieben Tage sagen ueber die Qualitaet einer Strategie nichts aus &mdash; die Zahlen hier
    zeigen den Betrieb, nicht den Erfolg. Ein Vorsprung wird erst nach Monaten
    beurteilbar, und auch dann nur gegen einen Massstab.
  </div>
</div></body></html>""" % (
        SEIT.strftime("%d.%m.%Y"), JETZT.strftime("%d.%m.%Y"),
        JETZT.strftime("%d.%m.%Y %H:%M"),
        "".join(karte(d) for d in depots),
        trade_tabelle(tr_super, "Super-Bot &mdash; Trades"),
        trade_tabelle(tr_crypto, "Crypto-Bot &mdash; Trades"),
        pruef_html, stoer_html)


def main():
    eq = verlauf("agents/equity_history.csv", "time", "super")
    eq_c = verlauf("agents/equity_history.csv", "time", "crypto")
    depots = [
        depot("Super-Bot", eq),
        depot("Crypto-Bot", eq_c),
        depot("Insider-Depot", verlauf("sec/paper_equity.csv", "zeit", "equity")),
        depot("Fundament", verlauf("fundament/equity.csv", "zeit", "equity")),
    ]
    tr_super  = trades("trades_history.json", "pnl_pct")
    tr_crypto = trades("crypto/trades_history.json", "pct")
    stoer = stoerungen()
    pruef = pruefungen()

    html = html_bauen(depots, tr_super, tr_crypto, stoer, pruef)
    tmp = ZIEL + ".tmp"
    with open(tmp, "w") as f:
        f.write(html)
    os.replace(tmp, ZIEL)
    print("geschrieben:", ZIEL, "(%d Zeichen)" % len(html))

    zeilen = ["📅 Wochenbericht " + SEIT.strftime("%d.%m.") + "–" + JETZT.strftime("%d.%m."), ""]
    for d in depots:
        if d.get("jetzt") is None:
            zeilen.append("• " + d["name"] + ": keine Daten")
        else:
            zeilen.append("• %s: $%s  (%s $ / %s %%)"
                          % (d["name"], eur(d["jetzt"]), vz(d["delta"]), vz(d["delta_pct"], 2)))
    zeilen.append("")
    zeilen.append("Trades: %d Super, %d Crypto" % (len(tr_super), len(tr_crypto)))
    auff = [p for p in pruef if p[1] > 0]
    zeilen.append("Funktionspruefung: %d Laeufe, %s"
                  % (len(pruef), "ohne Befund" if not auff else "%d mit Abweichung" % len(auff)))
    if stoer:
        zeilen.append("Stoerungen protokolliert: %d" % len(stoer))
    zeilen.append("")
    zeilen.append(LINK)
    tg("\n".join(zeilen))
    print("\n".join(zeilen))


if __name__ == "__main__":
    main()
