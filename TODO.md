# TODO — Trading-Bot-System (Stand 2026-06-28)

> Übergabe-/Merkliste für den Umstieg auf den Mac (Win11 wird abgelöst).
> Diese Liste lebt im Repo, damit die lokale Claude-Session auf dem Mac sie beim Start mitliest.

---

## 🎯 Priorität 1 — Claude voller Zugriff auf dem Mac (ZUERST)

Ziel: **Claude Code lokal auf dem Mac** → direkter Zugriff auf Pi (SSH), GitHub und lokale Dateien.
Kein Copy-Paste mehr; Claude führt Befehle selbst aus und liest Ausgaben.

- [ ] Homebrew installieren (Mac-lokales Terminal, NICHT die Pi-SSH-Sitzung)
- [ ] Node + Claude Code CLI installieren (`npm install -g @anthropic-ai/claude-code`)
- [ ] Repo auf dem Mac klonen (`git clone https://github.com/Andreasc1982/Traiding-bot.git`)
- [ ] GitHub-Push/Pull vom Mac testen (Login/Token)
- [x] SSH Mac → Pi (key-auth) — **ERLEDIGT 28.06.** (`ssh trading2025@192.168.188.62`)
- [ ] Claude Code im Repo-Ordner starten → vollen Zugriff verifizieren (Pi-SSH + GitHub + Dateien)
- [ ] Ab dann: Arbeit läuft über die **lokale** Claude-Session, nicht mehr über die Cloud-Session

## 🔧 Priorität 2 — Branch/Repo aufräumen

- [ ] 3 Commits von `claude/claude-dm-reading-gkceba` nach `main` bringen:
      `d076bc0` (super_bot Positions-Fix), `d6e1ca5` (DEPLOY_NOTE), `ed97e36` (SETUP_MAC)
- [ ] Dritten Branch `claude/add-github-token-config-…` prüfen/aufräumen
- [ ] Festlegen: Mac klont/arbeitet auf `main` als Standard

## 🚀 Priorität 3 — Super-Positions-Fix ausrollen

- [ ] `d076bc0` auf den Pi bringen (super_bot.py persistiert jetzt offene Positionen)
- [ ] Super-Bot neu starten, im Log `[STATE] Position wiederhergestellt …` prüfen
- [ ] Behebt die falschen kombinierten `HALT_BOTH` (verdampfende Super-Positionen)

## 🔐 Priorität 4 — Sicherheit

- [ ] WireGuard-Key **rotieren** (jennifer.conf + wg_qr.png enthalten den PRIVATEN Key)
- [ ] jennifer.conf + wg_qr.png aus dem Repo entfernen (inkl. History-Bereinigung)
- [ ] authorized_keys: Tippfehler-Zeile (`AAAC3`, ein A zu wenig) entfernt? → verifizieren
- [ ] `config.py` bleibt ausschließlich auf dem Pi (niemals committen — API-Keys)

## 📊 Priorität 5 — Bot-Status

- [ ] Crypto-Bot: aktuell ge-halted (Tageslimit −8%, 28.06. 06:34) → Auto-Resume bestätigen
- [ ] Sobald Claude direkten Zugriff hat: vollen Live-Zustand prüfen (Logs, Equity, Dashboards)

## 🌙 Priorität 6 — Antizyklischer Backtest (Connors RSI2)

Gewinner-Kombi: RSI(2)<10 + Kurs>MA200 + VIX>28 → 80% Win, +1,85%/Trade, 6% DD, +1,74% in Bären.
- [ ] **Robustheits-Check fertig laufen lassen** (läuft auf dem Pi):
      VIX>28 curve-fit? (Bereich 25–32 testen) + sind die Trades geklumpt (wenige Crashes)?
- [ ] Wenn robust → als **Paper-Variante** (wie die Clones) live mitlaufen lassen
- [ ] Niemals echtes Geld VOR bestandener Robustheitsprüfung

## 🪙 Priorität 7 — DEX-Welt

- [x] DEX in CLAUDE.md dokumentiert (`388f6b9`) + 6 Code-Dateien im Git — **ERLEDIGT**
- [ ] DEX Phase 2b (echte Jupiter-Swaps + funded Hot-Wallet) — später, braucht User-Wallet/Seed

## 🖥️ Priorität 8 — Win11 ablösen

- [ ] Wenn Mac voll läuft: SSH-Key + lokale Kopien sichern, dann Win11 ausmustern

---

## ✅ Schon erledigt (Referenz)

- SSH Mac → Pi mit key-auth eingerichtet (28.06.)
- DEX-Bots dokumentiert + Code im Git gesichert
- Nächtliche GitHub-Backups laufen wieder (25.–28.06.)
- CLAUDE.md aktualisiert (DEX, Health, Clones, ~19 Sessions)
- super_bot Positions-Fix programmiert (committet, aber noch nicht deployed)
