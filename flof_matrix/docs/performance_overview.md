# FLOF Performance Overview & Likely Degraders

This overview summarizes where results are most likely being degraded when the system is running but quality is low.

## System-level picture

FLOF uses a **funnel architecture**:

1. Structural gates (G1/G2/G3)
2. Tier-1 score gate (must pass before Tier-2/Tier-3 can help)
3. Grade threshold gate (B or better only)
4. Portfolio and risk gates
5. Trade management exits (including toxicity exits)

Low performance is often not one bug, but cumulative gate pressure and strict defaults.

## High-impact degraders

### 1) Entry over-filtering
- G2 inducement is required by default.
- Tier-1 gate minimum is 7/10.
- Killzone timing is enabled.
- Chop detector blocks directional entries in low VA/ATR sessions.

**Effect:** trade frequency can collapse, especially outside ideal sessions or when structure is valid but not fully confirmed.

### 2) Order-flow confirmation under sparse data
Order-flow scoring requires robust microstructure evidence (e.g., divergence + stacked imbalance for full points). In sparse tick environments (or synthetic ticks), these conditions trigger less often.

**Effect:** many setups lose 1-2 points and fail Tier-1/B-grade thresholds.

### 3) Layered risk throttles
RiskOverlord and portfolio controls are conservative (orders/min, daily DD, consecutive losses, exposure caps).

**Effect:** after a short adverse cluster, the system can enter reduced-opportunity mode quickly.

### 4) Early adverse-flow exits
Toxicity exit (T48) is enabled, which is protective but may cut winners before full expansion.

**Effect:** reduced average R and muted runner contribution.

## Fast diagnostic plan

1. Run a baseline backtest and record:
   - rejection counts by gate
   - trades/day
   - average R and win rate
2. Run sensitivity tests one lever at a time:
   - Tier-1 gate 7 -> 6
   - G2 required -> false
   - Keep risk controls unchanged initially
3. Confirm tick quality:
   - compare synthetic vs real tick data runs
4. Re-check whether PnL degradation is mostly from:
   - too few entries (funnel choke), or
   - poor exits / low average R

## Tooling

Use `scripts/performance_audit.py` for a quick pressure-point and rejection-gate overview.

### Recommended command

```bash
python scripts/performance_audit.py \
  --config flof_matrix/config/flof_base.toml \
  --profile futures \
  --results results/backtest_result.json \
  --top-gates 12 \
  --out results/performance_audit.json
```

This prints:
- the largest rejection bottleneck gate,
- an approximate gate funnel table,
- top rejection gates by frequency,
and saves the same core diagnostics in JSON for comparison across runs.
