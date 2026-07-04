from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check() -> dict[str, str]:
    """Health check endpoint to verify server status."""
    return {"status": "healthy"}
