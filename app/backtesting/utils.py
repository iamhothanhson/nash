from __future__ import annotations

from collections import defaultdict


def print_result(result: dict) -> None:
    trades = result["trades"]
    equity = result["equity_curve"]

    initial = result.get('initial_balance', 0)
    final = result['final_balance']
    print(f"Initial Capital: {initial:.2f}")
    print(f"Final Balance: {final:.2f}")
    print(f"ROI: {(final - initial) / initial * 100:.2f}%")
    print(f"Total Trades: {len(trades)}")
    winners = [t for t in trades if t.net_pnl > 0]
    losers = [t for t in trades if t.net_pnl <= 0]
    print(f"Win Rate: {len(winners) / max(len(trades), 1) * 100:.1f}%")
    if losers:
        pf = sum(t.net_pnl for t in winners) / abs(sum(t.net_pnl for t in losers)) if losers else float("inf")
        print(f"Profit Factor: {pf:.2f}")
    if equity:
        peak = max(e.equity for e in equity)
        trough = min(e.equity for e in equity)
        dd = (peak - trough) / peak * 100 if peak else 0
        print(f"Max Drawdown: {dd:.2f}%")

    # Group by setup_type
    groups = defaultdict(list)
    for t in trades:
        st = t.setup_type or "Unknown"
        groups[st].append(t)

    family_groups = defaultdict(list)
    family_names = {
        "breakout": "Breakout",
        "breakout_retest": "Retest",
        "pullback": "Pullback",
    }

    for st, ts in groups.items():
        if st in family_names:
            family_groups[family_names[st]].extend(ts)
        else:
            family_groups[st.capitalize()].extend(ts)

    # Sort by total net profit descending
    sorted_families = sorted(family_groups.items(), key=lambda x: sum(t.net_pnl for t in x[1]), reverse=True)
    all_trades = sum(len(ts) for _, ts in sorted_families)

    print()
    print(f"Trend Following: {all_trades} trades:")
    for name, ts in sorted_families:
        count = len(ts)
        total_margin = sum(t.risk_amount for t in ts)
        total_pnl = sum(t.net_pnl for t in ts)
        avg_margin = total_margin / count if count else 0
        roi = total_pnl / total_margin * 100 if total_margin else 0
        sign = "+" if total_pnl >= 0 else ""
        print(f"   - {name}: {count} trades, Avg Margin: {avg_margin:.2f} USDT, ROI: {sign}{roi:.2f}%, Net Profit: {sign}{total_pnl:.2f} USDT")
