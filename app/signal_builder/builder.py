from __future__ import annotations

from app.signal_builder.models import TradeSignal
from core.utils import get_coin_config, resolve_strategy_family
from config.constants import BREAKOUT
from app.signal_builder.config import TP_CONFIG
from app.signal_builder.take_profit import resolve_tp1_tp2_prices, resolve_tp3_price
from setup_builder.builder import Setup
MIN_SL_DISTANCE = 0.003
from strategy.trend_following.config import MAX_SL_DISTANCE


class SignalBuilder:

    @classmethod
    def _compute_stop_loss(
        cls,
        entry: float,
        anchor: float,
        direction: str,
        indicators,
        setup_type: str,
    ) -> tuple[float, float] | None:
        atr_v = float(indicators.atr_15m.iloc[-1])
        stop_atr_mult = 1.10

        buf = atr_v * stop_atr_mult
        if direction == "LONG":
            sl = anchor - buf
            dist = (entry - sl) / entry
        else:
            sl = anchor + buf
            dist = (sl - entry) / entry

        if setup_type == BREAKOUT and dist < MIN_SL_DISTANCE:
            if direction == "LONG":
                sl = entry * (1.0 - MIN_SL_DISTANCE)
            else:
                sl = entry * (1.0 + MIN_SL_DISTANCE)
            dist = MIN_SL_DISTANCE

        if dist <= 0 or dist > MAX_SL_DISTANCE:
            return None

        return sl, dist

    @classmethod
    def build(
        cls,
        setup: Setup,
    ) -> TradeSignal | None:

        indicators = setup.market_state.indicators
        setup_type = setup.setup_type.value
        direction = setup.side.value
        cfg = get_coin_config(setup.symbol)

        sl_data = cls._compute_stop_loss(
            entry=setup.entry,
            anchor=setup.anchor,
            direction=direction,
            indicators=indicators,
            setup_type=setup_type,
        )

        if sl_data is None:
            return None

        sl, dist = sl_data

        tp1_r = float(TP_CONFIG.get("tp1_r", 1.0))
        tp2_r = float(TP_CONFIG.get("tp2_r", 1.5))
        tp3_r = float(TP_CONFIG.get("tp3_r", 2.0))

        tp1, tp2 = resolve_tp1_tp2_prices(
            entry=setup.entry,
            direction=direction,
            dist=dist,
            data_15m=setup.market_state.data_15m,
            cfg=cfg,
            tp1_r=tp1_r,
            tp2_r=tp2_r,
            anchor=float(setup.anchor),
        )
        tp3 = resolve_tp3_price(
            entry=setup.entry,
            direction=direction,
            dist=dist,
            tp3_r=tp3_r,
            max_tp3_distance=None,
        )

        return TradeSignal(
            symbol=setup.symbol,
            direction=direction,
            entry=setup.entry,
            stop_loss=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            setup_score=int(round(setup.score)),
            setup_type=setup_type,
            strategy_family=resolve_strategy_family(setup_type),
            confirmation_mode="confirmed",
            tp1_r=tp1_r,
            tp2_r=tp2_r,
            tp3_r=tp3_r,
            market_state=setup.market_state,
            features=getattr(setup, "features", None),
        )