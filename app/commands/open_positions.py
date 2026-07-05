from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.common.rounding import round_price, round_qty, round_ratio, round_usd
from app.coins.loader import get_coin_config, price_rounding_decimal, price_tick_size
from app.config import settings
from app.execution.exchange_entry_gate import should_block_exchange_entry
from app.execution.execution_engine import create_execution_engine, ensure_demo_testnet_credentials
from app.monitoring import risk_limit_tracking
from app.monitoring.notifier import send_risk_limit_blocked_alert
from app.monitoring.events import emit_mode_event, strip_event_and_symbol_prefix
from app.monitoring.messages import (
    format_entry_filled_console_line,
    format_position_open_standard_line,
)
from app.monitoring.position_journal import log_position_open


def _position_state_path() -> Path:
    return PROJECT_ROOT / "runtime_data" / "runtime_positions.json"


def _count_open_tracked_positions(symbol: str) -> int:
    path = _position_state_path()
    if not path.exists():
        return 0
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(rows, list):
        return 0
    sym_u = symbol.strip().upper()
    n = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol", "")).strip().upper() != sym_u:
            continue
        if str(row.get("status", "OPEN")).strip().upper() == "OPEN":
            n += 1
    return n


def _account_risk_balance_usdt(engine) -> float:
    """Futures margin/wallet total for risk file (aligned with main live/demo sizing)."""
    client = getattr(engine, "_client", None)
    if client is not None and hasattr(client, "get_account_metrics"):
        try:
            m = client.get_account_metrics()
            v = float(m.get("total_margin_balance") or m.get("total_wallet_balance") or 0.0)
            if v > 0.0:
                return max(0.0, v)
        except Exception:
            pass
    return max(0.0, float(settings.INITIAL_CAPITAL))


def _append_runtime_position(
    *,
    symbol: str,
    side: str,
    qty: float,
    entry: float,
    stop_loss: float,
    tp1: float,
    tp2: float,
    tp3: float,
    stop_exchange_order_id: int | None,
) -> None:
    path = _position_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        existing = []
    if not isinstance(existing, list):
        existing = []
    direction = "LONG" if side == "BUY" else "SHORT"
    sym_u = symbol.strip().upper()
    tick = price_tick_size(sym_u)
    risk_per_unit = abs(float(entry) - float(stop_loss))
    initial_notional_usdt = abs(float(entry) * float(qty))
    leverage = max(1.0, float(settings.LEVERAGE))
    initial_margin_usdt = initial_notional_usdt / leverage
    rr = abs(float(tp1) - float(entry)) / risk_per_unit if risk_per_unit > 0 else 0.0
    row = {
        "symbol": sym_u,
        "side": direction,
        "status": "OPEN",
        "position": {
            "qty_total": round_qty(qty),
            "qty_open": round_qty(qty),
            "entry_price": round_price(entry, tick),
            "initial_notional_usdt": round_usd(initial_notional_usdt),
            "initial_margin_usdt": round_usd(initial_margin_usdt),
            "realized_pnl": round_usd(0.0),
            "fees_paid": round_usd(0.0),
        },
        "stop_loss": {
            "initial_stop_loss": round_price(stop_loss, tick),
            "current_stop_loss": round_price(stop_loss, tick),
            "initial_risk_usd": round_usd(abs(float(entry) - float(stop_loss)) * float(qty)),
            "risk_reward_ratio": round_ratio(rr),
            "sl_order_id": stop_exchange_order_id,
            "sl_hit": False,
        },
        "take_profits": [
            {
                "price": round_price(tp1, tick),
                "tp1_partial_close": round_ratio(50.0),
                "tp1_hit": False,
                "tp1_order_id": None,
                "exchange_tp_orders_placed": False,
            },
            {
                "price": round_price(tp2, tick),
                "tp2_partial_close": round_ratio(30.0),
                "tp2_hit": False,
                "tp2_order_id": None,
                "exchange_tp_orders_placed": False,
            },
            {
                "price": round_price(tp3, tick),
                "tp3_partial_close": round_ratio(20.0),
                "tp3_hit": False,
                "tp3_order_id": None,
                "exchange_tp_orders_placed": False,
            },
        ],
        "exchange": {
            "last_sent_stop_loss": round_price(stop_loss, tick),
            "last_sent_qty": round_qty(qty),
        },
        "meta": {
            "setup_type": "manual_open_trade",
            "setup_grade": "MANUAL",
            "strategy": "manual",
            "timeframe": None,
        },
        "timestamps": {
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": None,
            "closed_at": None,
        },
        "journal_logged": False,
    }
    existing.append(row)
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def _fapi_market_base() -> str:
    return settings.BINANCE_FAPI_MARKET_HOST.rstrip("/")


def get_current_price(symbol: str) -> float:
    sym = symbol.strip().upper()
    r = requests.get(
        f"{_fapi_market_base()}/fapi/v1/ticker/price",
        params={"symbol": sym},
        timeout=20,
    )
    r.raise_for_status()
    return float(r.json()["price"])


def _lot_size_constraints(symbol: str) -> tuple[float, float]:
    sym = symbol.strip().upper()
    r = requests.get(
        f"{_fapi_market_base()}/fapi/v1/exchangeInfo",
        params={"symbol": sym},
        timeout=30,
    )
    r.raise_for_status()
    for s in r.json().get("symbols", []):
        if s.get("symbol") == sym:
            for f in s.get("filters", []):
                if f.get("filterType") == "LOT_SIZE":
                    return float(f["stepSize"]), float(f["minQty"])
    return 0.001, 0.001


def round_quantity_to_lot_step(quantity: float, step: float) -> float:
    if step <= 0:
        return round(quantity, 8)
    n = math.floor(quantity / step + 1e-12)
    return round(n * step, 12)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open a manual futures trade with SL/TP.")
    parser.add_argument(
        "--size-usdt",
        "--size",
        dest="size_usdt",
        type=float,
        required=True,
        help="Position notional in USDT (e.g., --size-usdt 10). Alias: --size.",
    )
    parser.add_argument("--symbol", type=str, default=settings.SYMBOL, help="Symbol to trade (default from settings).")
    parser.add_argument("--side", type=str, choices=("BUY", "SELL"), default="BUY", help="Order side (BUY/SELL).")
    parser.add_argument(
        "--sl-pct",
        type=float,
        default=0.003,
        help="Stop-loss distance from entry as decimal (default 0.003 = 0.3%%).",
    )
    parser.add_argument(
        "--tp-pct",
        type=float,
        default=0.003,
        help="Take-profit distance from entry as decimal (default 0.003 = 0.3%%).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mode = settings.MODE
    if mode not in ("demo", "live"):
        print(f"Manual open-trade CLI supports demo/live only. Current MODE={mode!r}.")
        return 1
    if args.size_usdt <= 0:
        print("--size-usdt must be > 0 (USDT notional)")
        return 1
    if args.sl_pct <= 0 or args.tp_pct <= 0:
        print("--sl-pct and --tp-pct must be > 0")
        return 1

    symbol = str(args.symbol).strip().upper()
    if symbol not in settings.ALLOWED_SYMBOLS:
        print(f"Symbol {symbol} is not in ALLOWED_SYMBOLS.")
        return 1
    side = str(args.side).strip().upper()

    if mode == "demo":
        try:
            ensure_demo_testnet_credentials()
        except RuntimeError as exc:
            print(str(exc))
            return 1
    if mode == "live":
        confirm = input("Type Y to place LIVE manual order: ")
        if confirm != "Y":
            print("Cancelled.")
            return 1

    try:
        price = get_current_price(symbol)
        step, min_qty = _lot_size_constraints(symbol)
        raw_qty = float(args.size_usdt) / max(price, 1e-12)
        qty = round_quantity_to_lot_step(raw_qty, step)
        if qty < min_qty:
            qty = min_qty
        qty = round(float(qty), 8)
    except Exception as exc:
        print(f"Failed preparing qty: {exc}")
        return 1

    if side == "BUY":
        sl = round(float(price) * (1.0 - (2 * float(args.sl_pct))), 4)
        tp1 = round(float(price) * (1.0 + (1 *float(args.tp_pct))), 4)
        tp2 = round(float(price) * (1.0 + (2 * float(args.tp_pct))), 4)
        tp3 = round(float(price) * (1.0 + (3 * float(args.tp_pct))), 4)
    else:
        sl = round(float(price) * (1.0 + (2 * float(args.sl_pct))), 4)
        tp1 = round(float(price) * (1.0 - (1 * float(args.tp_pct))), 4)
        tp2 = round(float(price) * (1.0 - (2 * float(args.tp_pct))), 4)
        tp3 = round(float(price) * (1.0 - (3 * float(args.tp_pct))), 4)

    try:
        engine = create_execution_engine()
        risk_bal = _account_risk_balance_usdt(engine)
        rl_ok, rl_reason = risk_limit_tracking.risk_file_entry_gate(balance_usdt=risk_bal)
        if not rl_ok:
            print(rl_reason or "Trading stopped")
            send_risk_limit_blocked_alert(
                symbol, str(rl_reason or "Trading stopped"), balance_usdt=float(risk_bal)
            )
            return 1
        client = getattr(engine, "_client", None)
        if client is not None:
            exch_hedge = client.exchange_dual_side_enabled()
            cfg_mode = client.position_mode_label()
            if cfg_mode == "oneway" and exch_hedge:
                print(
                    "[WARN] BINANCE_POSITION_MODE=oneway but exchange hedge mode is ON; "
                    "set BINANCE_POSITION_MODE=hedge or auto"
                )
            elif cfg_mode == "hedge" and not exch_hedge:
                print(
                    "[WARN] BINANCE_POSITION_MODE=hedge but exchange one-way mode is ON; "
                    "set BINANCE_POSITION_MODE=oneway or auto"
                )
            tracked = _count_open_tracked_positions(symbol)
            blocked, why = should_block_exchange_entry(
                client,
                symbol,
                {symbol.strip().upper(): tracked},
                side=side,
            )
            if blocked:
                print(f"Order blocked: {symbol} | {why}")
                return 1
        result = engine.place_order(
            symbol,
            side,
            float(qty),
            float(sl),
            float(tp1),
            risk_percent=float(settings.RISK_PER_TRADE),
        )
    except Exception as exc:
        print(f"Order failed: {exc}")
        return 1

    if result is None:
        why = getattr(engine, "last_place_order_failure", None)
        print(f"Order not placed{f' | reason={why}' if why else ''}")
        return 1

    has_sl = bool(result.get("stop_loss_order")) if isinstance(result, dict) else False
    stop_exchange_order_id: int | None = None
    tp1_exchange_order_id: int | None = None
    fill_entry = float(price)
    if isinstance(result, dict):
        for key in ("avgPrice", "price"):
            raw_px = result.get(key)
            if raw_px is None:
                continue
            try:
                px = float(raw_px)
            except (TypeError, ValueError):
                continue
            if px > 0.0:
                fill_entry = px
                break
        raw_oid = result.get("stop_exchange_order_id")
        if raw_oid is not None:
            try:
                stop_exchange_order_id = int(raw_oid)
            except (TypeError, ValueError):
                stop_exchange_order_id = None
        raw_tp1_oid = result.get("tp1_exchange_order_id")
        if raw_tp1_oid is not None:
            try:
                tp1_exchange_order_id = int(raw_tp1_oid)
            except (TypeError, ValueError):
                tp1_exchange_order_id = None
    price_dp = price_rounding_decimal(symbol)
    hedge_on = bool(getattr(client, "use_hedge_position_side", lambda: False)()) if client else False
    _append_runtime_position(
        symbol=symbol,
        side=side,
        qty=float(qty),
        entry=float(fill_entry),
        stop_loss=float(sl),
        tp1=float(tp1),
        tp2=float(tp2),
        tp3=float(tp3),
        stop_exchange_order_id=stop_exchange_order_id,
    )
    risk_limit_tracking.record_new_open(balance_usdt=_account_risk_balance_usdt(engine))
    open_iso = datetime.now(timezone.utc).isoformat()
    direction = "LONG" if side == "BUY" else "SHORT"
    risk_usdt = abs(float(fill_entry) - float(sl)) * float(qty)
    size_usdt = float(args.size_usdt)
    tp1_px = float(tp1)
    tp2_px = float(tp2)
    tp3_px = float(tp3)
    pc_raw = get_coin_config(symbol).get("partial_close", [0.5, 0.3, 0.2])
    if not isinstance(pc_raw, list) or len(pc_raw) < 3:
        pc_raw = [0.5, 0.3, 0.2]
    partial_close = [float(pc_raw[0]), float(pc_raw[1]), float(pc_raw[2])]
    log_position_open(
        time_iso=open_iso,
        symbol=symbol,
        direction=direction,
        entry=float(fill_entry),
        stop_loss=float(sl),
        tp1=tp1_px,
        tp2=tp2_px,
        tp3=tp3_px,
        size_usdt=size_usdt,
        leverage=int(settings.LEVERAGE),
        risk_usdt=float(risk_usdt),
        partial_close=partial_close,
        strategy_family="liquidity",
        setup_type="manual_open_trade",
        sl_order_id=stop_exchange_order_id,
        tp1_order_id=tp1_exchange_order_id,
        tp2_order_id=None,
        tp3_order_id=None,
    )
    open_line = format_position_open_standard_line(
        symbol=symbol,
        entry=float(fill_entry),
        stop_loss=float(sl),
        size_usdt=size_usdt,
        leverage=int(settings.LEVERAGE),
        risk_usdt=float(risk_usdt),
        tp1=tp1_px,
        tp2=tp2_px,
        tp3=tp3_px,
        price_decimals=price_dp,
        strategy_family="liquidity",
        setup_type="manual_open_trade",
    )

    emit_mode_event(
        settings.MODE,
        symbol,
        direction,
        "OPEN",
        strip_event_and_symbol_prefix(open_line, "OPEN", symbol),
    )
    filled_line = format_entry_filled_console_line(
        mode=mode,
        symbol=symbol,
        direction=direction,
        hedge_on=hedge_on,
        leverage=int(settings.LEVERAGE),
        size_usdt=size_usdt,
        entry=float(fill_entry),
        stop_loss=float(sl),
        tp1=tp1_px,
        tp2=tp2_px,
        tp3=tp3_px,
        price_decimals=price_dp,
        status="Entry Filled" if has_sl else "Entry Filled (stop MISSING)",
    )
    print(filled_line)
    if not has_sl:
        print(f"[WARN] {symbol} | Stop-loss order not placed on exchange")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
