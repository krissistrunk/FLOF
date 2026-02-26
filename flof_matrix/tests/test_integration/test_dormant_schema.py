"""Integration test: Schema deactivation on DORMANT, trade_executed flag, Type C.

Verifies:
- Fix 1: Schema deactivates and ring buffer flushes on DORMANT transition
- Fix 1: Schema re-activates with fresh buffer on next killzone
- Fix 4: trade_executed flag transitions KILL → DORMANT
- Type C sudden move → DORMANT → schema drops to BASE
- Fix 6+7: Nuclear flatten resets on new session boundary
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from flof_matrix.core.ring_buffer import RingBuffer
from flof_matrix.core.types import PredatorState, SuddenMoveType
from flof_matrix.data.sentinel_feed import SentinelFeed, SchemaLevel
from flof_matrix.risk.risk_overlord import RiskOverlord
from flof_matrix.strategy.predator_state_machine import PredatorStateMachine


class TestDormantSchema:
    def _make_predator(self) -> PredatorStateMachine:
        return PredatorStateMachine(
            killzones=[{"start": "09:30", "end": "11:30"}],
        )

    @pytest.mark.integration
    def test_dormant_deactivates_schema_and_flushes_buffer(self):
        """Fix 1: Transition to DORMANT drops schema to BASE and clears ring buffer."""
        rb = RingBuffer(capacity=10_000)
        feed = SentinelFeed(ring_buffer=rb, backtest_mode=True)
        predator = PredatorStateMachine(
            killzones=[{"start": "09:30", "end": "11:30"}],
        )
        feed.on_start()

        # Wire transition callback (same as FlofStrategy.on_start)
        def on_transition(old, new):
            if new == PredatorState.DORMANT:
                feed.deactivate_killzone_schema()
            elif new == PredatorState.SCOUTING:
                feed.activate_killzone_schema()
            elif new == PredatorState.KILL:
                feed.activate_kill_schema()

        predator.register_transition_callback(on_transition)

        # Enter killzone → SCOUTING
        kz_time = datetime(2026, 1, 2, 10, 0)
        predator.evaluate_state(kz_time, 5000.0, 5.0)
        assert predator.state == PredatorState.SCOUTING
        assert feed.schema_level == SchemaLevel.KILLZONE
        assert feed.is_filling_buffer

        # Fill ring buffer with ticks
        base_ts = 1_000_000_000_000
        for i in range(500):
            feed.on_trade_tick(base_ts + i * 10_000_000, 5000.0, 10.0, 1)
        assert rb.count == 500

        # Leave killzone → DORMANT
        outside_kz = datetime(2026, 1, 2, 12, 0)
        predator.evaluate_state(outside_kz, 5000.0, 5.0)
        assert predator.state == PredatorState.DORMANT
        assert feed.schema_level == SchemaLevel.BASE
        assert rb.count == 0  # Buffer flushed

    @pytest.mark.integration
    def test_fresh_buffer_on_killzone_reentry(self):
        """Fix 1: Re-entering killzone starts with fresh (empty) ring buffer."""
        rb = RingBuffer(capacity=10_000)
        feed = SentinelFeed(ring_buffer=rb, backtest_mode=True)
        predator = self._make_predator()
        feed.on_start()

        def on_transition(old, new):
            if new == PredatorState.DORMANT:
                feed.deactivate_killzone_schema()
            elif new == PredatorState.SCOUTING:
                feed.activate_killzone_schema()

        predator.register_transition_callback(on_transition)

        # First killzone
        predator.evaluate_state(datetime(2026, 1, 2, 10, 0), 5000.0, 5.0)
        base_ts = 1_000_000_000_000
        for i in range(300):
            feed.on_trade_tick(base_ts + i * 10_000_000, 5000.0, 10.0, 1)
        assert rb.count == 300

        # Leave killzone
        predator.evaluate_state(datetime(2026, 1, 2, 12, 0), 5000.0, 5.0)
        assert rb.count == 0

        # Re-enter killzone — buffer is fresh
        predator.evaluate_state(datetime(2026, 1, 3, 10, 0), 5000.0, 5.0)
        assert predator.state == PredatorState.SCOUTING
        assert feed.schema_level == SchemaLevel.KILLZONE
        assert rb.count == 0  # Fresh buffer, no stale ticks

    @pytest.mark.integration
    def test_trade_executed_transitions_kill_to_dormant(self):
        """Fix 4: trade_executed=True causes KILL → DORMANT."""
        predator = self._make_predator()
        kz_time = datetime(2026, 1, 2, 10, 0)

        # Walk through DORMANT → SCOUTING → STALKING → KILL
        predator.evaluate_state(kz_time, 5000.0, 5.0)
        assert predator.state == PredatorState.SCOUTING

        # Force to STALKING via proximity
        predator.evaluate_state(kz_time, 5000.0, 5.0, poi_price=5002.0)
        assert predator.state == PredatorState.STALKING

        # Force to KILL
        predator.evaluate_state(
            kz_time, 5001.0, 5.0,
            poi_price=5002.0, has_choch=True, ring_buffer_ready=True,
        )
        assert predator.state == PredatorState.KILL

        # trade_executed → DORMANT
        predator.evaluate_state(
            kz_time, 5001.0, 5.0,
            trade_executed=True,
        )
        assert predator.state == PredatorState.DORMANT

    @pytest.mark.integration
    def test_type_c_forces_dormant_and_schema_base(self):
        """Type C sudden move → DORMANT → schema drops to BASE via callback."""
        rb = RingBuffer(capacity=10_000)
        feed = SentinelFeed(ring_buffer=rb, backtest_mode=True)
        predator = self._make_predator()
        feed.on_start()

        def on_transition(old, new):
            if new == PredatorState.DORMANT:
                feed.deactivate_killzone_schema()
            elif new == PredatorState.SCOUTING:
                feed.activate_killzone_schema()
            elif new == PredatorState.KILL:
                feed.activate_kill_schema()

        predator.register_transition_callback(on_transition)

        # Enter killzone → SCOUTING
        kz_time = datetime(2026, 1, 2, 10, 0)
        predator.evaluate_state(kz_time, 5000.0, 5.0)
        assert predator.state == PredatorState.SCOUTING
        assert feed.schema_level == SchemaLevel.KILLZONE

        # Fill some buffer
        for i in range(100):
            feed.on_trade_tick(1_000_000_000_000 + i * 10_000_000, 5000.0, 10.0, 1)
        assert rb.count == 100

        # Type C sudden move → DORMANT
        predator.evaluate_state(
            kz_time, 5000.0, 5.0,
            sudden_move=SuddenMoveType.TYPE_C,
        )
        assert predator.state == PredatorState.DORMANT
        assert feed.schema_level == SchemaLevel.BASE
        assert rb.count == 0


class TestFlattenResetsOnSessionBoundary:
    """Fix 6+7: Nuclear flatten must reset when a new session begins."""

    @pytest.mark.integration
    def test_flatten_resets_on_new_session(self):
        """RiskOverlord.reset_daily() clears flatten so bars resume processing."""
        risk = RiskOverlord(max_consecutive_losses=3)

        # Simulate 3 consecutive losses, then check() triggers nuclear flatten
        risk.record_loss()
        risk.record_loss()
        risk.record_loss()
        result = risk.check(now_ns=1_000_000_000_000)
        assert result["status"] == "breach"
        assert result["pillar"] == "consecutive_losses"
        assert risk.is_flattened, "Should be flattened after 3 consecutive losses + check()"

        # Simulate new session boundary → reset_daily clears flatten
        risk.reset_daily()
        assert not risk.is_flattened, "Flatten should be cleared after reset_daily"
        assert risk._consecutive_losses == 0, "Consecutive losses should reset"

    @pytest.mark.integration
    def test_flatten_does_not_block_session_boundary_in_strategy(self):
        """FlofStrategy.on_bar() calls reset_daily() before checking is_flattened.

        This verifies the fix ordering: date computation and reset happen
        before the flatten early-return, breaking the Catch-22.
        """
        from flof_matrix.nautilus.flof_strategy import FlofStrategy
        from flof_matrix.config.config_manager import ConfigManager
        from flof_matrix.core.event_bus import EventBus
        from flof_matrix.data.infra_health import InfraHealth
        from flof_matrix.data.sentinel_feed import SentinelFeed
        from flof_matrix.structure.poi_mapper import POIMapper
        from flof_matrix.structure.session_profiler import SessionProfiler
        from flof_matrix.structure.sudden_move import SuddenMoveClassifier
        from flof_matrix.order_flow.order_flow_engine import OrderFlowEngine
        from flof_matrix.order_flow.volume_profile_engine import VolumeProfileEngine
        from flof_matrix.strategy.predator_state_machine import PredatorStateMachine
        from flof_matrix.strategy.confluence_scorer import ConfluenceScorer
        from flof_matrix.strategy.velez_ma_module import VelezMAModule
        from flof_matrix.strategy.event_calendar import EventCalendar
        from flof_matrix.execution.execution_manager import ExecutionManager
        from flof_matrix.execution.trade_manager import TradeManager
        from flof_matrix.risk.portfolio_manager import PortfolioManager

        rb = RingBuffer(capacity=10_000)
        risk = RiskOverlord(max_consecutive_losses=3)
        strategy = FlofStrategy(
            config=ConfigManager(), event_bus=EventBus(), ring_buffer=rb,
            infra_health=InfraHealth(),
            sentinel_feed=SentinelFeed(ring_buffer=rb, backtest_mode=True),
            poi_mapper=POIMapper(), session_profiler=SessionProfiler(),
            order_flow_engine=OrderFlowEngine(ring_buffer=rb),
            volume_profile_engine=VolumeProfileEngine(ring_buffer=rb),
            velez_module=VelezMAModule(),
            sudden_move_classifier=SuddenMoveClassifier(),
            event_calendar=EventCalendar(),
            predator=PredatorStateMachine(),
            scorer=ConfluenceScorer(),
            execution_manager=ExecutionManager(tick_size=0.25, point_value=50.0),
            trade_manager=TradeManager(tick_size=0.25, point_value=50.0),
            portfolio_manager=PortfolioManager(),
            risk_overlord=risk,
        )
        strategy.on_start()

        # Process a bar on day 1 to set _last_session_date
        day1_bar = {
            "timestamp_ns": 1_736_780_400_000_000_000,  # ~2025-01-13 10:00 UTC
            "open": 5000.0, "high": 5010.0, "low": 4990.0,
            "close": 5005.0, "volume": 100.0,
        }
        strategy.on_bar(day1_bar)
        assert strategy._last_session_date != ""

        # Simulate nuclear flatten (3 consecutive losses + check triggers flatten)
        risk.record_loss()
        risk.record_loss()
        risk.record_loss()
        risk.check(now_ns=day1_bar["timestamp_ns"])
        assert risk.is_flattened

        # Process a bar on day 2 — should trigger reset_daily before flatten check
        day2_bar = {
            "timestamp_ns": 1_736_780_400_000_000_000 + 86_400_000_000_000,  # +1 day
            "open": 5010.0, "high": 5020.0, "low": 5000.0,
            "close": 5015.0, "volume": 100.0,
        }
        strategy.on_bar(day2_bar)

        # Flatten should be cleared by reset_daily at session boundary
        assert not risk.is_flattened, (
            "Flatten should reset on new session boundary — "
            "reset_daily() must run before the is_flattened early return"
        )
