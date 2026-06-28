# TODO — Trading-Bot-System (Stand 2026-06-28)

> Merkliste für laufende und offene Aufgaben.

---

## 🌙 Antizyklischer Backtest (Connors RSI2) — OFFEN

Gewinner-Kombi: RSI(2)<10 + Kurs>MA200 + VIX>28 → 80% Win, +1,85%/Trade, 6% DD, +1,74% in Bären.
- [ ] Robustheits-Check: VIX>28 curve-fit? (Bereich 25–32 testen) + Trade-Klumpung prüfen
- [ ] Wenn robust → als Paper-Variante (wie die Clones) live mitlaufen lassen
- [ ] Niemals echtes Geld VOR bestandener Robustheitsprüfung

## 🖥️ Win11 ablösen — fast fertig

- [x] SSH Mac → Pi ✅
- [x] GitHub vom Mac (SSH-Auth) ✅
- [x] WireGuard Mac Peer eingerichtet ✅
- [x] Secrets aus Repo (jennifer.conf/zip/wg_qr.png) ✅
- [x] git user.name/email gesetzt ✅
- [ ] deploy.sh auf Pi anlegen (git pull statt scp — optional)
- [ ] VS Code installieren (optional — Claude Code reicht bereits)
- [ ] Optional: Git-History bereinigen (`git filter-repo`) — Key bereits deaktiviert, Repo privat
- [ ] Win11 endgültig ausmustern

## 🪙 DEX Phase 2b — SPÄTER

- [ ] Echte Jupiter-Swaps + funded Hot-Wallet (braucht User-Wallet/Seed)

---

## ✅ Erledigt (Referenz)

- **28.06.** Claude Code lokal auf Mac, MCP-Server, SSH, GitHub SSH-Auth
- **28.06.** Branches aufgeräumt, main sauber
- **28.06.** super_bot PSAR-Churn-Fix + SL-Cooling für PSAR-STOP deployed
- **28.06.** WireGuard: Mac-Peer (10.8.0.3), Jennifer/Win11-Peer deaktiviert
- **28.06.** Secrets aus Repo entfernt (jennifer.conf, jennifer.zip, wg_qr.png)
- **28.06.** DEX Paper v3 gestartet ($500, EARLY-EXIT, BE-Floor, Progressive Trailing)
- DEX-Bots dokumentiert + Code im Git gesichert
- Nächtliche GitHub-Backups laufen wieder
- CLAUDE.md aktualisiert (DEX, Health, Clones, ~19 Sessions)
