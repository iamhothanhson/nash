from __future__ import annotations


def print_result(result: dict) -> None:
    trades = result["trades"]
    equity = result["equity_curve"]

    print(f"Total Trades: {len(trades)}")
    print(f"Final Balance: {result['final_balance']:.2f}")
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
