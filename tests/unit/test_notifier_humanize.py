from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.monitoring.notifier import format_plan_rejected_reason_for_telegram


@pytest.mark.unit
def test_humanize_blocked_trend_regime_emachop_explains_pullback_vs_breakout() -> None:
    s = format_plan_rejected_reason_for_telegram("blocked_by_trend_regime:ema_chop")
    assert "Trend Following" in s
    assert "50/200" in s
    assert "chop" in s.lower()

    s = format_plan_rejected_reason_for_telegram("blocked_by_trend_regime:adx_catastrophic")
    assert "ADX" in s or "adx" in s.lower()
    assert "catastrophic" in s.lower() or "floor" in s.lower()


@pytest.mark.unit
def test_humanize_rejected_score_liquidity() -> None:
    raw = "rejected_score | score=4 | min_A=6 | min_A+=8"
    s = format_plan_rejected_reason_for_telegram(raw)
    assert "4" in s
    assert "6" in s
    assert "8" in s


@pytest.mark.unit
def test_humanize_pipe_direction_mismatch() -> None:
    raw = "blocked_by_regime_direction_mismatch|setup=LONG|regime_bias=SHORT|regime_tag=qualified"
    s = format_plan_rejected_reason_for_telegram(raw)
    assert "LONG" in s
    assert "SHORT" in s


@pytest.mark.unit
def test_humanize_pipe_trend_strength_long_float_rounded() -> None:
    raw = (
        "blocked_by_trend_strength|score=0.3493058915030088|min=0.35|regime_tag=qualified"
    )
    s = format_plan_rejected_reason_for_telegram(raw)
    assert "HTF Regime Score 0.3493 < 0.35 Minimun" in s
    assert "5030088" not in s


@pytest.mark.unit
def test_humanize_pipe_trend_strength() -> None:
    raw = "blocked_by_trend_strength|score=0.31|min=0.45|regime_tag=qualified"
    s = format_plan_rejected_reason_for_telegram(raw)
    assert "HTF Regime Score 0.31 < 0.45 Minimun" in s


@pytest.mark.unit
def test_send_plan_rejected_alert_includes_setup_when_provided(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from app.monitoring import notifier

    monkeypatch.setattr(notifier.settings, "MODE", "demo", raising=False)
    monkeypatch.setattr(notifier.settings, "ALERTS_ENABLED", True, raising=False)
    monkeypatch.setattr(notifier.settings, "ALERTS_MODES", ("demo", "live"), raising=False)
    monkeypatch.setattr(notifier.settings, "TELEGRAM_BOT_TOKEN", "dummy", raising=False)
    monkeypatch.setattr(notifier.settings, "TELEGRAM_CHAT_ID", "1", raising=False)
    mock_post = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(notifier.requests, "post", mock_post)
    notifier.send_plan_rejected_alert(
        "TAOUSDT",
        strategy_label="Trend Following",
        setup_label="Trend Pullback",
        detail_reason="blocked_by_trend_regime:ema_chop",
    )
    text = mock_post.call_args.kwargs["json"]["text"]
    assert "Strategy: Trend Following | Setup: Trend Pullback" in text


@pytest.mark.unit
def test_send_order_plan_rejected_alert_exposure_format(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from app.monitoring import notifier

    monkeypatch.setattr(notifier.settings, "MODE", "live", raising=False)
    monkeypatch.setattr(notifier.settings, "ALERTS_ENABLED", True, raising=False)
    monkeypatch.setattr(notifier.settings, "ALERTS_MODES", ("demo", "live"), raising=False)
    monkeypatch.setattr(notifier.settings, "TELEGRAM_BOT_TOKEN", "dummy", raising=False)
    monkeypatch.setattr(notifier.settings, "TELEGRAM_CHAT_ID", "1", raising=False)
    mock_post = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(notifier.requests, "post", mock_post)
    detail = notifier.format_total_exposure_plan_reject_detail(521.49, 291.31, 97.10)
    notifier.send_order_plan_rejected_alert("TAOUSDT", detail)
    text = mock_post.call_args.kwargs["json"]["text"]
    assert "[REJECTED] [LIVE] TAOUSDT | Plan Rejected |" in text
    assert "Total exposure 521.49 > Max Exposure 291.31 - Account balance 97.10" in text


@pytest.mark.unit
def test_send_exchange_entry_blocked_alert_telegram_payload(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from app.monitoring import notifier

    monkeypatch.setattr(notifier.settings, "MODE", "demo", raising=False)
    monkeypatch.setattr(notifier.settings, "ALERTS_ENABLED", True, raising=False)
    monkeypatch.setattr(notifier.settings, "ALERTS_MODES", ("demo", "live"), raising=False)
    monkeypatch.setattr(notifier.settings, "TELEGRAM_BOT_TOKEN", "dummy", raising=False)
    monkeypatch.setattr(notifier.settings, "TELEGRAM_CHAT_ID", "1", raising=False)
    mock_post = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(notifier.requests, "post", mock_post)
    notifier.send_exchange_entry_blocked_alert("TAOUSDT", "per-symbol cap (1 open, max 1)")
    assert mock_post.called
    payload = mock_post.call_args.kwargs["json"]
    assert "[DEMO] [SKIP] TAOUSDT | Exchange entry blocked:" in payload["text"]
    assert "per-symbol cap (1 open, max 1)" in payload["text"]


@pytest.mark.unit
def test_send_risk_limit_blocked_alert_telegram_payload(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from app.monitoring import notifier

    monkeypatch.setattr(notifier.settings, "MODE", "demo", raising=False)
    monkeypatch.setattr(notifier.settings, "ALERTS_ENABLED", True, raising=False)
    monkeypatch.setattr(notifier.settings, "ALERTS_MODES", ("demo", "live"), raising=False)
    monkeypatch.setattr(notifier.settings, "TELEGRAM_BOT_TOKEN", "dummy", raising=False)
    monkeypatch.setattr(notifier.settings, "TELEGRAM_CHAT_ID", "1", raising=False)
    mock_post = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(notifier.requests, "post", mock_post)
    notifier.send_risk_limit_blocked_alert("TAOUSDT", "Exceed Total trade", balance_usdt=123.45)
    assert mock_post.called
    payload = mock_post.call_args.kwargs["json"]
    assert "[DEMO] [RISK LIMIT] TAOUSDT" in payload["text"]
    assert "Exceed Total trade" in payload["text"]
    assert "123.45" in payload["text"]


@pytest.mark.unit
def test_send_daily_performance_snapshot_alert(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from app.monitoring import notifier

    monkeypatch.setattr(notifier.settings, "MODE", "demo", raising=False)
    monkeypatch.setattr(notifier.settings, "ALERTS_ENABLED", True, raising=False)
    monkeypatch.setattr(notifier.settings, "ALERTS_MODES", ("demo", "live"), raising=False)
    monkeypatch.setattr(notifier.settings, "TELEGRAM_BOT_TOKEN", "dummy", raising=False)
    monkeypatch.setattr(notifier.settings, "TELEGRAM_CHAT_ID", "1", raising=False)
    monkeypatch.setattr(notifier.settings, "DAILY_PERFORMANCE_TELEGRAM", True, raising=False)
    mock_post = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(notifier.requests, "post", mock_post)
    snap = {
        "date": "2026-05-10",
        "starting_balance": 137.6,
        "ending_balance": 144.52,
        "daily_pnl": 6.92,
        "daily_pnl_percent": 5.03,
        "total_trade": 3,
        "win": 3,
        "loss": 0,
        "open": 0,
        "max_drawdown_percent": 0.33,
        "trading_stopped": False,
    }
    assert notifier.send_daily_performance_snapshot_alert(snap) is True
    text = mock_post.call_args.kwargs["json"]["text"]
    assert "[DEMO] [DAILY PERFORMANCE] 2026-05-10" in text
    assert '"daily_pnl": 6.92' in text


@pytest.mark.unit
def test_send_daily_performance_snapshot_alert_runtime_performance_heading(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from app.monitoring import notifier

    monkeypatch.setattr(notifier.settings, "MODE", "demo", raising=False)
    monkeypatch.setattr(notifier.settings, "ALERTS_ENABLED", True, raising=False)
    monkeypatch.setattr(notifier.settings, "ALERTS_MODES", ("demo", "live"), raising=False)
    monkeypatch.setattr(notifier.settings, "TELEGRAM_BOT_TOKEN", "dummy", raising=False)
    monkeypatch.setattr(notifier.settings, "TELEGRAM_CHAT_ID", "1", raising=False)
    monkeypatch.setattr(notifier.settings, "DAILY_PERFORMANCE_TELEGRAM", True, raising=False)
    mock_post = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(notifier.requests, "post", mock_post)
    snap = {
        "date": "2026-05-10",
        "starting_balance": 100.0,
        "ending_balance": 106.92,
        "daily_pnl": 6.92,
        "daily_pnl_percent": 6.92,
        "total_trade": 3,
        "win": 2,
        "loss": 1,
        "open": 0,
        "max_drawdown_percent": 0.33,
        "peak_balance": 106.92,
        "trading_stopped": False,
    }
    assert notifier.send_daily_performance_snapshot_alert(snap, heading="RUNTIME PERFORMANCE") is True
    text = mock_post.call_args.kwargs["json"]["text"]
    assert "[DEMO] [RUNTIME PERFORMANCE] 2026-05-10" in text


@pytest.mark.unit
def test_send_daily_performance_snapshot_alert_respects_env_off(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from app.monitoring import notifier

    monkeypatch.setattr(notifier.settings, "DAILY_PERFORMANCE_TELEGRAM", False, raising=False)
    mock_post = MagicMock(return_value=MagicMock(status_code=200))
    monkeypatch.setattr(notifier.requests, "post", mock_post)
    assert notifier.send_daily_performance_snapshot_alert({"date": "2026-01-01"}) is False
    assert not mock_post.called
