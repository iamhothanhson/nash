# core/logger.py

from __future__ import annotations

import logging
from enum import Enum


logger = logging.getLogger("Nash")


class LogType(str, Enum):
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    POSITION = "POSITION"
    RISK = "RISK"
    EXECUTOR = "EXECUTOR"
    MARKET = "MARKET"
    ERROR = "ERROR"


def log(
    log_type: LogType,
    symbol: str | None,
    msg: str,
) -> None:
    prefix = f"[{log_type.value}]"

    if symbol:
        prefix += f" [{symbol}]"

    logger.info("%s %s", prefix, msg)


def log_error(
    log_type: LogType,
    symbol: str | None,
    msg: str,
    exc: Exception | None = None,
) -> None:
    prefix = f"[{log_type.value}]"

    if symbol:
        prefix += f" [{symbol}]"

    if exc:
        logger.exception("%s %s", prefix, msg)
    else:
        logger.error("%s %s", prefix, msg)