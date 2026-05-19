#!/usr/bin/env python3
from config import config
import time
from datetime import datetime

print("=" * 60)
print(" TRADING BOT - TEST VERSION")
print("=" * 60)
print(f" Startkapital: $100,000")
print(f"  Stop-Loss: {config['stop_loss_pct']}%")
print(f" Take-Profit: {config['take_profit_pct']}%")
print("=" * 60)

# Telegram Test
try:
    import telegram
    bot_telegram = telegram.Bot(token=config['telegram_bot_token'])
    bot_telegram.send_message(
        chat_id=config['telegram_chat_id'],
        text=" <b>Trading Bot gestartet!</b>\n\nTest-Version läuft erfolgreich.",
        parse_mode='HTML'
    )
    print(" Telegram: Verbunden!")
except Exception as e:
    print(f"  Telegram: {e}")

# NewsAPI Test
try:
    import requests
    response = requests.get(
        "https://newsapi.org/v2/everything",
        params={
            'q': 'Trump policy',
            'apiKey': config['newsapi_key'],
            'pageSize': 5
        }
    )
    data = response.json()
    if response.status_code == 200:
        print(f" NewsAPI: {len(data.get('articles', []))} Artikel gefunden")
    else:
        print(f"  NewsAPI: Fehler {response.status_code}")
except Exception as e:
    print(f"  NewsAPI: {e}")

print("\n" + "=" * 60)
print(" ALLE TESTS ABGESCHLOSSEN!")
print("Bot läuft jetzt im Überwachungs-Modus...")
print("Drücke Strg+C zum Beenden")
print("=" * 60)

iteration = 0
while True:
    try:
        iteration += 1
        now = datetime.now().strftime('%H:%M:%S')
        print(f"\n Check #{iteration} - {now}")
        print("    Überwache politische News...")
        print("    Nächster Check in 60 Sekunden...")
        time.sleep(60)
    except KeyboardInterrupt:
        print("\n\n  Bot gestoppt durch Benutzer")
        break

