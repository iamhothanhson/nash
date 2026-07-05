
# Backtest
- Primary balance source: INITIAL_CAPITAL and tracking `VirtualAccount.balance`

# Demo/Live
- Primary balance source for sizing:** futures account metrics from Binance (`/fapi/v2/account`)
- Hard safety gate before order placement: `availableBalance`