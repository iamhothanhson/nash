from __future__ import annotations

from collections import defaultdict
from typing import Any
def print_result(result: dict) -> None:
    positions = result.get("positions", [])
    equity = result["equity_curve"]

    initial = result.get('initial_balance', 0)
    final = result['final_balance']
    print(f"Initial Capital: {initial:.2f}")
    print(f"Final Balance: {final:.2f}")
    print(f"ROI: {(final - initial) / initial * 100:.2f}%")
    print(f"Total Positions: {len(positions)}")
    winners = [p for p in positions if p.realized_pnl > 0]
    losers = [p for p in positions if p.realized_pnl <= 0]
    print(f"Win Rate: {len(winners) / max(len(positions), 1) * 100:.1f}%")
    if losers:
        wpnl = sum(p.realized_pnl for p in winners)
        lpnl = abs(sum(p.realized_pnl for p in losers))
        pf = wpnl / lpnl if lpnl else float("inf")
        print(f"Profit Factor: {pf:.2f}")
    if equity:
        peak = max(e.equity for e in equity)
        trough = min(e.equity for e in equity)
        dd = (peak - trough) / peak * 100 if peak else 0
        print(f"Max Drawdown: {dd:.2f}%")

    # Group by setup_type
    family_groups = defaultdict(list)
    family_names = {
        "breakout": "Breakout",
        "breakout_retest": "Retest",
        "pullback": "Pullback",
    }

    for p in positions:
        st = p.setup_type or "Unknown"
        if st in family_names:
            family_groups[family_names[st]].append(p)
        else:
            family_groups[st.capitalize()].append(p)

    # Sort by total net profit descending
    sorted_families = sorted(family_groups.items(), key=lambda x: sum(p.realized_pnl for p in x[1]), reverse=True)
    all_positions = sum(len(ps) for _, ps in sorted_families)

    print()
    print(f"Trend Following: {all_positions} positions:")
    for name, ps in sorted_families:
        count = len(ps)
        grades = defaultdict(int)
        for p in ps:
            grades[p.setup_grade] += 1
        grade_parts = ", ".join(f"{g}: {n}" for g, n in sorted(grades.items()))
        total_margin = sum(p.risk_amount for p in ps)
        total_pnl = sum(p.realized_pnl for p in ps)
        avg_margin = total_margin / count if count else 0
        roi = total_pnl / total_margin * 100 if total_margin else 0
        sign = "+" if total_pnl >= 0 else ""
        print(f"   - {name}: {count} positions, {grade_parts}")
        print(f"   - Avg Margin: {avg_margin:.2f} USDT, ROI: {sign}{roi:.2f}%, Net Profit: {sign}{total_pnl:.2f} USDT")


def has_enough_history(
    market_data: dict[str, Any], minimum_bars: int = 60,
) -> bool:
    for df in market_data.values():
        if len(df) < minimum_bars:
            return False
    return True
