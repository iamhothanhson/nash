.PHONY: test-unit test-integration test-fast test-regression send-telegram

# Smoke-test every live/demo Telegram alert (requires .env ALERTS_* + Telegram credentials).
send-telegram:
	PYTHONPATH=. python3 app/commands/send_telegram.py

test-unit:
	PYTHONPATH=. python3 -m pytest -m unit

test-integration:
	PYTHONPATH=. python3 -m pytest -m integration

test-fast: test-unit test-integration

test-regression:
	PYTHONPATH=. python3 -m pytest -m regression
