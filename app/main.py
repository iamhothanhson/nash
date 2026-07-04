from __future__ import annotations

import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)
for path in (APP_DIR, ROOT_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import uvicorn
from fastapi import FastAPI
from app.api.v1.api import api_router

app = FastAPI(
    title="Nash",
    description="FastAPI REST API wrapper for the AI Trading Bot",
    version="1.0.0",
)

app.include_router(api_router, prefix="/api/v1")


def main() -> None:
    """Run uvicorn server programmatically when app/main.py is executed directly."""
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
