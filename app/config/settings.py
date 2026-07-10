from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    dotenv_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

BINANCE_FAPI_LIVE_HOST = os.getenv("BINANCE_FAPI_LIVE_HOST", "https://fapi.binance.com").strip().rstrip("/")
BINANCE_FAPI_DEMO_HOST = os.getenv("BINANCE_FAPI_DEMO_BASE", "https://demo-fapi.binance.com").strip().rstrip("/")
BINANCE_FAPI_KLINES_URL = "fapi/v1/klines"

MODE = os.getenv("MODE", "demo").strip().lower()
INITIAL_CAPITAL = os.getenv("INITIAL_CAPITAL", 100.0)
DATA_SOURCE = os.getenv("DATA_SOURCE", "history").strip().lower()
BINANCE_POSITION_MODE = os.getenv("BINANCE_POSITION_MODE", "oneway").strip().lower()
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_SECRET = os.getenv("BINANCE_SECRET", "").strip()
BINANCE_TESTNET_API_KEY = os.getenv("BINANCE_TESTNET_API_KEY", "").strip()
BINANCE_TESTNET_SECRET = os.getenv("BINANCE_TESTNET_SECRET", "").strip()

HISTORY_AUTO_FETCH = os.getenv("HISTORY_AUTO_FETCH", "false").strip().lower()
BACKTEST_END = os.getenv("BACKTEST_END", "").strip()
LEVERAGE = int(os.getenv("LEVERAGE", "10"))

# Telegram
ALERTS_ENABLED = os.getenv("ALERTS_ENABLED", "false").strip().lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
ALERTS_MODES = os.getenv("ALERTS_MODES", "demo,live,backtest").strip().lower().split(",")

BINANCE_RECV_WINDOW_MS = min(60000, max(1000, int(os.getenv("BINANCE_RECV_WINDOW_MS", "60000"))))

# Strategy
ENABLE_LIQUIDITY_SWEEP_REVERSAL = os.getenv("ENABLE_LIQUIDITY_SWEEP_REVERSAL", "false").strip().lower()

TOTAL_EXPOSURE_MULTIPLIER = os.getenv("TOTAL_EXPOSURE_MULTIPLIER", 5)
BINANCE_MIN_POSITION_SIZE_USDT = os.getenv("BINANCE_MIN_POSITION_SIZE_USDT", 5)
EXPOSURE_MULTIPLIER = os.getenv("EXPOSURE_MULTIPLIER", 1.5)
MAX_TRADES_PER_DAY = os.getenv("MAX_TRADES_PER_DAY", 10)
MAX_LOSSES_PER_DAY = os.getenv("MAX_LOSSES_PER_DAY", 5)
MAX_DAILY_LOSS = os.getenv("MAX_DAILY_LOSS", 0.05)
TARGET_DAILY_ROI = os.getenv("TARGET_DAILY_ROI", 30.0)
MAX_OPEN_POSITIONS = os.getenv("MAX_OPEN_POSITIONS", 1)
MIN_POSITION_NOTIONAL = os.getenv("MIN_POSITION_NOTIONAL", 25)

RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.01"))
TP1_R = float(os.getenv("TP1_R", "1.0"))
TP2_R = float(os.getenv("TP2_R", "1.5"))
MAX_EXECUTION_RISK_PER_TRADE = float(os.getenv("MAX_EXECUTION_RISK_PER_TRADE", "0.03"))

_ALLOWED_SYMBOLS_RAW = os.getenv("ALLOWED_SYMBOLS", "TAOUSDT,RENDERUSDT,FETUSDT,SOLUSDT")
ALLOWED_SYMBOLS = [s.strip().upper().replace("/", "") for s in _ALLOWED_SYMBOLS_RAW.split(",") if s.strip()]
_ALLOWED_SET = frozenset(ALLOWED_SYMBOLS)

_SYMBOLS_RAW = os.getenv("SYMBOLS", "").strip()
if _SYMBOLS_RAW:
    _symbols = [s.strip().upper().replace("/", "") for s in _SYMBOLS_RAW.split(",") if s.strip()]
else:
    _symbols = list(ALLOWED_SYMBOLS)
SYMBOLS = [s for s in _symbols if s in _ALLOWED_SET]