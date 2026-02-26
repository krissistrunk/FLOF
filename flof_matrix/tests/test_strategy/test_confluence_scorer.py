"""Tests for ConfluenceScorer — each gate, each tier, grade assignment, latency."""

import time

import pytest

from flof_matrix.strategy.confluence_scorer import ConfluenceScorer, ScoringContext
from flof_matrix.core.types import Grade, OrderType, POIType, TradeDirection
from flof_matrix.core.data_types import POI


def make_poi(direction=TradeDirection.LONG, poi_type=POIType.ORDER_BLOCK, **kwargs):
    defaults = dict(
        type=poi_type, price=5000.0, zone_high=5002.0, zone_low=4998.0,
        timeframe="1H", direction=direction, has_inducement=True, is_fresh=True,
    )
    defaults.update(kwargs)
    return POI(**defaults)


def full_context(**overrides):
    """Create a full scoring context (A+ quality by default)."""
    defaults = dict(
        premium_discount="discount",
        has_inducement=True,
        is_chop=False,
        poi=make_poi(),
        trend_aligned=True,
        regime="aligned",
        has_liquidity_sweep=True,
        is_fresh_poi=True,
        has_choch=True,
        choch_displacement_exceeds_atr=True,
        order_flow_score=2,
        in_killzone=True,
        velez_enabled=True,
        has_20sma_halt=True,
        has_flat_200sma=True,
        has_elephant_bar=True,
        has_micro_trend=True,
        has_vwap_confluence=True,
        is_flip_zone=True,
        has_liquidity_near_target=True,
        entry_price=5000.0,
        stop_price=4990.0,
        target_price=5020.0,
    )
    defaults.update(overrides)
    return ScoringContext(**defaults)


class TestConfluenceScorer:
    def setup_method(self):
        self.scorer = ConfluenceScorer()

    # === Gate tests ===

    def test_g1_blocks_long_in_premium(self):
        ctx = full_context(premium_discount="premium")
        assert self.scorer.score(ctx) is None

    def test_g1_passes_long_in_discount(self):
        ctx = full_context(premium_discount="discount")
        assert self.scorer.score(ctx) is not None

    def test_g1_blocks_short_in_discount(self):
        ctx = full_context(
            premium_discount="discount",
            poi=make_poi(direction=TradeDirection.SHORT),
        )
        assert self.scorer.score(ctx) is None

    def test_g1_passes_short_in_premium(self):
        ctx = full_context(
            premium_discount="premium",
            poi=make_poi(direction=TradeDirection.SHORT),
        )
        assert self.scorer.score(ctx) is not None

    def test_g2_blocks_without_inducement(self):
        ctx = full_context(has_inducement=False)
        assert self.scorer.score(ctx) is None

    def test_g3_blocks_during_chop(self):
        ctx = full_context(is_chop=True)
        assert self.scorer.score(ctx) is None

    # === Tier 1 tests ===

    def test_tier1_gate_minimum(self):
        """Tier 1 < 7 = no trade even if total would be high."""
        ctx = full_context(
            trend_aligned=False,
            has_liquidity_sweep=False,
            has_choch=False,
            order_flow_score=0,
            in_killzone=False,
        )
        # Only fresh POI = 1 point Tier 1
        assert self.scorer.score(ctx) is None

    def test_tier1_full_score(self):
        ctx = full_context()
        signal = self.scorer.score(ctx)
        assert signal is not None
        assert signal.score_tier1 == 10

    # === Tier 2 tests ===

    def test_tier2_all_velez(self):
        ctx = full_context()
        signal = self.scorer.score(ctx)
        assert signal.score_tier2 == 4

    def test_tier2_disabled(self):
        ctx = full_context(velez_enabled=False)
        signal = self.scorer.score(ctx)
        assert signal.score_tier2 == 0

    # === Tier 3 tests ===

    def test_tier3_full(self):
        ctx = full_context()
        signal = self.scorer.score(ctx)
        assert signal.score_tier3 == 3

    # === Grade assignment ===

    def test_grade_a_plus(self):
        ctx = full_context()
        signal = self.scorer.score(ctx)
        assert signal.grade == Grade.A_PLUS
        assert signal.score_total == 17

    def test_grade_a(self):
        ctx = full_context(
            has_20sma_halt=False,
            has_flat_200sma=False,
            has_elephant_bar=False,
            has_micro_trend=False,
            has_liquidity_near_target=False,
        )
        signal = self.scorer.score(ctx)
        assert signal.score_total == 12
        assert signal.grade == Grade.A

    def test_grade_b(self):
        ctx = full_context(
            has_20sma_halt=False,
            has_flat_200sma=False,
            has_elephant_bar=False,
            has_micro_trend=False,
            has_vwap_confluence=False,
            is_flip_zone=False,
            has_liquidity_near_target=False,
        )
        signal = self.scorer.score(ctx)
        assert signal.score_total == 10
        assert signal.grade == Grade.B

    def test_grade_c_no_trade(self):
        """Score < 9 = Grade C = None."""
        ctx = full_context(
            trend_aligned=False,  # -2
            has_20sma_halt=False,
            has_flat_200sma=False,
            has_elephant_bar=False,
            has_micro_trend=False,
            has_vwap_confluence=False,
            is_flip_zone=False,
            has_liquidity_near_target=False,
        )
        signal = self.scorer.score(ctx)
        assert signal is None  # Score 8, gated by grade

    def test_synthetic_poi_capped_at_b(self):
        ctx = full_context(poi=make_poi(poi_type=POIType.SYNTHETIC_MA))
        signal = self.scorer.score(ctx)
        assert signal.grade == Grade.B

    # === Position sizing ===

    def test_a_plus_sizing(self):
        ctx = full_context()
        signal = self.scorer.score(ctx)
        assert signal.position_size_pct == 0.020

    def test_cascade_sizing(self):
        ctx = full_context(cascade_active=True)
        signal = self.scorer.score(ctx)
        assert signal.position_size_pct == 0.010  # 0.020 * 0.50

    # === Benchmark ===

    @pytest.mark.benchmark
    def test_scoring_latency(self):
        ctx = full_context()
        iterations = 10_000
        start = time.perf_counter_ns()
        for _ in range(iterations):
            self.scorer.score(ctx)
        avg_us = (time.perf_counter_ns() - start) / iterations / 1000
        assert avg_us < 500, f"Scoring too slow: {avg_us:.1f} us"
