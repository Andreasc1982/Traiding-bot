# Deploy- & Status-Notiz — 2026-06-19

## 1. Offener Live-Deploy: super_bot Positions-Persistenz

**Status:** Im Git-Branch `claude/claude-dm-reading-gkceba` committed (`d076bc0`), aber **noch NICHT auf dem Live-Server (Raspberry Pi) ausgerollt.**

**Was geändert wurde** (`super_bot.py`):
- `_save_state()` schreibt jetzt `positions` (Snapshot unter `positions_lock`) nach `super_state.json`.
- `_load_state()` stellt offene Positionen mit `entry>0 / shares>0`-Sanity-Check wieder her und loggt jede (`[STATE] Position wiederhergestellt: ...`).
- Gespiegelt von der bereits korrekten `crypto_bot._load_state()`.

**Warum** — behebt die Wurzel der falschen `−15%`-Halts: Bei jedem Super-Neustart (Crash, Halt-Kill, Resume) gingen bisher alle offenen Positionen aus dem Tracking verloren. Ihr Wert „verdampfte" aus dem Dashboard, während die Balance auf dem Post-Buy-Cash-Stand blieb → das kombinierte Portfolio fiel scheinbar um den Positionswert → Risk Agent las das als großen Drawdown → falsche `HALT_BOTH`-Bremse. Genau das verursachte die Resume→Halt-Schleife am **11./12./14./18.06.**

**Deploy-Schritte auf dem Server:**
```bash
# 1. Code holen (oder per scp aus dem Branch)
cd /home/trading2025/trading_bot
# super_bot.py aus Branch claude/claude-dm-reading-gkceba übernehmen

# 2. Syntax-Check
python3 -c 'import ast; ast.parse(open("super_bot.py").read()); print("OK")'

# 3. Super Bot neu starten
screen -S trading -X quit
screen -dmS trading bash -c '
  cd /home/trading2025/trading_bot &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u super_bot.py > /tmp/super_bot.log 2>&1'

# 4. Verifizieren
tail -f /tmp/super_bot.log   # sollte "[STATE] Position wiederhergestellt: ..." zeigen (falls Positionen offen)
```

> Hinweis: Ab dem ersten `_save_state()` nach dem Deploy enthält `super_state.json`
> das neue `positions`-Feld. Erst ein Neustart NACH einem solchen Save kann
> Positionen wiederherstellen. Beim allerersten Start nach Deploy ist `positions`
> in der alten State-Datei noch nicht vorhanden → keine Wiederherstellung, harmlos.

---

## 2. Aktiver Risk-Halt (Stand Git-Snapshot 2026-06-19 ~01:43)

**Beide Bots stehen** wegen `HALT_BOTH` (kombinierte −15%-Drawdown-Notbremse):
- Ausgelöst: **2026-06-18 07:14**, alle 7 Crypto-Positionen um 07:15 via `RISK-CLOSE-ALL` geschlossen.
- `halted=True`, `super_halted=True`, `crypto_halted=True`, `manual_hold=False`, `resume_at=None`.

**Verdacht: Fehl-Halt (Artefakt), kein echter −15%-Verlust:**
- `peak_value=91.859,91`, `combined` beim Halt `85.724,38` → echter Drawdown nur **−6,7%** (weit von −15% entfernt).
- Passt exakt zum Positions-Verdampf-Bug aus Punkt 1.

**Auto-Resume-Bedingungen (market-based):**
- Crypto: BTC +5% vom Halt-Tief (`halt_btc_price=63.853,79` → Ziel ≈ **$67.046**) ODER 48h-Safety-Net → **2026-06-20 07:14**.
- Super: SPY +2% vom Halt-Tief (`halt_spy_price=742,43`) ODER 24h-Safety-Net → **2026-06-19 07:14**.

**Sofort-Option:** Per Telegram `/start` senden → re-baselined den Peak und weckt beide Bots
(überschreibt das market-based Warten). Empfohlen erst NACH dem Deploy aus Punkt 1, sonst
kann derselbe Fehl-Halt erneut auftreten.

---

## 3. Clone-Experiment — Status OK

Alle 5 Clones laufen stabil, kein Clone hängt. Im ~26h-Fenster (17.06. 23:20 → 19.06. 01:30)
alle praktisch flat (±0,2% um $5.000) → Stichprobe noch zu dünn für eine Aussage.
- **D_contrarian**: $5.000 / 0 Trades — Kaufbedingung (oversold + Angst) seit Reset 17.06. nie eingetreten.
- **E_moonshot**: 5 offene Positionen, per Design noch kein Close.
- **A vs B** (Spike-Wert): A minimal vorn, aber im Rauschen.

Keine Aktion nötig — weiter Daten sammeln.
