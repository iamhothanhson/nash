from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from monitoring.logger import log

# Bounded retain window for backtests: exit logic uses tail(64) on 5m/15m candles,
# tail(20) volume on 5m, tail(120) ADX input on 15m (see build_exit_bar_slice).
_EXIT_SLICE_MAX_ROWS_5M = 320
_EXIT_SLICE_MAX_ROWS_15M = 192


def interval_to_timedelta(interval: str) -> pd.Timedelta:
    s = str(interval).strip().lower()
    if s.endswith("m"):
        return pd.Timedelta(minutes=int(s[:-1]))
    if s.endswith("h"):
        return pd.Timedelta(hours=int(s[:-1]))
    if s.endswith("d"):
        return pd.Timedelta(days=int(s[:-1]))
    return pd.to_timedelta(s)


def ensure_timestamp_column(df: pd.DataFrame) -> pd.DataFrame:
    if "timestamp" in df.columns:
        return df
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out.index, utc=True)
    return out


def last_closed_bar_open_ts(
    df: pd.DataFrame,
    interval: str,
    *,
    wall_now: pd.Timestamp | None = None,
) -> pd.Timestamp | None:
    wdf = ensure_timestamp_column(df)
    if wdf.empty or "timestamp" not in wdf.columns:
        return None
    ref = wall_now if wall_now is not None else pd.Timestamp.now(tz=timezone.utc)
    td = interval_to_timedelta(interval)
    ts_col = pd.to_datetime(wdf["timestamp"], utc=True)
    closed = wdf.loc[ts_col + td <= ref]
    if closed.empty:
        return None
    return pd.to_datetime(closed["timestamp"].iloc[-1], utc=True)


@dataclass(frozen=True)
class ExitBarSlice:
    bar_ts: float
    bar_open: pd.Timestamp
    close_px: float
    high: float
    low: float
    candles_5m: pd.DataFrame
    candles_15m: pd.DataFrame
    volume_ratio: float
    adx_input_15m: pd.DataFrame
    sub_bars_1m: pd.DataFrame | None = None


def volume_ratio_asof(df5_asof: pd.DataFrame) -> float:
    tail = df5_asof.tail(20)
    if tail.empty or "volume" not in tail.columns:
        return 1.0
    vols = tail["volume"].astype(float)
    avg = float(vols.mean())
    cur = float(vols.iloc[-1])
    return (cur / avg) if avg > 1e-12 else 1.0


def slice_asof_timestamp(
    df: pd.DataFrame,
    bar_open: pd.Timestamp,
    *,
    max_rows: int | None = 512,
) -> pd.DataFrame:
    """
    Rows with timestamp <= bar_open. When max_rows is set and the frame is time-ordered,
    only the last max_rows of that prefix are copied (cheap path via searchsorted).
    """
    wdf = ensure_timestamp_column(df)
    bo = pd.Timestamp(bar_open).tz_convert("UTC") if bar_open.tzinfo else pd.Timestamp(bar_open, tz=timezone.utc)
    if wdf.empty:
        return wdf.iloc[:0].copy()
    ts = pd.to_datetime(wdf["timestamp"], utc=True)

    if max_rows is None:
        return wdf.loc[ts <= bo].copy()

    if ts.is_monotonic_increasing:
        t_ns = ts.astype("int64").to_numpy()
        bo_ns = int(pd.Timestamp(bo).value)
        pos = int(np.searchsorted(t_ns, bo_ns, side="left")) - 1
        if pos < 0:
            return wdf.iloc[:0].copy()
        start = max(0, pos - max_rows + 1)
        return wdf.iloc[start : pos + 1].copy()

    mask = ts <= bo
    if not mask.any():
        return wdf.iloc[:0].copy()
    idx = mask.to_numpy().nonzero()[0]
    pos_rel = int(idx[-1])
    start = max(0, pos_rel - max_rows + 1)
    return wdf.iloc[start : pos_rel + 1].copy()


def build_exit_bar_slice(
    *,
    df5: pd.DataFrame,
    df15: pd.DataFrame,
    df1m: pd.DataFrame | None = None,
    interval_5m: str = "5m",
    interval_15m: str = "15m",
    bar_open: pd.Timestamp | None = None,
    wall_now: pd.Timestamp | None = None,
) -> ExitBarSlice | None:
    w5 = ensure_timestamp_column(df5)
    if bar_open is None:
        bo = last_closed_bar_open_ts(w5, interval_5m, wall_now=wall_now)
        if bo is None:
            return None
    else:
        bo = pd.Timestamp(bar_open)
        if bo.tzinfo is None:
            bo = bo.tz_localize("UTC")
        else:
            bo = bo.tz_convert("UTC")
    df5_asof = slice_asof_timestamp(w5, bo, max_rows=_EXIT_SLICE_MAX_ROWS_5M)
    if df5_asof.empty:
        return None
    df15_asof = slice_asof_timestamp(
        ensure_timestamp_column(df15), bo, max_rows=_EXIT_SLICE_MAX_ROWS_15M
    )
    candles_5m = df5_asof.tail(64)
    candles_15m = df15_asof.tail(64)
    n5 = len(df5_asof)
    if n5 >= 2:
        last = df5_asof.iloc[-2]
    else:
        last = df5_asof.iloc[-1]
    close_px = float(last["close"]) if "close" in last else float((float(last["high"]) + float(last["low"])) * 0.5)
    high = float(last["high"])
    low = float(last["low"])
    bar_ts = float(pd.Timestamp(bo).timestamp())
    vr = volume_ratio_asof(df5_asof)
    adx_in = df15_asof.tail(120)
    sub_bars_1m = None
    if df1m is not None and not df1m.empty:
        bar_end = bo + pd.Timedelta(minutes=5)
        try:
            sub_bars_1m = df1m.loc[bo:bar_end].copy()
        except KeyError:
            pass
    return ExitBarSlice(
        bar_ts=bar_ts,
        bar_open=bo,
        close_px=close_px,
        high=high,
        low=low,
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        volume_ratio=vr,
        adx_input_15m=adx_in,
        sub_bars_1m=sub_bars_1m,
    )


def log_exit_input_parity(
    *,
    mode: str,
    bar_ts: float,
    close_px: float,
    candles_5m_len: int,
    symbol: str = "",
) -> None:
    sym = str(symbol).strip().upper() or "—"
    log(
        f"[EXIT INPUT] mode={mode} ts={bar_ts:.3f} price={close_px:.6f} "
        f"candles_5m_len={candles_5m_len} symbol={sym}"
    )


def decide_exit_from_bar_slice(
    *,
    slice_: ExitBarSlice,
    time_in_trade: float,
    current_roi: float,
    roi_history: list[dict[str, float]],
    max_roi_seen: float,
    exit_manager: Any,
    direction: str,
    time_since_tp1: float | None,
    symbol: str,
    decide_exit_fn: Any,
    entry_price: float | None = None,
    breakout_level: float | None = None,
) -> dict[str, Any]:
    c5 = slice_.candles_5m
    c15 = slice_.candles_15m
    last_15m_high = last_15m_low = current_15m_close = None
    if len(c15) >= 1:
        last_15m_high = float(c15["high"].iloc[-1])
        last_15m_low = float(c15["low"].iloc[-1])
        current_15m_close = float(c15["close"].iloc[-1])
    adx_value = 0.0
    adx_df = slice_.adx_input_15m
    if not adx_df.empty and len(adx_df) >= 20:
        from indicators import calculate_adx

        adx_value = float(calculate_adx(adx_df.reset_index(drop=True), 14).iloc[-1])
    return decide_exit_fn(
        time_in_trade=float(time_in_trade),
        current_roi=float(current_roi),
        roi_history=list(roi_history),
        max_roi_seen=float(max_roi_seen),
        volume_ratio=float(slice_.volume_ratio),
        adx=float(adx_value),
        exit_manager=exit_manager,
        direction=str(direction),
        candle_opens=[float(x) for x in c5["open"].tolist()],
        candle_closes=[float(x) for x in c5["close"].tolist()],
        candle_highs=[float(x) for x in c5["high"].tolist()],
        candle_lows=[float(x) for x in c5["low"].tolist()],
        candle_volumes=[float(x) for x in c5["volume"].tolist()],
        time_since_tp1=time_since_tp1,
        last_15m_high=last_15m_high,
        last_15m_low=last_15m_low,
        current_15m_close=current_15m_close,
        symbol=str(symbol),
        entry_price=entry_price,
        breakout_level=breakout_level,
    )


def replay_decide_exit(
    *,
    df5: pd.DataFrame,
    df15: pd.DataFrame,
    bar_open: pd.Timestamp,
    **kwargs: Any,
) -> dict[str, Any]:
    sl = build_exit_bar_slice(df5=df5, df15=df15, bar_open=bar_open)
    if sl is None:
        return {"action": "HOLD", "reason": "no_bar_slice", "metrics": {}}
    return decide_exit_from_bar_slice(slice_=sl, **kwargs)
