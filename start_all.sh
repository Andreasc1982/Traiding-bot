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
if grep -q '"super"' /home/trading2025/trading_bot/agents/risk_halt.json 2>/dev/null; then
  echo "[start_all] Super Bot uebersprungen -- Risk-Halt aktiv"
else
  screen -dmS trading bash -c '
    cd /home/trading2025/trading_bot &&
    source /home/trading2025/trading_bot_env/bin/activate &&
    PYTHONUNBUFFERED=1 python3 -u super_bot.py > /tmp/super_bot.log 2>&1'
fi

# ── Crypto Bot ────────────────────────────────────────────────────────────────
if grep -q '"crypto"' /home/trading2025/trading_bot/agents/risk_halt.json 2>/dev/null; then
  echo "[start_all] Crypto Bot uebersprungen -- Risk-Halt aktiv"
else
  screen -dmS crypto bash -c '
    cd /home/trading2025/trading_bot/crypto &&
    source /home/trading2025/trading_bot_env/bin/activate &&
    PYTHONUNBUFFERED=1 python3 -u crypto_bot.py > /tmp/crypto_bot.log 2>&1'
fi

# ── Super Bot Dashboard HTTP server (port 8080, serves trading_bot/ root) ─────
screen -dmS dashboard bash -c '
  cd /home/trading2025/trading_bot &&
  python3 /home/trading2025/trading_bot/dash_server.py 8080 dashboard_super.html dashboard.html dashboard.json > /tmp/dashboard.log 2>&1'

# ── Crypto Bot Dashboard HTTP server (port 8081, serves crypto/ subdirectory) ─
screen -dmS dashboard_crypto bash -c '
  cd /home/trading2025/trading_bot/crypto &&
  python3 /home/trading2025/trading_bot/dash_server.py 8081 dashboard_crypto.html crypto_dashboard.json > /tmp/dashboard_crypto.log 2>&1'

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

# ── Clone-Experiment: Gateway + Clones (A–H) + Dashboard ──────────────────────
screen -dmS gateway bash -c '
  cd /home/trading2025/trading_bot/crypto &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u gateway.py > /tmp/gateway.log 2>&1'
sleep 3
for V in A_baseline B_nospikes C_conservative D_contrarian E_moonshot F_contrarian_vix28 G_core H_contra_refined; do
  screen -dmS clone_$V bash -c "
    cd /home/trading2025/trading_bot/crypto &&
    source /home/trading2025/trading_bot_env/bin/activate &&
    PYTHONUNBUFFERED=1 python3 -u clone.py $V > /tmp/clone_$V.log 2>&1"
done
screen -dmS clones_dashboard bash -c '
  fuser -k 8090/tcp 2>/dev/null; sleep 1;
  cd /home/trading2025/trading_bot/crypto/clones &&
  python3 /home/trading2025/trading_bot/dash_server.py 8090 clones_dashboard.html A_baseline_dashboard.json B_nospikes_dashboard.json C_conservative_dashboard.json D_contrarian_dashboard.json E_moonshot_dashboard.json F_contrarian_vix28_dashboard.json G_core_dashboard.json H_contra_refined_dashboard.json > /tmp/clones_dashboard.log 2>&1'

# DEX-Monitor (Solana, read-only)
screen -dmS dex bash -c '
  cd /home/trading2025/trading_bot &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u dex_monitor.py > /tmp/dex_monitor.log 2>&1'
# DEX Paper-Moonshot (simuliert, kein Geld)
screen -dmS dex_paper bash -c '
  cd /home/trading2025/trading_bot &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u dex_paper.py > /tmp/dex_paper.log 2>&1'
# DEX Paper v8 (Aggro-Pyramid) — A/B gegen Baseline v7
screen -dmS dex_paper_v8 bash -c '
  cd /home/trading2025/trading_bot &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u dex_paper.py v8 > /tmp/dex_paper_v8.log 2>&1'
# DEX Paper v9 (Fade-Cut) — A/B gegen Baseline v7
screen -dmS dex_paper_v9 bash -c '
  cd /home/trading2025/trading_bot &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u dex_paper.py v9 > /tmp/dex_paper_v9.log 2>&1'
screen -dmS dex_dashboard bash -c '
  fuser -k 8091/tcp 2>/dev/null; sleep 1;
  cd /home/trading2025/trading_bot/dex &&
  python3 /home/trading2025/trading_bot/dash_server.py 8091 dex_dashboard.html watchlist.json heartbeat.json paper_heartbeat.json paper_state.json paper_trades.json paper_heartbeat_v8.json paper_state_v8.json paper_trades_v8.json paper_heartbeat_v9.json paper_state_v9.json paper_trades_v9.json > /tmp/dex_dashboard.log 2>&1'

echo "[start_all] All screen sessions launched."
screen -list
