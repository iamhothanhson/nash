import importlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_main_module_imports():
    module = importlib.import_module("app.main")
    assert callable(module.main)
