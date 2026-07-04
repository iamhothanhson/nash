"""
Single-day JSON snapshot: ``runtime_data/risk_limit_tracking.json``.

**Contract (live / demo, default path):** whenever this file is **created or replaced**
on disk (via ``_write_tracking``), the same row is mirrored into
``performance/mm-yyyy_statistics.json`` as a **day snapshot** (``SNAPSHOT_EXPORT_KEYS``).

Schema (written to disk; legacy ``total_pnl`` / ``current_balance`` rows are
migrated on read):

- ``date`` (UTC), ``starting_balance``, ``ending_balance``
- ``daily_pnl`` — cumulative realized PnL for the UTC day (replaces old ``total_pnl``)
- ``daily_pnl_percent`` — ``100 * daily_pnl / starting_balance`` when start > 0
- ``total_trade``, ``win``, ``loss``, ``open`` (still open at UTC day end), ``max_drawdown_percent``,
  ``peak_balance`` (intraday high of balance for drawdown), ``trading_stopped``

Stops new entries when:

- ``loss`` >= ``MAX_LOSSES_PER_DAY`` (if cap > 0), or
- ``total_trade`` >= ``MAX_TRADES_PER_DAY``, or
- ``daily_pnl`` <= ``-starting_balance * MAX_DAILY_LOSS`` (when ``MAX_DAILY_LOSS`` > 0), or
- ``daily_pnl_percent`` >= ``TARGET_DAILY_ROI`` (when ``TARGET_DAILY_ROI`` < 9999)

After each successful write to the risk tracking file, the same day’s metrics
(export keys only) are upserted into ``performance/mm-yyyy_statistics.json``
(one JSON per calendar month). Override directory with ``PERFORMANCE_DIR`` (or legacy ``PERFORMANCE_STAT_DIR``).

**Backtest:** when ``sim_date_iso`` is set, the risk file still updates each sim
day but **does not** write ``performance/`` on every bar (avoids mixing
simulated days into the same month file as live). Use ``backtest.py --daily-stat``
or a separate ``PERFORMANCE_DIR`` for simulated month snapshots.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import settings
from monitoring.logger import log as file_log

SNAPSHOT_EXPORT_KEYS: tuple[str, ...] = (
    "date",
    "starting_balance",
    "ending_balance",
    "daily_pnl",
    "daily_pnl_percent",
    "total_trade",
    "win",
    "loss",
    "open",
    "max_drawdown_percent",
    "peak_balance",
    "trading_stopped",
)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def tracking_path() -> Path:
    raw = os.getenv("RISK_LIMIT_TRACKING_PATH", "").strip()
    if raw:
        return Path(raw)
    return _project_root() / "runtime_data" / "risk_limit_tracking.json"


def performance_dir() -> Path:
    raw = os.getenv("PERFORMANCE_DIR", "").strip() or os.getenv("PERFORMANCE_STAT_DIR", "").strip()
    if raw:
        return Path(raw)
    return _project_root() / "performance"


def performance_stat_dir() -> Path:
    """Alias for :func:`performance_dir` (legacy name)."""
    return performance_dir()


def _utc_date_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _effective_date_iso(sim_date_iso: str | None) -> str:
    """Wall-clock UTC day for live/demo; optional ``YYYY-MM-DD`` for backtests."""
    if sim_date_iso is None:
        return _utc_date_iso()
    d = str(sim_date_iso).strip()[:10]
    return d if len(d) == 10 and d[4] == "-" and d[7] == "-" else _utc_date_iso()


def _round2(x: float) -> float:
    return round(float(x), 2)


def _coerce_legacy(raw: dict[str, Any]) -> dict[str, Any]:
    """Map pre-refactor keys into the current schema."""
    out = dict(raw)
    if "daily_pnl" not in out and "total_pnl" in out:
        out["daily_pnl"] = out["total_pnl"]
    if "ending_balance" not in out and "current_balance" in out:
        out["ending_balance"] = out["current_balance"]
    return out


def _max_daily_loss_cap_usdt(row: dict[str, Any]) -> float | None:
    """Dollar loss cap for the day; ``None`` when ``MAX_DAILY_LOSS`` is not positive."""
    frac = float(getattr(settings, "MAX_DAILY_LOSS", 0.0))
    if frac <= 0.0:
        return None
    eq = max(float(row.get("starting_balance", 0.0)), 1e-9)
    return float(eq) * float(frac)


def _daily_pnl_for_limits(row: dict[str, Any]) -> float:
    return float(row.get("daily_pnl", row.get("total_pnl", 0.0)))


def _breaches_max_daily_loss(row: dict[str, Any]) -> bool:
    cap = _max_daily_loss_cap_usdt(row)
    if cap is None:
        return False
    return _daily_pnl_for_limits(row) <= -float(cap)


def _target_daily_roi_reached(row: dict[str, Any]) -> bool:
    target = float(getattr(settings, "TARGET_DAILY_ROI", 10.0))
    pct = float(row.get("daily_pnl_percent", 0.0))
    return pct >= target


def _default_row(*, date: str, balance: float) -> dict[str, Any]:
    b = _round2(balance)
    return {
        "date": date,
        "starting_balance": b,
        "ending_balance": b,
        "daily_pnl": 0.0,
        "daily_pnl_percent": 0.0,
        "total_trade": 0,
        "win": 0,
        "loss": 0,
        "open": 0,
        "max_drawdown_percent": 0.0,
        "trading_stopped": False,
        "peak_balance": b,
    }


_TRACKING_WRITE_LOCK = threading.Lock()


def _read_row(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically; unique temp names avoid races on a shared ``*.tmp``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2)
    with _TRACKING_WRITE_LOCK:
        fd, tmp_name = tempfile.mkstemp(
            suffix=".tmp",
            prefix=f"{path.stem}.",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise


def _recompute_derived(row: dict[str, Any]) -> None:
    start = _round2(float(row.get("starting_balance", 0.0)))
    end = _round2(float(row.get("ending_balance", 0.0)))
    daily = _round2(float(row.get("daily_pnl", 0.0)))
    row["starting_balance"] = start
    row["ending_balance"] = end
    row["daily_pnl"] = daily
    if start > 1e-9:
        row["daily_pnl_percent"] = _round2(100.0 * daily / start)
    else:
        row["daily_pnl_percent"] = 0.0
    prev_peak = float(row.get("peak_balance", 0.0))
    if prev_peak <= 1e-9:
        prev_peak = max(start, end)
    peak = max(prev_peak, start, end)
    row["peak_balance"] = _round2(peak)
    peak = float(row["peak_balance"])
    if peak > 1e-9:
        dd_now = 100.0 * max(0.0, peak - end) / peak
    else:
        dd_now = 0.0
    prev_max_dd = float(row.get("max_drawdown_percent", 0.0))
    row["max_drawdown_percent"] = _round2(max(prev_max_dd, dd_now))


def _scrub_legacy_keys(row: dict[str, Any]) -> None:
    row.pop("total_pnl", None)
    row.pop("current_balance", None)


def _month_performance_path(date_iso: str) -> Path:
    d = str(date_iso).strip()[:10]
    parts = d.split("-")
    if len(parts) < 2:
        return performance_dir() / "00-0000_statistics.json"
    yyyy, mm = parts[0], parts[1]
    return performance_dir() / f"{mm}-{yyyy}_statistics.json"


def _load_month_stat_blob(path: Path) -> dict[str, Any]:
    """Parse existing month JSON, or treat missing/empty/corrupt files as a fresh month."""
    if not path.exists():
        return {}
    try:
        txt = path.read_text(encoding="utf-8").strip()
        if not txt:
            return {}
        raw = json.loads(txt)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def row_to_snapshot(row: dict[str, Any], *, open_count: int | None = None) -> dict[str, Any]:
    """Export one tracking row to ``SNAPSHOT_EXPORT_KEYS`` (same shape as EOD Telegram)."""
    data = _coerce_legacy(dict(row))
    _recompute_derived(data)
    if open_count is not None:
        data["open"] = max(0, int(open_count))
    snap: dict[str, Any] = {}
    for k in SNAPSHOT_EXPORT_KEYS:
        snap[k] = data[k]
    return snap


def read_today_snapshot(*, open_count: int | None = None) -> dict[str, Any] | None:
    """Current UTC day row from ``runtime_data/risk_limit_tracking.json`` as a performance snapshot."""
    try:
        row = _read_row(tracking_path())
        if row is None:
            return None
        today = _utc_date_iso()
        bal = float(row.get("ending_balance", row.get("starting_balance", 0.0)))
        row = _normalize_row(row, today=today, balance=bal)
        return row_to_snapshot(row, open_count=open_count)
    except Exception as exc:
        file_log(f"[RISK LIMIT TRACK WARN] read_today_snapshot | {exc}")
        return None


def notify_performance_snapshot_after_close(
    *,
    open_positions: int | None = None,
    sim_date_iso: str | None = None,
) -> None:
    """Telegram today's stats JSON after a full close (live/demo; respects ``DAILY_PERFORMANCE_TELEGRAM``).

    Call after the ``[CLOSE]`` alert so Telegram message order is: CLOSE first, then RUNTIME PERFORMANCE.
    """
    if sim_date_iso is not None:
        return
    if str(getattr(settings, "MODE", "")).strip().lower() not in set(settings.ALERTS_MODES):
        return
    if not bool(getattr(settings, "PERFORMANCE_SNAPSHOT_ON_CLOSE", True)):
        return
    snap = read_today_snapshot(open_count=open_positions)
    if not snap:
        return
    try:
        from monitoring.notifier import send_daily_performance_snapshot_alert
    except ImportError:  # pragma: no cover
        from app.monitoring.notifier import send_daily_performance_snapshot_alert

    send_daily_performance_snapshot_alert(snap, heading="RUNTIME PERFORMANCE")


def _month_day_entries_through(as_of_date: str) -> list[dict[str, Any]]:
    """Sorted day rows from the month file with ``date <= as_of_date`` (UTC)."""
    d = str(as_of_date).strip()[:10]
    if len(d) != 10:
        return []
    month_key = d[:7]
    path = _month_performance_path(d)
    raw = _load_month_stat_blob(path)
    days = raw.get("days")
    if not isinstance(days, list):
        return []
    out: list[dict[str, Any]] = []
    for ent in days:
        if not isinstance(ent, dict):
            continue
        ent_d = str(ent.get("date", "")).strip()[:10]
        if len(ent_d) != 10 or ent_d[:7] != month_key or ent_d > d:
            continue
        out.append(ent)
    out.sort(key=lambda x: str(x.get("date", "")))
    return out


def build_month_cumulative_snapshot(
    as_of_date: str,
    *,
    open_count: int | None = None,
) -> dict[str, Any] | None:
    """
    Month-to-date aggregate through ``as_of_date`` (inclusive), same keys as daily snapshots.

    ``daily_pnl`` / ``daily_pnl_percent`` are MTD (sum of daily PnL vs month-start balance).
    """
    d = str(as_of_date).strip()[:10]
    rows = _month_day_entries_through(d)
    if not rows:
        return None
    first = rows[0]
    last = rows[-1]
    start = _round2(float(first.get("starting_balance", 0.0)))
    end = _round2(float(last.get("ending_balance", start)))
    mtd_pnl = _round2(sum(_round2(float(r.get("daily_pnl", 0.0))) for r in rows))
    peak = _round2(max(float(r.get("peak_balance", r.get("ending_balance", 0.0))) for r in rows))
    max_dd = _round2(max(float(r.get("max_drawdown_percent", 0.0)) for r in rows))
    if open_count is not None:
        open_v = max(0, int(open_count))
    else:
        open_v = max(0, int(last.get("open", 0)))
    snap: dict[str, Any] = {
        "date": d,
        "starting_balance": start,
        "ending_balance": end,
        "daily_pnl": mtd_pnl,
        "daily_pnl_percent": _round2(100.0 * mtd_pnl / start) if start > 1e-9 else 0.0,
        "total_trade": int(sum(int(r.get("total_trade", 0)) for r in rows)),
        "win": int(sum(int(r.get("win", 0)) for r in rows)),
        "loss": int(sum(int(r.get("loss", 0)) for r in rows)),
        "open": open_v,
        "max_drawdown_percent": max_dd,
        "peak_balance": peak,
        "trading_stopped": bool(last.get("trading_stopped", False)),
    }
    return snap


def notify_monthly_cumulative_telegram(
    as_of_date: str,
    *,
    open_count: int | None = None,
    sim_date_iso: str | None = None,
) -> None:
    """Telegram MTD JSON at UTC day rollover (live/demo; ``MONTHLY PERFORMANCE`` heading)."""
    if sim_date_iso is not None:
        return
    if str(getattr(settings, "MODE", "")).strip().lower() not in set(settings.ALERTS_MODES):
        return
    if not bool(getattr(settings, "MONTHLY_CUMULATIVE_TELEGRAM", True)):
        return
    snap = build_month_cumulative_snapshot(as_of_date, open_count=open_count)
    if not snap:
        return
    try:
        from monitoring.notifier import send_daily_performance_snapshot_alert
    except ImportError:  # pragma: no cover
        from app.monitoring.notifier import send_daily_performance_snapshot_alert

    send_daily_performance_snapshot_alert(
        snap,
        heading="MONTHLY PERFORMANCE",
        respect_daily_telegram_setting=False,
    )


def read_day_snapshot_for_date(date_iso: str) -> dict[str, Any] | None:
    """
    Load one day's snapshot from ``performance/MM-YYYY_statistics.json`` if present.

    ``date_iso`` must be ``YYYY-MM-DD`` (UTC calendar day used in month files).
    """
    d = str(date_iso).strip()[:10]
    if len(d) != 10 or d[4] != "-" or d[7] != "-":
        return None
    path = _month_performance_path(d)
    raw = _load_month_stat_blob(path)
    days = raw.get("days")
    if not isinstance(days, list):
        return None
    for ent in days:
        if not isinstance(ent, dict):
            continue
        if str(ent.get("date", "")).strip()[:10] != d:
            continue
        snap: dict[str, Any] = {}
        for k in SNAPSHOT_EXPORT_KEYS:
            if k not in ent:
                if k == "open":
                    snap[k] = 0
                elif k == "peak_balance":
                    start = _round2(float(ent.get("starting_balance", 0.0)))
                    end = _round2(float(ent.get("ending_balance", 0.0)))
                    snap[k] = _round2(max(start, end))
                else:
                    return None
            else:
                snap[k] = ent[k]
        return snap
    return None


def upsert_performance_snapshot(snapshot: dict[str, Any]) -> None:
    """
    Upsert one day (``SNAPSHOT_EXPORT_KEYS``) into ``performance/mm-yyyy_statistics.json``.

    Used when the risk tracking file is written and when ``backtest.py`` is run with
    ``--daily-stat``.
    """
    try:
        snap: dict[str, Any] = {}
        for k in SNAPSHOT_EXPORT_KEYS:
            snap[k] = snapshot[k]
        snap["starting_balance"] = _round2(float(snap["starting_balance"]))
        snap["ending_balance"] = _round2(float(snap["ending_balance"]))
        snap["daily_pnl"] = _round2(float(snap["daily_pnl"]))
        snap["daily_pnl_percent"] = _round2(float(snap["daily_pnl_percent"]))
        snap["total_trade"] = int(snap["total_trade"])
        snap["win"] = int(snap["win"])
        snap["loss"] = int(snap["loss"])
        snap["open"] = max(0, int(snap["open"]))
        snap["max_drawdown_percent"] = _round2(float(snap["max_drawdown_percent"]))
        snap["peak_balance"] = _round2(float(snap["peak_balance"]))
        snap["trading_stopped"] = bool(snap["trading_stopped"])
        date_iso = str(snap["date"]).strip()[:10]
        snap["date"] = date_iso
        month_meta = date_iso[:7]
        path = _month_performance_path(date_iso)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = _load_month_stat_blob(path)
        days = raw.get("days")
        if not isinstance(days, list):
            days = []
        replaced = False
        for i, ent in enumerate(days):
            if isinstance(ent, dict) and str(ent.get("date", "")).strip()[:10] == date_iso:
                days[i] = snap
                replaced = True
                break
        if not replaced:
            days.append(snap)
        days.sort(key=lambda x: str(x.get("date", "")) if isinstance(x, dict) else "")
        raw["month"] = month_meta
        raw["days"] = days
        _atomic_write(path, raw)
    except KeyError as exc:
        file_log(f"[RISK LIMIT TRACK WARN] upsert_performance_snapshot missing key | {exc}")
    except Exception as exc:
        file_log(f"[RISK LIMIT TRACK WARN] upsert_performance_snapshot | {exc}")


def _sync_month_performance(row: dict[str, Any]) -> None:
    try:
        _recompute_derived(row)
        snap = {k: row.get(k, 0 if k == "open" else row[k]) for k in SNAPSHOT_EXPORT_KEYS}
        upsert_performance_snapshot(snap)
    except Exception as exc:
        file_log(f"[RISK LIMIT TRACK WARN] _sync_month_performance | {exc}")


def _write_tracking(path: Path, row: dict[str, Any], *, sync_month: bool = True) -> None:
    """
    Persist ``path`` and optionally mirror the row into ``performance/`` (``*_statistics.json``).

    All live/demo updates go through here with ``sync_month=True`` so each disk
    write of the risk JSON is followed by an upsert of that UTC day's snapshot.
    """
    data = dict(row)
    _recompute_derived(data)
    _scrub_legacy_keys(data)
    _atomic_write(path, data)
    if sync_month:
        _sync_month_performance(data)


def _normalize_row(raw: dict[str, Any], *, today: str, balance: float) -> dict[str, Any]:
    """Ensure keys exist and types are sane; rollover if date != today."""
    if str(raw.get("date", "")).strip() != today:
        return _default_row(date=today, balance=balance)
    out = _coerce_legacy(dict(raw))
    out["date"] = today
    bal = _round2(float(balance))
    out["starting_balance"] = _round2(float(out.get("starting_balance", bal)))
    out["ending_balance"] = _round2(float(out.get("ending_balance", out.get("current_balance", bal))))
    out["daily_pnl"] = _round2(float(out.get("daily_pnl", out.get("total_pnl", 0.0))))
    out["daily_pnl_percent"] = _round2(float(out.get("daily_pnl_percent", 0.0)))
    out["total_trade"] = int(out.get("total_trade", 0))
    out["win"] = int(out.get("win", 0))
    out["loss"] = int(out.get("loss", 0))
    out["open"] = max(0, int(out.get("open", 0)))
    out["max_drawdown_percent"] = _round2(float(out.get("max_drawdown_percent", 0.0)))
    out["trading_stopped"] = bool(out.get("trading_stopped", False))
    pb = float(out.get("peak_balance", 0.0))
    if pb <= 1e-9:
        pb = max(float(out["starting_balance"]), float(out["ending_balance"]))
    out["peak_balance"] = _round2(pb)
    _recompute_derived(out)
    return out


def ensure_today(
    *,
    balance_usdt: float,
    sim_date_iso: str | None = None,
    open_at_eod: int | None = None,
) -> dict[str, Any]:
    """
    Load or create the row for the effective calendar day; reset when the day changes.

    ``sim_date_iso`` (``YYYY-MM-DD``): use simulated UTC date (backtest). When set, the
    risk JSON is still written to ``tracking_path()`` but ``performance/`` is not
    updated on each write (use backtest ``--daily-stat`` for month files).

    ``open_at_eod``: when the UTC day rolls over, set the completed day's ``open`` field
    to this count (positions still open at the prior day's end) before syncing to
    ``performance/``.
    """
    path = tracking_path()
    today = _effective_date_iso(sim_date_iso)
    bal = float(balance_usdt)
    sync_m = sim_date_iso is None
    existing = _read_row(path)
    if existing is None:
        row = _default_row(date=today, balance=bal)
        _write_tracking(path, row, sync_month=sync_m)
        return row
    existing_date = str(existing.get("date", "")).strip()
    if existing_date != today:
        if sync_m:
            try:
                prev_day = dict(_coerce_legacy(dict(existing)))
                if open_at_eod is not None:
                    prev_day["open"] = max(0, int(open_at_eod))
                _sync_month_performance(prev_day)
            except Exception as exc:
                file_log(f"[RISK LIMIT TRACK WARN] persist completed day to performance | {exc}")
        row = _normalize_row(existing, today=today, balance=bal)
        _write_tracking(path, row, sync_month=sync_m)
        return row
    return _normalize_row(existing, today=today, balance=bal)


def _max_trades_reached(row: dict[str, Any]) -> bool:
    """Same idea as ``risk_controls_allow``: no more opens when count >= cap."""
    cap = int(getattr(settings, "MAX_TRADES_PER_DAY", 0))
    return int(row.get("total_trade", 0)) >= cap


def _max_losses_reached(row: dict[str, Any]) -> bool:
    cap = int(getattr(settings, "MAX_LOSSES_PER_DAY", 0))
    if cap <= 0:
        return False
    return int(row.get("loss", 0)) >= cap


def _block_reason_from_row(row: dict[str, Any]) -> str | None:
    """Short human reason for UI/logs; ``None`` when new entries are allowed."""
    if _max_trades_reached(row):
        return "Exceed Total trade"
    if _breaches_max_daily_loss(row):
        return "Exceed Max Loss PNL"
    if _max_losses_reached(row):
        return "Exceed Max Loss Trade Per Day"
    if _target_daily_roi_reached(row):
        return "Target Daily ROI reached"
    if bool(row.get("trading_stopped", False)):
        return "Trading stopped"
    return None


def risk_file_entry_gate(
    *, balance_usdt: float, sim_date_iso: str | None = None
) -> tuple[bool, str | None]:
    """
    Returns ``(True, None)`` when opens are allowed, else ``(False, short_reason)``.
    Persists ``trading_stopped`` when a threshold (not manual-only stop) applies.
    """
    try:
        row = ensure_today(balance_usdt=balance_usdt, sim_date_iso=sim_date_iso)
        reason = _block_reason_from_row(row)
        if reason is None:
            return True, None
        if reason != "Trading stopped":
            try:
                if not bool(row.get("trading_stopped", False)):
                    sync = dict(row)
                    sync["trading_stopped"] = True
                    _write_tracking(tracking_path(), sync, sync_month=sim_date_iso is None)
            except Exception:
                pass
        return False, reason
    except Exception as exc:
        file_log(f"[RISK LIMIT TRACK WARN] risk_file_entry_gate | {exc}")
        return True, None


def risk_file_allows_new_entries(*, balance_usdt: float, sim_date_iso: str | None = None) -> bool:
    ok, _reason = risk_file_entry_gate(balance_usdt=balance_usdt, sim_date_iso=sim_date_iso)
    return ok


def record_new_open(*, balance_usdt: float, sim_date_iso: str | None = None) -> None:
    """Call after a new position is successfully opened (one increment per new open)."""
    try:
        path = tracking_path()
        today = _effective_date_iso(sim_date_iso)
        row = ensure_today(balance_usdt=balance_usdt, sim_date_iso=sim_date_iso)
        row["total_trade"] = int(row.get("total_trade", 0)) + 1
        row["ending_balance"] = _round2(balance_usdt)
        row["date"] = today
        if _max_trades_reached(row):
            row["trading_stopped"] = True
        _write_tracking(path, row, sync_month=sim_date_iso is None)
    except Exception as exc:
        file_log(f"[RISK LIMIT TRACK WARN] record_new_open | {exc}")


def record_full_position_close(
    *,
    exchange_pnl_usdt: float | None,
    internal_realized_pnl_usdt: float,
    journal_balance_usdt: float,
    max_losses_per_day: int | None = None,
    sim_date_iso: str | None = None,
    open_positions: int | None = None,
) -> None:
    """
    Call once when a position is fully closed. Prefer exchange realized PnL when set.
    Updates win/loss/daily_pnl/ending_balance; may set trading_stopped.
    """
    try:
        path = tracking_path()
        today = _effective_date_iso(sim_date_iso)
        max_loss = int(
            max_losses_per_day if max_losses_per_day is not None else settings.MAX_LOSSES_PER_DAY
        )
        pnl = float(exchange_pnl_usdt) if exchange_pnl_usdt is not None else float(internal_realized_pnl_usdt)
        pnl = _round2(pnl)

        existing = _read_row(path)
        if existing is None:
            row = _default_row(date=today, balance=journal_balance_usdt)
        else:
            row = _normalize_row(existing, today=today, balance=journal_balance_usdt)

        row["daily_pnl"] = _round2(_daily_pnl_for_limits(row) + pnl)
        row["ending_balance"] = _round2(journal_balance_usdt)
        if pnl > 0:
            row["win"] = int(row.get("win", 0)) + 1
        elif pnl < 0:
            row["loss"] = int(row.get("loss", 0)) + 1

        if max_loss > 0 and int(row.get("loss", 0)) >= max_loss:
            row["trading_stopped"] = True
        if _breaches_max_daily_loss(row):
            row["trading_stopped"] = True
        if _target_daily_roi_reached(row):
            row["trading_stopped"] = True

        row["date"] = today
        _write_tracking(path, row, sync_month=sim_date_iso is None)
    except Exception as exc:
        file_log(f"[RISK LIMIT TRACK WARN] record_full_position_close | {exc}")
