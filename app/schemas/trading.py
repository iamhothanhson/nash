from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel


class SignalSchema(BaseModel):
    direction: str
    entry: float
    score: float
    grade: str


class RunResultSchema(BaseModel):
    symbol: str
    has_setup: bool
    status: Optional[str] = None
    signal: Optional[SignalSchema] = None
    details: Optional[Dict[str, Any]] = None
