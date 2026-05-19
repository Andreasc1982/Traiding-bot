#!/bin/bash
cd /home/trading2025/trading_bot
source /home/trading2025/trading_bot_env/bin/activate

pkill -f super_bot.py
pkill -f "http.server"
sleep 2

screen -dmS trading bash -c 'cd /home/trading2025/trading_bot && source /home/trading2025/trading_bot_env/bin/activate && python3 super_bot.py'
screen -dmS dashboard bash -c 'cd /home/trading2025/trading_bot && python3 -m http.server 8080'

echo "Alles gestartet!"
screen -list
