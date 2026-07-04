## Installation
1. cd ai-trading-bot
2. python3 -m venv .venv
3. source .venv/bin/activate
4. pip install -r requirements.txt
5. Run: python3 manage.py

## Development
watchfiles --filter python "python3 main.py"

## Documentation
- Balance behavior by mode: docs/balance-by-mode.md

### Deploy Live Hearbeat
cp scripts/live_bot_daily_heartbeat.sh /usr/local/bin/
cp scripts/live-bot-daily-heartbeat.{service,timer} /etc/systemd/system/
chmod +x /usr/local/bin/live_bot_daily_heartbeat.sh
systemctl daemon-reload
systemctl enable --now live-bot-daily-heartbeat.timer