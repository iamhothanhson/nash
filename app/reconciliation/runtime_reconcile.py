"""Reconcile ``runtime_positions.json`` with exchange ``positionRisk`` snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.config import settings
from coins.loader import max_opened_positions_for, price_tick_size
from common.rounding import round_price
from execution.execution_engine import ExecutionEngine
from monitoring.logger import log
from position_management.staged import ManagedPosition
from reconciliation.close_attribution import finalize_exchange_flat_close

from config.constants import BREAKOUT, PULLBACK, TREND_FOLLOWING, TREND


@dataclass
class ReconcileStats:
    pruned: int = 0
    created: int = 0
    updated: int = 0
    pruned_symbols: list[str] = field(default_factory=list)
    created_symbols: list[str] = field(default_factory=list)
    updated_symbols: list[str] = field(default_factory=list)
    changed: bool = False
    skipped_symbols: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "pruned": self.pruned,
            "created": self.created,
            "updated": self.updated,
            "pruned_symbols": list(self.pruned_symbols),
            "created_symbols": list(self.created_symbols),
            "updated_symbols": list(self.updated_symbols),
            "changed": self.changed,
            "skipped": bool(self.skipped_symbols),
        }


def _local_open_rows(positions: list[ManagedPosition], sym: str) -> list[ManagedPosition]:
    return [p for p in positions if p.symbol == sym and not p.closed and float(p.qty_open) > 0]


def _is_breakout_pullback_pair(rows: list[ManagedPosition], *, direction: str) -> bool:
    if len(rows) != 2:
        return False
    setups: set[str] = set()
    for p in rows:
        if str(p.direction).upper() != direction:
            return False
        family = str(getattr(p, "strategy_family", "")).strip().upper()
        setup = str(getattr(p, "setup_type", "")).strip().upper()
        if family not in (TREND_FOLLOWING, TREND) or setup not in (BREAKOUT, PULLBACK):
            return False
        setups.add(setup)
    return setups == {BREAKOUT, PULLBACK}


def _remove_locals(
    positions: list[ManagedPosition],
    rows: list[ManagedPosition],
    *,
    sym: str,
    stats: ReconcileStats,
) -> None:
    for p in list(rows):
        if p in positions:
            positions.remove(p)
    if rows:
        stats.pruned += len(rows)
        if sym not in stats.pruned_symbols:
            stats.pruned_symbols.append(sym)
        stats.changed = True


def _handle_exchange_flat(
    engine: ExecutionEngine,
    positions: list[ManagedPosition],
    sym: str,
    local: list[ManagedPosition],
    stats: ReconcileStats,
) -> None:
    if not local:
        return
    for p in list(local):
        if not bool(p.close_journal_logged):
            finalize_exchange_flat_close(engine, p, positions=positions)
        else:
            p.qty_open = 0.0
            p.closed = True
    if len(local) > 1:
        log(f"[RECONCILE FLAT] {sym} | closed {len(local)} local OPEN row(s)")
    _remove_locals(positions, local, sym=sym, stats=stats)


def _adopt_from_exchange(
    positions: list[ManagedPosition],
    sym: str,
    direction: str,
    qty: float,
    entry: float,
    stats: ReconcileStats,
    make_reconciled_position: Callable[[str, str, float, float], ManagedPosition],
) -> None:
    positions.append(make_reconciled_position(sym, direction, qty, entry))
    stats.created += 1
    if sym not in stats.created_symbols:
        stats.created_symbols.append(sym)
    stats.changed = True


def _sync_local_to_exchange(
    keep: ManagedPosition,
    *,
    sym: str,
    ex_dir: str,
    ex_qty: float,
    ex_entry: float,
    stats: ReconcileStats,
) -> None:
    row_changed = False
    parts: list[str] = []
    if str(keep.direction).upper() != ex_dir:
        old = str(keep.direction).upper()
        keep.direction = ex_dir
        row_changed = True
        parts.append(f"side={old}->{ex_dir}")
    if abs(float(keep.qty_open) - ex_qty) > max(1e-8, 1e-6 * max(ex_qty, 1e-12)):
        old_q = float(keep.qty_open)
        old_t = float(keep.qty_total)
        keep.qty_open = ex_qty
        keep.qty_total = max(float(keep.qty_total), ex_qty)
        row_changed = True
        parts.append(f"qty_open={old_q:.8f}->{float(keep.qty_open):.8f}")
        if abs(float(keep.qty_total) - old_t) > 1e-12:
            parts.append(f"qty_total={old_t:.8f}->{float(keep.qty_total):.8f}")
    tick = price_tick_size(sym)
    ex_entry_r = round_price(ex_entry, tick) if ex_entry > 0.0 else 0.0
    local_entry_r = round_price(float(keep.entry), tick)
    if ex_entry_r > 0.0 and abs(local_entry_r - ex_entry_r) > tick * 0.5:
        old_e = float(keep.entry)
        keep.entry = ex_entry_r
        row_changed = True
        parts.append(f"entry={old_e:.4f}->{float(keep.entry):.4f}")
    if not row_changed:
        return
    stats.updated += 1
    if sym not in stats.updated_symbols:
        stats.updated_symbols.append(sym)
    stats.changed = True
    detail = " | " + " ; ".join(parts) if parts else ""
    log(
        f"[RECONCILE UPDATE] {sym} | ex_side={ex_dir} ex_amt={ex_qty:.8f} "
        f"ex_entry={ex_entry:.4f}{detail}"
    )


def _handle_exchange_open(
    engine: ExecutionEngine,
    positions: list[ManagedPosition],
    sym: str,
    *,
    ex_dir: str,
    ex_qty: float,
    ex_entry: float,
    stats: ReconcileStats,
    make_reconciled_position: Callable[[str, str, float, float], ManagedPosition],
) -> None:
    local = _local_open_rows(positions, sym)
    if not local:
        _adopt_from_exchange(positions, sym, ex_dir, ex_qty, ex_entry, stats, make_reconciled_position)
        return
    if not any(str(p.direction).upper() == ex_dir for p in local):
        _remove_locals(positions, local, sym=sym, stats=stats)
        _adopt_from_exchange(positions, sym, ex_dir, ex_qty, ex_entry, stats, make_reconciled_position)
        log(
            f"[RECONCILE REPLACE] {sym} | side mismatch local->exchange | "
            f"local_rows={len(local)} exchange_side={ex_dir} exchange_amt={ex_qty:.8f} "
            f"exchange_entry={ex_entry:.4f}"
        )
        return
    same_dir = [p for p in local if str(p.direction).upper() == ex_dir]
    if (
        max_opened_positions_for(sym) >= 2
        and _is_breakout_pullback_pair(same_dir, direction=ex_dir)
    ):
        return
    keep = next((p for p in same_dir), local[0])
    dupes = [p for p in local if p is not keep]
    if dupes:
        _remove_locals(positions, dupes, sym=sym, stats=stats)
    _sync_local_to_exchange(
        keep,
        sym=sym,
        ex_dir=ex_dir,
        ex_qty=ex_qty,
        ex_entry=ex_entry,
        stats=stats,
    )


def reconcile_all(
    engine: ExecutionEngine,
    *,
    load_positions: Callable[[], list[ManagedPosition]],
    save_positions: Callable[..., None],
    make_reconciled_position: Callable[[str, str, float, float], ManagedPosition],
) -> dict[str, object]:
    """
    Exchange = source of truth; runtime JSON = cache. At most one OPEN row per symbol.
    """
    stats = ReconcileStats()
    if settings.MODE not in ("live", "demo"):
        return stats.as_dict()
    client = getattr(engine, "_client", None)
    if client is None:
        return stats.as_dict()

    if hasattr(client, "sync_server_time"):
        try:
            client.sync_server_time(force=False)
        except Exception as exc:
            log(f"[RECONCILE] time sync before reconcile failed | {exc}")

    debug_events = bool(getattr(settings, "POSITION_EVENT_DEBUG", False))
    positions = load_positions()
    tol = 1e-10
    symbols = sorted({s.strip().upper() for s in settings.SYMBOLS})

    for sym in symbols:
        try:
            snap = client.get_position_risk_snapshot(sym)
        except Exception as exc:
            log(f"[RECONCILE] skipped {sym} | failed snapshot | {exc}")
            stats.skipped_symbols.append(sym)
            continue

        amt = float(snap.get("position_amt", 0.0))
        ex_entry = float(snap.get("entry_price", 0.0))
        local = _local_open_rows(positions, sym)
        if debug_events:
            ex_side = "NONE" if abs(amt) < tol else ("LONG" if amt > 0 else "SHORT")
            local_side = str(local[0].direction).upper() if local else "NONE"
            log(
                f"[RECONCILE STATE] {sym} | exchange={ex_side} amt={abs(amt):.8f} "
                f"entry={ex_entry:.4f} | local={local_side} open_rows={len(local)}"
            )

        if abs(amt) < tol:
            _handle_exchange_flat(engine, positions, sym, local, stats)
            continue

        ex_dir = "LONG" if amt > 0 else "SHORT"
        _handle_exchange_open(
            engine,
            positions,
            sym,
            ex_dir=ex_dir,
            ex_qty=abs(amt),
            ex_entry=ex_entry,
            stats=stats,
            make_reconciled_position=make_reconciled_position,
        )

    if stats.changed:
        save_positions(positions, merge_disk_open=False)
    return stats.as_dict()
