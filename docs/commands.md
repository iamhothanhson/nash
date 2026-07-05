## Save params to parameters folder
python3 app/commands/generate_params.py --roi 14.17

## Test an position on live and demo only
python3 app/commands/open_positions.py --size-usdt 10 --side SELL --sl-pct 0.001
python3 app/commands/simulate_position_events.py --mode demo --direction LONG --send-alerts

## Sync positions from Exchange
python3 app/commands/reconcile_positions.py --scan-allowed
python3 app/commands/reconcile_positions.py --write

# Telegram
python3 app/commands/send_telegram.py --list
python3 app/commands/send_telegram.py --report
python3 app/commands/send_telegram.py --mode demo --only runtime_performance
python3 app/commands/send_telegram.py --exit-decision

# Cronjob
3 0 * * * cd /root/ai-trading-bot && python3 app/analysis/daily_loss_report.py