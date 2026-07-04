from __future__ import annotations

from dataclasses import dataclass

from common.rounding import round_ratio
from config import settings
from monitoring.logger import log

MFE_DRAWDOWN_EXIT_REASON = "mfe_drawdown_exceeded"


def is_immediate_forced_exit_reason(reason: str) -> bool:
    """Time exits that skip backtest close delay and use full fill on the decision bar."""
    r = str(reason).strip()
    if r == MFE_DRAWDOWN_EXIT_REASON:
        return bool(getattr(settings, "EXIT_MFE_IMMEDIATE_ON_THRESHOLD", True))
    if r == "early_exit":
        return True
    return False


@dataclass(frozen=True)
class ExitManagerConfig:
    min_hold_seconds: float
    adx_threshold: float
    min_volume_ratio: float
    mfe_drawdown_threshold: float
    mfe_drawdown_threshold_strong_trend: float
    min_roi_mfe_drawdown_apply: float
    long_hold_mfe_tighten_after_seconds: float
    long_hold_mfe_tighten_sub: float
    mfe_tighten_step1_after_seconds: float
    mfe_tighten_step1_sub: float
    mfe_tighten_step2_after_seconds: float
    mfe_tighten_step2_sub: float
    mfe_profit_lock_after_seconds: float
    mfe_profit_lock_min_peak_roi: float
    mfe_profit_lock_min_roi: float

    mfe_require_structure_break: bool
    mfe_immediate_on_threshold: bool
    min_hold_pre_tp1_seconds: float
    min_hold_after_tp1_seconds: float
    ema_fast: int
    ema_slow: int
    min_consecutive_opposite_candles: int
    min_momentum_weak_signals: int
    early_exit_enabled: bool = True


def _roi_velocity(roi_history: list[dict[str, float]]) -> float | None:
    if len(roi_history) < 2:
        return None
    p0 = roi_history[-2]
    p1 = roi_history[-1]
    dt = float(p1.get("t", 0.0)) - float(p0.get("t", 0.0))
    if dt <= 0:
        return None
    return (float(p1.get("roi", 0.0)) - float(p0.get("roi", 0.0))) / dt


def _ema_last(values: list[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    alpha = 2.0 / (float(period) + 1.0)
    ema = float(values[0])
    for v in values[1:]:
        ema = alpha * float(v) + (1.0 - alpha) * ema
    return ema


def _mfe_giveback_should_close(
    *,
    exit_manager: ExitManagerConfig,
    strong_trend: bool,
    structure_break: bool | None,
    momentum_weak_confirmed: bool,
) -> bool:
    """Whether MFE / profit-lock paths may CLOSE (vs mfe_pullback_hold)."""
    if not bool(exit_manager.mfe_require_structure_break):
        if structure_break is None:
            return bool(momentum_weak_confirmed)
        if strong_trend:
            return bool(momentum_weak_confirmed)
        return True
    if structure_break is None:
        return bool(momentum_weak_confirmed)
    if strong_trend:
        return bool(structure_break and momentum_weak_confirmed)
    return bool(structure_break)


def _structure_break_15m(
    *,
    direction: str,
    last_15m_high: float | None,
    last_15m_low: float | None,
    current_15m_close: float | None,
) -> bool | None:
    """
    Confirmed 15m structure break vs prior bar (iloc[-2] range, iloc[-1] close).
    LONG: current close below prior bar low. SHORT: current close above prior bar high.
    Returns None if inputs are incomplete (caller should fall back to legacy exit rules).
    """
    if last_15m_high is None or last_15m_low is None or current_15m_close is None:
        return None
    c = float(current_15m_close)
    if str(direction).upper() == "LONG":
        return bool(c < float(last_15m_low))
    return bool(c > float(last_15m_high))


def _consecutive_opposite_candles(
    *,
    opens: list[float],
    closes: list[float],
    direction: str,
) -> int:
    n = min(len(opens), len(closes))
    if n <= 0:
        return 0
    is_long = str(direction).upper() == "LONG"
    count = 0
    for i in range(n - 1, -1, -1):
        o = float(opens[i])
        c = float(closes[i])
        opposite = (c < o) if is_long else (c > o)
        if not opposite:
            break
        count += 1
    return count


def _metrics_payload(
    *,
    expected_roi: float,
    weak_performance: bool,
    stagnant: bool,
    strong_trend: bool,
    roi_velocity: float | None,
    mfe_drawdown_normalized: float,
    momentum_weak_ema: bool,
    momentum_weak_candles: bool,
    momentum_weak_volume: bool,
    momentum_weak_confirmed: bool,
    tp1_grace_active: bool,
    structure_break: bool | None = None,
    early_exit_signals: list[str] | None = None,
) -> dict:
    out: dict = {
        "expected_roi": round_ratio(float(expected_roi), 2),
        "weak_performance": bool(weak_performance),
        "stagnant": bool(stagnant),
        "strong_trend": bool(strong_trend),
        "roi_velocity": (round_ratio(float(roi_velocity), 3) if roi_velocity is not None else None),
        "mfe_drawdown_normalized": round_ratio(float(mfe_drawdown_normalized), 4),
        "momentum_weak_ema": bool(momentum_weak_ema),
        "momentum_weak_candles": bool(momentum_weak_candles),
        "momentum_weak_volume": bool(momentum_weak_volume),
        "momentum_weak_confirmed": bool(momentum_weak_confirmed),
        "tp1_grace_active": bool(tp1_grace_active),
    }
    if structure_break is not None:
        out["structure_break"] = bool(structure_break)
    if early_exit_signals is not None:
        out["early_exit_signals"] = list(early_exit_signals)
    return out


def decide_exit(
    *,
    time_in_trade: float,
    current_roi: float,
    roi_history: list[dict[str, float]],
    max_roi_seen: float,
    volume_ratio: float,
    adx: float,
    exit_manager: ExitManagerConfig,
    direction: str = "LONG",
    candle_opens: list[float] | None = None,
    candle_closes: list[float] | None = None,
    candle_highs: list[float] | None = None,
    candle_lows: list[float] | None = None,
    candle_volumes: list[float] | None = None,
    time_since_tp1: float | None = None,
    last_15m_high: float | None = None,
    last_15m_low: float | None = None,
    current_15m_close: float | None = None,
    symbol: str = "",
    entry_price: float | None = None,
    breakout_level: float | None = None,
) -> dict:
    opens = [float(x) for x in (candle_opens or [])]
    closes = [float(x) for x in (candle_closes or [])]
    volumes = [float(x) for x in (candle_volumes or [])]
    is_long = str(direction).upper() == "LONG"

    ema_fast = _ema_last(closes, int(exit_manager.ema_fast))
    ema_slow = _ema_last(closes, int(exit_manager.ema_slow))
    momentum_weak_ema = bool(
        ema_fast is not None
        and ema_slow is not None
        and ((ema_fast < ema_slow) if is_long else (ema_fast > ema_slow))
    )
    opposite_count = _consecutive_opposite_candles(
        opens=opens,
        closes=closes,
        direction=direction,
    )
    momentum_weak_candles = opposite_count >= int(exit_manager.min_consecutive_opposite_candles)
    momentum_weak_volume = False
    if len(closes) >= 2 and len(volumes) >= 2:
        price_down = (closes[-1] < closes[-2]) if is_long else (closes[-1] > closes[-2])
        volume_up = volumes[-1] > volumes[-2]
        momentum_weak_volume = bool(price_down and volume_up)
    weak_votes = int(momentum_weak_ema) + int(momentum_weak_candles) + int(momentum_weak_volume)
    momentum_weak_confirmed = weak_votes >= max(1, int(exit_manager.min_momentum_weak_signals))

    tp1_grace_active = bool(
        time_since_tp1 is not None
        and float(time_since_tp1) >= 0.0
        and float(time_since_tp1) < float(exit_manager.min_hold_after_tp1_seconds)
    )
    pre_tp1 = time_since_tp1 is None
    pre_tp1_min_hold_active = pre_tp1 and float(time_in_trade) < float(
        exit_manager.min_hold_pre_tp1_seconds
    )
    mfe_exit_allowed = time_since_tp1 is not None

    min_hold_active = float(time_in_trade) < float(exit_manager.min_hold_seconds)
    if min_hold_active or pre_tp1_min_hold_active:
        return {
            "action": "HOLD",
            "reason": "min_hold_gate",
            "metrics": _metrics_payload(
                expected_roi=0.0,
                weak_performance=False,
                stagnant=False,
                strong_trend=bool(
                    float(adx) >= float(exit_manager.adx_threshold)
                    and float(volume_ratio) >= float(exit_manager.min_volume_ratio)
                ),
                roi_velocity=_roi_velocity(roi_history),
                mfe_drawdown_normalized=0.0,
                momentum_weak_ema=momentum_weak_ema,
                momentum_weak_candles=momentum_weak_candles,
                momentum_weak_volume=momentum_weak_volume,
                momentum_weak_confirmed=momentum_weak_confirmed,
                tp1_grace_active=tp1_grace_active,
                structure_break=None,
            ),
        }

    _early_exit_enabled = bool(getattr(exit_manager, "early_exit_enabled", True))
    if _early_exit_enabled and pre_tp1 and not pre_tp1_min_hold_active:
        from position_management.early_exit import evaluate_early_exit

        _ee = evaluate_early_exit(
            direction=direction,
            entry_price=entry_price,
            current_price=closes[-1] if closes else 0.0,
            current_roi=float(current_roi),
            breakout_level=breakout_level,
            last_15m_high=last_15m_high,
            last_15m_low=last_15m_low,
            current_15m_close=current_15m_close,
            candle_opens=opens,
            candle_closes=closes,
            candle_highs=[float(x) for x in (candle_highs or [])],
            candle_lows=[float(x) for x in (candle_lows or [])],
            candle_volumes=volumes,
            time_since_tp1=time_since_tp1,
            symbol=str(symbol),
        )
        if _ee.should_exit:
            return {
                "action": "CLOSE",
                "reason": "early_exit",
                "metrics": _metrics_payload(
                    expected_roi=0.0,
                    weak_performance=False,
                    stagnant=False,
                    strong_trend=bool(
                        float(adx) >= float(exit_manager.adx_threshold)
                        and float(volume_ratio) >= float(exit_manager.min_volume_ratio)
                    ),
                    roi_velocity=_roi_velocity(roi_history),
                    mfe_drawdown_normalized=0.0,
                    momentum_weak_ema=momentum_weak_ema,
                    momentum_weak_candles=momentum_weak_candles,
                    momentum_weak_volume=momentum_weak_volume,
                    momentum_weak_confirmed=momentum_weak_confirmed,
                    tp1_grace_active=tp1_grace_active,
                    structure_break=None,
                    early_exit_signals=_ee.signals,
                ),
            }
    strong_trend = bool(
        float(adx) >= float(exit_manager.adx_threshold)
        and float(volume_ratio) >= float(exit_manager.min_volume_ratio)
    )
    roi_velocity = _roi_velocity(roi_history)
    active_mfe_drawdown_threshold = (
        float(exit_manager.mfe_drawdown_threshold_strong_trend)
        if strong_trend
        else float(exit_manager.mfe_drawdown_threshold)
    )
    # Mildly tighten MFE giveback after long hold in non-strong trend.
    if (
        not strong_trend
        and float(time_in_trade) >= float(exit_manager.long_hold_mfe_tighten_after_seconds)
    ):
        active_mfe_drawdown_threshold = max(
            0.05,
            float(active_mfe_drawdown_threshold) - float(exit_manager.long_hold_mfe_tighten_sub),
        )
    if not strong_trend:
        if float(time_in_trade) >= float(exit_manager.mfe_tighten_step2_after_seconds):
            active_mfe_drawdown_threshold = max(
                0.05,
                float(active_mfe_drawdown_threshold) - float(exit_manager.mfe_tighten_step2_sub),
            )
        elif float(time_in_trade) >= float(exit_manager.mfe_tighten_step1_after_seconds):
            active_mfe_drawdown_threshold = max(
                0.05,
                float(active_mfe_drawdown_threshold) - float(exit_manager.mfe_tighten_step1_sub),
            )
    mfe_gain = max(0.0, float(max_roi_seen))
    mfe_drawdown_points = max(0.0, float(max_roi_seen) - float(current_roi))
    mfe_drawdown_normalized = (
        float(mfe_drawdown_points) / float(mfe_gain) if mfe_gain > 1e-12 else 0.0
    )
    if tp1_grace_active:
        return {
            "action": "HOLD",
            "reason": "tp1_grace_period",
            "metrics": _metrics_payload(
                expected_roi=0.0,
                weak_performance=False,
                stagnant=False,
                strong_trend=bool(strong_trend),
                roi_velocity=roi_velocity,
                mfe_drawdown_normalized=mfe_drawdown_normalized,
                momentum_weak_ema=momentum_weak_ema,
                momentum_weak_candles=momentum_weak_candles,
                momentum_weak_volume=momentum_weak_volume,
                momentum_weak_confirmed=momentum_weak_confirmed,
                tp1_grace_active=tp1_grace_active,
                structure_break=None,
            ),
        }
    structure_break = _structure_break_15m(
        direction=direction,
        last_15m_high=last_15m_high,
        last_15m_low=last_15m_low,
        current_15m_close=current_15m_close,
    )
    mfe_peak_eligible = float(max_roi_seen) >= float(exit_manager.min_roi_mfe_drawdown_apply)
    profit_lock_armed = bool(
        mfe_peak_eligible
        and not strong_trend
        and float(time_in_trade) >= float(exit_manager.mfe_profit_lock_after_seconds)
        and float(max_roi_seen) >= float(exit_manager.mfe_profit_lock_min_peak_roi)
        and float(current_roi) <= float(exit_manager.mfe_profit_lock_min_roi)
    )
    if mfe_exit_allowed and profit_lock_armed:
        sym_u = str(symbol).strip().upper() or "—"
        if bool(exit_manager.mfe_immediate_on_threshold):
            should_close = True
        elif bool(exit_manager.mfe_require_structure_break):
            should_close = (
                bool(momentum_weak_confirmed)
                if structure_break is None
                else bool(structure_break or momentum_weak_confirmed)
            )
        else:
            should_close = (
                bool(momentum_weak_confirmed)
                if structure_break is None
                else True
            )
        if should_close:
            if settings.should_log_exit_debug_trace():
                log(
                    f"[EXIT CHECK] {sym_u} | profit_lock=armed | roi={round_ratio(float(current_roi), 3)} | "
                    f"peak={round_ratio(float(max_roi_seen), 3)} | action=EXIT"
                )
            return {
                "action": "CLOSE",
                "reason": MFE_DRAWDOWN_EXIT_REASON,
                "metrics": _metrics_payload(
                    expected_roi=0.0,
                    weak_performance=False,
                    stagnant=False,
                    strong_trend=bool(strong_trend),
                    roi_velocity=roi_velocity,
                    mfe_drawdown_normalized=mfe_drawdown_normalized,
                    momentum_weak_ema=momentum_weak_ema,
                    momentum_weak_candles=momentum_weak_candles,
                    momentum_weak_volume=momentum_weak_volume,
                    momentum_weak_confirmed=momentum_weak_confirmed,
                    tp1_grace_active=tp1_grace_active,
                    structure_break=structure_break,
                ),
            }
    mfe_threshold_met = bool(
        mfe_peak_eligible
        and mfe_drawdown_normalized >= active_mfe_drawdown_threshold
    )
    if mfe_exit_allowed and mfe_threshold_met:
        sym_u = str(symbol).strip().upper() or "—"
        if bool(exit_manager.mfe_immediate_on_threshold):
            should_close = True
        else:
            should_close = _mfe_giveback_should_close(
                exit_manager=exit_manager,
                strong_trend=bool(strong_trend),
                structure_break=structure_break,
                momentum_weak_confirmed=bool(momentum_weak_confirmed),
            )
        if should_close:
            sb_log = "n/a" if structure_break is None else str(bool(structure_break))
            if settings.should_log_exit_debug_trace():
                log(
                    f"[EXIT CHECK] {sym_u} | mfe_drawdown={round_ratio(float(mfe_drawdown_normalized), 4)} | "
                    f"structure_break={sb_log} | require_15m={bool(exit_manager.mfe_require_structure_break)} | "
                    f"action=EXIT"
                )
            return {
                "action": "CLOSE",
                "reason": MFE_DRAWDOWN_EXIT_REASON,
                "metrics": _metrics_payload(
                    expected_roi=0.0,
                    weak_performance=False,
                    stagnant=False,
                    strong_trend=bool(strong_trend),
                    roi_velocity=roi_velocity,
                    mfe_drawdown_normalized=mfe_drawdown_normalized,
                    momentum_weak_ema=momentum_weak_ema,
                    momentum_weak_candles=momentum_weak_candles,
                    momentum_weak_volume=momentum_weak_volume,
                    momentum_weak_confirmed=momentum_weak_confirmed,
                    tp1_grace_active=tp1_grace_active,
                    structure_break=structure_break,
                ),
            }
        if (
            not bool(exit_manager.mfe_immediate_on_threshold)
            and structure_break is not None
        ):
            return {
                "action": "HOLD",
                "reason": "mfe_pullback_hold",
                "metrics": _metrics_payload(
                    expected_roi=0.0,
                    weak_performance=False,
                    stagnant=False,
                    strong_trend=bool(strong_trend),
                    roi_velocity=roi_velocity,
                    mfe_drawdown_normalized=mfe_drawdown_normalized,
                    momentum_weak_ema=momentum_weak_ema,
                    momentum_weak_candles=momentum_weak_candles,
                    momentum_weak_volume=momentum_weak_volume,
                    momentum_weak_confirmed=momentum_weak_confirmed,
                    tp1_grace_active=tp1_grace_active,
                    structure_break=structure_break,
                ),
            }

    return {
        "action": "HOLD",
        "reason": "conditions_not_met",
        "metrics": _metrics_payload(
            expected_roi=0.0,
            weak_performance=False,
            stagnant=False,
            strong_trend=bool(strong_trend),
            roi_velocity=roi_velocity,
            mfe_drawdown_normalized=mfe_drawdown_normalized,
            momentum_weak_ema=momentum_weak_ema,
            momentum_weak_candles=momentum_weak_candles,
            momentum_weak_volume=momentum_weak_volume,
            momentum_weak_confirmed=momentum_weak_confirmed,
            tp1_grace_active=tp1_grace_active,
            structure_break=structure_break,
        ),
    }
