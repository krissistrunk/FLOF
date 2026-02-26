"""Tests for ExecutionManager — MWP orders (Fix B), OCO brackets, sizing."""

import pytest

from flof_matrix.execution.execution_manager import ExecutionManager
from flof_matrix.core.types import Grade, OrderType, TradeDirection
from flof_matrix.core.data_types import POI, TradeSignal


def make_signal(direction=TradeDirection.LONG, grade=Grade.A, risk_pct=0.015):
    poi = POI(
        type=__import__("flof_matrix.core.types", fromlist=["POIType"]).POIType.ORDER_BLOCK,
        price=5000.0, zone_high=5002.0, zone_low=4998.0,
        timeframe="1H", direction=direction,
    )
    return TradeSignal(
        direction=direction, poi=poi,
        entry_price=5000.0, stop_price=4990.0, target_price=5020.0,
        grade=grade, score_total=12, score_tier1=8, score_tier2=3, score_tier3=1,
        position_size_pct=risk_pct, order_type=OrderType.MWP,
    )


class TestExecutionManager:
    def test_position_sizing(self):
        em = ExecutionManager(tick_size=0.25, point_value=50.0)
        # 100k equity, 2% risk, 10pt stop = 2000 / 500 = 4 contracts
        assert em.calculate_position_size(100_000, 0.02, 5000.0, 4990.0) == 4

    def test_position_sizing_small_account(self):
        em = ExecutionManager(tick_size=0.25, point_value=50.0)
        # 10k equity, 1% risk, 10pt stop = 100 / 500 = 0 contracts
        assert em.calculate_position_size(10_000, 0.01, 5000.0, 4990.0) == 0

    def test_position_sizing_zero_stop(self):
        em = ExecutionManager()
        assert em.calculate_position_size(100_000, 0.02, 5000.0, 5000.0) == 0

    def test_fix_b_mwp_order_type(self):
        """Fix B: Entry must use MWP, never raw Market."""
        em = ExecutionManager(default_order_type="market_with_protection")
        signal = make_signal()
        bracket = em.execute_signal(signal, equity=100_000)
        assert bracket is not None
        assert bracket.entry.order_type == OrderType.MWP

    def test_oco_bracket_structure(self):
        em = ExecutionManager(tick_size=0.25, point_value=50.0)
        signal = make_signal()
        bracket = em.create_oco_bracket(signal, contracts=2)
        assert bracket.entry.size == 2
        assert bracket.stop_loss.order_type == OrderType.STOP_WITH_PROTECTION
        assert bracket.take_profit.order_type == OrderType.LIMIT
        # Stop should be opposite direction
        assert bracket.stop_loss.direction == TradeDirection.SHORT
        assert bracket.take_profit.direction == TradeDirection.SHORT

    def test_oco_take_profit_at_2r(self):
        em = ExecutionManager(tick_size=0.25, point_value=50.0)
        signal = make_signal()  # Entry 5000, stop 4990 → risk = 10
        bracket = em.create_oco_bracket(signal, contracts=2, target_r=2.0)
        assert bracket.take_profit.price == 5020.0  # 5000 + 2*10

    def test_oco_short_direction(self):
        em = ExecutionManager(tick_size=0.25, point_value=50.0)
        signal = make_signal(direction=TradeDirection.SHORT)
        bracket = em.create_oco_bracket(signal, contracts=2)
        assert bracket.stop_loss.direction == TradeDirection.LONG
        assert bracket.take_profit.direction == TradeDirection.LONG

    def test_execute_signal_returns_none_for_zero_size(self):
        em = ExecutionManager(tick_size=0.25, point_value=50.0)
        signal = make_signal(risk_pct=0.0001)  # Very small risk
        result = em.execute_signal(signal, equity=1_000)
        assert result is None
