from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import requests

from config import settings
from strategy.trend_following.trend_following_config import (
    SELECTOR_TREND_MIN_STRENGTH_TO_COMPETE,
    TREND_REGIME_ADX_CATASTROPHIC,
)


def format_plan_rejected_reason_for_telegram(raw: str) -> str:
    """
    Turn internal selector/regime codes into short, readable sentences for Telegram.
    """
    s = str(raw).strip()
    if not s:
        return "No detail provided."

    parts: list[str] = []
    for chunk in s.split(","):
        chunk = chunk.strip()
        if chunk:
            parts.append(_humanize_plan_reject_fragment(chunk))

    out = " · ".join(parts) if parts else s
    return out[:3500] if len(out) > 3500 else out


def _humanize_plan_reject_fragment(chunk: str) -> str:
    """Single comma-separated fragment from signal_engine or strategies."""
    lower = chunk.lower()

    # Liquidity: rejected_score | score=3 | min_A=5 | min_A+=7
    if "rejected_score" in lower and "score=" in chunk:
        m_score = re.search(r"score=\s*([0-9]+)", chunk)
        m_a = re.search(r"min_A=\s*([0-9]+)", chunk)
        m_ap = re.search(r"min_A\+\s*=\s*([0-9]+)", chunk)
        sc = m_score.group(1) if m_score else "?"
        ma = m_a.group(1) if m_a else "?"
        mapl = m_ap.group(1) if m_ap else "?"
        return (
            f"Setup score {sc} is below grade gates (need ≥{ma} for A, ≥{mapl} for A+)"
        )

    # Selector arbitration (may include key=value pairs after first segment)
    if "|" in chunk and chunk.split("|", 1)[0].startswith("blocked_by_"):
        return _humanize_blocked_pipe_chunk(chunk)

    if ":" in chunk:
        status, _, tail = chunk.partition(":")
        status = status.strip()
        tail = tail.strip()
        if status == "blocked_by_trend_regime":
            return _humanize_regime_reason_only(tail, prefix="Trend regime gate")
        if status == "blocked_by_trend_strength":
            thr = float(SELECTOR_TREND_MIN_STRENGTH_TO_COMPETE)
            if tail in ("qualified", "") or not tail:
                return (
                    f"Trend regime composite strength is below {thr:.2f} "
                    "(SELECTOR_TREND_MIN_STRENGTH_TO_COMPETE) — trend candidate filtered out."
                )
            return _humanize_regime_reason_only(tail, prefix="Trend strength gate")
        if status == "blocked_by_regime_direction_mismatch":
            if tail == "qualified":
                return (
                    "Trend signal direction conflicts with higher-timeframe regime bias "
                    "(LONG/SHORT mismatch)."
                )
            return (
                "Trend signal direction does not match higher-timeframe regime bias "
                f"(detail: {tail})."
            )
        return f"{_titleish(status)}: {_humanize_regime_token(tail)}"

    # Bare arbitration reasons
    if chunk.startswith("winner_gap_too_small"):
        m = re.search(r"<([\d.]+)>", chunk)
        gap = _format_telegram_float(m.group(1)) if m else ""
        return (
            f"Top strategies scored too close together (gap < {gap}); "
            f"no winner declared."
            if gap
            else "Top strategies scored too close; no clear winner."
        )
    if chunk.startswith("below_min_score"):
        m = re.search(r"<([\d.]+)>", chunk)
        ms = _format_telegram_float(m.group(1)) if m else ""
        return (
            f"Best setup score ({ms}) is below the minimum selector threshold."
            if ms
            else "Best setup score is below the minimum selector threshold."
        )
    if chunk == "no_candidates":
        return "No strategy produced a scored candidate this bar."
    if chunk == "lost_competition":
        return "Another strategy won arbitration"
    if chunk in _REGIME_REASON_SENTENCES:
        return _REGIME_REASON_SENTENCES[chunk]

    return chunk.replace("_", " ").strip()


def _format_telegram_float(token: str, *, decimals: int = 4) -> str:
    """Pretty-print a numeric token for Telegram (avoid long float noise)."""
    t = str(token).strip()
    if t in ("?", ""):
        return t
    try:
        x = float(t)
    except ValueError:
        return t
    nd = max(0, min(12, int(decimals)))
    s = f"{round(x, nd):.{nd}f}" if nd > 0 else str(int(round(x)))
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s else "0"


def _humanize_blocked_pipe_chunk(chunk: str) -> str:
    """blocked_by_*|key=val|..."""
    bits = [b.strip() for b in chunk.split("|") if b.strip()]
    if not bits:
        return chunk
    head = bits[0]
    kv = {}
    for b in bits[1:]:
        if "=" in b:
            k, _, v = b.partition("=")
            kv[k.strip().lower()] = v.strip()

    if head == "blocked_by_regime_direction_mismatch":
        setup = kv.get("setup", "?")
        bias = kv.get("regime_bias", "?")
        return (
            f"Trend setup ({setup}) conflicts with HTF regime bias ({bias}) — trade blocked."
        )
    if head == "blocked_by_trend_strength":
        sc_raw = str(kv.get("score", "?"))
        need_raw = str(kv.get("min", "?"))
        sc = _format_telegram_float(sc_raw, decimals=4)
        need = _format_telegram_float(need_raw, decimals=4)
        return f"HTF Regime Score {sc} < {need} Minimun"
    if head == "blocked_by_trend_regime":
        tag = kv.get("regime_tag", "") or kv.get("reason", "")
        if tag:
            return _humanize_regime_reason_only(tag, prefix="Trend regime gate")
        return "Trend regime gate blocked trend-following trades."

    return _humanize_plan_reject_fragment(bits[0]) if len(bits) == 1 else chunk


def _humanize_regime_reason_only(token: str, *, prefix: str) -> str:
    body = _humanize_regime_token(token)
    return f"{prefix}: {body}"


def _humanize_regime_token(token: str) -> str:
    t = str(token).strip()
    if t in _REGIME_REASON_SENTENCES:
        return _REGIME_REASON_SENTENCES[t]
    return t.replace("_", " ") + "."


_REGIME_REASON_SENTENCES: dict[str, str] = {
    "adx_catastrophic": (
        "1h ADX is below the catastrophic floor — trend is too weak or chop-like "
        f"(default ADX floor {TREND_REGIME_ADX_CATASTROPHIC:g})."
    ),
    "below_min_strength": (
        "Overall trend regime score is below TREND_REGIME_MIN_STRENGTH — "
        "context not strong enough for trend trades."
    ),
    "ema_chop": (
        "EMA 50/200 chop (ranging) — trend bias is unclear. "
        "Trend Following entries blocked."
    ),
    "thin_liquidity_15m": (
        "15m volume is thin vs its recent average — liquidity gate blocked trend entry."
    ),
    "qualified": "Regime passed filters but another gate still blocked (see status line).",
    "insufficient_bars_1h": "Not enough 1h bars loaded for regime detection.",
    "missing_ohlc_columns": "1h data missing OHLC columns.",
    "adx_unavailable": "ADX could not be computed on 1h data.",
    "adx_invalid": "ADX value invalid on 1h.",
}


def _titleish(snake: str) -> str:
    return snake.replace("_", " ").strip().title()


def _is_enabled_for_mode() -> bool:
    if not bool(settings.ALERTS_ENABLED):
        return False
    return str(settings.MODE).strip().lower() in set(settings.ALERTS_MODES)


def send_alert(message: str) -> bool:
    """
    Send an alert message via Telegram.
    Returns True when sent, False when skipped/failed.

    New alert helpers: add a sample to ``monitoring.telegram_test_suite`` and run
    ``make send-telegram``.
    """
    if not _is_enabled_for_mode():
        return False
    token = str(settings.TELEGRAM_BOT_TOKEN or "").strip()
    chat_id = str(settings.TELEGRAM_CHAT_ID or "").strip()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": str(message),
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def format_total_exposure_plan_reject_detail(
    total_exposure: float, max_exposure: float, account_balance: float
) -> str:
    """Telegram detail line for aggregate exposure cap rejections in order_planner."""
    return (
        f"Total exposure {float(total_exposure):.2f} > Max Exposure {float(max_exposure):.2f} - "
        f"Account balance {float(account_balance):.2f}"
    )


def send_order_plan_rejected_alert(symbol: str, detail: str) -> bool:
    """
    Telegram when ``build_order_plan`` or live margin check rejects an entry.

    Format: ``[HH:MM:SS] [REJECTED] [MODE] SYMBOL | Plan Rejected | {detail}``
    """
    time_str = datetime.now().strftime("%H:%M:%S")
    mode = str(settings.MODE).strip().upper()
    sym = str(symbol).strip().upper()
    d = str(detail).strip()
    if len(d) > 400:
        d = d[:397] + "..."
    msg = f"[{time_str}] [REJECTED] [{mode}] {sym} | Plan Rejected | {d}"
    return send_alert(msg)


def send_plan_rejected_alert(
    symbol: str, *, strategy_label: str, detail_reason: str, setup_label: str | None = None
) -> bool:
    """Telegram template shared by signal_engine and strategies (same shape as PLAN REJECTED alerts)."""
    time_str = datetime.now().strftime("%H:%M:%S")
    mode = str(settings.MODE).strip().upper()
    human = format_plan_rejected_reason_for_telegram(detail_reason)
    strat = f"Strategy: {strategy_label}"
    if setup_label:
        strat = f"{strat} | Setup: {setup_label}"
    msg = (
        f"[{time_str}] [{mode}] [PLAN REJECTED] | {symbol} | "
        f"{strat} |\n"
        f"{human}"
    )
    return send_alert(msg)


def send_daily_performance_snapshot_alert(
    snapshot: dict[str, Any],
    *,
    heading: str = "DAILY PERFORMANCE",
    respect_daily_telegram_setting: bool = True,
) -> bool:
    """
    Telegram day stats JSON (``SNAPSHOT_EXPORT_KEYS`` from risk / performance tracking).

    Respects ``ALERTS_ENABLED`` / ``ALERTS_MODES`` / Telegram credentials like :func:`send_alert`.
    Set ``DAILY_PERFORMANCE_TELEGRAM=false`` to disable (unless ``respect_daily_telegram_setting`` is False).
    Use ``heading`` for EOD vs per-close vs MTD label.
    """
    if respect_daily_telegram_setting and not bool(
        getattr(settings, "DAILY_PERFORMANCE_TELEGRAM", True)
    ):
        return False
    time_str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    mode = str(settings.MODE).strip().upper()
    day = str(snapshot.get("date", "")).strip()[:10] or "?"
    label = str(heading).strip() or "DAILY PERFORMANCE"
    body = json.dumps(snapshot, indent=2)
    msg = f"[{time_str}] [{mode}] [{label}] {day}\n{body}"
    return send_alert(msg)


def send_risk_limit_blocked_alert(
    symbol: str, reason: str, *, balance_usdt: float | None = None
) -> bool:
    """
    Telegram when the risk JSON gate blocks a new entry (live/demo; respects ALERTS_*).
    """
    time_str = datetime.now().strftime("%H:%M:%S")
    mode = str(settings.MODE).strip().upper()
    sym = str(symbol).strip().upper()
    r = str(reason).strip() or "Trading stopped"
    if len(r) > 400:
        r = r[:397] + "..."
    bal = f" | Balance: {float(balance_usdt):.2f} USDT" if balance_usdt is not None else ""
    msg = f"[{time_str}] [{mode}] [RISK LIMIT] {sym} | {r}{bal}"
    return send_alert(msg)


def send_exchange_entry_blocked_alert(symbol: str, detail: str) -> bool:
    """
    Telegram when live/demo exchange pre-entry checks block a new order (respects ALERTS_*).
    """
    time_str = datetime.now().strftime("%H:%M:%S")
    mode = str(settings.MODE).strip().upper()
    sym = str(symbol).strip().upper()
    d = str(detail).strip() or "blocked"
    if len(d) > 400:
        d = d[:397] + "..."
    msg = f"[{time_str}] [{mode}] [SKIP] {sym} | Exchange entry blocked: {d}"
    return send_alert(msg)
