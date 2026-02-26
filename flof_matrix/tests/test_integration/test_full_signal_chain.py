"""Integration test: full signal chain end-to-end.

Signal → grade → portfolio gates → execute → manage.
"""

import pytest

from flof_matrix.strategy.confluence_scorer import ConfluenceScorer, ScoringContext
from flof_matrix.execution.execution_manager import ExecutionManager
from flof_matrix.execution.trade_manager import TradeManager, ManagedPosition
from flof_matrix.risk.portfolio_manager import PortfolioManager, PositionLedgerEntry
from flof_matrix.core.types import Grade, OrderType, POIType, TradeDirection, TradePhase
from flof_matrix.core.data_types import POI


class TestFullSignalChain:
    @pytest.mark.integration
    def test_end_to_end_a_grade_trade(self):
        """Full pipeline: A-grade signal → execute → phase 1 partial."""
        # 1. Score
        scorer = ConfluenceScorer()
        poi = POI(
            type=POIType.ORDER_BLOCK, price=5000.0,
            zone_high=5002.0, zone_low=4998.0,
            timeframe="1H", direction=TradeDirection.LONG,
            has_inducement=True, is_fresh=True,
        )
        ctx = ScoringContext(
            premium_discount="discount", has_inducement=True, is_chop=False, poi=poi,
            trend_aligned=True, regime="aligned",
            has_liquidity_sweep=True, is_fresh_poi=True,
            has_choch=True, choch_displacement_exceeds_atr=True,
            order_flow_score=2, in_killzone=True,
            velez_enabled=True, has_20sma_halt=True, has_flat_200sma=False,
            has_elephant_bar=False, has_micro_trend=False,
            has_vwap_confluence=True, is_flip_zone=False, has_liquidity_near_target=False,
            entry_price=5000.0, stop_price=4990.0, target_price=5020.0,
        )
        signal = scorer.score(ctx)
        assert signal is not None
        assert signal.grade == Grade.A

        # 2. Portfolio gates
        pm = PortfolioManager(
            p1_max_total_exposure=0.06, p2_max_per_group=2,
            p3_daily_drawdown_limit=-0.02, p4_max_loss_streak=3,
            p5_lockout_seconds=300,
            correlation_groups={"A": ["ES", "NQ", "YM"]},
        )
        passed, reason = pm.evaluate_gates("ES", signal.position_size_pct, now_ns=0)
        assert passed, f"Portfolio gate failed: {reason}"

        # 3. Execute
        em = ExecutionManager(tick_size=0.25, point_value=50.0)
        bracket = em.execute_signal(signal, equity=100_000)
        assert bracket is not None
        assert bracket.entry.order_type == OrderType.MWP

        # 4. Track position
        pm.add_position(PositionLedgerEntry(
            position_id="FLOF-0001", instrument="ES", correlation_group="A",
            direction=signal.direction, risk_pct=signal.position_size_pct,
            contracts=bracket.entry.size,
        ))

        # 5. Trade management — Phase 1 partial
        tm = TradeManager(tick_size=0.25, point_value=50.0)
        pos = ManagedPosition(
            position_id="FLOF-0001", direction=signal.direction, grade=signal.grade,
            entry_price=signal.entry_price, stop_price=signal.stop_price,
            target_price=signal.target_price,
            total_contracts=bracket.entry.size, entry_time_ns=0,
        )
        tm.add_position(pos)

        result = tm.evaluate_phase1(pos, 5020.0)  # At 2R
        assert result is not None
        tm.apply_phase1_result(pos, result)
        assert pos.phase == TradePhase.PHASE2_RUNNER

    @pytest.mark.integration
    def test_rejection_chain(self):
        """Signal rejected at G1 gate."""
        scorer = ConfluenceScorer()
        poi = POI(
            type=POIType.ORDER_BLOCK, price=5000.0,
            zone_high=5002.0, zone_low=4998.0,
            timeframe="1H", direction=TradeDirection.LONG,
            has_inducement=True,
        )
        ctx = ScoringContext(
            premium_discount="premium",  # WRONG for long
            has_inducement=True, is_chop=False, poi=poi,
            trend_aligned=True, regime="aligned",
            has_liquidity_sweep=True, is_fresh_poi=True,
            has_choch=True, choch_displacement_exceeds_atr=True,
            order_flow_score=2, in_killzone=True,
            velez_enabled=True, has_20sma_halt=True, has_flat_200sma=True,
            has_elephant_bar=True, has_micro_trend=True,
            has_vwap_confluence=True, is_flip_zone=True, has_liquidity_near_target=True,
            entry_price=5000.0, stop_price=4990.0, target_price=5020.0,
        )
        assert scorer.score(ctx) is None
