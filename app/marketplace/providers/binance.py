from __future__ import annotations

import os
import time
from typing import Any

import requests

from config import settings
from marketplace.schemas import OHLCVRecord


def _safe_float(value: Any) -> float:
    return float(value)


def _safe_int(value: Any) -> int:
    return int(value)


def get_ohlcv(
    symbol: str,
    timeframe: str,
    limit: int,
    *,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> list[OHLCVRecord]:
    """Fetch raw OHLCV rows from Binance Futures public klines endpoint."""
    params = {
        "symbol": symbol.strip().upper(),
        "interval": timeframe,
        "limit": max(1, min(int(limit), 1500)),
    }
    if start_time_ms is not None:
        params["startTime"] = int(start_time_ms)
    if end_time_ms is not None:
        params["endTime"] = int(end_time_ms)
    session = requests.Session()
    verify_setting: bool | str = True
    ca_bundle = os.getenv("REQUESTS_CA_BUNDLE", "").strip()
    if ca_bundle:
        verify_setting = ca_bundle
    allow_insecure_ssl = os.getenv("ALLOW_INSECURE_SSL", "false").strip().lower() == "true"

    payload: list[list[Any]] | None = None
    for attempt in range(4):
        try:
            response = session.get(
                settings.BINANCE_FAPI_KLINES_URL,
                params=params,
                timeout=20,
                verify=verify_setting,
            )
            response.raise_for_status()
            payload = response.json()
            break
        except requests.exceptions.SSLError:
            if not allow_insecure_ssl:
                if attempt == 3:
                    raise
                time.sleep(2**attempt)
                continue
            response = session.get(
                settings.BINANCE_FAPI_KLINES_URL,
                params=params,
                timeout=20,
                verify=False,
            )
            response.raise_for_status()
            payload = response.json()
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2**attempt)

    rows = payload or []
    out: list[OHLCVRecord] = []
    for row in rows:
        out.append(
            {
                "time": _safe_int(row[0]),
                "open": _safe_float(row[1]),
                "high": _safe_float(row[2]),
                "low": _safe_float(row[3]),
                "close": _safe_float(row[4]),
                "volume": _safe_float(row[5]),
            }
        )
    return out
