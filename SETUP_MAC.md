# Mac-Setup — Trading-Bot Dev-/Deploy-Rechner (ersetzt Win11)

Ziel: Der neue Mac übernimmt die Rolle des Win11-Rechners (`C:\Users\Jennifer\...`),
aber über **GitHub** statt scp-Direktkopie. Vier Bausteine: Git+Repo, Editor/Claude Code,
WireGuard-VPN, SSH zum Pi.

```
Bisher:  Win11 editieren  ──scp──►  Pi  ──►  restart
Neu:     Mac editieren ──push──► GitHub ──(scp ODER git pull)──► Pi ──► restart
```

---

## Phase 1 — Werkzeuge installieren

```bash
# 1. Homebrew (Paketmanager für macOS)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Git + Editor + Node (für Claude Code)
brew install git node
brew install --cask visual-studio-code

# 3. Claude Code CLI (damit Claude lokal arbeiten + zum Pi deployen kann)
npm install -g @anthropic-ai/claude-code
#   Aktueller Installer ggf. unter https://claude.com/claude-code

# 4. WireGuard-VPN
#   Einfachster Weg: "WireGuard" aus dem Mac App Store installieren (GUI).
#   CLI-Alternative:
brew install wireguard-tools
```

---

## Phase 2 — GitHub-Repo klonen

```bash
git config --global user.name  "Dein Name"
git config --global user.email "deine@mail"

# Repo holen (GitHub-Login im Browser, wenn gefragt)
cd ~
git clone https://github.com/Andreasc1982/Traiding-bot.git
cd Traiding-bot
```

Ab jetzt: hier editieren → `git add/commit` → `git push`. Das ist derselbe Stand,
den auch diese Claude-Code-Web-Session bearbeitet.

---

## Phase 3 — WireGuard einrichten (VPN zum Pi)

Die Config `jennifer.conf` liegt im Repo-Root.

**App-Variante (empfohlen):**
1. WireGuard-App öffnen → „Import tunnel(s) from file" → `jennifer.conf` wählen.
   (Oder QR `wg_qr.png` mit „Create from QR code" scannen.)
2. Tunnel aktivieren.

**CLI-Variante:**
```bash
sudo cp jennifer.conf /opt/homebrew/etc/wireguard/wg0.conf
sudo wg-quick up wg0     # runter: sudo wg-quick down wg0
```

**Test:** Bei aktivem VPN muss der Pi (10.8.0.1) erreichbar sein:
```bash
ping -c2 10.8.0.1
# Dashboards: http://10.8.0.1:8080/dashboard_super.html  (Super)
#             http://10.8.0.1:8081/dashboard_crypto.html (Crypto)
#             http://10.8.0.1:8090/clones_dashboard.html (Clones)
```

> ⚠️ Sicherheit: `jennifer.conf`/`wg_qr.png` enthalten den privaten WireGuard-Key und
> liegen im Git-Repo. Nach der Migration den Peer-Key rotieren und beide Dateien aus
> dem Repo entfernen (Git-History mitbereinigen). Siehe Abschnitt „Aufräumen".

---

## Phase 4 — SSH-Zugang zum Pi

**Option A — Key von Win11 übernehmen:** Kopiere `C:\Users\Jennifer\.ssh\id_*` (privat +
`.pub`) nach `~/.ssh/` auf dem Mac, dann `chmod 600 ~/.ssh/id_*`.

**Option B — Neuen Key auf dem Mac erzeugen (sauberer):**
```bash
ssh-keygen -t ed25519 -C "mac-deploy"
# Public Key auf den Pi (WireGuard muss an sein, einmalig Passwort):
ssh-copy-id trading2025@10.8.0.1
```

**SSH-Alias** anlegen, damit alle Befehle aus `CLAUDE.md` (`trading2025@trading`) 1:1 laufen:
```bash
cat >> ~/.ssh/config <<'EOF'

Host trading
    HostName 10.8.0.1
    User trading2025
EOF
chmod 600 ~/.ssh/config
```

**Test:**
```bash
ssh trading2025@trading "echo OK && screen -list"
```

---

## Phase 5 — Deploy-Workflow

### Variante A (sofort einsatzbereit): scp wie bisher, nur vom Mac
Die Befehle aus `CLAUDE.md` funktionieren unverändert, sobald SSH steht:
```bash
# Syntax-Check
scp super_bot.py trading2025@trading:/tmp/sb_check.py
ssh trading2025@trading "python3 -c 'import ast; ast.parse(open(\"/tmp/sb_check.py\").read()); print(\"OK\")'"
# Deploy
scp super_bot.py trading2025@trading:/home/trading2025/trading_bot/super_bot.py
# Neustart
ssh trading2025@trading "screen -S trading -X quit; screen -dmS trading bash -c 'cd /home/trading2025/trading_bot && source /home/trading2025/trading_bot_env/bin/activate && PYTHONUNBUFFERED=1 python3 -u super_bot.py > /tmp/super_bot.log 2>&1'"
```

### Variante B (mittelfristig sauberer): Pi zieht von GitHub
Der Pi hat bereits ein Git-Repo (vom Backup-Agent, Remote = dasselbe GitHub, Branch `main`).
Deploy = auf dem Pi pullen + neu starten. Vorsicht: der Backup-Agent committet auch
Laufzeit-Dateien (`trades_history.json`, `risk_log.json` …) — ein blinder `git pull` kann
mit lokalen Änderungen kollidieren. Deshalb ein kleines Deploy-Skript auf dem Pi:

```bash
# /home/trading2025/trading_bot/deploy.sh   (einmalig anlegen, chmod +x)
#!/bin/bash
cd /home/trading2025/trading_bot || exit 1
git stash push -m deploy-autostash 2>/dev/null   # Laufzeit-Dateien sichern
git fetch origin main
git checkout main
git pull --ff-only origin main
git stash pop 2>/dev/null || true
python3 -c 'import ast; ast.parse(open("super_bot.py").read()); print("super_bot OK")'
python3 -c 'import ast; ast.parse(open("crypto/crypto_bot.py").read()); print("crypto_bot OK")'
# Neustart der betroffenen Sessions:
screen -S trading -X quit; sleep 1
screen -dmS trading bash -c 'cd /home/trading2025/trading_bot && source /home/trading2025/trading_bot_env/bin/activate && PYTHONUNBUFFERED=1 python3 -u super_bot.py > /tmp/super_bot.log 2>&1'
echo "Deploy fertig."
```
Aufruf vom Mac: `ssh trading2025@trading "bash /home/trading2025/trading_bot/deploy.sh"`
(Voraussetzung: Branch ist auf GitHub nach `main` gemmerged.)

### Variante C (das „alles aus einer Hand"): Claude Code lokal
Mit Claude Code auf dem Mac **und aktivem WireGuard** kann Claude den kompletten Deploy
selbst fahren: Code hier editieren → committen → per SSH zum Pi deployen → Logs prüfen.
Dann läuft Editieren UND Deployen aus demselben Fenster.

---

## Aufräumen / Sicherheit (nach erfolgreicher Migration)

1. **WireGuard-Key rotieren** — neuen Peer auf dem Pi anlegen, neue Client-Config erzeugen,
   alte deaktivieren.
2. **Secrets aus dem Repo entfernen:**
   ```bash
   git rm jennifer.conf wg_qr.png
   git commit -m "Remove WireGuard secrets from repo"
   ```
   (Für echte Bereinigung der History später `git filter-repo` o.ä.)
3. **`config.py`** bleibt wie gehabt nur auf dem Pi (ist via `.gitignore` ausgeschlossen) —
   niemals committen (enthält API-Keys).

---

## Schnell-Checkliste

- [ ] Homebrew + git + node + VS Code + Claude Code installiert
- [ ] Repo geklont, `git config` gesetzt, Test-Push funktioniert
- [ ] WireGuard importiert, `ping 10.8.0.1` ok, Dashboards laden im Browser
- [ ] SSH-Key auf dem Pi, `ssh trading2025@trading "screen -list"` ok
- [ ] Ein Test-Deploy (scp oder deploy.sh) durchgespielt
- [ ] WireGuard-Key rotiert + Secrets aus Repo entfernt
