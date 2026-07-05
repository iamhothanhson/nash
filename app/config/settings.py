from __future__ import annotations

import os

MODE = os.getenv("MODE", "demo").strip().lower()

BINANCE_FAPI_LIVE_HOST = os.getenv("BINANCE_FAPI_LIVE_HOST", "https://fapi.binance.com").strip().rstrip("/")
BINANCE_FAPI_DEMO_HOST = os.getenv("BINANCE_FAPI_DEMO_BASE", "https://demo-fapi.binance.com").strip().rstrip("/")
BINANCE_FAPI_KLINES_URL = "fapi/v1/klines"

INITIAL_CAPITAL = os.getenv("INITIAL_CAPITAL", 100.0)
DATA_SOURCE = os.getenv("DATA_SOURCE", "history").strip().lower()
HISTORY_AUTO_FETCH = os.getenv("HISTORY_AUTO_FETCH", "true").strip().lower() == "true"
BACKTEST_END = os.getenv("BACKTEST_END", "").strip()

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_SECRET = os.getenv("BINANCE_SECRET", "").strip()
BINANCE_TESTNET_API_KEY = os.getenv("BINANCE_TESTNET_API_KEY", "").strip()
BINANCE_TESTNET_SECRET = os.getenv("BINANCE_TESTNET_SECRET_KEY", os.getenv("BINANCE_TESTNET_SECRET", "")).strip()

BINANCE_RECV_WINDOW_MS = min(60000, max(1000, os.getenv("BINANCE_RECV_WINDOW_MS", 60000)))
TOTAL_EXPOSURE_MULTIPLIER = os.getenv("TOTAL_EXPOSURE_MULTIPLIER", 5)
BINANCE_MIN_POSITION_SIZE_USDT = os.getenv("BINANCE_MIN_POSITION_SIZE_USDT", 5)
EXPOSURE_MULTIPLIER = os.getenv("EXPOSURE_MULTIPLIER", 1.5)

MAX_TRADES_PER_DAY = os.getenv("MAX_TRADES_PER_DAY", 10)
MAX_LOSSES_PER_DAY = os.getenv("MAX_LOSSES_PER_DAY", 5)
MAX_DAILY_LOSS = os.getenv("MAX_DAILY_LOSS", 0.05)
TARGET_DAILY_ROI = os.getenv("TARGET_DAILY_ROI", 30.0)
MAX_OPEN_POSITIONS = os.getenv("MAX_OPEN_POSITIONS", 1)

# Telegram
ALERTS_ENABLED = os.getenv("ALERTS_ENABLED", "false").strip().lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
ALERTS_MODES = os.getenv("ALERTS_MODES", "demo,live,backtest").strip().lower().split(",")
