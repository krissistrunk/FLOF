"""FlofStrategy — Main NautilusTrader Strategy that composes all FLOF modules.

This is the ONLY module that sends orders. Composes:
  ExecutionManager, TradeManager, PortfolioManager, ConfluenceScorer,
  PredatorStateMachine, OrderFlowEngine, and all structural modules.

Initialization order (from Scaffolding v4.0):
  1. ConfigManager → 2. EventBus → 3. RingBuffer → 4. InfraHealth →
  5. SentinelFeed → 6. HTFStructureMapper → 7. POIMapper →
  8. SessionProfiler → 9. OrderFlowEngine → 10. VolumeProfileEngine →
  11. VelezMAModule → 12. SuddenMoveClassifier → 13. EventCalendar →
  14. PredatorStateMachine → 15. ConfluenceScorer → 16. PortfolioManager →
  17. RiskOverlord → 18. FlofStrategy
"""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np

from flof_matrix.config.config_manager import ConfigManager
from flof_matrix.core.event_bus import EventBus
from flof_matrix.core.ring_buffer import RingBuffer
from flof_matrix.core.types import (
    EventType,
    Grade,
    OrderType,
    POIType,
    PredatorState,
    SuddenMoveType,
    TradeDirection,
    TradePhase,
)
from flof_matrix.core.data_types import Event, POI, TradeSignal
from flof_matrix.data.infra_health import InfraHealth
from flof_matrix.data.sentinel_feed import SchemaLevel, SentinelFeed
from flof_matrix.structure.htf_structure_mapper import (
    evaluate_macro_bias,
    evaluate_premium_discount,
    calculate_regime,
)
from flof_matrix.structure.poi_mapper import POIMapper
from flof_matrix.structure.session_profiler import SessionProfiler
from flof_matrix.structure.sudden_move import SuddenMoveClassifier
from flof_matrix.order_flow.order_flow_engine import OrderFlowEngine
from flof_matrix.order_flow.volume_profile_engine import VolumeProfileEngine
from flof_matrix.strategy.predator_state_machine import PredatorStateMachine
from flof_matrix.strategy.confluence_scorer import ConfluenceScorer, ScoringContext
from flof_matrix.strategy.velez_ma_module import VelezMAModule
from flof_matrix.strategy.event_calendar import EventCalendar
from flof_matrix.execution.execution_manager import ExecutionManager
from flof_matrix.execution.trade_manager import TradeManager, ManagedPosition
from flof_matrix.nautilus.fill_engine import PessimisticFillEngine
from flof_matrix.risk.risk_overlord import RiskOverlord
from flof_matrix.risk.portfolio_manager import PortfolioManager, PositionLedgerEntry
from flof_matrix.database.trade_logger import TradeLogger

logger = logging.getLogger(__name__)


class FlofStrategy:
    """Main strategy orchestrator. Composes all FLOF modules.

    In backtest mode this operates without NautilusTrader's Strategy base class,
    processing bars and ticks manually. For live trading, subclass
    nautilus_trader.trading.strategy.Strategy and delegate to this class.
    """

    def __init__(
        self,
        config: ConfigManager,
        event_bus: EventBus,
        ring_buffer: RingBuffer,
        infra_health: InfraHealth,
        sentinel_feed: SentinelFeed,
        poi_mapper: POIMapper,
        session_profiler: SessionProfiler,
        order_flow_engine: OrderFlowEngine,
        volume_profile_engine: VolumeProfileEngine,
        velez_module: VelezMAModule,
        sudden_move_classifier: SuddenMoveClassifier,
        event_calendar: EventCalendar,
        predator: PredatorStateMachine,
        scorer: ConfluenceScorer,
        execution_manager: ExecutionManager,
        trade_manager: TradeManager,
        portfolio_manager: PortfolioManager,
        risk_overlord: RiskOverlord,
        trade_logger: TradeLogger | None = None,
        fill_engine: PessimisticFillEngine | None = None,
    ) -> None:
        self._config = config
        self._event_bus = event_bus
        self._ring_buffer = ring_buffer
        self._infra_health = infra_health
        self._sentinel_feed = sentinel_feed
        self._poi_mapper = poi_mapper
        self._session_profiler = session_profiler
        self._ofe = order_flow_engine
        self._vpe = volume_profile_engine
        self._velez = velez_module
        self._smc = sudden_move_classifier
        self._calendar = event_calendar
        self._predator = predator
        self._scorer = scorer
        self._execution = execution_manager
        self._trade_manager = trade_manager
        self._portfolio = portfolio_manager
        self._risk = risk_overlord
        self._trade_logger = trade_logger
        self._fill_engine = fill_engine

        # State
        self._equity: float = 100_000.0
        self._point_value: float = config.get("execution.point_value", 50.0)
        self._equity_curve: list[tuple[int, float]] = []
        self._peak_equity: float = self._equity
        self._max_drawdown: float = 0.0
        self._max_drawdown_pct: float = 0.0
        self._current_price: float = 0.0
        self._atr: float = 5.0
        self._macro_bias: TradeDirection | None = None
        self._regime: str = "neutral"
        self._range_high: float = 0.0
        self._range_low: float = 0.0
        self._active_pois: list[POI] = []
        self._trade_count: int = 0
        self._trades: list[dict] = []
        self._rejections: list[dict] = []

        # Shadow scoring mode
        self._shadow_mode: bool = config.get("shadow.enabled", False)
        self._shadow_safety_dd: float = config.get("shadow.safety_max_drawdown_pct", -0.20)

        # Bar history for structural analysis
        self._bar_buffer: list[dict] = []
        self._bar_buffer_max: int = 500  # Rolling window
        self._bar_buffer_2m: list[dict] = []  # Aggregated 2m bars for Velez
        self._pending_1m_bar: dict | None = None  # Buffer for 2m aggregation
        self._session_bars: list[dict] = []  # Current session bars
        self._prev_day_high: float = 0.0
        self._prev_day_low: float = 0.0
        self._session_high: float = 0.0
        self._session_low: float = 0.0
        self._last_session_date: str = ""
        self._bars_since_poi_scan: int = 0
        self._poi_scan_interval: int = 5  # Scan POIs every N bars
        self._session_sweep_detected: bool = False  # Sticky per session

        # HTF bar aggregation
        self._daily_bars: list[dict] = []
        self._4h_bars: list[dict] = []
        self._bars_since_4h: int = 0
        self._4h_open: float = 0.0
        self._4h_high: float = 0.0
        self._4h_low: float = float("inf")
        self._4h_volume: float = 0.0
        self._4h_ts: int = 0
        self._session_open: float = 0.0
        self._session_volume: float = 0.0

        # Real tick mode — set by BacktestRunner when ticks are provided
        self._use_real_ticks: bool = False

        # Give RiskOverlord a reference to this strategy
        self._risk.set_strategy(self)

    def on_start(self) -> None:
        """Initialize strategy."""
        self._sentinel_feed.on_start()
        self._trade_just_executed = False
        self._predator.register_transition_callback(self._on_predator_transition)
        logger.info("FlofStrategy started")

    def _on_predator_transition(self, old_state: PredatorState, new_state: PredatorState) -> None:
        """Schema management on every predator state change."""
        if new_state == PredatorState.DORMANT:
            self._sentinel_feed.deactivate_killzone_schema()
        elif new_state == PredatorState.SCOUTING:
            self._sentinel_feed.activate_killzone_schema()
        elif new_state == PredatorState.KILL:
            self._sentinel_feed.activate_kill_schema()

    def on_bar(self, bar) -> None:
        """Process a new bar. Main coordination loop.

        Orchestrates: HTF update → POI scan → Session update → Predator state →
        Confluence score → Portfolio gates → Execute
        """
        timestamp_ns = bar.get("timestamp_ns", 0) if isinstance(bar, dict) else getattr(bar, "ts_event", 0)
        o = bar.get("open", 0.0) if isinstance(bar, dict) else getattr(bar, "open", 0.0)
        h = bar.get("high", 0.0) if isinstance(bar, dict) else getattr(bar, "high", 0.0)
        l = bar.get("low", 0.0) if isinstance(bar, dict) else getattr(bar, "low", 0.0)
        price = bar.get("close", 0.0) if isinstance(bar, dict) else getattr(bar, "close", 0.0)
        vol = bar.get("volume", 0.0) if isinstance(bar, dict) else getattr(bar, "volume", 0.0)
        self._current_price = price

        # Forward to sentinel feed
        self._sentinel_feed.on_bar(bar)

        # Get current time early — needed for session boundary detection
        current_time = self._timestamp_to_datetime(timestamp_ns)
        current_date = current_time.strftime("%Y-%m-%d")

        # New-session daily risk reset — must run even when flattened
        if current_date != self._last_session_date and self._last_session_date:
            self._risk.reset_daily()

        # Skip if risk overlord has flattened
        if self._risk.is_flattened:
            return

        # ── Accumulate bar history ──
        bar_dict = {"timestamp_ns": timestamp_ns, "open": o, "high": h, "low": l, "close": price, "volume": vol}
        self._bar_buffer.append(bar_dict)
        if len(self._bar_buffer) > self._bar_buffer_max:
            self._bar_buffer = self._bar_buffer[-self._bar_buffer_max:]

        # ── Aggregate 2m bars for Velez module ──
        if self._pending_1m_bar is None:
            self._pending_1m_bar = bar_dict
        else:
            prev = self._pending_1m_bar
            bar_2m = {
                "timestamp_ns": prev["timestamp_ns"],
                "open": prev["open"],
                "high": max(prev["high"], h),
                "low": min(prev["low"], l),
                "close": price,
                "volume": prev["volume"] + vol,
            }
            self._bar_buffer_2m.append(bar_2m)
            if len(self._bar_buffer_2m) > self._bar_buffer_max:
                self._bar_buffer_2m = self._bar_buffer_2m[-self._bar_buffer_max:]
            self._pending_1m_bar = None

        # ── Session tracking (PDH/PDL, session H/L) ──
        if current_date != self._last_session_date:
            # Fix 5: Session diagnostic logging
            if self._last_session_date:
                session_trades = sum(
                    1 for t in self._trades
                    if self._timestamp_to_datetime(t["timestamp_ns"]).strftime("%Y-%m-%d") == self._last_session_date
                )
                session_rejections = sum(
                    1 for r in self._rejections
                    if self._timestamp_to_datetime(r["timestamp_ns"]).strftime("%Y-%m-%d") == self._last_session_date
                )
                logger.info(
                    "SESSION %s: bars=%d trades=%d rejections=%d predator=%s ring_buffer=%d",
                    self._last_session_date,
                    len(self._session_bars),
                    session_trades,
                    session_rejections,
                    self._predator.state.name,
                    self._ring_buffer.count,
                )
            # Reset trade flag for new session
            self._trade_just_executed = False
            # New session — record equity snapshot and create daily bar
            if self._session_bars:
                self._equity_curve.append((timestamp_ns, self._equity))
                self._prev_day_high = self._session_high
                self._prev_day_low = self._session_low
                daily_bar = {
                    "timestamp_ns": self._session_bars[0]["timestamp_ns"] if isinstance(self._session_bars[0], dict) else 0,
                    "open": self._session_open,
                    "high": self._session_high,
                    "low": self._session_low,
                    "close": self._session_bars[-1]["close"] if isinstance(self._session_bars[-1], dict) else price,
                    "volume": self._session_volume,
                }
                self._daily_bars.append(daily_bar)
                if len(self._daily_bars) > 252:  # ~1 year of trading days
                    self._daily_bars = self._daily_bars[-252:]
            self._session_bars = []
            self._session_high = h
            self._session_low = l
            self._session_open = o
            self._session_volume = 0.0
            self._last_session_date = current_date
            # Reset 4H aggregation for new session
            self._bars_since_4h = 0
            self._4h_open = o
            self._4h_high = h
            self._4h_low = l
            self._4h_volume = 0.0
            self._4h_ts = timestamp_ns
            # Reset POI mapper for fresh session
            self._poi_mapper.clear()
            self._active_pois.clear()
            self._session_sweep_detected = False
            self._session_profiler.reset_vwap()

        self._session_bars.append(bar)
        self._session_high = max(self._session_high, h)
        self._session_low = min(self._session_low, l)
        self._session_volume += vol

        # ── 4H bar aggregation (every 240 1m bars) ──
        self._bars_since_4h += 1
        self._4h_high = max(self._4h_high, h)
        self._4h_low = min(self._4h_low, l)
        self._4h_volume += vol
        if self._bars_since_4h >= 240:
            bar_4h = {
                "timestamp_ns": self._4h_ts,
                "open": self._4h_open,
                "high": self._4h_high,
                "low": self._4h_low,
                "close": price,
                "volume": self._4h_volume,
            }
            self._4h_bars.append(bar_4h)
            if len(self._4h_bars) > 200:
                self._4h_bars = self._4h_bars[-200:]
            self._bars_since_4h = 0
            self._4h_open = price
            self._4h_high = price
            self._4h_low = price
            self._4h_volume = 0.0
            self._4h_ts = timestamp_ns

        # ── Update range (rolling 20-bar high/low for premium/discount) ──
        lookback = min(len(self._bar_buffer), 100)
        recent = self._bar_buffer[-lookback:]
        self._range_high = max(b["high"] for b in recent)
        self._range_low = min(b["low"] for b in recent)

        # ── Update ATR ──
        if len(self._bar_buffer) >= 15:
            self._atr = self._compute_atr_from_buffer()
            self._ofe.set_atr(self._atr)

        # ── Update session averages for OF engine (every 30 bars within session) ──
        session_bar_count = len(self._session_bars)
        if session_bar_count > 0 and session_bar_count % 30 == 0:
            avg_vol_per_sec = self._session_volume / max(session_bar_count * 60, 1)
            rb = self._ring_buffer
            if rb.count > 100:
                recent_ticks = rb._get_ordered_data()
                avg_trade_size = float(np.mean(recent_ticks["size"]))
            else:
                avg_trade_size = vol / 5.0
            self._ofe.set_session_averages(avg_vol_per_sec, avg_trade_size)

        # ── Update VWAP ──
        typical_price = (h + l + price) / 3.0
        self._session_profiler.update_vwap(typical_price, vol)

        # ── Update macro bias — use HTF data when available, else intraday ──
        if len(self._daily_bars) >= 5 and len(self._4h_bars) >= 3:
            from flof_matrix.nautilus.backtest_runner import BAR_DTYPE
            daily_arr = np.zeros(len(self._daily_bars), dtype=BAR_DTYPE)
            for idx, db in enumerate(self._daily_bars):
                for col in ("timestamp_ns", "open", "high", "low", "close", "volume"):
                    daily_arr[idx][col] = db[col]
            h4_arr = np.zeros(len(self._4h_bars), dtype=BAR_DTYPE)
            for idx, hb in enumerate(self._4h_bars):
                for col in ("timestamp_ns", "open", "high", "low", "close", "volume"):
                    h4_arr[idx][col] = hb[col]
            bias = evaluate_macro_bias(h4_arr, daily_arr)
            if bias is not None:
                self._macro_bias = bias
            # Calculate regime from daily closes if enough data
            if len(self._daily_bars) >= 30:
                daily_closes = np.array([d["close"] for d in self._daily_bars])
                self._regime = calculate_regime(daily_closes, daily_closes, price, 30, 30)
        elif len(self._bar_buffer) >= 30:
            self._update_intraday_bias()

        # ── Structural POI scanning (every N bars) ──
        self._bars_since_poi_scan += 1
        if self._bars_since_poi_scan >= self._poi_scan_interval and len(self._bar_buffer) >= 20:
            self._bars_since_poi_scan = 0
            self._scan_structure()

        # ── Simulate trade ticks into ring buffer for order flow (backtest mode) ──
        # Skip synthetic injection when real ticks are being fed by BacktestRunner
        state = self._predator.state
        if not self._use_real_ticks and state in (PredatorState.SCOUTING, PredatorState.STALKING, PredatorState.KILL):
            self._inject_synthetic_ticks(timestamp_ns, o, h, l, price, vol)

        # ── Detect CHOCH (Change of Character) on 1m bars ──
        has_choch = self._detect_choch()

        # Compute tape velocity from ring buffer
        tape_velocity_pct = self._compute_tape_velocity(timestamp_ns)

        # Check sudden moves
        health_report = self._infra_health.get_report(timestamp_ns)
        has_calendar = self._calendar.has_active_event(current_time)
        sudden_move = self._smc.classify(
            health_report, has_calendar,
            tape_velocity_pct=tape_velocity_pct,
            spread_current=1.0, spread_baseline=1.0,
        )

        # ── Evaluate predator state ──
        poi_price = self._active_pois[0].price if self._active_pois else None
        buffer_ready = self._ring_buffer.is_ready(
            self._config.get("predator.kill_mode_ring_buffer_min", 30)
        )

        self._predator.evaluate_state(
            current_time=current_time,
            current_price=price,
            atr=self._atr,
            poi_price=poi_price,
            has_choch=has_choch,
            ring_buffer_ready=buffer_ready,
            tape_velocity_pct=tape_velocity_pct,
            sudden_move=sudden_move,
            trade_executed=self._trade_just_executed,
        )
        self._trade_just_executed = False

        # Handle state transitions — schema activation handled by _on_predator_transition
        state = self._predator.state
        if state == PredatorState.KILL:
            self._try_entry(timestamp_ns, current_time, sudden_move)

        # Manage existing positions
        self._manage_positions(price, h, l, timestamp_ns)

        # Run risk overlord check
        self._risk.check(timestamp_ns)

    def _compute_atr_from_buffer(self, period: int = 14) -> float:
        """Compute ATR from bar buffer."""
        bars = self._bar_buffer[-(period + 1):]
        if len(bars) < 2:
            return self._atr
        trs = []
        for i in range(1, len(bars)):
            tr = max(
                bars[i]["high"] - bars[i]["low"],
                abs(bars[i]["high"] - bars[i - 1]["close"]),
                abs(bars[i]["low"] - bars[i - 1]["close"]),
            )
            trs.append(tr)
        return sum(trs) / len(trs) if trs else self._atr

    def _compute_tape_velocity(self, timestamp_ns: int) -> float:
        """Compute tape velocity as percentage of baseline tick rate.

        Counts ticks in the last 5 seconds and compares against the baseline
        rate derived from the full ring buffer span (needs 30+ seconds).
        Returns 0.0 if insufficient data.
        """
        if self._ring_buffer.count < 100:
            return 0.0

        recent = self._ring_buffer.window(5.0)
        recent_count = len(recent)
        if recent_count == 0:
            return 0.0

        # Baseline: average ticks-per-5s over the full buffer span
        data = self._ring_buffer._get_ordered_data()
        span_ns = int(data[-1]["timestamp_ns"]) - int(data[0]["timestamp_ns"])
        if span_ns < 30_000_000_000:  # Need at least 30s for stable baseline
            return 0.0

        span_seconds = span_ns / 1_000_000_000
        baseline_rate_per_5s = (len(data) / span_seconds) * 5.0
        if baseline_rate_per_5s <= 0:
            return 0.0

        return (recent_count / baseline_rate_per_5s) * 100.0

    def _scan_structure(self) -> None:
        """Run structural POI detection on accumulated bar data."""
        from flof_matrix.nautilus.backtest_runner import BAR_DTYPE

        # Convert bar buffer to structured numpy array for POI mapper
        n = min(len(self._bar_buffer), 100)
        recent = self._bar_buffer[-n:]
        bars_1m = np.zeros(n, dtype=BAR_DTYPE)
        for i, b in enumerate(recent):
            bars_1m[i]["timestamp_ns"] = b["timestamp_ns"]
            bars_1m[i]["open"] = b["open"]
            bars_1m[i]["high"] = b["high"]
            bars_1m[i]["low"] = b["low"]
            bars_1m[i]["close"] = b["close"]
            bars_1m[i]["volume"] = b["volume"]

        # Aggregate to 5m bars for OB detection (OBs need displacement > 1.5x ATR)
        bars_5m = self._aggregate_bars(bars_1m, 5)

        # Map POIs on 5m bars (order blocks need larger bodies for displacement)
        obs = self._poi_mapper.map_order_blocks(bars_5m, "5m")

        # FVGs and rejection blocks on 1m bars (smaller patterns)
        fvgs = self._poi_mapper.map_fvgs(bars_1m, "1m")
        rbs = self._poi_mapper.detect_rejection_block(bars_1m, "1m")

        # Liquidity sweep detection — check all recent bars (sticky per session)
        has_sweep = self._session_sweep_detected
        if not has_sweep and self._prev_day_high > 0 and self._prev_day_low > 0:
            for b in recent:  # Check all buffered bars for PDH/PDL sweeps
                if b["high"] > self._prev_day_high and b["close"] < self._prev_day_high:
                    has_sweep = True
                    self._session_sweep_detected = True
                    sweep_poi = POI(
                        type=POIType.LIQUIDITY_POOL,
                        price=self._prev_day_high,
                        zone_high=self._prev_day_high + (b["high"] - self._prev_day_high),
                        zone_low=self._prev_day_high,
                        timeframe="D", direction=TradeDirection.SHORT,
                        is_sweep_zone=True, is_fresh=True,
                    )
                    self._poi_mapper._pois.append(sweep_poi)
                    break
                if b["low"] < self._prev_day_low and b["close"] > self._prev_day_low:
                    has_sweep = True
                    self._session_sweep_detected = True
                    sweep_poi = POI(
                        type=POIType.LIQUIDITY_POOL,
                        price=self._prev_day_low,
                        zone_high=self._prev_day_low,
                        zone_low=self._prev_day_low - (self._prev_day_low - b["low"]),
                        timeframe="D", direction=TradeDirection.LONG,
                        is_sweep_zone=True, is_fresh=True,
                    )
                    self._poi_mapper._pois.append(sweep_poi)
                    break

        # Also check session high/low sweeps (intraday)
        if not has_sweep and len(self._session_bars) > 60:
            first_hour_high = max(b["high"] if isinstance(b, dict) else 0 for b in self._session_bars[:60])
            first_hour_low = min(b["low"] if isinstance(b, dict) else 9999 for b in self._session_bars[:60])
            for b in recent:
                if b["high"] > first_hour_high and b["close"] < first_hour_high:
                    has_sweep = True
                    self._session_sweep_detected = True
                    break
                if b["low"] < first_hour_low and b["close"] > first_hour_low:
                    has_sweep = True
                    self._session_sweep_detected = True
                    break

        # Build active POIs list — fresh POIs with inducement
        self._active_pois.clear()
        historical = self._poi_mapper.historical_pois
        for poi in self._poi_mapper.pois:
            if not poi.is_fresh:
                continue
            # Track freshness
            updated = self._poi_mapper.track_freshness(poi, self._current_price)
            if not updated.is_fresh:
                continue
            # Detect flip zone (T31)
            if not updated.is_flip_zone and self._poi_mapper.detect_flip_zone(updated, historical):
                updated = POI(
                    type=updated.type, price=updated.price,
                    zone_high=updated.zone_high, zone_low=updated.zone_low,
                    timeframe=updated.timeframe, direction=updated.direction,
                    is_extreme=updated.is_extreme, is_decisional=updated.is_decisional,
                    is_flip_zone=True, is_sweep_zone=updated.is_sweep_zone,
                    is_unicorn=updated.is_unicorn, has_inducement=updated.has_inducement,
                    is_fresh=updated.is_fresh,
                )
            # Attach inducement flag if sweeps exist
            if has_sweep and not poi.has_inducement:
                updated = POI(
                    type=updated.type, price=updated.price,
                    zone_high=updated.zone_high, zone_low=updated.zone_low,
                    timeframe=updated.timeframe, direction=updated.direction,
                    is_extreme=updated.is_extreme, is_decisional=updated.is_decisional,
                    is_flip_zone=updated.is_flip_zone, is_sweep_zone=updated.is_sweep_zone,
                    is_unicorn=updated.is_unicorn, has_inducement=True,
                    is_fresh=updated.is_fresh,
                )
            self._active_pois.append(updated)

        # Sort by proximity to current price
        if self._active_pois:
            self._active_pois.sort(key=lambda p: abs(p.price - self._current_price))

    @staticmethod
    def _aggregate_bars(bars_1m: np.ndarray, period: int) -> np.ndarray:
        """Aggregate 1-minute bars to larger timeframe."""
        from flof_matrix.nautilus.backtest_runner import BAR_DTYPE

        n_out = len(bars_1m) // period
        if n_out == 0:
            return bars_1m

        out = np.zeros(n_out, dtype=BAR_DTYPE)
        for i in range(n_out):
            chunk = bars_1m[i * period:(i + 1) * period]
            out[i]["timestamp_ns"] = chunk[0]["timestamp_ns"]
            out[i]["open"] = chunk[0]["open"]
            out[i]["high"] = chunk["high"].max()
            out[i]["low"] = chunk["low"].min()
            out[i]["close"] = chunk[-1]["close"]
            out[i]["volume"] = chunk["volume"].sum()
        return out

    def _detect_choch(self) -> bool:
        """Detect Change of Character on recent 1m bars.

        CHOCH = previous swing high/low broken in opposite direction with displacement.
        """
        if len(self._bar_buffer) < 10:
            return False

        recent = self._bar_buffer[-10:]
        # Find local swing high/low in last 10 bars
        highs = [b["high"] for b in recent]
        lows = [b["low"] for b in recent]
        closes = [b["close"] for b in recent]

        # Look for swing points in middle bars
        for i in range(2, len(recent) - 2):
            # Swing high broken to downside (bearish CHOCH)
            if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
                # Check if recent close broke below the low after this swing high
                swing_low = min(lows[i:i + 3])
                if closes[-1] < swing_low and abs(closes[-1] - swing_low) > self._atr * 0.5:
                    return True

            # Swing low broken to upside (bullish CHOCH)
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                swing_high = max(highs[i:i + 3])
                if closes[-1] > swing_high and abs(closes[-1] - swing_high) > self._atr * 0.5:
                    return True

        return False

    def _update_intraday_bias(self) -> None:
        """Determine macro bias from intraday price structure.

        Uses recent 30-bar close series: higher highs + higher lows = bullish.
        This approximates the daily/4H BOS when no higher-timeframe data is available.
        """
        recent = self._bar_buffer[-30:]
        closes = [b["close"] for b in recent]
        highs = [b["high"] for b in recent]
        lows = [b["low"] for b in recent]

        # Split into first/second half
        mid = len(recent) // 2
        first_high = max(highs[:mid])
        second_high = max(highs[mid:])
        first_low = min(lows[:mid])
        second_low = min(lows[mid:])

        if second_high > first_high and second_low > first_low:
            self._macro_bias = TradeDirection.LONG
        elif second_high < first_high and second_low < first_low:
            self._macro_bias = TradeDirection.SHORT
        else:
            self._macro_bias = None

    def _inject_synthetic_ticks(
        self, timestamp_ns: int, o: float, h: float, l: float, c: float, vol: float,
    ) -> None:
        """In backtest mode, synthesize trade ticks from bar data into the ring buffer.

        Creates 20 ticks per bar with a realistic OHLC path:
        O -> dip/push -> extreme -> settle at C.
        Side is computed per-tick from price direction (uptick = buy, downtick = sell)
        so the order flow engine sees realistic CVD divergence patterns.
        """
        n_ticks = 20
        tick_interval_ns = 60_000_000_000 // n_ticks
        per_tick_vol = vol / n_ticks if vol > 0 else 50.0

        # Seeded RNG for reproducibility per bar
        rng = np.random.default_rng(timestamp_ns % (2**31))

        bar_range = h - l
        if bar_range <= 0:
            bar_range = 0.25

        # Build a realistic OHLC path: O -> counter-move -> extreme -> C
        is_bullish = c >= o
        prices = np.empty(n_ticks)

        # Phase 1 (0-4): O to counter-extreme (dip for bullish, push for bearish)
        counter_target = l if is_bullish else h
        for i in range(5):
            frac = i / 4.0
            prices[i] = o + frac * (counter_target - o) * 0.6

        # Phase 2 (5-12): Counter-extreme to main extreme
        main_target = h if is_bullish else l
        for i in range(5, 13):
            frac = (i - 5) / 7.0
            start = prices[4]
            prices[i] = start + frac * (main_target - start)

        # Phase 3 (13-19): Main extreme settling to close
        for i in range(13, n_ticks):
            frac = (i - 13) / max(n_ticks - 14, 1)
            prices[i] = prices[12] + frac * (c - prices[12])

        # Add small noise while staying within [l, h]
        noise = rng.normal(0, bar_range * 0.03, size=n_ticks)
        prices = np.clip(prices + noise, l, h)

        prev_price = o
        for i in range(n_ticks):
            tick_price = float(prices[i])
            tick_size = per_tick_vol * rng.uniform(0.5, 1.5)

            # Side from price direction: uptick = buy (+1), downtick = sell (-1)
            if tick_price > prev_price:
                side = 1
            elif tick_price < prev_price:
                side = -1
            else:
                side = 1 if is_bullish else -1

            self._ring_buffer.push(
                timestamp_ns + i * tick_interval_ns,
                tick_price,
                tick_size,
                side,
            )
            prev_price = tick_price

    def on_trade_tick(self, timestamp_ns: int, price: float, size: float, side: int) -> None:
        """Process trade tick — forward to sentinel feed and manage positions."""
        if self._risk.is_flattened:
            return
        # Fix 2: Pre-activate schema if tick arrives during killzone but schema is BASE.
        # This captures the first killzone bar's ticks before on_bar triggers DORMANT→SCOUTING.
        if (
            self._sentinel_feed.schema_level == SchemaLevel.BASE
            and self._predator.state == PredatorState.DORMANT
        ):
            tick_time = self._timestamp_to_datetime(timestamp_ns)
            if self._predator.check_killzone(tick_time):
                self._sentinel_feed.activate_killzone_schema()

        self._sentinel_feed.on_trade_tick(timestamp_ns, price, size, side)
        self._current_price = price

    def _try_entry(
        self,
        timestamp_ns: int,
        current_time: datetime,
        sudden_move: SuddenMoveType,
    ) -> None:
        """Attempt a trade entry in Kill mode."""
        if not self._active_pois:
            return

        shadow_gates_failed: list[str] = []

        poi = self._active_pois[0]

        # Build scoring context
        premium_discount = evaluate_premium_discount(
            self._current_price, self._range_high, self._range_low
        )

        of_score, of_details = self._ofe.evaluate_order_flow()

        # Order flow gate: REJECTION_BLOCK entries require at least partial
        # directional order flow confirmation (CVD divergence or absorption).
        # Only activate when ring buffer has enough ticks for meaningful
        # divergence detection (>=20 ticks in 30s window). With synthetic
        # backtest ticks (~5/bar), this gate stays dormant.
        # Require dense tick data (real market = 100s-1000s of ticks per 30s;
        # synthetic backtest = ~20 per bar). Threshold of 100 ensures this gate
        # only activates with real tick feeds.
        of_window_data = self._ring_buffer.window(30)
        of_data_sufficient = len(of_window_data) >= 100
        if of_data_sufficient and poi.type == POIType.REJECTION_BLOCK:
            direction_int = 1 if poi.direction == TradeDirection.LONG else -1
            dir_score, dir_details = self._ofe.evaluate_directional_order_flow(direction_int)
            if dir_score == 0 and not dir_details.get("has_absorption"):
                if self._shadow_mode:
                    shadow_gates_failed.append("OF_gate_rejection_block")
                else:
                    rejection = {
                        "timestamp_ns": timestamp_ns,
                        "instrument": self._config.get("system.instrument", "ES"),
                        "poi_type": poi.type.name,
                        "poi_price": float(poi.price),
                        "direction": poi.direction.name,
                        "premium_discount": "",
                        "has_inducement": poi.has_inducement,
                        "is_chop": False,
                        "rejection_gate": "OF_gate_rejection_block",
                        "rejection_reason": "REJECTION_BLOCK requires order flow confirmation (CVD divergence or absorption)",
                        "score_at_rejection": None,
                        "context": dir_details,
                    }
                    self._rejections.append(rejection)
                    if self._trade_logger:
                        self._trade_logger.log_rejection(rejection)
                    return

        # Chop detection from session profiler
        is_chop = self._session_profiler.detect_chop(
            va_width=(self._session_high - self._session_low) if self._session_bars else 0,
            atr=self._atr,
            sma_slope=0.0,
        )

        # Velez module checks — use 2m bars as Velez expects
        velez_enabled = self._config.is_toggle_enabled("T16")
        velez_bars = self._bar_buffer_2m if self._bar_buffer_2m else self._bar_buffer
        close_prices = np.array([b["close"] for b in velez_bars[-250:]])
        has_20sma_halt = False
        has_flat_200 = False
        has_elephant = False
        has_micro_trend = False
        if velez_enabled and len(close_prices) >= 20:
            sma_20 = self._velez.compute_20sma(close_prices)
            direction_int = 1 if poi.direction == TradeDirection.LONG else -1
            if sma_20 is not None:
                has_20sma_halt = self._velez.check_20sma_halt(
                    sma_20, poi.zone_high, poi.zone_low,
                    direction=direction_int, current_price=self._current_price,
                )
            if len(close_prices) >= 25:
                has_micro_trend = self._velez.check_micro_trend(close_prices, direction_int)
            if len(close_prices) >= 210:
                has_flat_200 = self._velez.check_flat_200sma(
                    close_prices, poi.zone_high, poi.zone_low,
                    direction=direction_int, current_price=self._current_price,
                )
            # Elephant bar check using recent bars (direction-aware)
            if len(self._bar_buffer) >= 12:
                last = self._bar_buffer[-1]
                prev_bars = self._bar_buffer[-11:-1]
                avg_range = sum(b["high"] - b["low"] for b in prev_bars) / len(prev_bars)
                body = abs(last["close"] - last["open"])
                bar_rng = last["high"] - last["low"]
                if avg_range > 0 and bar_rng > 0:
                    size_ok = (body > 0.7 * bar_rng) and (bar_rng > 1.3 * avg_range)
                    # Bar color must match trade direction
                    if direction_int > 0:
                        color_ok = last["close"] > last["open"]  # bullish
                    else:
                        color_ok = last["close"] < last["open"]  # bearish
                    has_elephant = size_ok and color_ok

        # VWAP confluence
        has_vwap = self._session_profiler.check_vwap_confluence(
            poi.price
        ) if self._session_profiler._vwap > 0 else False

        # Pre-compute stop and target for liquidity near target check
        stop_price = self._vpe.calculate_stop_price(
            self._current_price,
            1 if poi.direction == TradeDirection.LONG else -1,
            self._atr,
            use_vp=self._config.is_toggle_enabled("T17"),
            atr_fallback_mult=self._config.get("stops.atr_stop_multiplier", 2.0),
            min_stop_atr_mult=self._config.get("stops.min_stop_atr_mult", 1.5),
        )
        target_r = self._config.get("phase1.target_r", 2.0)
        pre_risk = abs(self._current_price - stop_price)
        if pre_risk > 0:
            if poi.direction == TradeDirection.LONG:
                pre_target = self._current_price + target_r * pre_risk
            else:
                pre_target = self._current_price - target_r * pre_risk
        else:
            pre_target = 0.0

        # Liquidity near target check
        liquidity_levels = [self._prev_day_high, self._prev_day_low, self._session_high, self._session_low]
        has_liquidity_near_target = any(
            abs(lvl - pre_target) < self._atr for lvl in liquidity_levels if lvl > 0
        ) if pre_target > 0 else False

        ctx = ScoringContext(
            premium_discount=premium_discount,
            has_inducement=poi.has_inducement,
            is_chop=is_chop,
            poi=poi,
            trend_aligned=self._macro_bias == poi.direction if self._macro_bias else False,
            regime=self._regime,
            has_liquidity_sweep=any(p.is_sweep_zone for p in self._active_pois),
            is_fresh_poi=poi.is_fresh,
            has_choch=True,  # Already confirmed in state transition
            choch_displacement_exceeds_atr=True,
            order_flow_score=of_score,
            in_killzone=self._predator.check_killzone(current_time),
            velez_enabled=velez_enabled,
            has_20sma_halt=has_20sma_halt,
            has_flat_200sma=has_flat_200,
            has_elephant_bar=has_elephant,
            has_micro_trend=has_micro_trend,
            has_vwap_confluence=has_vwap,
            is_flip_zone=poi.is_flip_zone,
            has_liquidity_near_target=has_liquidity_near_target,
            entry_price=self._current_price,
            stop_price=stop_price,
            target_price=0.0,  # Recalculated from R multiple below
            cascade_active=sudden_move == SuddenMoveType.TYPE_B,
            # Wire config values through (profile overrides apply)
            tier1_gate_minimum=self._config.get("scoring.tier1.gate_minimum", 7),
            a_plus_min=self._config.get("grading.a_plus_min", 14),
            a_min=self._config.get("grading.a_min", 12),
            b_min=self._config.get("grading.b_min", 9),
            g2_required=self._config.get("gates.g2_inducement_required", True),
        )

        # Calculate target using config R multiple (not hardcoded 2R)
        risk = abs(ctx.entry_price - ctx.stop_price)
        if risk == 0:
            return
        if poi.direction == TradeDirection.LONG:
            ctx = ScoringContext(**{**ctx.__dict__, "target_price": ctx.entry_price + target_r * risk})
        else:
            ctx = ScoringContext(**{**ctx.__dict__, "target_price": ctx.entry_price - target_r * risk})

        # Score
        if self._shadow_mode:
            signal, scorer_gates = self._scorer.score_shadow(ctx)
            shadow_gates_failed.extend(scorer_gates)
        else:
            signal = self._scorer.score(ctx)
            if signal is None:
                # Track rejection with detailed gate/reason from scorer
                rej = self._scorer.last_rejection or {}
                rejection = {
                    "timestamp_ns": timestamp_ns,
                    "instrument": self._config.get("system.instrument", "ES"),
                    "poi_type": poi.type.name,
                    "poi_price": float(poi.price),
                    "direction": poi.direction.name,
                    "premium_discount": premium_discount,
                    "has_inducement": poi.has_inducement,
                    "is_chop": is_chop,
                    "rejection_gate": rej.get("gate", "unknown"),
                    "rejection_reason": rej.get("reason", "unknown"),
                    "score_at_rejection": rej.get("tier1_score"),
                    "context": None,
                }
                self._rejections.append(rejection)
                if self._trade_logger:
                    self._trade_logger.log_rejection(rejection)
                return

        # Portfolio gates
        passed, reason = self._portfolio.evaluate_gates(
            self._config.get("system.instrument", "ES"),
            signal.position_size_pct,
            timestamp_ns,
        )
        if not passed:
            if self._shadow_mode:
                shadow_gates_failed.append(f"portfolio:{reason}")
            else:
                logger.info("Portfolio gate rejected: %s", reason)
                rejection = {
                    "timestamp_ns": timestamp_ns,
                    "instrument": self._config.get("system.instrument", "ES"),
                    "poi_type": poi.type.name,
                    "direction": poi.direction.name,
                    "rejection_gate": reason,
                    "rejection_reason": reason,
                    "score_at_rejection": signal.score_total,
                    "poi_price": float(poi.price),
                    "context": None,
                }
                self._rejections.append(rejection)
                if self._trade_logger:
                    self._trade_logger.log_rejection(rejection)
                return

        # Shadow safety: halt if drawdown exceeds safety limit
        if self._shadow_mode and self._peak_equity > 0:
            current_dd = (self._equity - self._peak_equity) / self._peak_equity
            if current_dd < self._shadow_safety_dd:
                logger.warning("Shadow safety stop: drawdown %.1f%% exceeds limit %.1f%%",
                               current_dd * 100, self._shadow_safety_dd * 100)
                return

        # Apply fill engine slippage to entry
        if self._fill_engine is not None:
            is_buy = signal.direction == TradeDirection.LONG
            slipped_entry = self._fill_engine.apply_slippage(signal.entry_price, is_buy)
            signal = TradeSignal(
                direction=signal.direction,
                poi=signal.poi,
                entry_price=slipped_entry,
                stop_price=signal.stop_price,
                target_price=signal.target_price,
                grade=signal.grade,
                score_total=signal.score_total,
                score_tier1=signal.score_tier1,
                score_tier2=signal.score_tier2,
                score_tier3=signal.score_tier3,
                position_size_pct=signal.position_size_pct,
                order_type=signal.order_type,
            )

        # Execute
        bracket = self._execution.execute_signal(signal, self._equity)
        if bracket is None:
            if self._shadow_mode and shadow_gates_failed:
                # Shadow: force 1-contract bracket when tiny sizing rounds to 0
                bracket = self._execution.create_oco_bracket(signal, 1)
            else:
                return

        self._trade_count += 1
        self._trade_just_executed = True
        pos_id = f"FLOF-{self._trade_count:04d}"

        logger.info(
            "TRADE #%d: %s %s @ %.2f | Grade %s (score %d = T1:%d T2:%d T3:%d) | Stop %.2f | Target %.2f",
            self._trade_count, signal.direction.name, poi.type.name,
            signal.entry_price, signal.grade.value, signal.score_total,
            signal.score_tier1, signal.score_tier2, signal.score_tier3,
            signal.stop_price, signal.target_price,
        )

        # Track in portfolio
        self._portfolio.add_position(PositionLedgerEntry(
            position_id=pos_id,
            instrument=self._config.get("system.instrument", "ES"),
            correlation_group="",
            direction=signal.direction,
            risk_pct=signal.position_size_pct,
            contracts=bracket.entry.size,
        ))

        # Track in trade manager
        managed = ManagedPosition(
            position_id=pos_id,
            direction=signal.direction,
            grade=signal.grade,
            entry_price=signal.entry_price,
            stop_price=signal.stop_price,
            target_price=signal.target_price,
            total_contracts=bracket.entry.size,
            entry_time_ns=timestamp_ns,
        )
        self._trade_manager.add_position(managed)

        # Track for results
        trade_record = {
            "position_id": pos_id,
            "instrument": self._config.get("system.instrument", "ES"),
            "profile": self._config.get("system.profile", "futures"),
            "direction": signal.direction.name,
            "grade": signal.grade.value,
            "score_total": signal.score_total,
            "score_tier1": signal.score_tier1,
            "score_tier2": signal.score_tier2,
            "score_tier3": signal.score_tier3,
            "entry_price": signal.entry_price,
            "stop_price": signal.stop_price,
            "target_price": signal.target_price,
            "risk_pct": signal.position_size_pct,
            "contracts": bracket.entry.size,
            "poi_type": poi.type.name,
            "timestamp_ns": timestamp_ns,
            "active_toggles": None,
            "shadow_gates_failed": shadow_gates_failed if self._shadow_mode else [],
        }
        self._trades.append(trade_record)
        if self._trade_logger:
            self._trade_logger.log_trade(trade_record)

        # Update risk overlord (skip in shadow mode to prevent nuclear flattens)
        if not self._shadow_mode:
            self._risk.record_order(timestamp_ns)
        self._risk.update_positions(self._portfolio.open_position_count)

        # Publish event
        self._event_bus.publish_sync(Event(
            type=EventType.ORDER_FIRED,
            timestamp_ns=timestamp_ns,
            source="FlofStrategy",
            payload={
                "position_id": pos_id,
                "direction": signal.direction.name,
                "grade": signal.grade.value,
                "score": signal.score_total,
            },
        ))

    def _manage_positions(self, price: float, bar_high: float, bar_low: float, now_ns: int) -> None:
        """Manage all open positions through phases.

        Uses bar_high/bar_low for stop/target/favorable checks so that
        intra-bar extremes are not missed (especially important for SHORT
        positions where bar_low is the favorable extreme, not close).
        """
        for pos in list(self._trade_manager.positions.values()):
            # Check stop hit (use bar extreme against the position)
            if pos.direction == TradeDirection.LONG:
                if bar_low <= pos.stop_price:
                    self._close_position(pos, now_ns, "stop_hit", exit_price=pos.stop_price)
                    continue
            else:
                if bar_high >= pos.stop_price:
                    self._close_position(pos, now_ns, "stop_hit", exit_price=pos.stop_price)
                    continue

            # Check target hit (use bar extreme in favor of the position)
            if pos.direction == TradeDirection.LONG:
                if bar_high >= pos.target_price:
                    self._close_position(pos, now_ns, "target_hit", exit_price=pos.target_price)
                    continue
            else:
                if bar_low <= pos.target_price:
                    self._close_position(pos, now_ns, "target_hit", exit_price=pos.target_price)
                    continue

            # Update favorable movement tracking (use bar extreme in favor)
            if pos.direction == TradeDirection.LONG:
                if bar_high > pos.highest_favorable:
                    pos.highest_favorable = bar_high
                    pos.last_movement_ns = now_ns
            else:
                if bar_low < pos.highest_favorable:
                    pos.highest_favorable = bar_low
                    pos.last_movement_ns = now_ns

            # Micro trail: once price reaches +1R, move stop to breakeven
            # Use bar extreme (high for longs, low for shorts) so intra-bar
            # wicks that touch the threshold trigger protection immediately
            favorable = bar_high if pos.direction == TradeDirection.LONG else bar_low
            micro = self._trade_manager.check_micro_trail(pos, price, favorable_price=favorable)
            if micro:
                self._trade_manager.apply_micro_trail(pos, micro)

            # Phase 1: Partial exit
            result = self._trade_manager.evaluate_phase1(pos, price)
            if result:
                # Record partial PnL before applying
                direction_sign = 1 if pos.direction == TradeDirection.LONG else -1
                partial_pnl = (result["price"] - pos.entry_price) * direction_sign * result["contracts"] * self._point_value
                pos.partial_pnl_dollars += partial_pnl
                self._trade_manager.apply_phase1_result(pos, result)
                continue

            # Phase 2: Structural trail for runners (T19)
            if pos.phase == TradePhase.PHASE2_RUNNER:
                result = self._trade_manager.evaluate_phase2(pos, price)
                if result:
                    pos.stop_price = result["new_stop"]

            # Phase 3: Climax exit for runners — absorption + delta stall
            # Uses detect_absorption() (bool→score) and sell_delta_pct (centered)
            # min_ticks=100 guard on sell_delta ensures dormant with synthetic data
            if pos.phase == TradePhase.PHASE2_RUNNER:
                absorption_score = 1.0 if self._ofe.detect_absorption(window_seconds=5) else 0.0
                sell_delta = self._ofe.calculate_sell_delta_pct(window_seconds=30, min_ticks=100)
                # Center around 0: 0.5 sell_delta → 0.0 (stalled), 0.8 → 0.3 (selling)
                delta_pct = sell_delta - 0.5
                result = self._trade_manager.evaluate_phase3(pos, absorption_score, delta_pct, current_price=price)
                if result:
                    self._close_position(pos, now_ns, result["reason"], exit_price=price)
                    continue

            # Tape failure (T18): exit when sell delta overwhelms
            # min_ticks=100 ensures this only fires with real tick data
            # Volume gate: skip T18 when bar volume < 50% of session average
            # to prevent ghost exits in low-liquidity sessions
            if self._config.is_toggle_enabled("T18"):
                session_bar_count = len(self._session_bars)
                if session_bar_count > 0:
                    avg_session_vol = self._session_volume / session_bar_count
                    current_bar_vol = self._session_bars[-1]["volume"] if isinstance(self._session_bars[-1], dict) else 0
                    t18_vol_threshold = self._config.get("stops.t18_volume_threshold_pct", 0.50)
                    volume_sufficient = current_bar_vol >= avg_session_vol * t18_vol_threshold
                else:
                    volume_sufficient = True  # No session data yet, allow T18

                if volume_sufficient:
                    sell_delta = self._ofe.calculate_sell_delta_pct(window_seconds=30, min_ticks=100)
                    # T21: tighten threshold when 20 SMA health fails
                    sma_ok = True
                    if self._config.is_toggle_enabled("T21") and len(self._bar_buffer_2m) >= 20:
                        closes_20 = np.array([b["close"] for b in self._bar_buffer_2m[-20:]])
                        sma_20 = float(np.mean(closes_20))
                        if pos.direction == TradeDirection.LONG:
                            sma_ok = price >= sma_20
                        else:
                            sma_ok = price <= sma_20
                    result = self._trade_manager.check_tape_failure(
                        pos, sell_delta_pct=sell_delta, sma_health_ok=sma_ok,
                    )
                    if result:
                        self._close_position(pos, now_ns, result["action"], exit_price=price)
                        continue

            # T48: Toxicity exit — immediate exit if order flow turns against position
            if self._config.is_toggle_enabled("T48"):
                direction_int = 1 if pos.direction == TradeDirection.LONG else -1
                adverse_delta = self._ofe.calculate_adverse_delta_pct(direction_int, window_seconds=30, min_ticks=100)
                result = self._trade_manager.check_toxicity_exit(pos, adverse_delta)
                if result:
                    self._close_position(pos, now_ns, result["action"], exit_price=price)
                    continue

            # Toxicity timer (T35)
            if self._config.is_toggle_enabled("T35"):
                result = self._trade_manager.check_toxicity_timer(pos, now_ns)
                if result:
                    self._close_position(pos, now_ns, result["action"], exit_price=price)
                    continue

    def _close_position(self, pos: ManagedPosition, now_ns: int, reason: str, exit_price: float = 0.0) -> None:
        """Close a position, calculate PnL, and update all trackers."""
        if exit_price == 0.0:
            exit_price = self._current_price

        # Apply fill engine slippage to exit
        if self._fill_engine is not None:
            is_buy_to_close = pos.direction == TradeDirection.SHORT
            exit_price = self._fill_engine.apply_slippage(exit_price, is_buy_to_close)

        # Calculate PnL
        direction_sign = 1 if pos.direction == TradeDirection.LONG else -1
        risk = abs(pos.entry_price - pos.stop_price)
        pnl_per_contract = (exit_price - pos.entry_price) * direction_sign
        pnl_dollars = pnl_per_contract * pos.remaining_contracts * self._point_value
        pnl_dollars += pos.partial_pnl_dollars  # Add accumulated partial exit PnL
        pnl_r = pnl_per_contract / risk if risk > 0 else 0.0

        # Store on position
        pos.exit_price = exit_price
        pos.exit_reason = reason
        pos.exit_time_ns = now_ns
        pos.pnl_dollars = pnl_dollars
        pos.pnl_r_multiple = pnl_r

        # Update equity and track curve
        self._equity += pnl_dollars
        self._equity_curve.append((now_ns, self._equity))
        if self._equity > self._peak_equity:
            self._peak_equity = self._equity
        drawdown = self._peak_equity - self._equity
        if drawdown > self._max_drawdown:
            self._max_drawdown = drawdown
            self._max_drawdown_pct = drawdown / self._peak_equity if self._peak_equity > 0 else 0.0

        # Update trade record
        for trade in self._trades:
            if trade["position_id"] == pos.position_id:
                trade["exit_price"] = exit_price
                trade["exit_reason"] = reason
                trade["pnl_dollars"] = pnl_dollars
                trade["pnl_r_multiple"] = pnl_r
                trade["exit_time_ns"] = now_ns
                break

        # Track win/loss for risk management (skip in shadow mode to prevent nuclear flattens)
        if not self._shadow_mode:
            if pnl_dollars > 0:
                self._risk.record_win()
            elif pnl_dollars < 0:
                self._risk.record_loss()

        # Remove from trackers
        self._trade_manager.remove_position(pos.position_id)
        self._portfolio.remove_position(pos.position_id)
        self._risk.update_positions(self._portfolio.open_position_count)

        self._event_bus.publish_sync(Event(
            type=EventType.POSITION_CLOSED,
            timestamp_ns=now_ns,
            source="FlofStrategy",
            payload={
                "position_id": pos.position_id,
                "reason": reason,
                "pnl_dollars": pnl_dollars,
                "pnl_r_multiple": pnl_r,
            },
        ))

    def cancel_all_orders(self) -> None:
        """Called by RiskOverlord during Nuclear Flatten."""
        logger.warning("Cancelling all working orders")

    def flatten_all_positions(self) -> None:
        """Called by RiskOverlord during Nuclear Flatten."""
        logger.warning("Flattening all positions")
        for pos in list(self._trade_manager.positions.values()):
            self._close_position(pos, 0, "nuclear_flatten", exit_price=self._current_price)

    def force_dormant(self) -> None:
        """Called by RiskOverlord during Nuclear Flatten."""
        self._predator.force_dormant()

    def on_stop(self) -> None:
        """Clean shutdown — close all remaining positions at current price."""
        for pos in list(self._trade_manager.positions.values()):
            self._close_position(pos, 0, "end_of_backtest", exit_price=self._current_price)
        self._sentinel_feed.on_stop()
        logger.info("FlofStrategy stopped — equity: $%.2f", self._equity)

    @staticmethod
    def _timestamp_to_datetime(timestamp_ns: int) -> datetime:
        """Convert nanosecond timestamp to Eastern Time datetime."""
        import pytz
        utc_dt = datetime.utcfromtimestamp(timestamp_ns / 1_000_000_000)
        utc_dt = pytz.utc.localize(utc_dt)
        et = pytz.timezone("US/Eastern")
        return utc_dt.astimezone(et).replace(tzinfo=None)
