from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

pytestmark = pytest.mark.unit


def _reload_settings(**env: str) -> object:
    for key in ("RECONCILE_INTERVAL_SEC",):
        os.environ.pop(key, None)
    os.environ.update(env)
    project_env = PROJECT_ROOT / ".env"
    real_exists = Path.exists

    def _exists(self: Path) -> bool:
        if self.resolve() == project_env.resolve():
            return False
        return real_exists(self)

    with patch("dotenv.load_dotenv"), patch.object(Path, "exists", _exists):
        import config.settings as settings_mod

        return importlib.reload(settings_mod)


def test_reconcile_interval_default() -> None:
    s = _reload_settings()
    assert s.RECONCILE_INTERVAL_SEC == 15.0


def test_reconcile_interval_from_env() -> None:
    s = _reload_settings(RECONCILE_INTERVAL_SEC="30")
    assert s.RECONCILE_INTERVAL_SEC == 30.0


def test_reconcile_interval_floor() -> None:
    s = _reload_settings(RECONCILE_INTERVAL_SEC="1")
    assert s.RECONCILE_INTERVAL_SEC == 3.0
