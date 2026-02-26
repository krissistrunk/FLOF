"""Integration test: Tape velocity computation from ring buffer.

Verifies Fix 3: _compute_tape_velocity returns meaningful percentages
based on recent vs baseline tick rates.
"""

import pytest

from flof_matrix.core.ring_buffer import RingBuffer
from flof_matrix.data.sentinel_feed import SentinelFeed
from flof_matrix.data.infra_health import InfraHealth
from flof_matrix.core.event_bus import EventBus
from flof_matrix.config.config_manager import ConfigManager
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
from flof_matrix.risk.risk_overlord import RiskOverlord
from flof_matrix.database.trade_logger import TradeLogger
from flof_matrix.nautilus.flof_strategy import FlofStrategy


def _make_strategy(rb: RingBuffer | None = None) -> FlofStrategy:
    """Build a FlofStrategy with minimal wiring for tape velocity tests."""
    config = ConfigManager()
    event_bus = EventBus()
    if rb is None:
        rb = RingBuffer(capacity=500_000)
    infra = InfraHealth()
    feed = SentinelFeed(ring_buffer=rb, backtest_mode=True)
    poi_mapper = POIMapper()
    session_profiler = SessionProfiler()
    ofe = OrderFlowEngine(ring_buffer=rb)
    vpe = VolumeProfileEngine(ring_buffer=rb)
    velez = VelezMAModule()
    smc = SuddenMoveClassifier()
    calendar = EventCalendar()
    predator = PredatorStateMachine()
    scorer = ConfluenceScorer()
    em = ExecutionManager(tick_size=0.25, point_value=50.0)
    tm = TradeManager(tick_size=0.25, point_value=50.0)
    pm = PortfolioManager()
    risk = RiskOverlord()
    strategy = FlofStrategy(
        config=config, event_bus=event_bus, ring_buffer=rb,
        infra_health=infra, sentinel_feed=feed, poi_mapper=poi_mapper,
        session_profiler=session_profiler, order_flow_engine=ofe,
        volume_profile_engine=vpe, velez_module=velez,
        sudden_move_classifier=smc, event_calendar=calendar,
        predator=predator, scorer=scorer,
        execution_manager=em, trade_manager=tm,
        portfolio_manager=pm, risk_overlord=risk,
    )
    strategy.on_start()
    return strategy


class TestTapeVelocity:
    @pytest.mark.integration
    def test_returns_zero_with_empty_buffer(self):
        """No ticks → velocity is 0.0."""
        strategy = _make_strategy()
        assert strategy._compute_tape_velocity(1_000_000_000_000) == 0.0

    @pytest.mark.integration
    def test_returns_zero_with_insufficient_span(self):
        """< 30s of data → velocity is 0.0 (unstable baseline)."""
        rb = RingBuffer(capacity=500_000)
        strategy = _make_strategy(rb)

        # Push 20s of ticks (not enough for 30s baseline)
        base_ts = 1_000_000_000_000
        for i in range(200):
            rb.push(base_ts + i * 100_000_000, 5000.0, 10.0, 1)  # 100ms apart = 20s

        result = strategy._compute_tape_velocity(base_ts + 200 * 100_000_000)
        assert result == 0.0

    @pytest.mark.integration
    def test_steady_rate_returns_around_100(self):
        """Uniform tick rate → velocity ~100%."""
        rb = RingBuffer(capacity=500_000)
        strategy = _make_strategy(rb)

        # Push 60s of ticks at steady 10ms intervals (6000 ticks)
        base_ts = 1_000_000_000_000
        for i in range(6000):
            rb.push(base_ts + i * 10_000_000, 5000.0, 10.0, 1)

        result = strategy._compute_tape_velocity(base_ts + 6000 * 10_000_000)
        # Steady rate → ~100%
        assert 90.0 < result < 110.0

    @pytest.mark.integration
    def test_burst_returns_high_velocity(self):
        """Recent burst after slow period → velocity well above 100%."""
        rb = RingBuffer(capacity=500_000)
        strategy = _make_strategy(rb)

        base_ts = 1_000_000_000_000
        # 55s of slow ticks: 1 tick per 100ms = 550 ticks
        for i in range(550):
            rb.push(base_ts + i * 100_000_000, 5000.0, 10.0, 1)

        # Last 5s: burst of 500 ticks at 10ms intervals
        burst_start = base_ts + 55_000_000_000
        for i in range(500):
            rb.push(burst_start + i * 10_000_000, 5000.0, 10.0, 1)

        result = strategy._compute_tape_velocity(burst_start + 500 * 10_000_000)
        # Baseline: ~1050 ticks / 60s × 5 = ~87.5 ticks per 5s
        # Recent window: 500 ticks in 5s
        # Velocity: 500 / 87.5 * 100 ≈ 571%
        assert result > 300.0, f"Expected velocity > 300%, got {result:.1f}%"
