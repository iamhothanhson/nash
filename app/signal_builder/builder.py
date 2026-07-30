from __future__ import annotations

from typing import Any

from app.signal_builder.models import TradeSignal
from app.signal_builder.take_profit import tp_from_r
from setup_builder.builder import Setup
from app.signal_builder.stop_loss import compute_stop_loss
from app.signal_builder.models import TrailingStopConfig


class SignalBuilder:

    @classmethod
    def build(
        cls,
        setup: Setup,
        pipeline_stats: Any = None,
    ) -> TradeSignal | None:

        config = setup.config
        indicators = setup.market_state.indicators
        atr = indicators.atr_15m or 0.0
        setup_type = setup.setup_type.value
        direction = setup.side.value

        stop_loss = compute_stop_loss(
            entry=setup.entry,
            anchor=setup.anchor,
            atr=atr,
            direction=direction,
            atr_mult=config["sl_atr_mult"],
        )

        if stop_loss is None:
            return None

        tp1_r = float(config.get("tp1_rr", 2.0))
        tp2_atr_mult = config["tp2"]["atr_mult"]

        tp1 = tp_from_r(entry=setup.entry, stop_loss=stop_loss, direction=direction, rr=tp1_r)
        tp1_pct = abs(tp1 - setup.entry) / setup.entry * 100
        trailing_stop = TrailingStopConfig(
            type="atr",
            tp2_atr_mult=tp2_atr_mult,
        )

        if pipeline_stats:
            pipeline_stats.signal_built += 1

        return TradeSignal(
            symbol=setup.symbol,
            direction=direction,
            entry=setup.entry,
            stop_loss=stop_loss,
            tp1=tp1,
            tp1_r=tp1_r,
            tp1_pct=tp1_pct,
            trailing_stop=trailing_stop,
            setup_score=int(round(setup.score)),
            setup_grade=setup.grade,
            setup_type=setup_type,
            strategy_family=setup.strategy_family,
            confirmation_mode="confirmed",
            market_state=setup.market_state,
            features=getattr(setup, "features", None),
        )
