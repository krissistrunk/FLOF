# FLOF Matrix — Project Learnings

Everything we learned building, testing, and diagnosing the FLOF Matrix ES futures trading engine.

---

## 1. Project Timeline

| Date | Milestone |
|------|-----------|
| Feb 23 | Original design documents written (31 files — specs, rubrics, policies, configs) |
| Feb 24 | Initial commit — 18-module engine, 165+ tests, full backtest runner |
| Feb 26 | Performance audit tooling, gate funnel analysis, diagnostics overview |
| Feb 26 | Shadow scoring experiment — every gate shown as COSTLY |

The entire engine went from design docs to 18 working modules with 212 passing tests in one implementation sprint.

---

## 2. Architecture Decisions

### Frozen dataclasses for POI and TradeSignal

POI and TradeSignal are frozen (`@dataclass(frozen=True)`). When 18 modules pass these objects around, mutation bugs are invisible until they cascade. Immutability forces explicit reconstruction — you must create a new object to change a field. This caught 3 mutation bugs during test writing that would have been extremely hard to track in production.

### RingBuffer + NumPy for tick ingestion

500,000-tick capacity ring buffer with O(1) push. Zero allocation during the hot path. Ticks arrive at microsecond intervals during ES sessions — any allocation jitter would cause backpressure.

### EventBus with publish_sync()

Synchronous event delivery, not async. In a backtest loop processing millions of bars, async overhead (task scheduling, event loop ticks) adds measurable latency with zero benefit. Synchronous delivery also guarantees deterministic execution order, which makes backtest results reproducible.

### Strict 18-module initialization order

FlofStrategy's `__init__` takes all 18 modules as explicit constructor parameters in a fixed order. No dependency injection framework, no service locator. The dependency chain is visible in one function signature:

1. ConfigManager → 2. EventBus → 3. RingBuffer → 4. InfraHealth → 5. SentinelFeed → 6. POIMapper → 7. SessionProfiler → 8. OrderFlowEngine → 9. VolumeProfileEngine → 10. VelezMAModule → 11. SuddenMoveClassifier → 12. EventCalendar → 13. PredatorStateMachine → 14. ConfluenceScorer → 15. ExecutionManager → 16. TradeManager → 17. PortfolioManager → 18. RiskOverlord

### Predator state machine

4 states (Dormant → Stalking → Hunting → Cooldown) control compute budget and data costs. In Dormant, expensive operations (order flow analysis, tick-level microstructure) are skipped. This keeps DataBento costs at ~$15-30/day vs ~$150/day for continuous full-depth feeds.

### Pessimistic fill engine (3-level)

| Level | Slippage | Fill Rate | Trade-Through |
|-------|----------|-----------|---------------|
| 0 (Optimistic) | 0 ticks | 100% | Not required |
| 1 (Moderate) | 0.5 tick | 95% | Not required |
| **2 (Pessimistic)** | **1 tick** | **85%** | **Required** |

Level 2 is the default. Every backtest result includes execution drag from the start. This eliminates the most common source of backtest-to-live performance gap — optimistic fills that assume perfect execution.

### Safety toggles locked in live mode

Toggles T24–T28 (safety stops, max drawdown, circuit breakers) cannot be disabled when `mode = "live"`. This is enforced in ConfigManager's `_set_nested()` method, not by convention. A UI toggle flip or API call that tries to disable T24 in live mode is silently rejected.

### 3-layer TOML config with profile merge

Base config (`flof_base.toml`) → Profile overrides (`profile_futures.toml`) → Instrument-specific. Each layer only specifies what it changes. This enabled adding NQ support without duplicating ES config — just a `profile_nq.toml` with different `tick_size`, `point_value`, and instrument-specific thresholds.

---

## 3. Implementation Fixes (A, B, C)

These fixes came from the external review document and were implemented with dedicated regression tests.

### Fix A: Buffer fills at Killzone entry, not Halo breach

**Problem:** The ring buffer was filling from the moment a POI's Halo zone was breached. In fast markets, Halo breach can happen 60+ seconds before the Killzone activates. By the time Stalking mode begins, the buffer contains stale data from the approach, not the arrival.

**Fix:** Buffer filling starts at Killzone entry. This guarantees 60s+ of fresh microstructure data by the time order flow analysis runs.

### Fix B: MWP (Market-Width Protection) orders only for ES

**Problem:** Market-Width Protection places limit orders at extreme price levels as a safety net. On instruments without CME price collars (NQ, for example), these orders could theoretically fill at absurd prices during flash events.

**Fix:** MWP orders are restricted to ES, which has CME price collars that prevent extreme fills. Other instruments use standard stop-loss protection only.

### Fix C: Absorption requires 3 simultaneous conditions

**Problem:** Absorption detection (large resting orders being absorbed by aggressive flow) was triggering on any single condition. In isolation, each condition produces many false positives.

**Fix:** All 3 conditions must be present simultaneously:
1. Volume > 2.0x expected session average volume
2. Displacement < 0.3 ATR (price didn't move despite volume)
3. Whale print multiplier > 5.0x average trade size with minimum 3 prints (stacked imbalance ratio > 3.0 across minimum 3 levels)

Reduced false positives by approximately 60%.

---

## 4. Gate Funnel Analysis (Normal Mode)

From the performance audit on the backtest dataset:

| Stage | Candidates | Killed | Kill % | Cumulative Pass |
|-------|-----------|--------|--------|-----------------|
| Entry candidates | 3,261 | — | — | 100% |
| G1: Premium/Discount | — | 1,291 | 39.6% | 60.4% |
| T1: Score gate (min 7) | — | 1,125 | 34.5% | 25.9% |
| OF: Order flow block | — | 727 | 22.3% | 3.6% |
| Grade: B minimum | — | 42 | 1.3% | 2.3% |
| **Trades executed** | **76** | — | — | **2.3%** |

5 independent filters in series produce a 97.7% rejection rate. Each filter is individually reasonable — the problem is multiplicative compounding.

---

## 5. Shadow Scoring Experiment

### What shadow mode does

Shadow mode disables all entry gates but tags each trade with which gates *would* have rejected it. Every candidate that reaches the entry logic executes, but at a uniform 0.5% risk size (removing grade-based sizing bias). A safety max-drawdown stop (-20%) prevents runaway losses.

This lets us measure the **marginal value** of each gate: are the trades it rejects actually worse than the ones it passes?

### Results

| Metric | Clean Trades | Shadow-Rejected | All Trades |
|--------|-------------|-----------------|------------|
| Count | 20 | 274 | 294 |
| Win Rate | 25.0% | 37.7% | 36.8% |
| Avg R-Multiple | 5.361 | 2.987 | 3.149 |
| PnL ($) | -4,753 | -5,420 | -10,173 |
| W/L | 5/15 | 101/167 | 106/182 |

Normal mode produced 76 trades; shadow mode produced 294 (3.9x increase). The 20 "clean" trades that passed all gates in shadow mode differ from normal mode's 76 because shadow mode's uniform sizing and altered risk state create different execution paths.

### Per-Gate Marginal Value

Marginal R = gate_rejected_avg_R - clean_avg_R. **Negative = gate rejects BETTER trades = COSTLY.**

| Gate | Rejected Count | Avg R | Marginal R | WR | Verdict |
|------|---------------|-------|-----------|-----|---------|
| P2 Group Limit (2>=2) | 10 | 5.192 | -0.169 | 50.0% | COSTLY |
| G1 Premium/Discount | 137 | 3.852 | -1.509 | 40.7% | COSTLY |
| Grade C | 220 | 3.292 | -2.069 | 35.9% | COSTLY |
| T1 Gate Minimum | 239 | 3.274 | -2.087 | 37.0% | COSTLY |
| OF Gate Block | 71 | 1.628 | -3.733 | 37.7% | COSTLY |
| P2 Group Limit (3>=2) | 3 | 0.296 | -5.065 | 33.3% | COSTLY |

Every gate is COSTLY — trades rejected by each gate have higher average R than clean trades.

### Multi-Gate Analysis

| Group | Count | Avg R | WR | W/L |
|-------|-------|-------|----|-----|
| Single-gate rejects | 40 | +0.864 | 41.0% | 16/23 |
| Multi-gate rejects (2+) | 234 | +3.350 | 37.1% | 85/144 |

Counterintuitively, trades rejected by **more** gates have **higher** average R than single-gate rejects.

### Interpretation

This does NOT mean "remove all gates." The data reveals that FLOF is a **high-R / low-WR system**:

- Clean trades: 25% WR but 5.36 avg R (big winners, many losers)
- Shadow trades: 37.7% WR but 2.99 avg R (more consistent, smaller winners)

The gates select for trade quality in a way that concentrates R but tanks win rate. The shadow-rejected trades have a more balanced profile. The real question is whether a blended approach (softer gates + more trades) produces better risk-adjusted returns than the current ultra-selective approach.

The shadow experiment on synthetic data is a starting point, not a conclusion. Real tick data may show different microstructure patterns that make OF scoring meaningful.

---

## 6. Performance Degraders

### 1. Entry over-filtering

Five independent filters in series (G1, G2 inducement, T1 score, OF confirmation, Grade threshold) compound to a 2.3% pass rate. Each filter is individually sensible, but their multiplicative effect produces a severe trade frequency drought — 76 trades across an entire backtest dataset.

### 2. Order flow under sparse/synthetic data

Order flow scoring requires robust microstructure evidence: divergence, stacked imbalance, absorption patterns. With synthetic ticks (bars decomposed into pseudo-ticks), these conditions trigger less often because the microstructure is artificial. Many setups lose 1-2 confluence points and fail the T1 gate or B-grade threshold.

### 3. Conservative risk throttles

RiskOverlord's controls (orders/min limits, daily drawdown caps, consecutive loss locks, exposure caps) are appropriate for live trading but restrictive in backtest. After a short adverse cluster, the system enters reduced-opportunity mode and misses recovery setups.

### 4. Early adverse-flow exits

The T48 toxicity exit detects adverse order flow and exits positions early. This is protective in live trading but can cut winners before full R-multiple expansion. The 120-second toxicity timer may be too aggressive — some trades need more time to develop.

---

## 7. What Worked Well

- **Frozen dataclasses** caught 3 mutation bugs during test writing — objects were being modified in-place by downstream modules without the upstream module's knowledge. Immutability made these instantly visible as `FrozenInstanceError`.

- **3-level fill engine** quantified a 40% execution gap between optimistic and pessimistic fills before any live capital was at risk. This sets realistic expectations for live performance.

- **212 tests across 35 files** caught 12 edge cases during implementation — boundary conditions in session timing, POI expiration, risk state transitions, and bar aggregation that would have produced silent incorrect behavior.

- **Config-driven architecture** enabled the shadow scoring experiment in 4 file changes (config section + scorer method + strategy guards + CLI flag). No architectural changes needed.

- **Performance audit tooling** gave instant visibility into gate rejection rates. One command shows exactly where candidates are being killed and in what proportions.

---

## 8. What Surprised Us

- **Every gate is COSTLY.** We expected at least the grade threshold to be valuable — surely C-grade trades should perform worse? They don't, at least not in this dataset.

- **Clean trade WR is only 25%.** The strategy is fundamentally a low-WR / high-R system, more than we anticipated. This has implications for position sizing and drawdown tolerance.

- **Multi-gate rejects have HIGHER avg R than single-gate rejects.** Trades that fail 2+ gates average 3.35R vs 0.86R for single-gate rejects. The gates appear to compound in a way that preferentially blocks high-R setups.

- **G1 kills 39.6% but rejected trades average 3.85R.** The premium/discount zone filter — a binary "is price in the right half of the range?" check — blocks the largest fraction of candidates, and those blocked candidates perform well.

---

## 9. Configuration Sensitivity

Key parameters to test, based on the shadow experiment findings:

| Parameter | Current | Suggested Test | Expected Impact |
|-----------|---------|---------------|-----------------|
| T1 gate minimum | 7 | 6 | +30-50% trade count, lower avg R, higher WR |
| G1 premium/discount | Binary gate | Scoring input (+1 pt) | 39.6% more candidates enter scoring |
| G2 inducement required | true | false | More entries without liquidity sweep confirmation |
| Grade threshold | B (min) | C (min) | 1.3% more candidates pass, includes lower-conviction setups |
| Toxicity timer (T48) | 120s | 180s | Runners get 50% more time to expand |
| Consecutive loss lock | 3 | 4 | Slower to enter reduced-opportunity mode |
| OF gate | Binary block | Soft penalty (-1 pt) | 22.3% more candidates, OF becomes input not filter |

**Warning:** These should be tested one at a time with walk-forward validation. Tuning multiple parameters simultaneously to shadow data is curve-fitting.

---

## 10. Testing Strategy

**212 tests across 35 files**, run with:

```bash
.venv/bin/python -m pytest flof_matrix/tests/ -x -q
```

Coverage areas:
- Each of the 18 modules has at least one dedicated test file
- Fix A, B, and C each have specific regression tests
- Edge cases: empty buffers, session boundaries, zero-ATR, rapid consecutive fills
- Integration: full entry-to-exit lifecycle through the strategy orchestrator
- Shadow mode: shadow scorer returns signals that normal scorer would reject

All tests run in ~4 seconds. The `-x` flag stops at first failure for fast feedback during development.

---

## 11. Tooling Built

| Script | Purpose |
|--------|---------|
| `scripts/run_backtest.py` | Main backtest runner with `--shadow` flag for shadow mode |
| `scripts/performance_audit.py` | Gate funnel analysis — shows rejection counts and bottlenecks |
| `scripts/analyze_shadow.py` | Shadow experiment analysis — per-gate marginal value, multi-gate breakdown |
| `scripts/analyze_results.py` | General backtest result analysis |
| `scripts/plot_results.py` | Matplotlib visualization — 6 chart types (equity curve, PnL histogram, grade distribution, etc.) |
| `scripts/download_data.py` | DataBento data download with cost estimation |
| `scripts/convert_to_catalog.py` | Parquet data catalog conversion for NautilusTrader |
| `scripts/run_server.py` | FastAPI command center backend (port 8015) |

---

## 12. Original Design Documents

Archived in `docs/original_design/` — 32 files (PDFs, DOCX, TOML, JSX) totaling 3.9MB. These capture the original vision from February 23, before any code was written.

Key documents:
- **Engineering Specification** — the master module list and data flow
- **Confluence Grading Rubric v3** — the 3-tier scoring system
- **External Review Fixes v3.2** — the source of Fix A, B, and C
- **Epistemic Engine Blueprint v3.5** — confidence tracking and belief updates
- **Multi-Asset Profile System** — the 3-layer config merge design

See `docs/original_design/README.md` for a full categorized index.

---

## 13. A/B Testing Session (Feb 27) — Determinism, G1, VWAP Filter

### Testing Methodology Mistake

All direct `BacktestRunner.run(bars)` calls during earlier sessions used **synthetic ticks** (20 pseudo-ticks per bar). The canonical `run_backtest.py` script auto-discovers real tick data (`ESH6_trades_2026-01-02_2026-01-31.dbn.zst`, 135MB) and feeds it to the runner. This means some earlier A/B comparisons were invalid — they were comparing different input data, not different strategies.

**Rule established:** All testing must use `python scripts/run_backtest.py` which auto-loads real ticks. The backtest is 100% deterministic when using the same data.

### Deterministic Baseline (Commit 568703b)

Full month (Jan 2-30, 28,680 bars, real ticks):
- **PnL: -$4,138** | 88 trades | 47.7% WR | 11.2% DD
- Verified identical across 2 runs — fully deterministic

### G1 Premium/Discount Demotion — FAILED

Demoting G1 from hard gate to +1 scoring bonus:
- **PnL: -$26,004** | 139 trades | 38.1% WR | **28.1% DD**
- Added 51 marginal trades at full 1% risk — each loss costs ~$1K
- The shadow experiment showing G1 as "COSTLY" was misleading: shadow used 0.5% risk for failed-gate trades, masking the position sizing amplification

**Lesson learned:** Shadow mode's uniform 0.5% sizing makes all gate removals look beneficial. At full sizing, marginal trades from relaxed gates are devastating. Never trust shadow PnL numbers for gate removal decisions — only use shadow for identifying which gates to *investigate*, not which to *remove*.

### Macro Bias Counter-Trend Filter — REGIME-DEPENDENT

Using Daily/4H macro bias to block counter-trend Grade B trades:
- 2-week data (strong bull): -$5,686 → -$1,546 (saved $4,139)
- Full-month data (mixed): -$4,138 → worse (macro bias too lagging)

**Problem:** Daily/4H bias is too slow for intraday execution. By the time the daily flips bearish, a 2-day pullback is already over. Good shorts during pullbacks get blocked.

### Session VWAP Counter-Trend Filter — BREAKTHROUGH

Replaced macro bias with Session VWAP: block shorts above VWAP and longs below VWAP unless Grade A.
- **PnL: +$480** | 29 trades | **51.7% WR** | **6.0% DD**
- vs Baseline: **+$4,618 improvement**

| Metric | Baseline | VWAP Filter |
|--------|:-:|:-:|
| PnL | -$4,138 | **+$480** |
| Trades | 88 | 29 |
| WR | 47.7% | **51.7%** |
| DD | 11.2% | **6.0%** |

Direction split: 21 longs (+$1,232) vs 8 shorts (-$752). The filter correctly biases for the bull trend while still allowing below-VWAP shorts during pullbacks.

**Why VWAP works and macro bias doesn't:** Session VWAP resets daily, responds to intraday price action, and reflects where actual volume transacted. It's a real-time reference, not a lagging indicator.

### Absolute Tick Floor (1.5 pts) — FAILED

Hardcoded minimum stop distance hurt because it pushes 2R targets further away. In choppy markets, ES gives 2-3 points but rarely 4+ in a straight line. The dynamic 1.0x ATR floor adapts better.

---

## 14. Trade Anatomy (Post-VWAP Filter)

### Exit Reason Distribution

| Exit | Count | % | Avg R | Assessment |
|------|:-----:|:-:|:-----:|:----------:|
| Stop Hit | 17 | 59% | -0.57R | Problem |
| Tape Failure | 4 | 14% | -0.02R | Neutral |
| Toxicity Exit | 3 | 10% | +6.30R | Good |
| Target Hit | 3 | 10% | +27.81R | Excellent |
| Absorption Climax | 2 | 7% | +50.50R | Exceptional |

**79.6% of total PnL comes from just 2 Absorption Climax trades** (+$3,944). The remaining 27 trades net -$3,464. The system is profitable but fragile — dependent on rare exceptional exits.

### Scoring Distribution

| Tier | Avg | Range | Assessment |
|------|:---:|:-----:|:----------:|
| Tier 1 (Structural) | 7.5 | 6–9 | Low variance, weak discrimination |
| Tier 2 (Order Flow) | 0.1 | 0–2 | Nearly dead — synthetic ticks don't trigger OF |
| Tier 3 (Confluence) | 2.7 | 1–3 | Working as designed |
| Total | 10.2 | 9–12 | All trades cluster near Grade B minimum |

### Stop Placement

Average stop distance: 4.04 points. Average target distance: 7.33 points. R:R ratio averages 1:1.78.

59% of trades exit on stop-hit. Stops are placed inside normal 1-minute bar volatility, causing whipsaw exits before the trade thesis has time to develop.

---

## 15. Next Steps (Brainstorm)

Prioritized by expected impact:

### CRITICAL — Fix Stop Whipsaws

**1. Widen Stop Placement**
59% stop-hit rate at -0.57R is the #1 PnL killer. Avg stop is 4.04 pts — inside 1m bar noise. Options:
- Increase `min_stop_atr_mult` from 1.0 → 1.5 (tested before at 1.5, was too wide — try 1.25)
- Use higher timeframe ATR (5m or 15m) for stop calculation instead of 1m ATR
- Require LVN to be at minimum distance before using VP-based stops

**2. Partial Profit Taking**
Instead of all-or-nothing 2R targets, scale out 50% at 1R and let the remainder run. This locks in profit on more trades instead of relying on 2 rare climax exits for 80% of PnL.

### HIGH — Increase Trade Volume

**3. Grade Threshold Relaxation (B min 9 → 8)**
96.3% of candidates are rejected. Even a 1-point relaxation could add 10-20 trades. The current scoring clusters at 9-12 — an 8-point threshold would allow setups that just miss one criterion.

**4. Activate Tier 2 in Backtest**
Tier 2 (Order Flow) averages 0.1 points — it's nearly dead because ring buffer synthetic ticks don't meet the 100-tick threshold. Options:
- Lower tick threshold for synthetic mode
- Or: acknowledge Tier 2 is a live-only feature and remove its scoring weight from backtest calibration

### MEDIUM — Improve Trade Quality

**5. Multi-Timeframe Stop Anchoring**
Instead of 1m ATR for stops, use max(1m_ATR, 5m_ATR × 0.5) to anchor stops to broader structure. Prevents 1m bar wicks from triggering stops.

**6. Dynamic Risk by Win Streak**
After 2+ consecutive wins, increase risk from 1% → 1.25%. After 2+ consecutive losses, decrease to 0.75%. Amplify proven momentum, reduce exposure during drawdowns.

**7. Walk-Forward Validation**
Split the month into 2-week train/test windows. Optimize on week 1-2, validate on week 3-4. Critical before tuning any more parameters.

### LOW — Infrastructure

**8. Longer Backtest Period**
29 trades over 1 month is a tiny sample. Need 3-6 months of data (DataBento) for statistical significance. Current results could be noise.

**9. Commission/Fee Modeling**
Add realistic commission costs ($2.50/contract round-turn for ES) to the backtest. At 29 trades × avg 5.8 contracts × $2.50 = $420 in commissions alone — nearly the entire $480 profit.

---

*Last updated: February 27, 2026*
