from __future__ import annotations

from fastapi import Depends
from app.marketplace.binance_marketplace import BinanceMarketplace
from app.trading_pipeline import TradingPipeline


def get_marketplace() -> BinanceMarketplace:
    """Dependency provider for BinanceMarketplace."""
    return BinanceMarketplace()


def get_pipeline(marketplace: BinanceMarketplace = Depends(get_marketplace)) -> TradingPipeline:
    """Dependency provider for TradingPipeline."""
    return TradingPipeline(marketplace=marketplace)
