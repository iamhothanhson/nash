from __future__ import annotations

from pathlib import Path


def pytest_collection_modifyitems(items):
    for item in items:
        p = Path(str(item.fspath)).as_posix()
        if "/tests/unit/" in p:
            item.add_marker("unit")
        elif "/tests/integration/" in p:
            item.add_marker("integration")
        elif "/tests/regression/" in p:
            item.add_marker("regression")
