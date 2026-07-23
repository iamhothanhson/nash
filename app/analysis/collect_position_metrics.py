from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from indicators.models import Indicators as Indicators
from analysis.models import EntrySnapshot, MarketStateSnapshot, IndicatorSnapshot, SetupFeatureSnapshot

_ANALYSIS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "analysis"


def clear_analysis_file() -> None:
    filepath = _ANALYSIS_DIR / "position_analysis.json"
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text("[]\n", encoding="utf-8")


def save_entry_snapshot(snapshot: EntrySnapshot) -> str:
    position_id = snapshot.position_id or str(int(time.time() * 1_000_000))

    _ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = _ANALYSIS_DIR / "position_analysis.json"

    existing: list[dict[str, Any]] = []
    if filepath.exists():
        raw = filepath.read_text(encoding="utf-8")
        if raw.strip():
            loaded = json.loads(raw)
            existing = loaded if isinstance(loaded, list) else [loaded]

    existing.append({
        "position_id": position_id,
        "symbol": snapshot.symbol,
        "side": snapshot.side,
        "strategy_setup": snapshot.strategy_setup,
        "captured_at": snapshot.captured_at.isoformat(),
        "market_state": {
            "regime": snapshot.market_state.regime,
            "trend_direction": snapshot.market_state.trend_direction,
            "trend_aligned": snapshot.market_state.trend_aligned,
            "regime_confidence": round(snapshot.market_state.regime_confidence, 2),
            "market_structure": snapshot.market_state.market_structure,
            "is_trending": snapshot.market_state.is_trending,
            "is_ranging": snapshot.market_state.is_ranging,
            "is_high_volatility": snapshot.market_state.is_high_volatility,
        },
        "indicators": {
            "ema_slope_15m": round(snapshot.indicators.ema_slope_15m, 2),
            "ema_slope_1h": round(snapshot.indicators.ema_slope_1h, 2),
            "adx_15m": round(snapshot.indicators.adx_15m, 2),
            "adx_1h": round(snapshot.indicators.adx_1h, 2),
            "atr_percent": round(snapshot.indicators.atr_percent, 2),
            "atr_percentile": snapshot.indicators.atr_percentile,
            "rsi": round(snapshot.indicators.rsi, 2),
            "volume_ratio": round(snapshot.indicators.volume_ratio, 2),
        },
        "setup_features": {
            "setup_score": round(snapshot.setup_features.setup_score, 2),
            "confirmation_mode": snapshot.setup_features.confirmation_mode,
            "breakout_strength_pct": round(snapshot.setup_features.breakout_strength_pct, 2),
            "distance_from_level_pct": round(snapshot.setup_features.distance_from_level_pct, 2),
            "candle_body_ratio": round(snapshot.setup_features.candle_body_ratio, 2),
            "wick_ratio": round(snapshot.setup_features.wick_ratio, 2),
            "touch_count": snapshot.setup_features.touch_count,
            "breakout_level_age": snapshot.setup_features.breakout_level_age,
            "htf_confirmed": snapshot.setup_features.htf_confirmed,
        },
    })

    filepath.write_text(json.dumps(existing, indent=2, default=str) + "\n", encoding="utf-8")
    return position_id


def update_entry_result(position_id: str, result: str, pnl_pct: float, pnl_usdt: float, exit_reason: str) -> None:
    filepath = _ANALYSIS_DIR / "position_analysis.json"
    if not filepath.exists():
        return

    raw = filepath.read_text(encoding="utf-8")
    if not raw.strip():
        return

    data: list[dict[str, Any]] = json.loads(raw)
    if not isinstance(data, list):
        data = [data]

    for entry in data:
        if entry.get("position_id") == position_id:
            entry["result"] = result
            entry["pnl_pct"] = round(pnl_pct, 2)
            entry["pnl_usdt"] = round(pnl_usdt, 2)
            entry["exit_reason"] = exit_reason
            break

    filepath.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


def build_entry_snapshot(
    market_state: Any,
    features: dict[str, Any] | None,
    symbol: str = "",
    side: str = "",
    strategy_setup: str = "",
    position_id: str = "",
    setup_score: float = 0.0,
) -> EntrySnapshot:
    ind = getattr(market_state, "indicators", None) if market_state else None

    def enum_val(obj: Any, fallback: str) -> str:
        return getattr(obj, "value", fallback) if obj is not None else fallback

    def series_last(series: Any) -> float:
        if series is None:
            return 0.0
        try:
            return float(series.iloc[-1])
        except Exception:
            return 0.0

    def ind_val(attr: str, default: Any = None) -> Any:
        return getattr(ind, attr, default) if ind else default

    feat = features or {}

    return EntrySnapshot(
        symbol=symbol,
        side=side,
        strategy_setup=strategy_setup,
        position_id=position_id,
        captured_at=datetime.now(),
        market_state=MarketStateSnapshot(
            regime=enum_val(getattr(market_state, "regime", None), "Unknown"),
            trend_direction=enum_val(getattr(market_state, "trend_direction", None), "Neutral"),
            trend_aligned=getattr(market_state, "trend_aligned", False),
            regime_confidence=getattr(market_state, "regime_confidence", 50),
            market_structure=enum_val(getattr(market_state, "structure", None), "Range"),
            is_trending=getattr(market_state, "is_trending", False),
            is_ranging=getattr(market_state, "is_ranging", False),
            is_high_volatility=getattr(market_state, "is_high_volatility", False),
        ),
        indicators=IndicatorSnapshot(
            ema_slope_15m=ind_val("ema_slope", 0.0),
            ema_slope_1h=ind_val("ema20_slope_1h", 0.0),
            adx_15m=series_last(getattr(ind, "adx_15m", None)),
            adx_1h=series_last(getattr(ind, "adx_1h", None)),
            atr_percent=ind_val("atr_percent", 0.0),
            atr_percentile=ind_val("atr_percentile", 0),
            rsi=ind_val("rsi", 50.0),
            volume_ratio=ind_val("volume_ratio", 1.0),
        ),
        setup_features=SetupFeatureSnapshot(
            setup_score=setup_score,
            confirmation_mode=feat.get("confirmation_mode", ""),
            breakout_strength_pct=feat.get("breakout_strength_pct", 0.0),
            distance_from_level_pct=feat.get("distance_from_level_pct", 0.0),
            candle_body_ratio=feat.get("candle_body_ratio", 0.0),
            wick_ratio=feat.get("wick_ratio", 0.0),
            touch_count=feat.get("touch_count", 0),
            breakout_level_age=feat.get("breakout_level_age", 0),
            htf_confirmed=feat.get("htf_confirmed", False),
        ),
        indicators_raw=ind,
    )
