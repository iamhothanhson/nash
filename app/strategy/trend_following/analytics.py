"""
Trend-following analytics helpers (post-hoc aggregation).

Does not import execution or liquidity strategies. Feed closed-trade dicts from backtests
or notebooks — keys are flexible via parameters.

Example row keys: ``setup_type`` ('breakout' | 'pullback'), ``realized_pnl_usd`` or ``roi``.
"""

from __future__ import annotations

from config.constants import BREAKOUT, PULLBACK
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class SetupSliceStats:
    """Per-setup-type performance summary."""

    n: int
    wins: int
    profit_factor: float
    win_rate: float
    total_pnl: float
    total_roi: float
    avg_pnl: float
    avg_roi: float


def _f(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v else 0.0


def summarize_by_setup_type(
    trades: Iterable[Mapping[str, Any]],
    *,
    setup_key: str = "setup_type",
    pnl_key: str = "realized_pnl",
    roi_key: str = "roi",
) -> dict[str, SetupSliceStats]:
    """
    Split trades by setup (e.g. breakout vs pullback) and compute PF, WR, total ROI.

    - ``pnl_key``: prefer USD PnL if present; else 0.
    - ``roi_key``: summed for total_roi / avg when rows have ROI.
    """
    buckets: dict[str, list[Mapping[str, Any]]] = {BREAKOUT: [], PULLBACK: [], "other": []}
    for t in trades:
        if not isinstance(t, Mapping):
            continue
        st = str(t.get(setup_key, "other")).strip().upper()
        if st == BREAKOUT:
            buckets[BREAKOUT].append(t)
        elif st == PULLBACK:
            buckets[PULLBACK].append(t)
        else:
            buckets["other"].append(t)

    out: dict[str, SetupSliceStats] = {}
    for name, rows in buckets.items():
        if not rows:
            out[name] = SetupSliceStats(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
            continue
        pnl_sum = 0.0
        roi_sum = 0.0
        win_pnl = 0.0
        loss_pnl = 0.0
        wins = 0
        n = len(rows)
        for r in rows:
            p = _f(r.get(pnl_key))
            pnl_sum += p
            roi_sum += _f(r.get(roi_key))
            if p > 0:
                wins += 1
                win_pnl += p
            elif p < 0:
                loss_pnl += p
        gross_loss = abs(loss_pnl) if loss_pnl < 0 else 0.0
        pf = (win_pnl / gross_loss) if gross_loss > 1e-12 else (float("inf") if win_pnl > 0 else 0.0)
        if pf == float("inf"):
            pf = 99.99
        out[name] = SetupSliceStats(
            n=n,
            wins=wins,
            profit_factor=round(pf, 4),
            win_rate=round(wins / n, 4) if n else 0.0,
            total_pnl=round(pnl_sum, 4),
            total_roi=round(roi_sum, 4),
            avg_pnl=round(pnl_sum / n, 6) if n else 0.0,
            avg_roi=round(roi_sum / n, 6) if n else 0.0,
        )
    return out


def format_setup_summary(stats: Mapping[str, SetupSliceStats]) -> str:
    """Human-readable multi-line summary for logs or reports."""
    lines = []
    for k in (BREAKOUT, PULLBACK, "other"):
        s = stats.get(k)
        if s is None:
            continue
        lines.append(
            f"{k}: n={s.n} WR={s.win_rate:.2%} PF={s.profit_factor:.3f} "
            f"total_pnl={s.total_pnl:.4f} total_roi={s.total_roi:.4f}"
        )
    return "\n".join(lines)
