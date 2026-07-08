from __future__ import annotations

import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)
for path in (APP_DIR, ROOT_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.config import SYMBOLS
from app.exchange import BinanceMarketplace
from app.trading_pipeline import TradingPipeline

import uvicorn
from fastapi import FastAPI

app = FastAPI(
    title="Nash",
    description="FastAPI REST API wrapper for the AI Trading Bot",
    version="1.0.0",
)

def main() -> None:
    marketplace = BinanceMarketplace()
    pipeline = TradingPipeline(
        marketplace=marketplace,
    )

    for symbol in SYMBOLS:
        result = pipeline.run_symbol(symbol)
        print(f"{symbol}: {result.get('status') if isinstance(result, dict) else result}")
        if isinstance(result, dict) and result.get("signal"):
            sig = result["signal"]
            print(f"  {sig['direction']}  entry={sig['entry']:.4f}  score={sig['score']}  grade={sig['grade']}")

if __name__ == "__main__":
    main()
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)