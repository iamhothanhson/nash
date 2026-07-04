from __future__ import annotations

from config import settings
from monitoring.logger import log as file_log
from monitoring.notifier import send_plan_rejected_alert
from strategy.liquidity_sweep_reversal.base_sweep_revesal import LiquiditySweepReversalBase
from strategy.trend_following.strategy import TrendFollowingStrategyBase
from strategy.trend_following.trend_following_config import TREND_REGIME_FILTER
from strategy_selector.context import set_last_selection
from strategy_selector.logging_utils import format_selection_human
from strategy_selector.models import SelectorMode
from strategy_selector.selector import StrategySelector

from config.constants import BREAKOUT, BREAKOUT_RETEST, PULLBACK

reversal_strategy = LiquiditySweepReversalBase()
trend_strategy = TrendFollowingStrategyBase()
_strategy_selector = StrategySelector()


def _selector_debug_enabled() -> bool:
    return bool(getattr(settings, "STRATEGY_SELECTOR_DEBUG", False))


def _selector_mode() -> SelectorMode:
    m = str(getattr(settings, "STRATEGY_SELECTOR_MODE", "winner_takes_all")).strip().lower()
    return m if m in ("winner_takes_all", "weighted_scores") else "winner_takes_all"

def _plan_debug_enabled() -> bool:
    return bool(getattr(settings, "STRATEGY_PLAN_DEBUG", False))


def _trend_setup_display_name(setup_type: str) -> str:
    """Display name for trend setup in PLAN REJECTED alerts (strategy line carries family)."""
    s = str(setup_type).strip().upper()
    if s == BREAKOUT:
        return "Breakout"
    if s == BREAKOUT_RETEST:
        return "Breakout Retest"
    if s == PULLBACK:
        return "Pullback"
    return str(setup_type).title() if setup_type else "Trend Following"


def _liquidity_sweep_display_name(setup_type: str) -> str:
    s = str(setup_type).strip().lower()
    if s == "liquidity_sweep_reversal":
        return "Liquidity Sweep Reversal"
    return f"Liquidity Sweep ({setup_type})" if setup_type else "Liquidity Sweep Reversal"


def _notify_plan_rejected(
    symbol: str,
    *,
    detail_reason: str,
    strategy_label: str,
    setup_label: str | None = None,
) -> None:
    """Telegram when a strategy built a signal but selector did not execute it (not gated on STRATEGY_PLAN_DEBUG)."""
    send_plan_rejected_alert(
        symbol,
        strategy_label=strategy_label,
        detail_reason=detail_reason,
        setup_label=setup_label,
    )


def get_signal(
    data_1h,
    data_15m,
    data_5m,
    symbol: str,
    *,
    bars_since_last_close=None,
):

    enable_trend = bool(settings.ENABLE_TREND_STRATEGY)

    rev = reversal_strategy.build_signal(
        data_1h,
        data_15m,
        data_5m,
        symbol=symbol,
        bars_since_last_close=bars_since_last_close,
    )

    # --- Liquidity-only parity path (no trend regime, scoring, or min_score on reversal) ---
    if not enable_trend:
        set_last_selection(None)
        if rev:
            return rev
        return None

    trend = trend_strategy.build_signal(
        data_15m,
        data_5m,
        symbol=symbol,
        data_1h=data_1h,
    )

    result = _strategy_selector.select(
        symbol=str(symbol),
        data_1h=data_1h,
        data_15m=data_15m,
        data_5m=data_5m,
        reversal_signal=rev,
        trend_signal=trend,
        enable_trend=True,
        trend_regime_filter=bool(TREND_REGIME_FILTER),
        mode=_selector_mode(),
        min_score=float(getattr(settings, "SELECTOR_MIN_SCORE", 0.08)),
    )

    if _selector_debug_enabled():
        file_log(format_selection_human(result), strip_setup=True)

    trend_selected_but_not_executed = trend is not None and (
        result.execution_signal is None
        or str(getattr(result.execution_signal, "strategy_family", "")).strip().lower()
        != "trend_following"
    )
    if trend_selected_but_not_executed:
        reason = result.reject_reason or "lost_competition"
        trend_block_reasons: list[str] = []
        for row in result.debug.get("candidates", []):
            if not isinstance(row, dict):
                continue
            if str(row.get("family", "")).strip().lower() != "trend_following":
                continue
            status = str(row.get("status", "")).strip()
            if status.startswith("blocked_by_"):
                regime_reason = str(row.get("regime_reason", "")).strip()
                if status == "blocked_by_regime_direction_mismatch":
                    td = str(row.get("trend_direction", "")).strip()
                    rd = str(row.get("regime_direction", "")).strip()
                    trend_block_reasons.append(
                        f"{status}|setup={td}|regime_bias={rd}|regime_tag={regime_reason}"
                    )
                elif status == "blocked_by_trend_strength":
                    tr = row.get("trend_strength")
                    mr = row.get("min_required")
                    trend_block_reasons.append(
                        f"{status}|score={tr}|min={mr}|regime_tag={regime_reason}"
                    )
                elif regime_reason:
                    trend_block_reasons.append(f"{status}:{regime_reason}")
                else:
                    trend_block_reasons.append(status)
        filtered_reason = ",".join(trend_block_reasons) if trend_block_reasons else "none"
        detail_reason = filtered_reason if filtered_reason != "none" else reason
        if _plan_debug_enabled():
            file_log(
                f'[PLAN REJECTED] {symbol} | "trend_selected_but_not_executed | reason: {detail_reason}"',
                mode=settings.MODE,
                strip_setup=True,
            )
        _notify_plan_rejected(
            symbol=symbol,
            detail_reason=detail_reason,
            strategy_label="Trend Following",
            setup_label=_trend_setup_display_name(str(getattr(trend, "setup_type", "unknown"))),
        )

    reversal_selected_but_not_executed = rev is not None and (
        result.execution_signal is None
        or str(getattr(result.execution_signal, "strategy_family", "")).strip().lower()
        != "liquidity"
    )
    if reversal_selected_but_not_executed:
        detail_reason_rev = result.reject_reason or "lost_competition"
        if _plan_debug_enabled():
            file_log(
                f'[PLAN REJECTED] {symbol} | "reversal_selected_but_not_executed | reason: {detail_reason_rev}"',
                mode=settings.MODE,
                strip_setup=True,
            )
        _notify_plan_rejected(
            symbol=symbol,
            detail_reason=detail_reason_rev,
            strategy_label=_liquidity_sweep_display_name(str(getattr(rev, "setup_type", "unknown"))),
        )

    return result.execution_signal
