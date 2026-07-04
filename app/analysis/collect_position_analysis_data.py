"""
Trade data collection — called from main.py and backtest.py on every close.
Collects market regime + trade metrics using pre-fetched OHLCV data and writes
enriched records to data/position_analysis/position_analysis_data.json.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from monitoring.logger import log

_ANALYSIS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "position_analysis"
_ANALYSIS_FILE = _ANALYSIS_DIR / "position_analysis_data.json"

# Cache OHLCV fetched during signal analysis / position management so recording
# reuses them instead of re-fetching.  Keyed by symbol, e.g.  {"BTCUSDT": {"5m": df, "15m": df, "1h": df}}
_OHLCV_CACHE: dict[str, dict[str, pd.DataFrame]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _infer_session(ts: datetime) -> str:
    h = ts.hour
    if h < 8:
        return "ASIA"
    if h < 16:
        return "EU"
    return "US"


def _slice_data_at_entry(df: pd.DataFrame, entry_dt: datetime, min_bars: int) -> pd.DataFrame:
    if df.empty:
        return df
    ts_col = "time" if "time" in df.columns else "timestamp"
    df = df.copy()
    if ts_col in df.columns:
        if df[ts_col].dtype.kind in ("i", "f"):
            entry_ms = int(entry_dt.timestamp() * 1000)
            df = df[df[ts_col] <= entry_ms].tail(min_bars + 5)
        else:
            df[ts_col] = pd.to_datetime(df[ts_col])
            df = df[df[ts_col] <= entry_dt].tail(min_bars + 5)
    else:
        df = df[df.index <= entry_dt].tail(min_bars + 5)
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# MAE / MFE computation from OHLCV between entry and exit
# ---------------------------------------------------------------------------


def _compute_mae_mfe(
    data_5m: pd.DataFrame,
    entry_dt: datetime,
    exit_dt: datetime,
    entry_price: float,
    direction: str,
) -> dict[str, float]:
    """Compute approximate MAE and MFE (in R multiples) from 5m OHLCV."""
    if data_5m.empty:
        return {"mae_r": 0.0, "mfe_r": 0.0}

    ts_col = "time" if "time" in data_5m.columns else "timestamp"
    df = data_5m.copy()

    if ts_col in df.columns:
        if df[ts_col].dtype.kind in ("i", "f"):
            entry_ms = int(entry_dt.timestamp() * 1000)
            exit_ms = int(exit_dt.timestamp() * 1000)
            window = df[(df[ts_col] >= entry_ms) & (df[ts_col] <= exit_ms)]
        else:
            df[ts_col] = pd.to_datetime(df[ts_col])
            window = df[(df[ts_col] >= entry_dt) & (df[ts_col] <= exit_dt)]
    else:
        window = df[(df.index >= entry_dt) & (df.index <= exit_dt)]

    if len(window) < 2:
        return {"mae_r": 0.0, "mfe_r": 0.0}

    high = window["high"].astype(float).max()
    low = window["low"].astype(float).min()
    risk = abs(entry_price) * 0.01 if abs(entry_price) > 0 else 1.0

    if direction.upper() == "LONG":
        mfe_px = high - entry_price
        mae_px = entry_price - low
    else:
        mfe_px = entry_price - low
        mae_px = high - entry_price

    risk_actual = abs(entry_price) * 0.01 if abs(entry_price) > 0 else risk
    return {
        "mae_r": round(mae_px / max(risk_actual, 1e-12), 2),
        "mfe_r": round(mfe_px / max(risk_actual, 1e-12), 2),
    }


# ---------------------------------------------------------------------------
# Build record + write
# ---------------------------------------------------------------------------


def _build_trade_record(
    trade: dict[str, Any],
    regime: dict[str, Any],
    mae_r: float,
    mfe_r: float,
    result: str,
) -> dict[str, Any]:
    opened_dt = trade["opened_dt"]
    entry = trade["entry"]
    stop_loss = trade["stop_loss"]
    risk_pct = abs(entry - stop_loss) / max(entry, 1e-12) * 100 if stop_loss else 0.0

    record = {
        "coin": trade["coin"],
        "side": trade["side"],
        "strategy_setup": trade["strategy_setup"],
        "market_regime": {
            "regime": regime.get("regime", "Unknown"),
            "confidence": regime.get("confidence", 50),
            "trend_direction": regime.get("trend_direction", "Neutral"),
            "ema_slope": regime.get("ema_slope", 0.0),
            "ema20_slope_1h": regime.get("ema20_slope_1h", 0.0),
            "adx": regime.get("adx", 0.0),
            "adx_1h": regime.get("adx_1h", 0.0),
            "atr_percentile": regime.get("atr_percentile", 50),
            "market_structure": regime.get("market_structure", "Range"),
            "volume_ratio": regime.get("volume_ratio", 1.0),
            "atr_percent": regime.get("atr_percent", 0.0),
            "rsi": regime.get("rsi", 50.0),
        },
        "trade_context": {
            "session": _infer_session(opened_dt),
            "result": result,
            "opened": trade["opened"],
            "closed": trade["closed"],
            "entry_price": entry,
            "stop_loss": stop_loss,
            "risk_pct": round(risk_pct, 2),
            "pnl_usdt": trade["pnl_usdt"],
            "bars_held": trade["bars_held"],
            "tp_hit": trade["tp_hit"],
            "closed_reason": trade["closed_reason"],
        },
        "trade_performance": {
            "mae_r": mae_r,
            "mfe_r": mfe_r,
        },
    }

    if result == "Loss":
        from analysis.loss_analyzer import analyze_loss_record as _analyze
        try:
            enriched = _analyze(record)
            record["analysis"] = enriched.get("analysis", {})
        except Exception:
            pass
    elif result == "Win":
        from analysis.win_analyzer import analyze_win_record
        try:
            enriched = analyze_win_record(record)
            record["analysis"] = enriched.get("analysis", {})
        except Exception:
            pass

    return record


def _write_analysis_file(records: list[dict[str, Any]]) -> None:
    _ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    existing: list[dict[str, Any]] = []
    if _ANALYSIS_FILE.exists():
        try:
            existing = json.loads(_ANALYSIS_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    if not isinstance(existing, list):
        existing = []

    existing_keys = {
        (
            r.get("coin", ""),
            r.get("trade_context", {}).get("opened", ""),
            r.get("trade_context", {}).get("closed", ""),
        )
        for r in existing
        if isinstance(r, dict)
    }

    for rec in records:
        key = (
            rec.get("coin", ""),
            rec.get("trade_context", {}).get("opened", ""),
            rec.get("trade_context", {}).get("closed", ""),
        )
        found = False
        for i, existing_rec in enumerate(existing):
            if not isinstance(existing_rec, dict):
                continue
            ek = (
                existing_rec.get("coin", ""),
                existing_rec.get("trade_context", {}).get("opened", ""),
                existing_rec.get("trade_context", {}).get("closed", ""),
            )
            if ek == key:
                existing[i] = rec
                found = True
                break
        if not found:
            existing.append(rec)

    _ANALYSIS_FILE.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Telegram notification for loss analysis results
# ---------------------------------------------------------------------------


def _send_loss_telegram(record: dict[str, Any]) -> None:
    """Send a structured loss-analysis notification via Telegram."""
    tc = record.get("trade_context", {})
    la = record.get("analysis", {})
    mr = record.get("market_regime", {})
    tp = record.get("trade_performance", {})

    evidence_list = la.get("evidence", [])
    evidence_strings = [
        e["message"] if isinstance(e, dict) else str(e)
        for e in evidence_list
    ]

    dto = {
        "coin": record.get("coin", ""),
        "side": record.get("side", ""),
        "setup": record.get("strategy_setup", ""),
        "session": tc.get("session", ""),
        "result": "Loss",
        "closed_reason": tc.get("closed_reason", ""),
        "entry_price": tc.get("entry_price", 0),
        "stop_loss": tc.get("stop_loss", 0),
        "risk_pct": tc.get("risk_pct", 0),
        "pnl_usdt": tc.get("pnl_usdt", 0),
        "bars_held": tc.get("bars_held", 0),
        "market_regime": {
            "regime": mr.get("regime", "Unknown"),
            "trend_direction": mr.get("trend_direction", "Neutral"),
            "market_structure": mr.get("market_structure", "Range"),
        },
        "trade_performance": {
            "mae_r": tp.get("mae_r", 0),
            "mfe_r": tp.get("mfe_r", 0),
        },
        "analysis": {
            "primary_reason": la.get("primary_reason", "Unknown"),
            "confidence": la.get("confidence", 0),
            "evidence": evidence_strings,
        },
    }

    try:
        from config import settings as _stg
        import requests as _rq

        if not bool(_stg.ALERTS_ENABLED):
            return
        if str(_stg.MODE).strip().lower() not in set(_stg.ALERTS_MODES):
            return
        token = str(_stg.TELEGRAM_BOT_TOKEN or "").strip()
        chat_id = str(_stg.TELEGRAM_CHAT_ID or "").strip()
        if not token or not chat_id:
            return
        now = datetime.now(timezone.utc)
        date_part = now.strftime("%Y:%m:%d %H:%M:%S")
        mode = str(_stg.MODE).upper() if hasattr(_stg, "MODE") else "?"
        headline = f"[{mode}] [LOSS ANALYSIS] {date_part}"
        text = f"{headline}\n{json.dumps(dto, indent=2)}"
        resp = _rq.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        if resp.status_code != 200:
            log(f"[LOSS TELEGRAM] HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        log(f"[LOSS TELEGRAM] Failed: {exc}")


def _send_win_telegram(record: dict[str, Any]) -> None:
    """Send a structured win-analysis notification via Telegram."""
    tc = record.get("trade_context", {})
    ta = record.get("analysis", {})
    mr = record.get("market_regime", {})
    tp = record.get("trade_performance", {})

    factor_messages = [
        f["message"] if isinstance(f, dict) else str(f)
        for f in (ta.get("key_factors") or [])
    ]

    dto = {
        "coin": record.get("coin", ""),
        "side": record.get("side", ""),
        "setup": record.get("strategy_setup", ""),
        "session": tc.get("session", ""),
        "result": "Win",
        "closed_reason": tc.get("closed_reason", ""),
        "entry_price": tc.get("entry_price", 0),
        "stop_loss": tc.get("stop_loss", 0),
        "risk_pct": tc.get("risk_pct", 0),
        "pnl_usdt": tc.get("pnl_usdt", 0),
        "bars_held": tc.get("bars_held", 0),
        "market_regime": {
            "regime": mr.get("regime", "Unknown"),
            "trend_direction": mr.get("trend_direction", "Neutral"),
            "market_structure": mr.get("market_structure", "Range"),
        },
        "trade_performance": {
            "mae_r": tp.get("mae_r", 0),
            "mfe_r": tp.get("mfe_r", 0),
        },
        "analysis": {
            "factor_count": ta.get("factor_count", 0),
            "key_factors": factor_messages,
        },
    }

    try:
        from config import settings as _stg
        import requests as _rq

        if not bool(_stg.ALERTS_ENABLED):
            return
        if str(_stg.MODE).strip().lower() not in set(_stg.ALERTS_MODES):
            return
        token = str(_stg.TELEGRAM_BOT_TOKEN or "").strip()
        chat_id = str(_stg.TELEGRAM_CHAT_ID or "").strip()
        if not token or not chat_id:
            return
        now = datetime.now(timezone.utc)
        date_part = now.strftime("%Y:%m:%d %H:%M:%S")
        mode = str(_stg.MODE).upper() if hasattr(_stg, "MODE") else "?"
        headline = f"[{mode}] [WIN ANALYSIS] {date_part}"
        text = f"{headline}\n{json.dumps(dto, indent=2)}"
        resp = _rq.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        if resp.status_code != 200:
            log(f"[WIN TELEGRAM] HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        log(f"[WIN TELEGRAM] Failed: {exc}")


def _notify_missing_regime(symbol: str, trade_info: dict[str, Any]) -> None:
    """Send a single-line Telegram alert when market regime data is missing."""
    try:
        from config import settings as _stg
        import requests as _rq

        if not bool(_stg.ALERTS_ENABLED):
            log(f"[NO ANALYSIS] {symbol} | ALERTS_ENABLED=False, skipping Telegram")
            return
        if str(_stg.MODE).strip().lower() not in set(_stg.ALERTS_MODES):
            log(f"[NO ANALYSIS] {symbol} | MODE={_stg.MODE} not in ALERTS_MODES={_stg.ALERTS_MODES}, skipping Telegram")
            return
        token = str(_stg.TELEGRAM_BOT_TOKEN or "").strip()
        chat_id = str(_stg.TELEGRAM_CHAT_ID or "").strip()
        if not token or not chat_id:
            log(f"[NO ANALYSIS] {symbol} | TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set, skipping Telegram")
            return

        side = trade_info.get("side", "?")
        pnl = trade_info.get("pnl", 0)
        text = (
            f"[{str(_stg.MODE).upper()}] [NO ANALYSIS] {symbol} {side} "
            f"| PNL: {pnl:.2f} | market_regime_detail missing"
        )
        resp = _rq.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
        if resp.status_code != 200:
            log(f"[NO ANALYSIS] Telegram HTTP {resp.status_code}: {resp.text[:200]}")
        else:
            log(f"[NO ANALYSIS] Telegram sent for {symbol}")
    except Exception as exc:
        log(f"[NO ANALYSIS] Failed: {exc}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_regime_for_trade(
    data_1h: pd.DataFrame,
    data_15m: pd.DataFrame | None,
    data_5m: pd.DataFrame,
    symbol: str,
    entry_dt: datetime,
    exit_dt: datetime,
    trade_info: dict[str, Any],
    *,
    write_to_disk: bool = True,
) -> dict[str, Any] | None:
    """
    Compute market regime + trade performance for a single trade using
    pre-fetched OHLCV data. Handles both wins and losses.

    ``trade_info`` keys used:
        side, entry, stop_loss, pnl, opened (display string), closed (display string),
        strategy_setup, bars_held, tp_hit, closed_reason, market_structure

    ``result`` is inferred from pnl sign unless explicitly provided.

    Returns the enriched record (with ``analysis`` for losses) or None on failure.
    """
    sym_raw = symbol.upper().replace("USDT", "")

    regime = trade_info.get("market_regime_detail")
    if regime is None or not isinstance(regime, dict):
        log(f"[TRACE] {sym_raw} | market_regime_detail missing in trade_info, skipping")
        _notify_missing_regime(symbol, trade_info)
        return None

    signal_ms = trade_info.get("market_structure")
    if signal_ms and isinstance(signal_ms, str) and signal_ms.strip():
        regime["market_structure"] = signal_ms.strip()

    entry = float(trade_info.get("entry", 0.0))
    direction = str(trade_info.get("side", "LONG")).upper()
    perf = _compute_mae_mfe(data_5m, entry_dt, exit_dt, entry, direction)

    opened_display = entry_dt.strftime("%b-%d-%Y %H:%M:%S")
    closed_display = exit_dt.strftime("%b-%d-%Y %H:%M:%S")

    pnl = float(trade_info.get("pnl", 0.0))

    trade = {
        "coin": sym_raw,
        "side": direction,
        "strategy_setup": str(trade_info.get("strategy_setup", "unknown")),
        "entry": entry,
        "stop_loss": float(trade_info.get("stop_loss", 0.0)),
        "pnl_usdt": pnl,
        "opened": opened_display,
        "closed": closed_display,
        "closed_reason": str(trade_info.get("closed_reason", "")),
        "opened_dt": entry_dt,
        "closed_dt": exit_dt,
        "bars_held": int(trade_info.get("bars_held", 1)),
        "tp_hit": bool(trade_info.get("tp_hit", False)),
        "tp1_hit": bool(trade_info.get("tp1_hit", False)),
        "tp2_hit": bool(trade_info.get("tp2_hit", False)),
        "tp3_hit": bool(trade_info.get("tp3_hit", False)),
    }

    result = "Win" if pnl >= 0 else "Loss"
    record = _build_trade_record(trade, regime, perf["mae_r"], perf["mfe_r"], result)

    if write_to_disk:
        _write_analysis_file([record])

    if result == "Loss":
        _send_loss_telegram(record)
    elif result == "Win":
        _send_win_telegram(record)

    return record
