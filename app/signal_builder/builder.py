from __future__ import annotations

from app.signal_builder.models import TradeSignal
from strategy.trend_following.config import MAX_SL_DISTANCE, TREND_BREAKOUT_STOP_ATR_MULT
from strategy.trend_following.breakout.config import BREAKOUT_LONG
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

        buf = atr_v * stop_atr_mult
        direction = setup.side.value

        if direction == "LONG":
            sl = setup.anchor - buf
            dist = (entry - sl) / entry
        else:
            sl = setup.anchor + buf
            dist = (sl - entry) / entry

        if setup_type == BREAKOUT and dist < BREAKOUT_LONG["min_sl_distance"]:
            if direction == "LONG":
                sl = entry * (1.0 - BREAKOUT_LONG["min_sl_distance"])
            else:
                sl = entry * (1.0 + BREAKOUT_LONG["min_sl_distance"])

            dist = BREAKOUT_LONG["min_sl_distance"]

        if dist <= 0 or dist > MAX_SL_DISTANCE:
            return None

        return sl, dist

    @classmethod
    def build(
        cls,
        setup: Setup,
        entry: float,
    ) -> TradeSignal | None:

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

        return TradeSignal(
            direction=direction,
            entry=entry,
            stop_loss=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=0.0,
            setup_score=int(round(setup.score)),
            setup_type=setup_type,
            strategy_family=TREND_FOLLOWING,
            confirmation_mode="confirmed",
            tp1_r=tp1_r,
            tp2_r=tp2_r,
        )