"""Per-symbol last close 5m bar timestamp (live/demo entry anti-churn)."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from coins.loader import normalize_coin_symbol

_last_close_5m_bar_ts: dict[str, float] = {}


def floor_ts_to_5m_bar(ts: float) -> float:
    return math.floor(float(ts) / 300.0) * 300.0


def closed_5m_bar_ts_from_iso(time_iso: str) -> float | None:
    try:
        dt = datetime.fromisoformat(str(time_iso).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return floor_ts_to_5m_bar(dt.astimezone(timezone.utc).timestamp())


def record_symbol_close_bar(symbol: str, bar_ts: float) -> None:
    sym = normalize_coin_symbol(str(symbol))
    ts = float(bar_ts)
    if ts <= 0.0:
        return
    prev = float(_last_close_5m_bar_ts.get(sym, 0.0) or 0.0)
    _last_close_5m_bar_ts[sym] = max(prev, ts)


def get_last_close_bar_ts(symbol: str) -> float | None:
    sym = normalize_coin_symbol(str(symbol))
    ts = float(_last_close_5m_bar_ts.get(sym, 0.0) or 0.0)
    return ts if ts > 0.0 else None


def count_bars_since_close_5m(*, latest_closed_bar_ts: float | None, last_close_bar_ts: float | None) -> int | None:
    """Closed 5m bars elapsed since ``last_close_bar_ts`` (same units as kline bar timestamps)."""
    if last_close_bar_ts is None:
        return None
    if latest_closed_bar_ts is None:
        return None
    delta = float(latest_closed_bar_ts) - float(last_close_bar_ts)
    if delta < 0.0:
        return 0
    return max(0, int(round(delta / 300.0)))


def log_entry_after_bars_skip(
    symbol: str,
    bars_since: int,
    min_bars: int,
    *,
    strip_setup: bool = False,
) -> None:
    """Emit bars-since-close skip line when ENTRY_AFTER_BARS_DEBUG is enabled."""
    from config import settings
    from monitoring.logger import log

    if not settings.ENTRY_AFTER_BARS_DEBUG:
        return
    log(
        f"[SKIP] {symbol} | bars_since_last_close {int(bars_since)} < {int(min_bars)}",
        strip_setup=strip_setup,
    )


def reset_symbol_close_tracking() -> None:
    """Test helper."""
    _last_close_5m_bar_ts.clear()
