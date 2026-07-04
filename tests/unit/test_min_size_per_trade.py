from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))


def _reload_settings(**env: str) -> object:
    for key in (
        "MIN_POSITION_PCT_OF_BALANCE",
        "MIN_POSITION_SIZE_USDT",
        "MODE",
    ):
        os.environ.pop(key, None)
    os.environ.update(env)
    project_env = PROJECT_ROOT / ".env"
    real_exists = Path.exists

    def _exists(self: Path) -> bool:
        if self.resolve() == project_env.resolve():
            return False
        return real_exists(self)

    with patch("dotenv.load_dotenv"), patch.object(Path, "exists", _exists):
        if "config.settings" in sys.modules:
            import config.settings as settings_mod

            return importlib.reload(settings_mod)
        return importlib.import_module("config.settings")


def test_min_position_pct_default() -> None:
    s = _reload_settings(MODE="demo")
    assert s.MIN_POSITION_PCT_OF_BALANCE == 10.0


def test_min_position_pct_from_env() -> None:
    s = _reload_settings(MODE="demo", MIN_POSITION_PCT_OF_BALANCE="15")
    assert s.MIN_POSITION_PCT_OF_BALANCE == 15.0


def test_min_position_size_usdt_from_env() -> None:
    s = _reload_settings(MODE="demo", MIN_POSITION_SIZE_USDT="25")
    assert s.MIN_POSITION_SIZE_USDT == 25.0


def test_min_position_size_usdt_default() -> None:
    s = _reload_settings(MODE="demo")
    assert s.MIN_POSITION_SIZE_USDT == 20.0
