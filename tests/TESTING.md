## Testing Flow

1. After normal code change: run `make test-fast`
2. If `test-fast` fails: debug with `make test-unit` or `make test-integration`
3. After major refactor/strategy/risk/execution changes: run `make test-regression`
4. Before merge/release: ensure `make test-fast` passes (and run regression for big changes)

## Test Types

### Unit tests (`tests/unit`)

- Pure function logic only
- Rounding helpers (`round_price`, `round_qty`, etc.)
- Risk/math calculations (position sizing, thresholds)
- Config/env parsing defaults and validation
- Decision helpers (score mapping, exit decision pieces)

### Integration tests (`tests/integration`)

- Small module chains (no full live loop)
- Candles -> signal -> order plan
- Staged position management TP/SL transitions
- Runtime position file load/save/merge/reconcile with temp files/fake clients
- AI routing behavior with mock/disabled modes
- Notification and lifecycle logging behavior

### Regression tests (`tests/regression`)

- End-to-end behavior checks on fixed data
- Deterministic 30d/90d backtest outputs (range/band checks)
- Full lifecycle: open -> partial close -> final close -> journal/runtime consistency
- Dust-close path behavior and fallback handling
- No-crash + key KPI guardrails (ROI, drawdown, trades) within expected bands

## Command Structure

- `test-unit` -> only unit
- `test-integration` -> only integration
- `test-fast` -> `test-unit` + `test-integration`
- `test-regression` -> regression suite only
