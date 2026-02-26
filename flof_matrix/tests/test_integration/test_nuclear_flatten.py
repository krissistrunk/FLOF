"""Integration test: Nuclear Flatten — drawdown breach → full sequence."""

import pytest

from flof_matrix.risk.risk_overlord import RiskOverlord
from flof_matrix.core.event_bus import EventBus
from flof_matrix.core.types import EventType


class MockStrategy:
    def __init__(self):
        self.orders_cancelled = False
        self.positions_flattened = False
        self.forced_dormant = False

    def cancel_all_orders(self):
        self.orders_cancelled = True

    def flatten_all_positions(self):
        self.positions_flattened = True

    def force_dormant(self):
        self.forced_dormant = True


class TestNuclearFlatten:
    @pytest.mark.integration
    def test_drawdown_triggers_full_sequence(self):
        """Daily drawdown breach → Nuclear Flatten sequence."""
        event_bus = EventBus()
        strategy = MockStrategy()
        risk_events = []

        def on_risk_breach(event):
            risk_events.append(event)

        event_bus.subscribe_sync(EventType.RISK_LIMIT_BREACHED, on_risk_breach)

        ro = RiskOverlord(
            max_daily_drawdown_pct=-0.03,
            live_mode=False,
            event_bus=event_bus,
            strategy=strategy,
        )

        # Trigger drawdown
        ro.update_daily_pnl(-0.04)
        result = ro.check(now_ns=1_000_000_000_000)

        # Verify sequence
        assert result["status"] == "breach"
        assert result["pillar"] == "T27_daily_drawdown"

        # 1. Orders cancelled
        assert strategy.orders_cancelled

        # 2. Positions flattened
        assert strategy.positions_flattened

        # 3. RISK_LIMIT_BREACHED event published
        assert len(risk_events) == 1
        assert risk_events[0].type == EventType.RISK_LIMIT_BREACHED
        assert risk_events[0].payload["reason"] == "T27_daily_drawdown"

        # 4. Strategy forced to DORMANT
        assert strategy.forced_dormant

        # 5. Bot is flattened
        assert ro.is_flattened

    @pytest.mark.integration
    def test_stale_data_countdown(self):
        """Stale data alert → 5s countdown → Nuclear Flatten."""
        strategy = MockStrategy()
        ro = RiskOverlord(
            stale_data_countdown_seconds=5.0,
            live_mode=False,
            strategy=strategy,
        )

        base = 1_000_000_000_000
        ro.on_stale_data_alert(base)

        # Before countdown
        result = ro.check(base + 3_000_000_000)
        assert result["status"] == "ok"

        # After countdown
        result = ro.check(base + 6_000_000_000)
        assert result["status"] == "breach"
        assert result["pillar"] == "T28_stale_data"
        assert strategy.orders_cancelled

    @pytest.mark.integration
    def test_consecutive_losses_flatten(self):
        strategy = MockStrategy()
        ro = RiskOverlord(
            max_consecutive_losses=3,
            live_mode=False,
            strategy=strategy,
        )

        ro.record_loss()
        ro.record_loss()
        assert ro.check(1_000_000_000)["status"] == "ok"

        ro.record_loss()
        result = ro.check(2_000_000_000)
        assert result["status"] == "breach"
        assert strategy.forced_dormant
