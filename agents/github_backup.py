#!/usr/bin/env python3
"""
GitHub Backup Agent
Commits and pushes all trading-bot changes to GitHub every night at 02:00.

Setup:
  1. Add your GitHub repo URL to config.py:
       "github_repo": "https://<token>@github.com/<user>/<repo>.git"
     A personal access token embedded in the URL is the simplest auth method
     on a headless server (no SSH key needed).
  2. The agent sets/updates the 'origin' remote automatically from config.py
     each run, so you can rotate tokens by editing config.py alone.
  3. git init + initial commit are done once by the deploy procedure.

What is committed:
  - All .py source files, HTML dashboards, shell scripts
  - trades_history.json (both bots), backtest/optimize results + logs, risk_log.json
  Excluded by .gitignore:
  - config.py (API keys/secrets)
  - Runtime state: super_state.json, crypto/crypto_state.json
  - Control files: bot_control.json, crypto/crypto_control.json
  - Live JSON feeds: dashboard.json, crypto/crypto_dashboard.json
  - agents/risk_halt.json
  - *.log, __pycache__/

Screen session: backup (9th session, started by start_all.sh)
Log: /tmp/backup.log
"""

import os
import subprocess
import time
from datetime import datetime, timedelta

try:
    from config import config
except ImportError:
    config = {}

TELEGRAM_TOKEN   = config.get("telegram_bot_token", "")
TELEGRAM_CHAT_ID = config.get("telegram_chat_id", "")
REPO_DIR         = "/home/trading2025/trading_bot"
BACKUP_HOUR      = 2    # 02:00 local time


# ── Helpers ────────────────────────────────────────────────────────────────

def send(msg):
    """Send a Telegram message (best-effort)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        import requests
        requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=5,
        )
    except Exception:
        pass


def run(cmd):
    """Run a shell command in REPO_DIR. Return (returncode, combined output)."""
    result = subprocess.run(
        cmd, shell=True, cwd=REPO_DIR,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    return result.returncode, result.stdout.strip()


def seconds_until_backup():
    """Seconds until the next BACKUP_HOUR:00 local time."""
    now    = datetime.now()
    target = now.replace(hour=BACKUP_HOUR, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


# ── Core backup logic ──────────────────────────────────────────────────────

def backup():
    now_str  = datetime.now().strftime("%Y-%m-%d %H:%M")
    repo_url = config.get("github_repo", "")

    print("[BACKUP] Start " + now_str)

    # Stage all tracked + new files (respects .gitignore)
    rc, out = run("git add -A")
    if rc != 0:
        msg = "❌ GitHub Backup FEHLER (git add): " + out[:300]
        print(msg); send(msg)
        return

    # Nothing changed → skip commit silently
    rc, out = run("git status --porcelain")
    if not out:
        print("[BACKUP] Keine Änderungen — kein Commit nötig")
        return

    # Commit
    rc, out = run('git commit -m "Auto backup ' + now_str + '"')
    if rc != 0:
        msg = "❌ GitHub Backup FEHLER (git commit): " + out[:300]
        print(msg); send(msg)
        return
    print("[BACKUP] Commit OK: " + out.split("\n")[0])

    # Push — skipped if github_repo not configured yet
    if not repo_url:
        print("[BACKUP] Kein 'github_repo' in config.py — Push übersprungen")
        print("[BACKUP] Füge github_repo zu config.py hinzu um Push zu aktivieren")
        return

    # Set/update remote (tolerates first run where origin doesn't exist yet)
    rc, _ = run("git remote get-url origin")
    if rc == 0:
        run("git remote set-url origin " + repo_url)
    else:
        run("git remote add origin " + repo_url)

    # Try 'main' first, fall back to 'master'
    rc, out = run("git push origin main")
    if rc != 0:
        rc, out = run("git push origin master")
    if rc != 0:
        msg = "❌ GitHub Backup FEHLER (push): " + out[:300]
        print(msg); send(msg)
        return

    msg = "✅ GitHub Backup OK — " + now_str
    print(msg); send(msg)


# ── Main loop ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("[BACKUP] GitHub Backup Agent gestartet")
    send("🔄 GitHub Backup Agent gestartet")

    while True:
        wait = seconds_until_backup()
        h, m = divmod(int(wait), 3600)
        m //= 60
        print("[BACKUP] Nächster Backup in " +
              str(h) + "h " + str(m) + "m (02:00 Uhr)")

        time.sleep(wait)

        try:
            backup()
        except Exception as e:
            msg = "❌ GitHub Backup Ausnahme: " + str(e)[:200]
            print(msg); send(msg)

        # Sleep 90 s to prevent double-firing if wake-up lands exactly on the hour
        time.sleep(90)
