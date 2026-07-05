from __future__ import annotations

from strategy.trend_following.config import (
    BREAKOUT_MIN_SL_DISTANCE,
    MAX_SL_DISTANCE,
    TREND_BREAKOUT_STOP_ATR_MULT,
)
from strategy.liquidity_sweep_reversal.sweep_revesal_config import (
    ATR_PERIOD,
    ATR_MULTIPLIER,
)
from indicators import calculate_atr
from config import settings
from app.signal_builder.config import TP_CONFIG
from app.signal_builder.take_profit import resolve_tp1_tp2_prices
from setup_builder.builder import Setup
from config.constants import BREAKOUT, TREND_FOLLOWING


class SignalBuilder:
    @staticmethod
    def _compute_stop_loss(
        setup: Setup,
        entry: float,
        ohlcv,
        cfg,
        setup_type: str,
    ) -> tuple[float, float] | None:
        """Compute stop loss and distance for the trade signal."""
        atr_v = float(calculate_atr(ohlcv, ATR_PERIOD).iloc[-1])

        if setup_type == BREAKOUT:
            stop_atr_mult = float(TREND_BREAKOUT_STOP_ATR_MULT)

            if stop_atr_mult <= 0:
                stop_atr_mult = float(ATR_MULTIPLIER)
            else:
                stop_atr_mult = scale_atr_stop_mult(stop_atr_mult, cfg)
        else:
            stop_atr_mult = float(ATR_MULTIPLIER)
            stop_atr_mult = scale_atr_stop_mult(stop_atr_mult, cfg)

        buf = atr_v * stop_atr_mult
        direction = setup.side.value

        if direction == "LONG":
            sl = setup.anchor - buf
            dist = (entry - sl) / entry
        else:
            sl = setup.anchor + buf
            dist = (sl - entry) / entry

        if setup_type == BREAKOUT and dist < BREAKOUT_MIN_SL_DISTANCE:
            if direction == "LONG":
                sl = entry * (1.0 - BREAKOUT_MIN_SL_DISTANCE)
            else:
                sl = entry * (1.0 + BREAKOUT_MIN_SL_DISTANCE)

            dist = BREAKOUT_MIN_SL_DISTANCE

        if dist <= 0 or dist > MAX_SL_DISTANCE:
            return None

        return sl, dist

    @classmethod
    def build(
        cls,
        setup: Setup,
        entry: float,
    ) -> TradeSignal | None:
        """Build a trade signal for trend following strategies."""

        cfg = get_coin_config(setup.symbol)
        ohlcv = getattr(setup.market_state, "data_15m", None)
        setup_type = setup.setup_type.value

        sl_data = cls._compute_stop_loss(
            setup=setup,
            entry=entry,
            ohlcv=ohlcv,
            cfg=cfg,
            setup_type=setup_type,
        )

        if sl_data is None:
            return None

        sl, dist = sl_data
        direction = setup.side.value

        tp1_r = float(TP_CONFIG.get("tp1_r", 1.0))
        tp2_r = float(TP_CONFIG.get("tp2_r", 1.5))

        tp1, tp2 = resolve_tp1_tp2_prices(
            entry=entry,
            direction=direction,
            dist=dist,
            data_15m=ohlcv,
            cfg=cfg,
            tp1_r=tp1_r,
            tp2_r=tp2_r,
            anchor=float(setup.anchor),
        )

        risk_mult = float(GRADE_RISK_MULTIPLIERS.get(setup.grade, 1.0))

        risk_per_trade = float(settings.RISK_PER_TRADE) * risk_mult
        r_multiple = abs(entry - sl) / max(entry, 1e-12)

        return TradeSignal(
            direction=direction,
            entry=entry,
            stop_loss=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=0.0,
            setup_score=int(round(setup.score)),
            signal_risk_per_trade=risk_per_trade,
            setup_type=setup_type,
            setup_grade=setup.grade,
            strategy_family=TREND_FOLLOWING,
            r_multiple=r_multiple,
            confirmation_mode="confirmed",
            confidence=float(sig_conf),
            tp1_r=tp1_r,
            tp2_r=tp2_r,
        )