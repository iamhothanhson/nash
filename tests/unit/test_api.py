from __future__ import annotations

import sys
from pathlib import Path
from typing import Generator

# Setup sys.path like other unit tests in this project
PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
for path in (APP_PATH, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.main import app
from app.schemas.trading import RunResultSchema

client = TestClient(app)


# A mock pipeline class to override deps.get_pipeline
class MockTradingPipeline:

    def run_symbol(self, symbol: str) -> dict | None:
        if symbol == "TAOUSDT":
            return {
                "status": "success",
                "signal": {
                    "direction": "LONG",
                    "entry": 100.0,
                    "score": 8.5,
                    "grade": "A",
                },
                "other_info": "some_extra_metadata",
            }
        return None


@pytest.fixture(autouse=True)
def override_dependencies() -> Generator[None, None, None]:
    app.dependency_overrides[deps.get_pipeline] = lambda: MockTradingPipeline()
    yield
    app.dependency_overrides.clear()


def test_health() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_symbols() -> None:
    response = client.get("/api/v1/trading/symbols")
    assert response.status_code == 200
    assert "symbols" in response.json()


def test_run_symbol_with_setup() -> None:
    response = client.post("/api/v1/trading/run/TAOUSDT")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "TAOUSDT"
    assert data["has_setup"] is True
    assert data["signal"]["direction"] == "LONG"
    assert data["details"]["other_info"] == "some_extra_metadata"


def test_run_symbol_no_setup() -> None:
    response = client.post("/api/v1/trading/run/RENDERUSDT")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "RENDERUSDT"
    assert data["has_setup"] is False
    assert data["status"] == "no_setup"


def test_run_symbol_not_found() -> None:
    response = client.post("/api/v1/trading/run/INVALID")
    assert response.status_code == 404


def test_run_all() -> None:
    response = client.post("/api/v1/trading/run-all")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    symbols_in_response = [item["symbol"] for item in data]
    assert "TAOUSDT" in symbols_in_response
    assert "RENDERUSDT" in symbols_in_response
