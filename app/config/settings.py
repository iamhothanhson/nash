from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency fallback
    load_dotenv = None

_CANDIDATE_DOTENV_PATHS = [
    Path(__file__).resolve().parent.parent.parent / ".env",  # project root/.env
    Path(__file__).resolve().parent.parent / ".env",  # legacy app/.env
]
_DOTENV_PATH = next((p for p in _CANDIDATE_DOTENV_PATHS if p.exists()), _CANDIDATE_DOTENV_PATHS[0])
if load_dotenv is not None:
    load_dotenv(dotenv_path=_DOTENV_PATH)
elif _DOTENV_PATH.exists():
    # Minimal fallback loader when python-dotenv is not installed.
    for raw_line in _DOTENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return bool(default)
    if raw in ("1", "true", "yes", "on", "y"):
        return True
    if raw in ("0", "false", "no", "off", "n"):
        return False
    return bool(default)


def _normalize_symbol_token(raw: str) -> str:
    """Accept TAOUSDT, TAO/USDT, SOL/USDT → TAOUSDT, SOLUSDT."""
    s = raw.strip().upper().replace("/", "")
    if not s.endswith("USDT"):
        s = f"{s}USDT"
    return s


def get_allowed_symbols() -> list[str]:
    # Default universe includes SOL; existing .env with only TAO+RENDER unchanged.
    symbols_str = os.getenv("ALLOWED_SYMBOLS", "TAOUSDT,RENDERUSDT,FETUSDT,SOLUSDT")
    out: list[str] = []
    seen: set[str] = set()
    for s in symbols_str.split(","):
        u = _normalize_symbol_token(s)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out or ["TAOUSDT", "RENDERUSDT", "FETUSDT", "SOLUSDT"]


def get_symbols() -> list[str]:
    raw = os.getenv("SYMBOLS", "").strip()
    if not raw:
        return list(ALLOWED_SYMBOLS)
    return [_normalize_symbol_token(s) for s in raw.split(",") if s.strip()]


def _env_float_optional(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return None
    return max(0.0, _env_float(name, 0.0))


def should_log_exit_debug_trace() -> bool:
    """Live/demo: keep exit trace logs. Backtest: only if EXIT_DEBUG=true."""
    return MODE != "backtest" or EXIT_DEBUG


ALLOWED_SYMBOLS = get_allowed_symbols()
_ALLOW_SET = frozenset(ALLOWED_SYMBOLS)

_SYMBOLS_CAND = [s for s in get_symbols() if s in _ALLOW_SET]
SYMBOLS = []
_sym_seen: set[str] = set()
for s in _SYMBOLS_CAND:
    if s not in _sym_seen:
        _sym_seen.add(s)
        SYMBOLS.append(s)
if not SYMBOLS:
    raise Exception("No allowed symbols to trade")

MODE = os.getenv("MODE", "demo").strip().lower()
if MODE not in ("backtest", "demo", "live"):
    raise ValueError(f"Invalid MODE: {MODE!r}; use backtest | demo | live")

DATA_SOURCE = os.getenv("DATA_SOURCE", "mainnet").strip().lower()
if DATA_SOURCE not in ("mainnet", "testnet", "history"):
    raise ValueError(f"Invalid DATA_SOURCE: {DATA_SOURCE!r}; use mainnet | testnet | history")
# When true, backtest.py --fetch may download klines into history_data/*.csv.
# When false, --fetch is blocked; DATA_SOURCE=testnet/mainnet still use live Binance klines.
HISTORY_AUTO_FETCH = os.getenv("HISTORY_AUTO_FETCH", "true").strip().lower() == "true"
# DATA_SOURCE=history only: when true, slice day windows relative to latest local CSV row.
BACKTEST_HISTORY_ANCHOR_LATEST = _env_bool("BACKTEST_HISTORY_ANCHOR_LATEST", True)
# Optional fixed anchor for deterministic backtests. Accepts ISO date/time
# (e.g. 2026-05-10 or 2026-05-10T23:55:00Z) or epoch seconds/milliseconds.
BACKTEST_END = os.getenv("BACKTEST_END", "").strip()

BINANCE_FAPI_LIVE_HOST = os.getenv("BINANCE_FAPI_LIVE_HOST", "https://fapi.binance.com").strip().rstrip("/")
BINANCE_FAPI_DEMO_HOST = os.getenv("BINANCE_FAPI_DEMO_BASE", "https://demo-fapi.binance.com").strip().rstrip("/")
# Public market data (klines, ticker, exchangeInfo): independent of MODE (demo/live).
# "history" uses mainnet as source for cache backfill.
BINANCE_FAPI_MARKET_HOST = (
    BINANCE_FAPI_LIVE_HOST if DATA_SOURCE in ("mainnet", "history") else BINANCE_FAPI_DEMO_HOST
)
BINANCE_FAPI_KLINES_URL = f"{BINANCE_FAPI_MARKET_HOST}/fapi/v1/klines"
# Signed order REST: demo → testnet; live/backtest → mainnet.
BINANCE_FAPI_REST_BASE = BINANCE_FAPI_DEMO_HOST if MODE == "demo" else BINANCE_FAPI_LIVE_HOST

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_SECRET = os.getenv("BINANCE_SECRET", "").strip()
BINANCE_TESTNET_API_KEY = os.getenv("BINANCE_TESTNET_API_KEY", "").strip()
BINANCE_TESTNET_SECRET = os.getenv("BINANCE_TESTNET_SECRET_KEY", os.getenv("BINANCE_TESTNET_SECRET", "")).strip()
def _resolve_binance_position_mode() -> str:
    from execution.position_mode import normalize_position_mode_setting

    raw = os.getenv("BINANCE_POSITION_MODE", "auto")
    return normalize_position_mode_setting(raw)


BINANCE_POSITION_MODE = _resolve_binance_position_mode()
# Signed REST recvWindow (ms). Max 60000 on Binance USDT-M futures.
BINANCE_RECV_WINDOW_MS = min(60000, max(1000, _env_int("BINANCE_RECV_WINDOW_MS", 60000)))

INITIAL_CAPITAL = _env_float("INITIAL_CAPITAL", 100.0)
# Aggregate open-book exposure cap: balance * TOTAL_EXPOSURE_MULTIPLIER. Legacy: TOTAL_VIRTUAL_EXPOSURE, VIRTUAL_MAX_EXPOSURE_FRAC.
_LEGACY_EXPOSURE_V1 = _env_float("VIRTUAL_MAX_EXPOSURE_FRAC", 0.9)
_LEGACY_EXPOSURE_V2 = _env_float("TOTAL_VIRTUAL_EXPOSURE", _LEGACY_EXPOSURE_V1)
TOTAL_EXPOSURE_MULTIPLIER = _env_float("TOTAL_EXPOSURE_MULTIPLIER", 5)

# Base risk = A+ tier (default 1%); A uses A_GRADE_RISK_MULT in other modules if wired.
RISK_PER_TRADE = _env_float("RISK_PER_TRADE", 0.01)
TP1_R = _env_float("TP1_R", 1.0)
TP2_R = _env_float("TP2_R", 1.5)
MAX_EXECUTION_RISK_PER_TRADE = _env_float("MAX_EXECUTION_RISK_PER_TRADE", 0.03)
A_GRADE_RISK_MULT = _env_float("A_GRADE_RISK_MULT", 0.75)
LEVERAGE = _env_int("LEVERAGE", 10)

# Minimum position notional as percent of balance (10 = 10%).
MIN_POSITION_PCT_OF_BALANCE = _env_float("MIN_POSITION_PCT_OF_BALANCE", 10.0)

# Minimum single-position notional (USDT). Plans below this are rejected (default 20).
MIN_POSITION_SIZE_USDT = max(0.0, _env_float("MIN_POSITION_SIZE_USDT", 20.0))

# Max single-position notional (USDT) cap: equity * EXPOSURE_MULTIPLIER (see order_planner).
EXPOSURE_MULTIPLIER = _env_float("EXPOSURE_MULTIPLIER", 1.5)

MAX_TRADES_PER_DAY = _env_int("MAX_TRADES_PER_DAY", 10)
MAX_LOSSES_PER_DAY = _env_int("MAX_LOSSES_PER_DAY", 5)
ANALYZE_LOSSES = _env_bool("ANALYZE_LOSSES", True)
LOSS_FILTER_ENABLED = _env_bool("LOSS_FILTER_ENABLED", False)
# Daily loss cap as a fraction of virtual equity (e.g. 0.05 = 5%).
MAX_DAILY_LOSS = _env_float("MAX_DAILY_LOSS", 0.05)
# Daily ROI target percent (e.g. 10 = 10%); when daily_pnl_percent >= this, trading_stopped=true.
TARGET_DAILY_ROI = _env_float("TARGET_DAILY_ROI", 30.0)
MAX_OPEN_POSITIONS = _env_int("MAX_OPEN_POSITIONS", 1)
POSITION_MANAGE_LOOP_SEC = _env_float("POSITION_MANAGE_LOOP_SEC", 3.0)
# Live/demo: place reduce-only LIMIT orders at TP1/TP2 right after entry (+ exchange SL).
EXCHANGE_TP_ORDERS_ON_OPEN = _env_bool("EXCHANGE_TP_ORDERS_ON_OPEN", True)
# Live/demo: after TP1, place TP2 TAKE_PROFIT_MARKET on exchange (BE stop qty excludes TP2 leg).
EXCHANGE_TP2_AFTER_TP1 = _env_bool("EXCHANGE_TP2_AFTER_TP1", True)
# Live/demo: detect TP1/TP2 via GET /fapi/v1/order status=FILLED (not 5m bar touch).
EXCHANGE_TP_DETECT_BY_ORDER_STATUS = _env_bool("EXCHANGE_TP_DETECT_BY_ORDER_STATUS", True)
# Live/demo: throttle retries after a failed HARD STOP exchange close; reduce trigger spam under volatility.
HARD_STOP_FAILED_CLOSE_COOLDOWN_SEC = _env_float("HARD_STOP_FAILED_CLOSE_COOLDOWN_SEC", 3.0)
# Live/demo: block new entries on a symbol after a HARD STOP exit until this many seconds elapse.
HARD_STOP_REENTRY_COOLDOWN_SEC = _env_float("HARD_STOP_REENTRY_COOLDOWN_SEC", 900.0)

HARD_STOP_BUFFER_FRAC = _env_float("HARD_STOP_BUFFER_FRAC", 0.0)
HARD_STOP_STALE_MARK_MAX_AGE_SEC = _env_float("HARD_STOP_STALE_MARK_MAX_AGE_SEC", 20.0)
HARD_STOP_MAX_SLIPPAGE_R = _env_float("HARD_STOP_MAX_SLIPPAGE_R", 4.0)
# After TP2: avoid instant runner kill from the forming 5m wick + tightened TP1-level stop.
HARD_STOP_AFTER_TP2_GRACE_SEC = _env_float("HARD_STOP_AFTER_TP2_GRACE_SEC", 300.0)
HARD_STOP_AFTER_TP2_SKIP_SAME_BAR = _env_bool("HARD_STOP_AFTER_TP2_SKIP_SAME_BAR", True)
HARD_STOP_AFTER_TP2_USE_CLOSED_BAR_ONLY = _env_bool("HARD_STOP_AFTER_TP2_USE_CLOSED_BAR_ONLY", True)
# After TP2 partial: runner exits via staged SL + exchange stop; not software price hard-stop.
HARD_STOP_DISABLE_PRICE_ON_RUNNER = _env_bool("HARD_STOP_DISABLE_PRICE_ON_RUNNER", True)
# Live/demo: block new entries on a symbol after a regular SL exit to avoid immediate churn re-entry.
SL_REENTRY_COOLDOWN_SEC = _env_float("SL_REENTRY_COOLDOWN_SEC", 900.0)
ENTRY_SCAN_LOOP_SEC = _env_float("ENTRY_SCAN_LOOP_SEC", 30.0)
# Live/demo: min seconds between reconcile_all runs (exchange positionRisk sync).
RECONCILE_INTERVAL_SEC = max(3.0, _env_float("RECONCILE_INTERVAL_SEC", 15.0))
STRATEGY_SELECTOR_DEBUG = _env_bool("STRATEGY_SELECTOR_DEBUG", False)
STRATEGY_PLAN_DEBUG = _env_bool("STRATEGY_PLAN_DEBUG", False)
ENABLE_TREND_STRATEGY = _env_bool("ENABLE_TREND_STRATEGY", True)
TREND_SETUP_AUCTION_LOG = _env_bool("TREND_SETUP_AUCTION_LOG", False)
STRATEGY_PLAN_LOG_EMPTY_CANDIDATES = _env_bool("STRATEGY_PLAN_LOG_EMPTY_CANDIDATES", False)
# Live/demo/backtest: log `[SKIP] … | Plan rejected | …` lines (can be very noisy).
PLAN_REJECT_DEBUG = _env_bool("PLAN_REJECT_DEBUG", False)
# Demo mode: cap position notional to this USD amount when calculated size exceeds it.
MAX_DEMO_POSITION_CAP = _env_float("MAX_DEMO_POSITION_CAP", 1000.0)
# Evaluate early exit signals (breakout failure, structure break, strong rejection) before TP1 hit.
EARLY_EXIT_ENABLED = _env_bool("EARLY_EXIT_ENABLED", True)
# Log [SKIP] {symbol} | bars_since_last_close N < M when entry is blocked after a close.
ENTRY_AFTER_BARS_DEBUG = _env_bool("ENTRY_AFTER_BARS_DEBUG", False)
# Log ``Rejected Volatility | {symbol} | volatility=…`` when liquidity entry is blocked (noisy).
VOLATILITY_REJECT_DEBUG = _env_bool("VOLATILITY_REJECT_DEBUG", False)
# Backtest virtual wallet: log balance and planned size when ``build_order_plan`` uses ``virtual``.
VIRTUAL_BALANCE_DEBUG = _env_bool("VIRTUAL_BALANCE_DEBUG", False)
# Log full position sizing inputs/outputs (balance, risk%, sl_distance, notional, caps) per trade.
RISK_SIZING_DEBUG = _env_bool("RISK_SIZING_DEBUG", False)
POSITION_EVENT_DEBUG = (
    os.getenv("POSITION_EVENT_DEBUG", os.getenv("DEBUG", "false")).strip().lower() == "true"
)

BACKTEST_EXIT_SLIPPAGE_BPS = _env_float("BACKTEST_EXIT_SLIPPAGE_BPS", 0.0)
BACKTEST_CLOSE_DELAY_BARS = _env_int("BACKTEST_CLOSE_DELAY_BARS", 0)
BACKTEST_PARTIAL_FILL_RATIO = _env_float("BACKTEST_PARTIAL_FILL_RATIO", 1.0)
BACKTEST_PARTIAL_FILL_DELAY_BARS = _env_int("BACKTEST_PARTIAL_FILL_DELAY_BARS", 1)

# After MARKET entry: poll exchange position size before reduce-only SL. 0 = 15s; raise if demo lags.
POSITION_WAIT_AFTER_ENTRY_SEC = _env_float("POSITION_WAIT_AFTER_ENTRY_SEC", 0.0)
POSITION_STOP_PLACE_ATTEMPTS = _env_int("POSITION_STOP_PLACE_ATTEMPTS", 12)
POSITION_STOP_PLACE_RETRY_SLEEP_SEC = _env_float("POSITION_STOP_PLACE_RETRY_SLEEP_SEC", 0.5)
POSITION_DUST_CLOSE_ENABLED = os.getenv("POSITION_DUST_CLOSE_ENABLED", "true").strip().lower() == "true"
POSITION_DUST_CLOSE_NOTIONAL_USDT = _env_float("POSITION_DUST_CLOSE_NOTIONAL_USDT", 3.0)

EMA_FAST_1H = _env_int("EMA_FAST_1H", 50)
EMA_SLOW_1H = _env_int("EMA_SLOW_1H", 200)
EMA_DISTANCE_THRESHOLD = _env_float("EMA_DISTANCE_THRESHOLD", 0.002)
EMA_SLOPE_MIN = _env_float("EMA_SLOPE_MIN", 0.05)

ATR_MIN_RELATIVE = _env_float("ATR_MIN_RELATIVE", 0.0010)
ATR_MAX_RELATIVE = _env_float("ATR_MAX_RELATIVE", 0.0400)
ATR_REGIME_LOOKBACK = _env_int("ATR_REGIME_LOOKBACK", 96)
ATR_REGIME_LOW_Q = _env_float("ATR_REGIME_LOW_Q", 0.14)
ATR_REGIME_HIGH_Q = _env_float("ATR_REGIME_HIGH_Q", 0.85)
ATR_REGIME_EXTREME_Q = _env_float("ATR_REGIME_EXTREME_Q", 0.95)

SL_BUFFER_FRAC = _env_float("SL_BUFFER_FRAC", 0.0015)
MIN_SL_DISTANCE = _env_float("MIN_SL_DISTANCE", 0.005)

# --- Strategy selector (arbitration & adaptive scoring; liquidity strategy internals unchanged) ---
_ss_mode_raw = os.getenv("STRATEGY_SELECTOR_MODE", "winner_takes_all").strip().lower()
STRATEGY_SELECTOR_MODE = (
    _ss_mode_raw if _ss_mode_raw in ("winner_takes_all", "weighted_scores") else "winner_takes_all"
)
# Applied only when both liquidity and trend candidates exist (arbitration); not when one family is off.
SELECTOR_MIN_SCORE = _env_float("SELECTOR_MIN_SCORE", 0.12)
SELECTOR_SCORE_FLOOR = _env_float("SELECTOR_SCORE_FLOOR", 0.05)
SELECTOR_DYNAMIC_MIN_SCORE = _env_bool("SELECTOR_DYNAMIC_MIN_SCORE", True)
SELECTOR_DYNAMIC_MIN_SCORE_VOL_LOW = _env_float("SELECTOR_DYNAMIC_MIN_SCORE_VOL_LOW", 0.70)
SELECTOR_DYNAMIC_MIN_SCORE_ADD = _env_float("SELECTOR_DYNAMIC_MIN_SCORE_ADD", 0.02)
SELECTOR_DYNAMIC_MIN_SCORE_SUB = _env_float("SELECTOR_DYNAMIC_MIN_SCORE_SUB", 0.01)
SELECTOR_DYNAMIC_MIN_SCORE_MAX = _env_float("SELECTOR_DYNAMIC_MIN_SCORE_MAX", 0.20)
SELECTOR_MIN_WINNER_GAP = _env_float("SELECTOR_MIN_WINNER_GAP", 0.02)

_AI_ENABLED_RAW = os.getenv("AI_ENABLED")
if _AI_ENABLED_RAW is None:
    _AI_ENABLED_RAW = os.getenv("AI_EVAL_ENABLED", "false")
AI_ENABLED = _AI_ENABLED_RAW.strip().lower() == "true"
_AI_MODE_RAW = os.getenv("AI_MODE")
if _AI_MODE_RAW is None:
    _AI_MODE_RAW = os.getenv("AI_EVAL_MODE", "mock")
AI_MODE = _AI_MODE_RAW.strip().lower()
AI_MIN_CONFIDENCE = _env_float("AI_MIN_CONFIDENCE", 0.55)

# Runtime alerts (Telegram)
ALERTS_ENABLED = os.getenv("ALERTS_ENABLED", "false").strip().lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
_ALERTS_MODES_RAW = os.getenv("ALERTS_MODES", "demo,live")
ALERTS_MODES = tuple(
    m.strip().lower()
    for m in _ALERTS_MODES_RAW.split(",")
    if m.strip().lower() in ("backtest", "demo", "live")
)
# Daily performance JSON on Telegram (same gate as ALERTS_*): EOD + optional each close.
DAILY_PERFORMANCE_TELEGRAM = os.getenv("DAILY_PERFORMANCE_TELEGRAM", "true").strip().lower() == "true"
PERFORMANCE_SNAPSHOT_ON_CLOSE = _env_bool("PERFORMANCE_SNAPSHOT_ON_CLOSE", True)
MONTHLY_CUMULATIVE_TELEGRAM = _env_bool("MONTHLY_CUMULATIVE_TELEGRAM", True)

# Advanced exit manager: HOLD/CLOSE based on time + ROI progression + momentum.
EXIT_MIN_HOLD_SECONDS = _env_float("EXIT_MIN_HOLD_SECONDS", 2100.0)
EXIT_ADX_THRESHOLD = _env_float("EXIT_ADX_THRESHOLD", 22.0)
EXIT_MIN_VOLUME_RATIO = _env_float("EXIT_MIN_VOLUME_RATIO", 0.9)
# Maximum Favorable Excursion
EXIT_MFE_DRAWDOWN_THRESHOLD = _env_float("EXIT_MFE_DRAWDOWN_THRESHOLD", 0.2)
# MFE giveback / profit-lock exits only when peak leveraged ROI reached this level (%).
MIN_ROI_MFE_DRAWDOWN_APPLY = _env_float("MIN_ROI_MFE_DRAWDOWN_APPLY", 30.0)
# Minimum minutes in trade before pre-TP1 MFE exits.
EXIT_MIN_HOLD_PRE_TP1_MINUTES = _env_float("EXIT_MIN_HOLD_PRE_TP1_MINUTES", 60.0)
# When true, CLOSE as soon as normalized giveback >= threshold (no 15m/momentum hold for recovery).
EXIT_MFE_IMMEDIATE_ON_THRESHOLD = _env_bool("EXIT_MFE_IMMEDIATE_ON_THRESHOLD", False)
# When true, MFE giveback exits need a 15m structure break (prior bar range violation). When false, giveback can exit without it.
EXIT_MFE_REQUIRE_STRUCTURE_BREAK = _env_bool("EXIT_MFE_REQUIRE_STRUCTURE_BREAK", True)
EXIT_MFE_DRAWDOWN_THRESHOLD_STRONG_TREND = _env_float(
    "EXIT_MFE_DRAWDOWN_THRESHOLD_STRONG_TREND",
    min(0.95, EXIT_MFE_DRAWDOWN_THRESHOLD + 0.05),
)
# Tighten MFE exit after long hold (primarily for non-strong-trend remainder legs).
EXIT_LONG_HOLD_MFE_TIGHTEN_AFTER_SECONDS = _env_float("EXIT_LONG_HOLD_MFE_TIGHTEN_AFTER_SECONDS", 9000.0)
EXIT_LONG_HOLD_MFE_TIGHTEN_SUB = _env_float("EXIT_LONG_HOLD_MFE_TIGHTEN_SUB", 0.03)
# Non-strong-trend MFE time-decay tightening schedule.
EXIT_MFE_TIGHTEN_STEP1_AFTER_SECONDS = _env_float("EXIT_MFE_TIGHTEN_STEP1_AFTER_SECONDS", 7200.0)
EXIT_MFE_TIGHTEN_STEP1_SUB = _env_float("EXIT_MFE_TIGHTEN_STEP1_SUB", 0.02)
EXIT_MFE_TIGHTEN_STEP2_AFTER_SECONDS = _env_float("EXIT_MFE_TIGHTEN_STEP2_AFTER_SECONDS", 10800.0)
EXIT_MFE_TIGHTEN_STEP2_SUB = _env_float("EXIT_MFE_TIGHTEN_STEP2_SUB", 0.05)
# Long-hold profit-lock: once peak ROI is high enough, avoid giving back below a floor.
EXIT_MFE_PROFIT_LOCK_AFTER_SECONDS = _env_float("EXIT_MFE_PROFIT_LOCK_AFTER_SECONDS", 9000.0)
EXIT_MFE_PROFIT_LOCK_MIN_PEAK_ROI = _env_float("EXIT_MFE_PROFIT_LOCK_MIN_PEAK_ROI", 2.5)
EXIT_MFE_PROFIT_LOCK_MIN_ROI = _env_float("EXIT_MFE_PROFIT_LOCK_MIN_ROI", 0.6)
EXIT_MIN_HOLD_AFTER_TP1_SECONDS = _env_float("EXIT_MIN_HOLD_AFTER_TP1_SECONDS", 5400.0)
EXIT_EMA_FAST = _env_int("EXIT_EMA_FAST", 9)
EXIT_EMA_SLOW = _env_int("EXIT_EMA_SLOW", 21)
EXIT_MIN_CONSECUTIVE_OPPOSITE_CANDLES = _env_int("EXIT_MIN_CONSECUTIVE_OPPOSITE_CANDLES", 2)
EXIT_MIN_MOMENTUM_WEAK_SIGNALS = _env_int("EXIT_MIN_MOMENTUM_WEAK_SIGNALS", 2)
APPLY_EXIT_TUNING = _env_bool("APPLY_EXIT_TUNING", True)  # live/demo; backtest when apply_exit_tuning is None
EXIT_PARITY_LOG = _env_bool("EXIT_PARITY_LOG", False)
EXIT_PARITY_VALIDATE = _env_bool("EXIT_PARITY_VALIDATE", False)
# Backtest log noise: [EXIT CHECK] / [EXIT DECISION] lines only when EXIT_DEBUG=true.
EXIT_DEBUG = _env_bool("EXIT_DEBUG", False)

# Volatility: hard skip only below ATR_MIN_RELATIVE * this factor (mild low vol still trades).
VOLATILITY_HARD_REJECT_MULT = _env_float("VOLATILITY_HARD_REJECT_MULT", 0.88)

_explicit_sym = os.getenv("SYMBOL", "").strip().upper()
SYMBOL = _explicit_sym if _explicit_sym in SYMBOLS else SYMBOLS[0]
