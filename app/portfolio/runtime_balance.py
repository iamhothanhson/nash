"""Runtime balance resolution: backtest virtual ledger vs live/demo exchange wallet."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import settings
from portfolio.capital_tracker import (
    VirtualAccount,
    portfolio_available_balance,
    positions_open_notional,
)

if TYPE_CHECKING:
    pass

_LAST_BALANCE_SYNC_WARN_TS = 0.0
_EXCHANGE_CACHE: dict[str, Any] | None = None
_EXCHANGE_CACHE_DATE: str | None = None


def _cache_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data" / "runtime_data" / "exchange_balance.json"


def _load_disk_cache() -> dict[str, Any] | None:
    path = _cache_path()
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "risk_balance" in data:
                return data
    except Exception:
        pass
    return None


def _write_disk_cache(cache: dict[str, Any]) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception:
        pass


def uses_exchange_balance(mode: str | None = None) -> bool:
    return str(mode or settings.MODE).strip().lower() in ("live", "demo")


def _reset_exchange_cache() -> None:
    global _EXCHANGE_CACHE, _EXCHANGE_CACHE_DATE
    _EXCHANGE_CACHE = None
    _EXCHANGE_CACHE_DATE = None
    try:
        _cache_path().unlink(missing_ok=True)
    except Exception:
        pass


def get_runtime_account_state(engine: Any, virtual: VirtualAccount) -> dict[str, float]:
    """
    - backtest: virtual ledger (available = wallet minus locked margin)
    - live/demo: Binance futures wallet metrics from the execution client.
      Fetched once per UTC day and cached until the next UTC rollover.
      The last known balance is persisted to disk so it survives restarts.
    """
    global _LAST_BALANCE_SYNC_WARN_TS, _EXCHANGE_CACHE, _EXCHANGE_CACHE_DATE
    mode = str(settings.MODE).strip().lower()
    client = getattr(engine, "_client", None)

    if mode == "backtest":
        return {
            "risk_balance": float(virtual.balance),
            "available_balance": portfolio_available_balance(virtual),
            "open_notional": float(virtual.open_notional),
        }

    if uses_exchange_balance(mode) and client is not None:
        today = datetime.now(timezone.utc).date().isoformat()

        if _EXCHANGE_CACHE is not None and _EXCHANGE_CACHE_DATE == today:
            return {
                "risk_balance": _EXCHANGE_CACHE["risk_balance"],
                "available_balance": _EXCHANGE_CACHE["available_balance"],
                "open_notional": _EXCHANGE_CACHE["open_notional"],
            }

        attempts = 3
        for attempt in range(attempts):
            try:
                metrics = client.get_account_metrics()
                risk_balance = float(
                    metrics.get("total_margin_balance")
                    or metrics.get("total_wallet_balance")
                    or 0.0
                )
                _EXCHANGE_CACHE = {
                    "risk_balance": max(0.0, risk_balance),
                    "available_balance": max(0.0, float(metrics.get("available_balance", 0.0))),
                    "open_notional": max(0.0, float(metrics.get("open_notional", 0.0))),
                }
                _EXCHANGE_CACHE_DATE = today
                _write_disk_cache(_EXCHANGE_CACHE)
                return {
                    "risk_balance": _EXCHANGE_CACHE["risk_balance"],
                    "available_balance": _EXCHANGE_CACHE["available_balance"],
                    "open_notional": _EXCHANGE_CACHE["open_notional"],
                }
            except Exception as exc:
                now_ts = time.time()
                if attempt + 1 < attempts:
                    time.sleep(min(1.0 * (2**attempt), 4.0))
                    continue
                if now_ts - _LAST_BALANCE_SYNC_WARN_TS >= 60.0:
                    from monitoring.logger import log

                    log(f"[BALANCE SYNC] futures wallet fetch failed after {attempts} attempts | {exc}")
                    _LAST_BALANCE_SYNC_WARN_TS = now_ts

    if _EXCHANGE_CACHE is not None:
        return {
            "risk_balance": _EXCHANGE_CACHE["risk_balance"],
            "available_balance": _EXCHANGE_CACHE["available_balance"],
            "open_notional": _EXCHANGE_CACHE["open_notional"],
        }

    disk = _load_disk_cache()
    if disk is not None:
        _EXCHANGE_CACHE = disk
        return {
            "risk_balance": _EXCHANGE_CACHE["risk_balance"],
            "available_balance": _EXCHANGE_CACHE["available_balance"],
            "open_notional": _EXCHANGE_CACHE["open_notional"],
        }

    if uses_exchange_balance(mode):
        raise RuntimeError(
            f"exchange balance unavailable in '{mode}' mode — "
            f"Binance API unreachable and no cached balance found"
        )

    return {
        "risk_balance": float(virtual.balance),
        "available_balance": float(virtual.balance),
        "open_notional": float(virtual.open_notional),
    }


def entry_balance_kwargs(
    engine: Any,
    virtual: VirtualAccount,
    *,
    positions: list | None = None,
    account_balance: float | None = None,
    available_balance: float | None = None,
    open_notional_total: float | None = None,
) -> dict[str, float]:
    """Resolved balances for ``run_cycle`` / sizing (live/demo always from exchange when possible)."""
    acct = get_runtime_account_state(engine, virtual)
    risk = float(account_balance if account_balance is not None else acct["risk_balance"])
    if uses_exchange_balance():
        if available_balance is not None:
            avail = float(available_balance)
        elif account_balance is not None:
            # Caller supplied wallet snapshot without separate available (use risk as margin base).
            avail = risk
        else:
            avail = float(acct["available_balance"])
        return {
            "account_balance": risk,
            "available_balance": avail,
            "open_notional_total": float(
                open_notional_total if open_notional_total is not None else acct["open_notional"]
            ),
        }
    open_n = float(
        open_notional_total
        if open_notional_total is not None
        else (positions_open_notional(positions) if positions else acct["open_notional"])
    )
    avail = float(
        available_balance
        if available_balance is not None
        else portfolio_available_balance(virtual, positions)
    )
    return {
        "account_balance": risk,
        "available_balance": avail,
        "open_notional_total": open_n,
    }
