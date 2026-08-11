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
screen -S dydx           -X quit 2>/dev/null || true
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
#[clones beendet 2026-07-26] 
# ── Clone-Experiment: Gateway + Clones (A–H) + Dashboard ──────────────────────
#[clones beendet 2026-07-26] screen -dmS gateway bash -c '
#[clones beendet 2026-07-26]   cd /home/trading2025/trading_bot/crypto &&
#[clones beendet 2026-07-26]   source /home/trading2025/trading_bot_env/bin/activate &&
#[clones beendet 2026-07-26]   PYTHONUNBUFFERED=1 python3 -u gateway.py > /tmp/gateway.log 2>&1'
#[clones beendet 2026-07-26] sleep 3
#[clones beendet 2026-07-26] for V in A_baseline G_core G_mexc I_wide; do
#[clones beendet 2026-07-26]   screen -dmS clone_$V bash -c "
#[clones beendet 2026-07-26]     cd /home/trading2025/trading_bot/crypto &&
#[clones beendet 2026-07-26]     source /home/trading2025/trading_bot_env/bin/activate &&
#[clones beendet 2026-07-26]     PYTHONUNBUFFERED=1 python3 -u clone.py $V > /tmp/clone_$V.log 2>&1"
#[clones beendet 2026-07-26] done
#[clones beendet 2026-07-26] screen -dmS clones_dashboard bash -c '
#[clones beendet 2026-07-26]   fuser -k 8090/tcp 2>/dev/null; sleep 1;
#[clones beendet 2026-07-26]   cd /home/trading2025/trading_bot/crypto/clones &&
#[clones beendet 2026-07-26]   python3 /home/trading2025/trading_bot/dash_server.py 8090 clones_dashboard.html A_baseline_dashboard.json G_core_dashboard.json G_mexc_dashboard.json I_wide_dashboard.json > /tmp/clones_dashboard.log 2>&1'
#[clones beendet 2026-07-26] 
# DEX-Monitor (Solana, read-only)
#[dex beendet 20260726] screen -dmS dex bash -c '
#[dex beendet 20260726]   cd /home/trading2025/trading_bot &&
#[dex beendet 20260726]   source /home/trading2025/trading_bot_env/bin/activate &&
#[dex beendet 20260726]   PYTHONUNBUFFERED=1 python3 -u dex_monitor.py > /tmp/dex_monitor.log 2>&1'
# DEX Paper v12 (Jupiter-Fill) — EINZIGE aktive Variante.
# v7/v9/v10/v11 SUNSET 20.07. (eingefroren $10-19) — Prozesse beendet 25.07.,
# NICHT mehr starten (Monitor hatte sie am 22.07. faelschlich wiederbelebt -> TG-Spam).
#[dex beendet 20260726] screen -dmS dex_paper_v12 bash -c '
#[dex beendet 20260726]   cd /home/trading2025/trading_bot &&
#[dex beendet 20260726]   source /home/trading2025/trading_bot_env/bin/activate &&
#[dex beendet 20260726]   PYTHONUNBUFFERED=1 python3 -u dex_paper.py v12 > /tmp/dex_paper_v12.log 2>&1'
# DEX Bundle-Collector (vorwaerts, Launch-Funding-Graphen frischer Tokens)
#[dex beendet 20260726] screen -dmS dex_bundle bash -c '
#[dex beendet 20260726]   cd /home/trading2025/trading_bot &&
#[dex beendet 20260726]   source /home/trading2025/trading_bot_env/bin/activate &&
#[dex beendet 20260726]   PYTHONUNBUFFERED=1 python3 -u dex_bundle_collector.py > /tmp/dex_bundle_collector.log 2>&1'
# dYdX Orderbuch-Imbalance-Sammler (read-only, kein Konto)
screen -dmS dydx bash -c '
  cd /home/trading2025/trading_bot &&
  source /home/trading2025/trading_bot_env/bin/activate &&
  PYTHONUNBUFFERED=1 python3 -u dydx_collect.py > /tmp/dydx.log 2>&1'
#[dex beendet 20260726] screen -dmS dex_dashboard bash -c '
#[dex beendet 20260726]   fuser -k 8091/tcp 2>/dev/null; sleep 1;
#[dex beendet 20260726]   cd /home/trading2025/trading_bot/dex &&
#[dex beendet 20260726]   python3 /home/trading2025/trading_bot/dash_server.py 8091 dex_dashboard.html watchlist.json heartbeat.json paper_heartbeat.json paper_state.json paper_trades.json paper_heartbeat_v9.json paper_state_v9.json paper_trades_v9.json paper_heartbeat_v10.json paper_state_v10.json paper_trades_v10.json paper_heartbeat_v11.json paper_state_v11.json paper_trades_v11.json paper_heartbeat_v12.json paper_state_v12.json paper_trades_v12.json bundle_live.html bundle_probe/live_report.json bundle_probe.html bundle_probe/report.json > /tmp/dex_dashboard.log 2>&1'

# Insider-Papierdepot Dashboard (Port 8097)
screen -dmS insider_dash bash -c '
  fuser -k 8097/tcp 2>/dev/null; sleep 1;
  cd /home/trading2025/trading_bot/sec &&
  python3 /home/trading2025/trading_bot/dash_server.py 8097 insider_dashboard.html insider_dashboard.json paper_equity.csv > /tmp/insider_dash.log 2>&1'

# Fundament-Dashboard (Port 8098)
screen -dmS fundament_dash bash -c '
  fuser -k 8098/tcp 2>/dev/null; sleep 1;
  cd /home/trading2025/trading_bot/fundament &&
  python3 /home/trading2025/trading_bot/dash_server.py 8098 dashboard.html dashboard.json equity.csv > /tmp/fundament_dash.log 2>&1'

echo "[start_all] All screen sessions launched."
screen -list
