"""Integration test: Fix B — No raw Market Orders, only MWP/SWP."""

import pytest

from flof_matrix.execution.execution_manager import ExecutionManager
from flof_matrix.core.types import Grade, OrderType, POIType, TradeDirection
from flof_matrix.core.data_types import POI, TradeSignal


class TestFixBOrderTypes:
    @pytest.mark.integration
    def test_no_raw_market_orders(self):
        """Fix B: All entry orders must be MWP, stops must be SWP."""
        em = ExecutionManager(
            tick_size=0.25,
            point_value=50.0,
            default_order_type="market_with_protection",
        )

        poi = POI(
            type=POIType.ORDER_BLOCK, price=5000.0,
            zone_high=5002.0, zone_low=4998.0,
            timeframe="1H", direction=TradeDirection.LONG,
        )

        for grade, risk in [(Grade.A_PLUS, 0.02), (Grade.A, 0.015), (Grade.B, 0.01)]:
            signal = TradeSignal(
                direction=TradeDirection.LONG, poi=poi,
                entry_price=5000.0, stop_price=4990.0, target_price=5020.0,
                grade=grade, score_total=14, score_tier1=10,
                score_tier2=3, score_tier3=1,
                position_size_pct=risk, order_type=OrderType.MWP,
            )

            bracket = em.execute_signal(signal, equity=100_000)
            if bracket is None:
                continue

            # CRITICAL: Entry must be MWP, never raw Market
            assert bracket.entry.order_type == OrderType.MWP, \
                f"Grade {grade.value}: entry should be MWP, got {bracket.entry.order_type}"

            # Stop must be SWP
            assert bracket.stop_loss.order_type == OrderType.STOP_WITH_PROTECTION, \
                f"Grade {grade.value}: stop should be SWP"

            # TP must be Limit
            assert bracket.take_profit.order_type == OrderType.LIMIT, \
                f"Grade {grade.value}: TP should be Limit"
