from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POSITION_HISTORY_DIR = Path("data/position_history")
RUNTIME_POSITIONS = Path("data/runtime/positions.json")


def save_runtime_position(pos: dict[str, Any]) -> None:
    """Write the current (open) position to runtime/positions.json."""
    RUNTIME_POSITIONS.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_POSITIONS.write_text(json.dumps(pos, indent=2, default=str), encoding="utf-8")


def archive_position(pos: dict[str, Any]) -> None:
    """Append the closed position to the monthly history file."""
    now = datetime.now(timezone.utc)
    month_file = POSITION_HISTORY_DIR / f"{now.strftime('%m-%Y')}.json"
    POSITION_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    history: list[dict[str, Any]] = []
    if month_file.exists():
        raw = month_file.read_text(encoding="utf-8")
        if raw.strip():
            loaded = json.loads(raw)
            history = loaded if isinstance(loaded, list) else [loaded]

    history.append(pos)
    month_file.write_text(json.dumps(history, indent=2, default=str), encoding="utf-8")
