"""
Daily loss report — aggregates position analysis records closed on a given date
and saves a structured report to data/daily/YYYY-MM-DD_loss.json.

Cron usage (end of UTC day):
  0 0 * * * cd /path/to/project && python3 app/analysis/daily_loss_report.py

Hooks also into main.py UTC day rollover and backtest day boundary.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ANALYSIS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "position_analysis"
_ANALYSIS_FILE = _ANALYSIS_DIR / "position_analysis_data.json"
_PERF_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "performance"
_REPORT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "daily"


def _journal_display_to_dt(display: str) -> datetime | None:
    try:
        return datetime.strptime(display.strip(), "%b-%d-%Y %H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _load_analysis_file() -> list[dict[str, Any]]:
    try:
        data = json.loads(_ANALYSIS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _normalize_evidence(msg: str) -> str:
    """Collapse evidence messages into a reusable label by stripping the measured value."""
    msg = re.sub(r"=\s*\d+\.?\d*", "", msg)
    msg = re.sub(r"\s+—\s+.*$", "", msg)
    msg = re.sub(r"\s+at entry.*$", "", msg)
    msg = re.sub(r"\s+before.*$", "", msg)
    msg = re.sub(r"\s+for a breakout\.?$", "", msg)
    msg = re.sub(r"\s+", " ", msg).strip().strip(".").strip()
    return msg


def build_daily_loss_report(
    date_str: str,
    *,
    total_trades: int | None = None,
    wins: int | None = None,
    write_to_disk: bool = True,
    send_telegram: bool = False,
) -> dict[str, Any] | None:
    """
    Load position analysis records closed on ``date_str`` (YYYY-MM-DD),
    aggregate loss reasons and evidence, and optionally persist + notify.

    When ``total_trades`` / ``wins`` are not provided they are derived
    from data/performance/*_statistics.json (if available).
    """
    target_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).date()

    if not _ANALYSIS_FILE.exists():
        return None

    all_records = _load_analysis_file()
    loss_records: list[dict[str, Any]] = []
    for rec in all_records:
        if rec.get("trade_context", {}).get("result") != "Loss":
            continue
        closed = rec.get("trade_context", {}).get("closed", "")
        dt = _journal_display_to_dt(closed)
        if dt is not None and dt.date() == target_date:
            loss_records.append(rec)

    if not loss_records:
        return None

    losses = len(loss_records)

    if total_trades is None or wins is None:
        perf_total, perf_wins = _count_trades_from_performance(target_date)
        if total_trades is None:
            total_trades = perf_total
        if wins is None:
            wins = perf_wins

    total_trades = total_trades or losses
    wins = wins or max(0, total_trades - losses)

    reason_counts: Counter[str] = Counter()
    evidence_counter: Counter[str] = Counter()

    for rec in loss_records:
        la = rec.get("analysis", {})
        reason = la.get("primary_reason", "Unknown")
        reason_counts[reason] += 1
        for ev in la.get("evidence", []):
            key = _normalize_evidence(str(ev.get("message", "")))
            if key:
                evidence_counter[key] += 1

    loss_summary = dict(reason_counts.most_common())
    top_evidence = [msg for msg, _ in evidence_counter.most_common(5)]

    report: dict[str, Any] = {
        "date": date_str,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "loss_summary": loss_summary,
        "top_evidence": top_evidence,
    }

    if write_to_disk:
        _REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = _REPORT_DIR / f"{date_str}_loss.json"
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if send_telegram:
        _send_telegram(report)

    return report


def _count_trades_from_performance(target_date: datetime.date) -> tuple[int, int]:
    """Read total_trade + win from data/performance/mm-yyyy_statistics.json for target_date."""
    d = target_date.isoformat()
    yyyy, mm = d.split("-")[0], d.split("-")[1]
    path = _PERF_DIR / f"{mm}-{yyyy}_statistics.json"
    if not path.is_file():
        return 0, 0
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0, 0
    days = blob.get("days", [])
    for entry in days:
        if str(entry.get("date", "")).strip()[:10] == d:
            return int(entry.get("total_trade", 0)), int(entry.get("win", 0))
    return 0, 0


def _send_telegram(report: dict[str, Any]) -> None:
    """Send a Telegram message with the loss report summary (respects ALERTS_ENABLED / ALERTS_MODES)."""
    import sys as _sys

    _root = str(Path(__file__).resolve().parent.parent)
    if _root not in _sys.path:
        _sys.path.insert(0, _root)

    from config import settings as _settings
    import requests as _requests

    if not bool(_settings.ALERTS_ENABLED):
        return
    if str(_settings.MODE).strip().lower() not in set(_settings.ALERTS_MODES):
        return

    date_str = report.get("date", "?")
    mode_tag = str(_settings.MODE).strip().upper()
    report_path = _REPORT_DIR / f"{date_str}_loss.json"
    report_json = report_path.read_text(encoding="utf-8").strip() if report_path.is_file() else json.dumps(report, indent=4)
    lines = [
        f"[{mode_tag}] [DAILY LOSS REPORT] [{date_str}]",
        report_json,
    ]
    token = str(_settings.TELEGRAM_BOT_TOKEN or "").strip()
    chat_id = str(_settings.TELEGRAM_CHAT_ID or "").strip()
    if not token or not chat_id:
        return
    try:
        resp = _requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": "\n".join(lines), "disable_web_page_preview": True},
            timeout=15,
        )
        if resp.status_code != 200:
            from monitoring.logger import log

            log(f"[LOSS REPORT] Telegram send failed | status={resp.status_code} | {resp.text[:200]}")
    except Exception as exc:
        from monitoring.logger import log

        log(f"[LOSS REPORT] Telegram send exception | {exc}")


if __name__ == "__main__":
    import argparse
    import sys as _sys
    _root = str(Path(__file__).resolve().parent.parent)
    if _root not in _sys.path:
        _sys.path.insert(0, _root)

    from config import settings as _cfg

    parser = argparse.ArgumentParser(description="Daily loss report")
    parser.add_argument("--date", type=str, default=None, help="YYYY-MM-DD (default: yesterday UTC or BACKTEST_END)")
    parser.add_argument("--dry-run", action="store_true", help="Skip Telegram, print report to stdout")
    args = parser.parse_args()

    if args.date:
        date_str = args.date
    elif _cfg.MODE == "backtest" and _cfg.BACKTEST_END:
        date_str = _cfg.BACKTEST_END[:10]
    else:
        from datetime import timedelta
        date_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    report = build_daily_loss_report(
        date_str,
        send_telegram=not args.dry_run,
    )
    if report is None:
        if not args.dry_run:
            _send_telegram({
                "date": date_str,
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "loss_summary": {},
                "top_evidence": [],
            })
        print(f"No losses closed on {date_str}")
        _sys.exit(0)
    if args.dry_run:
        print(json.dumps(report, indent=2))
    else:
        print(f"Loss report saved for {date_str}")
        _sys.exit(0)
