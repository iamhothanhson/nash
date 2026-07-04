#!/usr/bin/env python3
"""Send sample Telegram messages for every live/demo alert (smoke test)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.config import settings
from app.monitoring.telegram_test_suite import (
    EXIT_DECISION_CASE_KEYS,
    REPORT_CASE_KEYS,
    all_report_test_cases,
    all_telegram_test_cases,
    run_telegram_test_suite,
)


def _parse_args() -> argparse.Namespace:
    keys = ", ".join(c.key for c in all_telegram_test_cases())
    p = argparse.ArgumentParser(
        description="Send one sample Telegram per live/demo notification path (smoke test)."
    )
    p.add_argument(
        "--mode",
        choices=("demo", "live", "both"),
        default=None,
        help="Label as DEMO, LIVE, or both. Default: both (full suite); with --report/--exit-decision: current MODE.",
    )
    p.add_argument("--symbol", default="TAOUSDT", help="Symbol used in sample payloads.")
    p.add_argument(
        "--only",
        default="",
        help=f"Comma-separated case keys to send (default: all). Keys: {keys}",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List cases without calling Telegram.",
    )
    p.add_argument(
        "--exit-decision",
        action="store_true",
        help="Send only TIME EXIT / exit-decision Telegram samples.",
    )
    p.add_argument(
        "--report",
        action="store_true",
        help="Send performance report JSON samples (RUNTIME / DAILY / MONTHLY PERFORMANCE).",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=0.35,
        help="Seconds between messages (default: 0.35).",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="Print registered test case keys and exit.",
    )
    return p.parse_args()


def _modes_from_arg(raw: str) -> tuple[str, ...]:
    if raw == "both":
        return ("demo", "live")
    return (raw,)


def _resolve_modes(args: argparse.Namespace) -> tuple[str, ...]:
    """``--report`` / ``--exit-decision``: one mode (3 msgs). Full suite: demo + live."""
    if args.mode is not None:
        return _modes_from_arg(args.mode)
    if bool(args.report) or bool(args.exit_decision):
        m = str(settings.MODE).strip().lower()
        return (m,) if m in ("demo", "live") else ("demo",)
    return ("demo", "live")


def main() -> int:
    args = _parse_args()
    if args.list:
        if bool(args.report):
            cases = all_report_test_cases(args.symbol)
        elif bool(args.exit_decision):
            exit_keys = set(EXIT_DECISION_CASE_KEYS)
            cases = [c for c in all_telegram_test_cases(args.symbol) if c.key in exit_keys]
        else:
            cases = all_telegram_test_cases(args.symbol)
        for case in cases:
            print(f"  {case.key:32} {case.title}")
        return 0

    only = [k.strip() for k in str(args.only).split(",") if k.strip()] or None
    suite_cases = None
    if bool(args.report):
        report_keys = set(REPORT_CASE_KEYS)
        only = [k for k in (only or list(REPORT_CASE_KEYS)) if k in report_keys]
        if not only:
            print("[send-telegram] --report matched no --only keys", file=sys.stderr)
            return 1
        suite_cases = all_report_test_cases(args.symbol)
    elif bool(args.exit_decision):
        exit_keys = set(EXIT_DECISION_CASE_KEYS)
        only = [k for k in (only or list(EXIT_DECISION_CASE_KEYS)) if k in exit_keys]
        if not only:
            print("[send-telegram] --exit-decision matched no --only keys", file=sys.stderr)
            return 1
    modes = _resolve_modes(args)

    print(
        f"[send-telegram] ALERTS_ENABLED={settings.ALERTS_ENABLED} "
        f"ALERTS_MODES={settings.ALERTS_MODES} modes={','.join(modes)} "
        f"dry_run={args.dry_run}"
    )

    try:
        results = run_telegram_test_suite(
            modes=modes,
            symbol=args.symbol,
            only=only,
            cases=suite_cases,
            dry_run=bool(args.dry_run),
            delay_sec=float(args.delay),
        )
    except RuntimeError as exc:
        print(f"[send-telegram] ERROR: {exc}", file=sys.stderr)
        print("Set ALERTS_ENABLED=true, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID in .env", file=sys.stderr)
        return 1

    sent = skipped = failed = 0
    for row in results:
        mode = row["mode"]
        key = row["key"]
        title = row["title"]
        if row.get("skipped") == "dry-run":
            print(f"  [dry-run] [{mode}] {key} | {title}")
            skipped += 1
            continue
        if row.get("skipped"):
            print(f"  [skip]    [{mode}] {key} | {title} — {row['skipped']}")
            skipped += 1
            continue
        if row.get("ok"):
            print(f"  [ok]      [{mode}] {key} | {title}")
            sent += 1
        else:
            print(f"  [fail]    [{mode}] {key} | {title}")
            failed += 1

    print(f"[send-telegram] done sent={sent} skipped={skipped} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
