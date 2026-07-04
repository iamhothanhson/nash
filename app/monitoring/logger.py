from __future__ import annotations

import atexit
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from monitoring.messages import format_bot_start_line


def _effective_settings():
    """
    Prefer app.config.settings when present so tests that patch app.config.settings.MODE
    stay consistent with code that imports config.settings (duplicate module instances).
    """
    mod = sys.modules.get("app.config.settings")
    if mod is not None:
        return mod
    from config import settings as cfg

    return cfg


_BACKTEST_LOGS_PREPARED = False
_BACKTEST_LINE_BUFFER: list[tuple[Path, str]] = []
_BACKTEST_FLUSH_THRESHOLD = 128
# Portfolio backtest CLI sets this True only with `--log`; avoids heavy daily log I/O by default.
_BACKTEST_FILE_LOG_ENABLED = False


def set_backtest_file_logging(enabled: bool) -> None:
    """When False (default), `log()` skips file writes for MODE=backtest."""
    global _BACKTEST_FILE_LOG_ENABLED, _BACKTEST_LOGS_PREPARED, _BACKTEST_LINE_BUFFER
    _BACKTEST_FILE_LOG_ENABLED = bool(enabled)
    if not _BACKTEST_FILE_LOG_ENABLED:
        _BACKTEST_LINE_BUFFER.clear()
        _BACKTEST_LOGS_PREPARED = False


def flush_backtest_log_buffer() -> None:
    """Append all buffered backtest log lines to disk (same paths as unbuffered writes)."""
    global _BACKTEST_LINE_BUFFER
    if not _BACKTEST_LINE_BUFFER:
        return
    by_file: dict[Path, list[str]] = defaultdict(list)
    for path, line in _BACKTEST_LINE_BUFFER:
        by_file[path].append(line)
    _BACKTEST_LINE_BUFFER.clear()
    for path, lines in by_file.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.writelines(lines)


atexit.register(flush_backtest_log_buffer)


def _prepare_backtest_logs(logs_dir: Path, current_log_file: Path) -> None:
    global _BACKTEST_LOGS_PREPARED
    if _BACKTEST_LOGS_PREPARED:
        return
    _BACKTEST_LOGS_PREPARED = True

    for log_file in logs_dir.glob("*.log"):
        if log_file.is_file():
            log_file.unlink()
    # Recreate today's log file using the standard date-based format.
    current_log_file.touch(exist_ok=True)


def reset_backtest_logs_for_new_run() -> None:
    """
    Force a fresh backtest log file for each backtest invocation.
    """
    global _BACKTEST_LOGS_PREPARED
    _BACKTEST_LINE_BUFFER.clear()
    _BACKTEST_LOGS_PREPARED = False
    now = datetime.now()
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    current_log_file = logs_dir / f"{now.strftime('%d-%b-%Y')}.log"
    _prepare_backtest_logs(logs_dir, current_log_file)


def log(msg: str, *, mode: str | None = None, strip_setup: bool = False) -> None:
    """Append timestamped message to daily log file."""
    now = datetime.now()
    active_mode = str(mode or _effective_settings().MODE).strip().lower()
    if active_mode == "backtest" and not _BACKTEST_FILE_LOG_ENABLED:
        return

    date_str = now.strftime("%d-%b-%Y")
    time_str = now.strftime("%H:%M:%S")

    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"{date_str}.log"
    if active_mode == "backtest":
        _prepare_backtest_logs(logs_dir, log_file)

    message = str(msg)
    if strip_setup:
        message = "\n".join(
            part for part in message.splitlines() if not part.strip().startswith("setup=")
        )
    if mode:
        message = f"[{str(mode).upper()}] {message}"

    line = f"[{time_str}] {message}\n"
    if active_mode == "backtest":
        _BACKTEST_LINE_BUFFER.append((log_file, line))
        if len(_BACKTEST_LINE_BUFFER) >= _BACKTEST_FLUSH_THRESHOLD:
            flush_backtest_log_buffer()
        return

    with log_file.open("a", encoding="utf-8") as f:
        f.write(line)


__all__ = [
    "flush_backtest_log_buffer",
    "format_bot_start_line",
    "log",
    "reset_backtest_logs_for_new_run",
    "set_backtest_file_logging",
]

