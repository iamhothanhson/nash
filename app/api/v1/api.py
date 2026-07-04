from __future__ import annotations

from fastapi import APIRouter
from app.api.v1.endpoints import health, trading

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(trading.router, prefix="/trading", tags=["trading"])
