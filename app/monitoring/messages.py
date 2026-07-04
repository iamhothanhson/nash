from __future__ import annotations

from common.rounding import format_price, round_usd

from config.constants import BREAKOUT, PULLBACK, LIQUIDITY_SWEEP, LIQUIDITY_SWEEP_REVERSAL


def _position_mode_display_label(raw: str) -> str:
    text = str(raw).strip()
    if "(" in text:
        head, tail = text.split("(", 1)
        return f"{_position_mode_display_label(head)} ({tail}"
    s = text.lower()
    if s in ("one-way", "oneway"):
        return "One-way"
    if s == "hedge":
        return "Hedge"
    if s == "auto":
        return "Auto"
    return text.title() or "Auto"


def format_bot_start_line(
    *,
    mode_label: str,
    symbols_str: str,
    balance_label: str,
    balance_value: float,
    leverage: int,
    position_mode: str | None = None,
) -> str:
    pm = (
        f" | Position Mode: {_position_mode_display_label(position_mode)}"
        if position_mode
        else ""
    )
    return (
        f"[BOT START] Mode: {mode_label}{pm} | Symbols: {symbols_str} | "
        f"{balance_label}: {float(balance_value):.2f} | Leverage: {int(leverage)}x"
    )


def strip_event_prefix(line: str, event: str) -> str:
    prefix = f"[{event}] "
    text = str(line)
    return text[len(prefix) :] if text.startswith(prefix) else text


def strip_event_and_symbol_prefix(line: str, event: str, symbol: str) -> str:
    text = strip_event_prefix(line, event)
    sym_prefix = f"{str(symbol).upper()} | "
    return text[len(sym_prefix) :] if text.startswith(sym_prefix) else text


def format_mode_event_line(mode: str, symbol: str, side: str, event: str, payload: str) -> str:
    return f"[{str(mode).upper()}] [{event}] {str(symbol).upper()} [{str(side).upper()}] | {payload}"


def _tp_price_distance_pct(entry: float, tp_price: float) -> float:
    e = float(entry)
    if e <= 0.0:
        return 0.0
    return abs(float(tp_price) - e) / e * 100.0


def format_open_strategy_setup_labels(
    *,
    strategy_family: str | None = None,
    setup_type: str | None = None,
) -> tuple[str, str]:
    """Human-readable Strategy / Setup labels for OPEN Telegram and console lines."""
    fam = str(strategy_family or "liquidity").strip().upper()
    st = str(setup_type or "unknown").strip().upper()
    if fam in ("trend_following", "trend"):
        strategy = "Trend Following"
        if st == BREAKOUT:
            setup = "Breakout"
        elif st == PULLBACK:
            setup = "Pullback"
        elif st in ("", "unknown"):
            setup = "Unknown"
        else:
            setup = st.replace("_", " ").title()
        return strategy, setup
    if fam == "liquidity":
        strategy = "Liquidity"
        if st in (LIQUIDITY_SWEEP, LIQUIDITY_SWEEP_REVERSAL):
            setup = "Liquidity Sweep Reversal"
        elif st == "manual_open_trade":
            setup = "Manual"
        elif st in ("", "unknown"):
            setup = "Unknown"
        else:
            setup = st.replace("_", " ").title()
        return strategy, setup
    strategy = fam.replace("_", " ").title() if fam else "Unknown"
    setup = st.replace("_", " ").title() if st and st != "unknown" else "Unknown"
    return strategy, setup


def format_tp3_display(*, tp3: float, price_decimals: int = 2) -> str:
    """Human label for TP3 — fixed price or structure runner."""
    if float(tp3) <= 0.0:
        return "Runner (15m structure trail)"
    return format_price(float(tp3), int(price_decimals))


def format_position_open_standard_line(
    *,
    symbol: str,
    entry: float,
    stop_loss: float,
    size_usdt: float,
    leverage: int,
    risk_usdt: float,
    tp1: float,
    tp2: float,
    tp3: float,
    price_decimals: int = 2,
    strategy_family: str | None = None,
    setup_type: str | None = None,
) -> str:
    lev = max(1, int(leverage))
    margin_usdt = float(size_usdt) / float(lev)
    sym_u = str(symbol).strip().upper()
    e = float(entry)
    sl = float(stop_loss)
    sl_pct = (-abs(sl - e) / e * 100.0) if e > 0.0 else 0.0
    pd = int(price_decimals)
    t1 = _tp_price_distance_pct(e, float(tp1))
    t2 = _tp_price_distance_pct(e, float(tp2))
    t3_s = format_tp3_display(tp3=float(tp3), price_decimals=pd)
    t3_pct = "" if float(tp3) <= 0.0 else f" ({_tp_price_distance_pct(e, float(tp3)):.2f}%)"
    r = float(risk_usdt)
    strategy_s, setup_s = format_open_strategy_setup_labels(
        strategy_family=strategy_family,
        setup_type=setup_type,
    )
    return (
        f"[OPEN] {sym_u} | Strategy: {strategy_s} | Setup: {setup_s} | "
        f"Entry: {format_price(e, pd)} | Size: {float(size_usdt):.2f} USDT | Margin: {margin_usdt:.2f} | "
        f"SL: {format_price(sl, pd)} ({sl_pct:.2f}%) | "
        f"TP1: {format_price(float(tp1), pd)} ({t1:.2f}%) | "
        f"TP2: {format_price(float(tp2), pd)} ({t2:.2f}%) | "
        f"TP3: {t3_s}{t3_pct} | Risk: {r:.2f} USDT"
    )


def _size_usdt_display(size_usdt: float) -> str:
    v = float(size_usdt)
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.2f}"


def format_entry_filled_console_line(
    *,
    mode: str,
    symbol: str,
    direction: str,
    hedge_on: bool,
    leverage: int,
    size_usdt: float,
    entry: float,
    stop_loss: float,
    tp1: float,
    tp2: float,
    tp3: float,
    price_decimals: int = 2,
    status: str = "Entry Filled",
) -> str:
    """Console line for manual / live entry fills: ``[DEMO] | [TAOUSDT] | [SHORT] | ...``."""
    mode_u = str(mode).strip().upper()
    sym_u = str(symbol).strip().upper()
    dir_u = str(direction).strip().upper()
    pd = int(price_decimals)
    lev = max(1, int(leverage))
    hedge_s = "ON" if hedge_on else "OFF"
    size_s = _size_usdt_display(size_usdt)
    tp3_s = format_tp3_display(tp3=float(tp3), price_decimals=pd)
    return (
        f"[{mode_u}] | [{sym_u}] | [{dir_u}] | Hedge={hedge_s} | Lev={lev}x | "
        f"Size={size_s} USDT | Entry={format_price(float(entry), pd)} | "
        f"SL={format_price(float(stop_loss), pd)} | "
        f"TP1={format_price(float(tp1), pd)}| TP2={format_price(float(tp2), pd)} | "
        f"TP3={tp3_s} | {status}"
    )


def format_open_console_line(
    *,
    symbol: str,
    direction: str,
    entry: float,
    size: float,
    stop_loss: float,
    tp1: float,
    tp2: float,
    tp3: float,
    allocated_capital: float,
    risk_usdt: float,
    setup_type: str,
    setup_grade: str,
    price_decimals: int = 2,
) -> str:
    _ = setup_type
    _ = setup_grade
    sym = symbol.replace("USDT", "").strip().upper()
    pd = int(price_decimals)
    tp3_s = format_tp3_display(tp3=float(tp3), price_decimals=pd)
    return (
        f"[OPEN] {sym} | dir={direction.upper()} | entry={format_price(float(entry), pd)} | size={float(size):.2f} | "
        f"SL={format_price(float(stop_loss), pd)} | TP1={format_price(float(tp1), pd)} TP2={format_price(float(tp2), pd)} TP3={tp3_s} | "
        f"alloc={float(allocated_capital):.2f} | risk={float(risk_usdt):.2f} USDT"
    )


def _format_duration_minutes_display(duration_minutes_val: str | float) -> str:
    if duration_minutes_val == "":
        return "n/a"
    try:
        return f"{float(duration_minutes_val):.1f}"
    except (TypeError, ValueError):
        return str(duration_minutes_val)


def format_fill_pnl_usdt(
    internal_pnl: float,
    exchange_pnl_usdt: float | None = None,
) -> str:
    """Single-fill PnL line for TP/SL alerts; appends exchange realized PnL when known."""
    pnl_v = round_usd(float(internal_pnl), 2)
    line = f"PNL: {pnl_v:+.2f} USDT"
    if exchange_pnl_usdt is not None:
        ex_v = round_usd(float(exchange_pnl_usdt), 2)
        line += f" | Exchange PNL: {ex_v:+.2f} USDT"
    return line


def format_close_console_line(
    *,
    symbol: str,
    size_usdt: float,
    leverage: int,
    entry: float,
    exit_px: float,
    duration_minutes_val: str | float,
    final_pnl: float,
    exchange_pnl_usdt: float | None = None,
    price_decimals: int = 2,
) -> str:
    sym_u = str(symbol).strip().upper()
    lev = max(1, int(leverage))
    margin_usdt = float(size_usdt) / float(lev)
    pd = int(price_decimals)
    entry_r = format_price(float(entry), pd)
    exit_r = format_price(float(exit_px), pd)
    pnl_r = round_usd(float(final_pnl), 2)
    pnl_s = f"{pnl_r:+.2f}"
    dur_s = _format_duration_minutes_display(duration_minutes_val)
    line = (
        f"[CLOSE] {sym_u} | Size: {float(size_usdt):.2f} USDT | Margin: {margin_usdt:.2f} USDT | "
        f"Entry: {entry_r} | Exit: {exit_r} | "
        f"Duration: {dur_s} min | PNL: {pnl_s} USDT"
    )
    if exchange_pnl_usdt is not None:
        ex_r = round_usd(float(exchange_pnl_usdt), 2)
        line += f" | Exchange PNL: {ex_r:+.2f} USDT"
    return line


def roi_drop_percent_from_exit_metrics(
    *,
    reason: str,
    metrics: dict | None = None,
    current_roi: float | None = None,
    max_roi_seen: float | None = None,
) -> float | None:
    """
    ROI points lost since peak for MFE exits: ``max_roi_seen - current_roi`` (leveraged ROI %).

    Example: peak 10.0%, current 4.0% → returns 6.0 (logged as ``ROI Drop Percent: 6.00%``).

    Exit logic still uses normalized giveback ``(peak-current)/peak`` vs threshold.
    """
    if str(reason).strip() != "mfe_drawdown_exceeded":
        return None
    if max_roi_seen is None or current_roi is None:
        return None
    try:
        peak = float(max_roi_seen)
        cur = float(current_roi)
    except (TypeError, ValueError):
        return None
    return max(0.0, peak - cur)


def format_exit_decision_close_line(
    symbol: str,
    reason: str,
    *,
    metrics: dict | None = None,
    current_roi: float | None = None,
    max_roi_seen: float | None = None,
) -> str:
    """``[EXIT DECISION]`` line for time-exit closes; adds ROI drop % for MFE giveback."""
    sym = str(symbol).strip().upper()
    r = str(reason).strip()
    line = f"[EXIT DECISION] {sym} | Action: CLOSE | Reason: {r}"
    drop = roi_drop_percent_from_exit_metrics(
        reason=r,
        metrics=metrics,
        current_roi=current_roi,
        max_roi_seen=max_roi_seen,
    )
    if drop is not None:
        line += f" | ROI Drop Percent: {drop:.2f}%"
    return line


def format_time_exit_reason_with_thresholds(
    reason: str,
    *,
    exit_manager: object,
    metrics: dict | None = None,
) -> str:
    """Human-readable TIME EXIT reason plus the key threshold that triggered it."""
    r = str(reason).strip() or "TIME EXIT"
    m = metrics or {}
    if r == "mfe_drawdown_exceeded":
        strong = bool(m.get("strong_trend", False))
        threshold = (
            float(getattr(exit_manager, "mfe_drawdown_threshold_strong_trend", 0.0))
            if strong
            else float(getattr(exit_manager, "mfe_drawdown_threshold", 0.0))
        )
        return (
            f"{r} | peak ROI >= "
            f"{float(getattr(exit_manager, 'min_roi_mfe_drawdown_apply', 0.0)):.2f}% and "
            f"ROI giveback >= {threshold * 100.0:.2f}%"
        )
    if r == "early_exit":
        signals = m.get("early_exit_signals", [])
        if signals:
            labels = {
                "breakout_failure": "Breakout Failure",
                "structure_break": "Structure Break",
                "strong_rejection": "Strong Rejection",
            }
            readable = [labels.get(s, s.replace("_", " ").title()) for s in signals]
            return f"{', '.join(readable)}"
        return "Early Exit"
    return r


def format_post_tp2_exchange_sl_placed_line(
    *,
    symbol: str,
    order_id: int | None,
    stop_price: float,
    size_usdt: float,
    price_decimals: int = 2,
) -> str:
    """Daily log / Telegram when a post-TP2 conditional stop is placed on the exchange."""
    sym_u = str(symbol).strip().upper()
    px_s = format_price(float(stop_price), int(price_decimals))
    oid = order_id if order_id is not None else "?"
    return (
        f"[SL MOVE] {sym_u} | Placed Conditional Stop Loss orderId={oid} "
        f"Price={px_s} Size USDT: {float(size_usdt):.2f}"
    )


def format_risk_flow_line(symbol: str, risk_breakdown: dict[str, float] | dict[str, int]) -> str:
    sym_u = str(symbol).strip().upper()
    return (
        f"[RISK FLOW] {sym_u} | "
        f"Base={float(risk_breakdown.get('base', 0.0)):.4f} | "
        f"Signal={float(risk_breakdown.get('signal', 0.0)):.4f} | "
        f"Planned={float(risk_breakdown.get('planned', 0.0)):.4f} | "
        f"Final={float(risk_breakdown.get('final', 0.0)):.4f}"
    )
