from __future__ import annotations

from monitoring.logger import log
from monitoring.messages import format_mode_event_line, strip_event_and_symbol_prefix, strip_event_prefix
from monitoring.notifier import send_alert


def emit_mode_event(mode: str, symbol: str, side: str, event: str, payload: str) -> str:
    line = format_mode_event_line(mode, symbol, side, event, payload)
    log(line)
    send_alert(line)
    return line


def emit_mode_event_with_options(
    mode: str,
    symbol: str,
    side: str,
    event: str,
    payload: str,
    *,
    to_alert: bool,
) -> str:
    line = format_mode_event_line(mode, symbol, side, event, payload)
    log(line)
    if to_alert:
        send_alert(line)
    return line
