from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from app.api import deps
from app.config import SYMBOLS
from app.schemas.trading import RunResultSchema
from app.trading_pipeline import TradingPipeline

router = APIRouter()


@router.get("/symbols")
def get_symbols() -> dict[str, list[str]]:
    """Get the list of configured trading symbols."""
    return {"symbols": SYMBOLS}


@router.post("/run/{symbol}", response_model=RunResultSchema)
def run_symbol(
    symbol: str,
    pipeline: TradingPipeline = Depends(deps.get_pipeline),
) -> RunResultSchema:
    """Run the trading pipeline for a specific symbol."""
    symbol_upper = symbol.strip().upper()
    if symbol_upper not in SYMBOLS:
        raise HTTPException(
            status_code=404,
            detail=f"Symbol '{symbol}' is not in the configured symbols list.",
        )

    try:
        result = pipeline.run_symbol(symbol_upper)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to run pipeline for {symbol_upper}: {str(e)}",
        )

    if result is None:
        return RunResultSchema(symbol=symbol_upper, has_setup=False, status="no_setup")

    if isinstance(result, dict):
        signal = result.get("signal")
        signal_schema = None
        if signal:
            signal_schema = {
                "direction": signal.get("direction"),
                "entry": signal.get("entry"),
                "score": signal.get("score"),
                "grade": signal.get("grade"),
            }
        return RunResultSchema(
            symbol=symbol_upper,
            has_setup=signal is not None,
            status=result.get("status"),
            signal=signal_schema,
            details={k: v for k, v in result.items() if k not in ("signal", "status")},
        )

    return RunResultSchema(symbol=symbol_upper, has_setup=False, status=str(result))


@router.post("/run-all", response_model=list[RunResultSchema])
def run_all(
    pipeline: TradingPipeline = Depends(deps.get_pipeline),
) -> list[RunResultSchema]:
    """Run the trading pipeline for all configured symbols."""
    results = []
    for symbol in SYMBOLS:
        try:
            result = pipeline.run_symbol(symbol)
            if result is None:
                results.append(
                    RunResultSchema(symbol=symbol, has_setup=False, status="no_setup")
                )
            elif isinstance(result, dict):
                signal = result.get("signal")
                signal_schema = None
                if signal:
                    signal_schema = {
                        "direction": signal.get("direction"),
                        "entry": signal.get("entry"),
                        "score": signal.get("score"),
                        "grade": signal.get("grade"),
                    }
                results.append(
                    RunResultSchema(
                        symbol=symbol,
                        has_setup=signal is not None,
                        status=result.get("status"),
                        signal=signal_schema,
                        details={
                            k: v
                            for k, v
                            in result.items()
                            if k not in ("signal", "status")
                        },
                    )
                )
            else:
                results.append(
                    RunResultSchema(symbol=symbol, has_setup=False, status=str(result))
                )
        except Exception as e:
            results.append(
                RunResultSchema(
                    symbol=symbol,
                    has_setup=False,
                    status=f"error: {str(e)}",
                )
            )
    return results
