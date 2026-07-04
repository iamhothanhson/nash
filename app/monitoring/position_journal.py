from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from coins.loader import price_tick_size
from common.rounding import round_price

from config.constants import BREAKOUT, PULLBACK


def _round_journal_price(symbol: str, value: float) -> float:
    """Round a price for journal storage using the coin's ``price_rounding_decimal`` tick."""
    sym_u = str(symbol).strip().upper()
    tick = price_tick_size(sym_u) if sym_u else 0.01
    return round_price(float(value), tick)

log = logging.getLogger(__name__)

_CLEARED_PATHS: set[Path] = set()


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _reports_dir() -> Path:
    d = _repo_root() / "data" / "position_history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_time_iso(time_iso: str) -> datetime:
    raw = time_iso.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _month_key_from_iso(time_iso: str) -> str:
    """YYYY-MM (UTC), e.g. 2026-03."""
    return _parse_time_iso(time_iso).strftime("%Y-%m")


def _positions_history_journal_path_for_month(month: str) -> Path:
    """
    ``YYYY-MM`` -> ``data/position_history/MM-YYYY-positions-history.json``.

    If the new file is missing but legacy ``open-positions-YYYY-MM.json`` exists, rename it once.
    """
    root = _reports_dir()
    segs = month.strip().split("-")
    if len(segs) == 2 and len(segs[0]) == 4 and segs[0].isdigit() and len(segs[1]) == 2 and segs[1].isdigit():
        yyyy, mm = segs[0], segs[1]
    else:
        yyyy, mm = month, "01"
    new_path = root / f"{mm}-{yyyy}-positions-history.json"
    legacy = root / f"open-positions-{month}.json"
    if not new_path.exists() and legacy.exists():
        try:
            legacy.rename(new_path)
        except OSError:
            pass
    return new_path


def _positions_history_display_dt(time_iso: str) -> str:
    """UTC instant -> ``MMM-dd-yyyy HH:mm:ss`` (e.g. ``May-12-2026 19:36:17``)."""
    dt = _parse_time_iso(time_iso)
    return dt.strftime("%b-%d-%Y %H:%M:%S")


_MISSING_OPENED_CLOSED = object()

_JOURNAL_ROW_KEY_ORDER: tuple[str, ...] = (
    "status",
    "symbol",
    "side",
    "strategy_setup",
    "size_usdt",
    "margin_usdt",
    "entry",
    "stop_loss",
    "take_profit",
    "pnl_usdt",
    "exchange_pnl_usdt",
    "balance_usdt",
    "closed_reason",
    "opened",
    "closed",
)


def _journal_row_key_ordered(row: dict[str, Any]) -> dict[str, Any]:
    """Stable key order; ``closed_reason`` sits directly under ``balance_usdt``, before ``opened`` / ``closed``."""
    out: dict[str, Any] = {}
    for k in _JOURNAL_ROW_KEY_ORDER:
        if k in row:
            out[k] = row[k]
    for k, v in row.items():
        if k not in out:
            out[k] = v
    return out


def journal_strategy_setup_value(
    *,
    strategy_setup: str | None = None,
    strategy_family: str | None = None,
    setup_type: str | None = None,
) -> str:
    """
    Canonical ``strategy_setup`` for the positions history journal (stored directly under ``side``).

    Trend: ``trend_following_breakout`` or ``trend_following_pullback`` from ``setup_type``.
    Liquidity (default): ``liquidity_sweep_reversal``.
    """
    if strategy_setup and str(strategy_setup).strip():
        return str(strategy_setup).strip()
    fam = str(strategy_family or "liquidity").strip().upper()
    st = str(setup_type or "unknown").strip().upper()
    if fam in ("trend_following", "trend"):
        if st == BREAKOUT:
            return "trend_following_breakout"
        if st == PULLBACK:
            return "trend_following_pullback"
        if st not in ("", "unknown"):
            return f"trend_following_{st}"
        return "trend_following_unknown"
    return "liquidity_sweep_reversal"


def infer_journal_closed_reason(tags_upper: set[str] | None) -> str:
    """
    Pick a single journal ``closed_reason`` label from exit fill tags (same candle batch, excluding ``CLOSE``).
    """
    if not tags_upper:
        return "UNKNOWN"
    tu = {str(x).upper().strip() for x in tags_upper}
    tu.discard("CLOSE")
    for label in ("HARD STOP", "TIME EXIT", "SL HIT", "TP3 HIT", "TP2 HIT", "TP1 HIT"):
        if label in tu:
            return label
    if tu:
        return next(iter(sorted(tu)))
    return "UNKNOWN"


def _legacy_journal_ts_to_display(ts: Any, month: str) -> str | None:
    """
    Legacy ``timestamp`` field ``DD-HH:mm:ss`` plus internal ``YYYY-MM`` month key -> display string.
    Used to backfill ``opened`` when merging a close into rows written before ``opened`` existed.
    """
    if not isinstance(ts, str):
        return None
    segs = month.strip().split("-")
    if len(segs) != 2 or len(segs[0]) != 4 or not segs[0].isdigit() or len(segs[1]) != 2 or not segs[1].isdigit():
        return None
    yyyy_s, mm_s = segs[0], segs[1]
    parts = ts.split("-", 1)
    if len(parts) != 2:
        return None
    day_s, clock = parts[0], parts[1]
    try:
        year, month_i, day = int(yyyy_s), int(mm_s), int(day_s)
        toks = clock.split(":")
        if len(toks) != 3:
            return None
        hh, mi, ss = int(toks[0]), int(toks[1]), int(toks[2])
        dt = datetime(year, month_i, day, hh, mi, ss, tzinfo=timezone.utc)
    except (ValueError, OSError):
        return None
    return dt.strftime("%b-%d-%Y %H:%M:%S")


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    """Load JSON array file, or legacy one-object-per-line."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    try:
        if raw.startswith("["):
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        out: list[dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out
    except (json.JSONDecodeError, TypeError):
        return []


def _save_json_array(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(items, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _append_json_journal_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    overwrite_enabled = os.getenv("JOURNAL_OVERWRITE", "").strip().lower() == "true"
    if overwrite_enabled and path not in _CLEARED_PATHS:
        if path.exists():
            path.unlink()
        _CLEARED_PATHS.add(path)
    items = _load_json_array(path)
    items.append(record)
    _save_json_array(path, items)


def _tp_price_distance_pct(entry: float, tp_price: float) -> float:
    """Distance from entry to TP **price**, in **percent of entry** (e.g. 3.0 means 3%, not 0.03)."""
    e = float(entry)
    if e <= 0.0:
        return 0.0
    return abs(float(tp_price) - e) / e * 100.0


def _partial_close_pct_triplet(fr: list[float] | None) -> tuple[float, float, float]:
    """Coin ``partial_close`` fractions (e.g. 0.5, 0.3, 0.2) -> TP partial-close percents (50, 30, 20)."""
    if not fr or len(fr) < 3:
        fr = [0.5, 0.3, 0.2]
    return (
        round(float(fr[0]) * 100.0, 2),
        round(float(fr[1]) * 100.0, 2),
        round(float(fr[2]) * 100.0, 2),
    )


def _set_journal_exchange_order_ids(
    row: dict[str, Any],
    *,
    sl_order_id: int | None = None,
    tp1_order_id: int | None = None,
    tp2_order_id: int | None = None,
    tp3_order_id: int | None = None,
) -> None:
    sl = row.get("stop_loss")
    if not isinstance(sl, dict):
        sl = {}
        row["stop_loss"] = sl
    if sl_order_id is not None:
        sl["sl_order_id"] = sl_order_id
    tps = row.get("take_profit")
    if not isinstance(tps, list):
        return
    order_keys = ("tp1_order_id", "tp2_order_id", "tp3_order_id")
    order_vals = (tp1_order_id, tp2_order_id, tp3_order_id)
    for i, oid in enumerate(order_vals):
        if oid is None:
            continue
        if i >= len(tps) or not isinstance(tps[i], dict):
            continue
        tps[i][order_keys[i]] = oid


def _merge_tp_hits_on_take_profit(row: dict[str, Any], *, tp1_hit: bool, tp2_hit: bool, tp3_hit: bool) -> None:
    """Set ``tp1_hit`` / ``tp2_hit`` / ``tp3_hit`` on the matching ``take_profit`` row (index 0..2)."""
    tps = row.get("take_profit")
    if not isinstance(tps, list):
        return
    keys = ("tp1_hit", "tp2_hit", "tp3_hit")
    vals = (bool(tp1_hit), bool(tp2_hit), bool(tp3_hit))
    for i, block in enumerate(tps):
        if i >= 3 or not isinstance(block, dict):
            continue
        block[keys[i]] = vals[i]


def _set_journal_stop_loss_risk_usdt(target: dict[str, Any], risk_r: float) -> None:
    """Write ``risk_usdt`` under ``stop_loss`` and remove legacy top-level ``risk_usdt``."""
    sl = target.get("stop_loss")
    if not isinstance(sl, dict):
        sl = {}
        target["stop_loss"] = sl
    sl["risk_usdt"] = risk_r
    target.pop("risk_usdt", None)


def log_position_open(
    *,
    time_iso: str,
    symbol: str,
    direction: str,
    entry: float,
    stop_loss: float,
    tp1: float,
    tp2: float,
    tp3: float,
    size_usdt: float,
    leverage: int,
    risk_usdt: float,
    partial_close: list[float] | None = None,
    strategy_setup: str | None = None,
    strategy_family: str | None = None,
    setup_type: str | None = None,
    sl_order_id: int | None = None,
    tp1_order_id: int | None = None,
    tp2_order_id: int | None = None,
    tp3_order_id: int | None = None,
) -> None:
    """Append one ``status: Open`` row to ``data/position_history/MM-YYYY-positions-history.json`` (JSON array).

    ``take_profit`` lists three TP rows. Each row includes ``tp{N}_partial_close`` (percent of position
    closed at that tier), ``tp{N}_hit`` (``false`` until updated on close), ``price``, and ``percent``.
    ``strategy_setup`` (under ``side``) is ``liquidity_sweep_reversal`` or ``trend_following_*`` from
    ``journal_strategy_setup_value``.
    """
    e = float(entry)
    sl = float(stop_loss)
    lev = max(1, int(leverage))
    margin_usdt = float(size_usdt) / float(lev)
    sl_pct = (-abs(sl - e) / e * 100.0) if e > 0.0 else 0.0
    t1 = _tp_price_distance_pct(e, float(tp1))
    t2 = _tp_price_distance_pct(e, float(tp2))
    t3 = _tp_price_distance_pct(e, float(tp3))
    pc1, pc2, pc3 = _partial_close_pct_triplet(partial_close)
    month = _month_key_from_iso(time_iso)
    path = _positions_history_journal_path_for_month(month)
    opened_disp = _positions_history_display_dt(time_iso)
    ss = journal_strategy_setup_value(
        strategy_setup=strategy_setup,
        strategy_family=strategy_family,
        setup_type=setup_type,
    )
    sym_u = str(symbol).strip().upper()
    record = {
        "status": "Open",
        "symbol": sym_u,
        "side": str(direction).strip().upper(),
        "strategy_setup": ss,
        "size_usdt": round(float(size_usdt), 2),
        "margin_usdt": round(margin_usdt, 2),
        "entry": _round_journal_price(sym_u, e),
        "stop_loss": {
            "price": _round_journal_price(sym_u, sl),
            "percent": round(sl_pct, 2),
            "risk_usdt": round(float(risk_usdt), 4),
            "sl_order_id": sl_order_id,
            "sl_hit": False,
        },
        "take_profit": [
            {
                "tp1_partial_close": pc1,
                "tp1_hit": False,
                "price": _round_journal_price(sym_u, float(tp1)),
                "percent": round(t1, 2),
                "tp1_order_id": tp1_order_id,
            },
            {
                "tp2_partial_close": pc2,
                "tp2_hit": False,
                "price": _round_journal_price(sym_u, float(tp2)),
                "percent": round(t2, 2),
                "tp2_order_id": tp2_order_id,
            },
            {
                "tp3_partial_close": pc3,
                "tp3_hit": False,
                "price": _round_journal_price(sym_u, float(tp3)),
                "percent": round(t3, 2),
                "tp3_order_id": tp3_order_id,
            },
        ],
        "pnl_usdt": None,
        "exchange_pnl_usdt": None,
        "balance_usdt": None,
        "closed_reason": None,
        "opened": opened_disp,
        "closed": None,
    }
    _append_json_journal_record(path, _journal_row_key_ordered(record))


def duration_minutes(open_time_iso: str, close_time_iso: str) -> str | float:
    if not (open_time_iso and close_time_iso):
        return ""
    try:
        a = datetime.fromisoformat(open_time_iso.strip().replace("Z", "+00:00"))
        b = datetime.fromisoformat(close_time_iso.strip().replace("Z", "+00:00"))
        if a.tzinfo is None:
            a = a.replace(tzinfo=timezone.utc)
        if b.tzinfo is None:
            b = b.replace(tzinfo=timezone.utc)
        return round((b - a).total_seconds() / 60.0, 2)
    except Exception:
        return ""


def _journal_row_is_open_for_close_merge(row: dict[str, Any]) -> bool:
    """True if this journal row can receive a close merge (legacy ``event`` or new ``status``)."""
    st = str(row.get("status", "")).strip()
    if st == "Closed":
        return False
    if st == "Open":
        return True
    ev = str(row.get("event", "")).strip().upper()
    if ev == "CLOSE":
        return False
    return ev == "OPEN"


def _opened_time_matches(row: dict[str, Any], open_time_iso: str) -> bool:
    """True when journal row ``opened`` matches the position open instant."""
    if not open_time_iso or not str(open_time_iso).strip():
        return False
    opened_disp = str(row.get("opened", "")).strip()
    if not opened_disp:
        return False
    return opened_disp == _positions_history_display_dt(open_time_iso)


def _find_open_journal_row_index(
    items: list[dict[str, Any]],
    *,
    symbol: str,
    direction: str,
    open_time_iso: str,
) -> int | None:
    """Latest matching open row by symbol, side, and opening time."""
    sym_u = str(symbol).strip().upper()
    side_u = str(direction).strip().upper()
    if not open_time_iso or not str(open_time_iso).strip():
        return None
    for i in range(len(items) - 1, -1, -1):
        o = items[i]
        if not isinstance(o, dict):
            continue
        if not _journal_row_is_open_for_close_merge(o):
            continue
        if o.get("balance_usdt") is not None:
            continue
        if str(o.get("symbol", "")).upper() != sym_u:
            continue
        if str(o.get("side", "")).upper() != side_u:
            continue
        if not _opened_time_matches(o, open_time_iso):
            continue
        return i
    return None


def _tp_hit_from_row(row: dict[str, Any], index: int) -> bool:
    tps = row.get("take_profit")
    if not isinstance(tps, list) or index >= len(tps):
        return False
    block = tps[index]
    if not isinstance(block, dict):
        return False
    keys = ("tp1_hit", "tp2_hit", "tp3_hit")
    return bool(block.get(keys[index], False))


def update_open_position_journal(
    *,
    time_iso: str,
    symbol: str,
    direction: str,
    open_time_iso: str,
    entry: float,
    qty_total: float,
    leverage: int,
    tp1_hit: bool | None = None,
    tp2_hit: bool | None = None,
    tp3_hit: bool | None = None,
    stop_loss_price: float | None = None,
    risk_usdt: float | None = None,
    exchange_order_ids: dict[str, int | None] | None = None,
) -> bool:
    """Patch the latest matching ``status: Open`` row (TP hits, breakeven SL) while still open."""
    month = _month_key_from_iso(time_iso)
    path = _positions_history_journal_path_for_month(month)
    items = _load_json_array(path)
    idx = _find_open_journal_row_index(
        items,
        symbol=symbol,
        direction=direction,
        open_time_iso=open_time_iso,
    )
    if idx is None:
        return False
    o = items[idx]
    changed = False
    if tp1_hit is not None or tp2_hit is not None or tp3_hit is not None:
        _merge_tp_hits_on_take_profit(
            o,
            tp1_hit=bool(tp1_hit) if tp1_hit is not None else _tp_hit_from_row(o, 0),
            tp2_hit=bool(tp2_hit) if tp2_hit is not None else _tp_hit_from_row(o, 1),
            tp3_hit=bool(tp3_hit) if tp3_hit is not None else _tp_hit_from_row(o, 2),
        )
        changed = True
    if stop_loss_price is not None:
        sl = o.get("stop_loss")
        if not isinstance(sl, dict):
            sl = {}
            o["stop_loss"] = sl
        e = float(o.get("entry", entry))
        sl_px = float(stop_loss_price)
        sl["price"] = _round_journal_price(str(symbol).strip().upper(), sl_px)
        sl["percent"] = round((-abs(sl_px - e) / e * 100.0) if e > 0.0 else 0.0, 2)
        changed = True
    if risk_usdt is not None:
        _set_journal_stop_loss_risk_usdt(o, round(float(risk_usdt), 4))
        changed = True
    if isinstance(exchange_order_ids, dict):
        _set_journal_exchange_order_ids(
            o,
            sl_order_id=exchange_order_ids.get("sl_order_id"),
            tp1_order_id=exchange_order_ids.get("tp1_order_id"),
            tp2_order_id=exchange_order_ids.get("tp2_order_id"),
            tp3_order_id=exchange_order_ids.get("tp3_order_id"),
        )
        changed = True
    if not changed:
        return True
    items[idx] = _journal_row_key_ordered(o)
    items = [_journal_row_key_ordered(r) if isinstance(r, dict) else r for r in items]
    _save_json_array(path, items)
    return True


def log_position_closed(
    *,
    time_iso: str,
    symbol: str,
    direction: str,
    open_time_iso: str,
    entry: float,
    stop_loss: float,
    tp1: float,
    tp2: float,
    tp3: float,
    qty_total: float,
    leverage: int,
    risk_usdt: float,
    pnl_usdt: float,
    balance_usdt: float,
    exchange_pnl_usdt: float | None = None,
    partial_close: list[float] | None = None,
    tp1_hit: bool = False,
    tp2_hit: bool = False,
    tp3_hit: bool = False,
    closed_reason: str = "",
    strategy_setup: str | None = None,
    strategy_family: str | None = None,
    setup_type: str | None = None,
) -> None:
    """Merge close outcome into the matching ``status: Open`` row (symbol, side, opening time)."""
    e = float(entry)
    sl = float(stop_loss)
    lev = max(1, int(leverage))
    size_usdt = e * float(qty_total)
    margin_usdt = float(size_usdt) / float(lev)
    sym_u = str(symbol).strip().upper()
    side_u = str(direction).strip().upper()
    entry_r = _round_journal_price(sym_u, e)
    size_r = round(size_usdt, 2)
    margin_r = round(margin_usdt, 2)
    month = _month_key_from_iso(time_iso)
    open_path = _positions_history_journal_path_for_month(month)
    pnl_r = round(float(pnl_usdt), 2)
    bal_r = round(float(balance_usdt), 2)
    exch = (
        round(float(exchange_pnl_usdt), 4)
        if exchange_pnl_usdt is not None
        else None
    )
    risk_r = round(float(risk_usdt), 4)
    closed_disp = _positions_history_display_dt(time_iso)
    reason_s = str(closed_reason).strip() or "UNKNOWN"

    items = _load_json_array(open_path)
    open_idx = _find_open_journal_row_index(
        items,
        symbol=symbol,
        direction=direction,
        open_time_iso=open_time_iso,
    )
    if open_idx is None:
        return

    o = items[open_idx]
    if not o.get("opened"):
        fb = _legacy_journal_ts_to_display(o.get("timestamp"), month)
        if fb:
            o["opened"] = fb
    o["entry"] = entry_r
    o["size_usdt"] = size_r
    o["margin_usdt"] = margin_r
    _set_journal_stop_loss_risk_usdt(o, risk_r)
    sl_block = o.get("stop_loss")
    if not isinstance(sl_block, dict):
        sl_block = {}
        o["stop_loss"] = sl_block
    sl_block["price"] = _round_journal_price(sym_u, sl)
    sl_block["percent"] = round((-abs(sl - e) / e * 100.0) if e > 0.0 else 0.0, 2)
    sl_block["sl_hit"] = reason_s.strip().upper() == "SL HIT" or "SL HIT" in reason_s.upper()
    o["pnl_usdt"] = pnl_r
    o["exchange_pnl_usdt"] = exch
    o["balance_usdt"] = bal_r
    o["closed_reason"] = reason_s
    o["closed"] = closed_disp
    o["status"] = "Closed"
    o.pop("event", None)
    _merge_tp_hits_on_take_profit(o, tp1_hit=tp1_hit, tp2_hit=tp2_hit, tp3_hit=tp3_hit)
    if "strategy_setup" not in o:
        o["strategy_setup"] = journal_strategy_setup_value(
            strategy_setup=strategy_setup,
            strategy_family=strategy_family,
            setup_type=setup_type,
        )
    items[open_idx] = _journal_row_key_ordered(o)
    items = [_journal_row_key_ordered(r) if isinstance(r, dict) else r for r in items]
    _save_json_array(open_path, items)
