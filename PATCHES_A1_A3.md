# Patches A1 + A3 — zur Anwendung in einer Pi-Sitzung

**Warum nicht direkt eingespielt:** Beide Patches ändern laufenden Bot-Code
(`super_bot.py`, `crypto/crypto_bot.py`, `crypto/clone.py`). Die Mac-Kopien einiger
Dateien driften seit dem 13.08. wieder (Pi hat neuere Stände, z. B. `insider_paper.py`
vom 21.08.). Live-Code wird darum nur in einer Pi-Sitzung geändert — mit
`pi_sync.sh check` vorher, `.bak_<ts>`-Sicherung, `py_compile`, Neustart einzeln.
Alles Übrige aus dem Deploy (venue/, studien/) ist parallel und berührt nichts.

---

## A1 — `entry_ts` + `einsatz_usd` in die Trade-Records

**Ziel:** Einstiegszeit und Einsatz werden gespeichert statt rückgerechnet
(Lücke aus der 22.08.-Analyse: Haltedauer musste über Little's Gesetz geschätzt,
Einsatz aus profit/pct rekonstruiert werden).

**Beide Bots, an drei Stellen je Bot:**

1. **Kauf** (alle Kauf-Pfade: normal, Spike, Whale — überall, wo das
   `positions[symbol]`-Dict angelegt wird) zusätzlich:
   ```python
   "entry_ts": time.time(),
   "einsatz_usd": round(shares * price, 2),   # crypto: qty * price
   ```
2. **Verkauf** (`close_position`, dort wo der Trade-Record für
   `trades_history.json` gebaut wird) zusätzlich:
   ```python
   "entry_ts": pos.get("entry_ts"),
   "einsatz_usd": pos.get("einsatz_usd"),
   "haltedauer_h": round((time.time() - pos["entry_ts"]) / 3600, 2)
                   if pos.get("entry_ts") else None,
   ```
3. **State-Restore** (`_load_state`): keine Änderung nötig — fehlende Keys bei
   Alt-Positionen ergeben `None` im Record (gewollt, ehrlicher als Schätzwert).

**Auch in den Papierdepots** (`insider_paper.py`, `fundament_bot.py`): dieselben
zwei Felder an den Kauf-/Verkaufsstellen, Feldnamen identisch halten — dann kann
eine spätere Auswertung alle vier Depots gleich behandeln.

**Test:** einen Papier-Kauf/Verkauf im Testmodus durchspielen und prüfen, dass
beide Felder im Trade-Record ankommen; `py_compile` auf beide Dateien.

---

## A3 — Maker-Kostenmodell als Clone-Variante F

**Ziel:** misst den Sofort-Hebel „Limit statt Market" — halbe Gebühr (0,16 %
statt 0,26 % je Seite bei Kraken) gegen das Risiko verpasster Fills.

**`crypto/clone.py`, VARIANTS ergänzen:**
```python
"F_maker": dict(spikes=False, memes=True, contrarian=False,
                score_min=0.1, port=8098, maker=True),
```
(wie B_nospikes, plus `maker`-Flag; Port 8098 ist frei — 8097 hat das Insider-Dashboard.)

**Fill-Simulation (Kern des Patches):** Beim Kaufsignal wird nicht sofort gefüllt,
sondern eine Limit-Order zum aktuellen Gateway-Preis simuliert:
```python
# im Kauf-Pfad, wenn VARIANT.get("maker"):
#   Limit = aktueller Preis; Order "offen" in self._pending[symbol] = (limit, ts)
#   In jedem 1s-Preis-Tick aus prices.json:
#     - Preis <= Limit  → Fill zum LIMIT (nicht zum Tick-Preis), Gebühr 0.16 %/Seite
#     - älter als FILL_WINDOW = 120 s → verworfen, Log/Zähler "MISSED_FILL"
#   Verkäufe (Stops) bleiben Taker 0.26 % — ein Stop, der auf einen Maker-Fill
#   wartet, wäre eine Lüge im Risikomodell.
```
`MISSED_FILL`-Zähler ins Dashboard-JSON — die verpassten Entries SIND das
Messergebnis; ohne sie wäre die Variante geschönt.

**Betrieb:** Session `clone_F_maker` in `monitor_agent.BOTS` + `start_all.sh`
ergänzen (beide Stellen — sonst setzt der nächste Monitor-Neustart die Änderung
still zurück, bekannte Falle vom 12.08.). Start bei 5.000 $ wie alle Clones.

**Entscheidungskriterium (vorab):** F schlägt B über ≥ 60 Tage nach Kosten UND
MISSED_FILL-Quote < 25 % → Maker-Ausführung wird Kandidat für den Live-Pfad.
