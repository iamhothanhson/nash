from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from position_management.exit_bar_utils import build_exit_bar_slice, decide_exit_from_bar_slice
from position_management.exit_manager import decide_exit
from position_management.exit_tuning import build_exit_manager_config
from position_management.staged import ManagedPosition, apply_staged_management
from order_planning.order_planner import build_order_plan
from risk.risk_multiplier_manager import compute_risk_multiplier
from trading.signal_engine import get_signal


def _load_frame(timeframe: str) -> pd.DataFrame:
    path = PROJECT_ROOT / "history_data" / f"TAOUSDT_{timeframe}.csv"
    raw = pd.read_csv(path)
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(raw["time"], unit="ms", utc=True),
            "open": raw["open"].astype(float),
            "high": raw["high"].astype(float),
            "low": raw["low"].astype(float),
            "close": raw["close"].astype(float),
            "volume": raw["volume"].astype(float),
        }
    ).sort_values("timestamp").reset_index(drop=True)


def _eval_snapshot(
    *,
    d1h: pd.DataFrame,
    d15: pd.DataFrame,
    d5: pd.DataFrame,
    live_like: bool,
) -> dict[str, object]:
    signal = get_signal(d1h, d15, d5, symbol="TAOUSDT")
    out: dict[str, object] = {
        "signal_exists": signal is not None,
        "direction": (str(getattr(signal, "direction", "")).upper() if signal is not None else None),
        "skip_reason": None,
        "planned_notional": None,
    }
    if signal is None:
        return out

    risk_multiplier, skip_reason = compute_risk_multiplier("TAOUSDT", d15, d5)
    out["skip_reason"] = skip_reason
    if str(skip_reason or "").strip().lower() == "insufficient data":
        return out

    balance = 333.0
    kwargs = dict(
        signal=signal,
        balance=balance,
        positions_per_symbol={"TAOUSDT": 0},
        open_positions_total=0,
        allocation_share=1.0,
        symbol="TAOUSDT",
        max_open_positions=1,
        open_notional_total=0.0,
        risk_multiplier=float(risk_multiplier),
        data_15m=d15,
    )
    if live_like:
        # Mirror live-side hard cap semantics (non-binding in this harness when ample).
        kwargs["max_notional_account_cap"] = float(balance) * max(1.0, float(settings.LEVERAGE))
    plan = build_order_plan(**kwargs)
    if isinstance(plan, dict):
        out["planned_notional"] = round(float(plan.get("notional", 0.0)), 6)
    return out


def test_live_backtest_entry_parity_replay() -> None:
    d1h_all = _load_frame("1h")
    d15_all = _load_frame("15m")
    d5_all = _load_frame("5m")

    # Deterministic multi-bar replay over recent closed bars.
    start = max(420, len(d5_all) - 220)
    end = len(d5_all) - 20
    mismatches: list[str] = []

    for idx in range(start, end):
        d5 = d5_all.iloc[:idx].tail(420).reset_index(drop=True)
        if len(d5) < 250:
            continue
        ts = d5["timestamp"].iloc[-1]
        d15 = d15_all[d15_all["timestamp"] <= ts].tail(max(200, settings.ATR_REGIME_LOOKBACK + 24)).reset_index(
            drop=True
        )
        d1h = d1h_all[d1h_all["timestamp"] <= ts].tail(420).reset_index(drop=True)
        if len(d15) < 120 or len(d1h) < 250:
            continue

        live_eval = _eval_snapshot(d1h=d1h, d15=d15, d5=d5, live_like=True)
        backtest_eval = _eval_snapshot(d1h=d1h, d15=d15, d5=d5, live_like=False)
        if live_eval != backtest_eval:
            mismatches.append(
                f"{str(ts)} | live={live_eval} | backtest={backtest_eval}"
            )

    assert not mismatches, (
        f"Parity drift detected on {len(mismatches)} replay bars.\n"
        + "\n".join(mismatches[:5])
    )


def _pnl(direction: str, entry: float, exit_px: float, qty: float) -> float:
    fee_rate = 0.0004
    gross = (exit_px - entry) * qty if str(direction).upper() == "LONG" else (entry - exit_px) * qty
    fee = (entry * qty + exit_px * qty) * fee_rate
    return gross - fee


def _fill_tag(fill: object) -> str:
    if isinstance(fill, dict):
        return str(fill.get("tag", ""))
    return str(getattr(fill, "tag", ""))


def _simulate_exit_path(
    *,
    d5_all: pd.DataFrame,
    d15_all: pd.DataFrame,
    start_idx: int,
    live_like: bool,
) -> dict[str, object]:
    row = d5_all.iloc[start_idx]
    entry = float(row["close"])
    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="LONG",
        qty_total=1.0,
        qty_open=1.0,
        entry=entry,
        stop_loss=entry * 0.995,
        tp1=entry * 1.005,
        tp2=entry * 1.010,
        tp3=entry * 1.015,
        setup_type="liquidity_sweep",
        setup_grade="A",
        open_time_iso=pd.Timestamp(row["timestamp"]).isoformat(),
        initial_risk_usd=entry * 0.005,
    )
    exit_cfg = build_exit_manager_config(apply_tuning=True)
    close_idx: int | None = None
    close_reason = "none"

    for idx in range(start_idx + 1, min(start_idx + 80, len(d5_all))):
        ts = pd.Timestamp(d5_all.iloc[idx]["timestamp"])
        d5 = d5_all[d5_all["timestamp"] <= ts].tail(420).reset_index(drop=True)
        d15 = d15_all[d15_all["timestamp"] <= ts].tail(max(200, settings.ATR_REGIME_LOOKBACK + 24)).reset_index(
            drop=True
        )
        if len(d5) < 64 or len(d15) < 64:
            continue
        if live_like:
            sl = build_exit_bar_slice(df5=d5, df15=d15, wall_now=ts + pd.Timedelta(minutes=5))
        else:
            sl = build_exit_bar_slice(df5=d5, df15=d15, bar_open=ts)
        if sl is None:
            continue
        fills = apply_staged_management(pos, high=sl.high, low=sl.low, now_ts=sl.bar_ts, pnl_fn=_pnl)
        if not fills and pos.qty_open > 0:
            current_roi = ((float(sl.close_px) - float(pos.entry)) / max(float(pos.entry), 1e-12)) * 100.0 * float(
                settings.LEVERAGE
            )
            pos.roi_history.append({"t": float(sl.bar_ts), "roi": float(current_roi)})
            pos.max_roi_seen = max(float(pos.max_roi_seen), float(current_roi))
            decision = decide_exit_from_bar_slice(
                slice_=sl,
                time_in_trade=max(0.0, float(sl.bar_ts) - float(pd.Timestamp(pos.open_time_iso).timestamp())),
                current_roi=float(current_roi),
                roi_history=list(pos.roi_history),
                max_roi_seen=float(pos.max_roi_seen),
                exit_manager=exit_cfg,
                direction=str(pos.direction),
                time_since_tp1=(
                    max(0.0, float(sl.bar_ts) - float(pos.tp1_hit_at_ts))
                    if pos.tp1_hit_at_ts is not None
                    else None
                ),
                symbol="TAOUSDT",
                decide_exit_fn=decide_exit,
            )
            if str(decision.get("action", "HOLD")).upper() == "CLOSE":
                qty = float(pos.qty_open)
                px = float(sl.close_px)
                pnl = float(_pnl(pos.direction, pos.entry, px, qty))
                pos.realized_pnl += pnl
                pos.qty_open = 0.0
                pos.closed = True
                fills = [{"tag": "TIME EXIT", "price": px, "qty_closed": qty, "qty_remaining": 0.0, "pnl": pnl}]
        if fills and any(_fill_tag(f).upper() == "SL HIT" for f in fills):
            close_reason = "SL"
        elif fills and any(_fill_tag(f).upper() == "TP3 HIT" for f in fills):
            close_reason = "TP3"
        elif fills and any(_fill_tag(f).upper() == "TIME EXIT" for f in fills):
            close_reason = "TIME EXIT"
        if pos.closed:
            close_idx = idx
            break

    return {
        "closed": bool(pos.closed),
        "close_idx": close_idx,
        "close_reason": close_reason,
        "realized_pnl": round(float(pos.realized_pnl), 6),
    }


def test_live_backtest_exit_path_parity_replay() -> None:
    d15_all = _load_frame("15m")
    d5_all = _load_frame("5m")
    start_idx = max(300, len(d5_all) - 260)
    live = _simulate_exit_path(d5_all=d5_all, d15_all=d15_all, start_idx=start_idx, live_like=True)
    backtest = _simulate_exit_path(d5_all=d5_all, d15_all=d15_all, start_idx=start_idx, live_like=False)

    assert live["closed"] == backtest["closed"]
    assert live["close_reason"] == backtest["close_reason"]
    assert live["close_idx"] == backtest["close_idx"]
    assert abs(float(live["realized_pnl"]) - float(backtest["realized_pnl"])) <= 1e-6

