#!/bin/bash
# Trading Bot — full startup script
# Called by systemd on boot. Safe to run manually too.

export TERM=xterm-256color
export HOME=/home/trading2025

# ── Kill stale screen sessions (safe at boot; no-ops if not running) ──────────
screen -S trading        -X quit 2>/dev/null || true
screen -S crypto         -X quit 2>/dev/null || true
screen -S dashboard      -X quit 2>/dev/null || true
screen -S dashboard_crypto -X quit 2>/dev/null || true
screen -S monitor        -X quit 2>/dev/null || true
screen -S risk           -X quit 2>/dev/null || true
screen -S optimize       -X quit 2>/dev/null || true
screen -S tgrouter       -X quit 2>/dev/null || true
screen -S backup         -X quit 2>/dev/null || true
sleep 2

# ── Clear orphaned port processes ─────────────────────────────────────────────
fuser -k 8080/tcp 2>/dev/null || true
fuser -k 8081/tcp 2>/dev/null || true
sleep 1

# ── Super Bot ─────────────────────────────────────────────────────────────────
screen -dmS trading bash -c '
  cd /home/trading2025/trading_bot &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u super_bot.py > /tmp/super_bot.log 2>&1'

# ── Crypto Bot ────────────────────────────────────────────────────────────────
screen -dmS crypto bash -c '
  cd /home/trading2025/trading_bot/crypto &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u crypto_bot.py > /tmp/crypto_bot.log 2>&1'

# ── Super Bot Dashboard HTTP server (port 8080, serves trading_bot/ root) ─────
screen -dmS dashboard bash -c '
  cd /home/trading2025/trading_bot &&
  python3 -m http.server 8080 > /tmp/dashboard.log 2>&1'

# ── Crypto Bot Dashboard HTTP server (port 8081, serves crypto/ subdirectory) ─
screen -dmS dashboard_crypto bash -c '
  cd /home/trading2025/trading_bot/crypto &&
  python3 -m http.server 8081 > /tmp/dashboard_crypto.log 2>&1'

# ── Monitor Agent ─────────────────────────────────────────────────────────────
screen -dmS monitor bash -c '
  cd /home/trading2025/trading_bot/agents &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u monitor_agent.py > /tmp/monitor.log 2>&1'

# ── Risk Agent ────────────────────────────────────────────────────────────────
screen -dmS risk bash -c '
  cd /home/trading2025/trading_bot/agents &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u risk_agent.py > /tmp/risk.log 2>&1'

# ── Optimization Agent ────────────────────────────────────────────────────────
screen -dmS optimize bash -c '
  cd /home/trading2025/trading_bot/agents &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u optimize_agent.py > /tmp/optimize.log 2>&1'

# ── Telegram Router ───────────────────────────────────────────────────────────
screen -dmS tgrouter bash -c '
  cd /home/trading2025/trading_bot &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u telegram_router.py > /tmp/tgrouter.log 2>&1'

# ── GitHub Backup Agent ───────────────────────────────────────────────────
screen -dmS backup bash -c '
  cd /home/trading2025/trading_bot/agents &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u github_backup.py > /tmp/backup.log 2>&1'

echo "[start_all] All screen sessions launched."
screen -list
