"""Backtest Runner — Entry point for running FLOF Matrix backtests.

Supports two modes:
  1. Manual loop (default): Iterates bars in Python, calling FlofStrategy.on_bar()
  2. NautilusTrader engine: Uses BacktestEngine with a NautilusFlofStrategy adapter

Initialization order (from Scaffolding v4.0):
  1. ConfigManager → 2. EventBus → 3. RingBuffer → 4. InfraHealth →
  5. SentinelFeed → 6. (HTFStructureMapper) → 7. POIMapper →
  8. SessionProfiler → 9. OrderFlowEngine → 10. VolumeProfileEngine →
  11. VelezMAModule → 12. SuddenMoveClassifier → 13. EventCalendar →
  14. PredatorStateMachine → 15. ConfluenceScorer → 16. PortfolioManager →
  17. RiskOverlord → 18. FlofStrategy

Shutdown: reverse order. PredatorStateMachine stops first (no new trades).
RiskOverlord stops LAST.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

import numpy as np

from flof_matrix.config.config_manager import ConfigManager
from flof_matrix.core.event_bus import EventBus
from flof_matrix.core.ring_buffer import RingBuffer
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
from flof_matrix.risk.risk_overlord import RiskOverlord
from flof_matrix.risk.portfolio_manager import PortfolioManager
from flof_matrix.nautilus.flof_strategy import FlofStrategy
from flof_matrix.nautilus.fill_engine import PessimisticFillEngine
from flof_matrix.database.trade_logger import TradeLogger

logger = logging.getLogger(__name__)


BAR_DTYPE = np.dtype([
    ("timestamp_ns", np.int64),
    ("open", np.float64),
    ("high", np.float64),
    ("low", np.float64),
    ("close", np.float64),
    ("volume", np.float64),
])


class BacktestRunner:
    """Sets up all modules in correct order and runs a backtest."""

    def __init__(
        self,
        config_path: str | Path,
        profile: str = "futures",
        instrument: str | None = None,
        fill_level: int = 2,
        db_dsn: str | None = None,
    ) -> None:
        self._config_path = Path(config_path)
        self._profile = profile
        self._instrument = instrument
        self._fill_level = fill_level
        self._db_dsn = db_dsn
        self._strategy: FlofStrategy | None = None
        self._fill_engine: PessimisticFillEngine | None = None
        self._trade_logger: TradeLogger | None = None

    def setup(self) -> FlofStrategy:
        """Initialize all modules in correct order."""

        # 1. ConfigManager
        config = ConfigManager()
        config.load(self._config_path, self._profile, self._instrument)

        # 2. EventBus
        event_bus = EventBus(
            max_queue_depth=config.get("event_bus.max_queue_depth", 1000),
        )

        # 3. RingBuffer
        ring_buffer = RingBuffer(
            capacity=config.get("order_flow.ring_buffer_capacity", 500_000),
        )

        # 4. InfraHealth
        infra_health = InfraHealth(
            databento_latency_max_ms=config.get("sudden_move.databento_latency_max_ms", 500),
            broker_latency_max_ms=config.get("sudden_move.broker_api_latency_max_ms", 400),
            heartbeat_timeout_seconds=config.get("sudden_move.heartbeat_timeout_es_seconds", 5),
            event_bus=event_bus,
        )

        # 5. SentinelFeed
        sentinel_feed = SentinelFeed(
            ring_buffer=ring_buffer,
            backtest_mode=True,
        )

        # 7. POIMapper
        poi_mapper = POIMapper()

        # 8. SessionProfiler
        session_profiler = SessionProfiler()

        # 9. OrderFlowEngine
        order_flow_engine = OrderFlowEngine(
            ring_buffer=ring_buffer,
            cvd_lookback_seconds=config.get("order_flow.cvd_divergence_lookback_seconds", 30),
            absorption_volume_threshold=config.get("order_flow.absorption_volume_threshold", 2.0),
            absorption_displacement_max=config.get("order_flow.absorption_displacement_max", 0.3),
            whale_print_multiplier=config.get("order_flow.whale_print_multiplier", 5.0),
            whale_block_min_prints=config.get("order_flow.whale_block_min_prints", 3),
        )

        # 10. VolumeProfileEngine
        volume_profile_engine = VolumeProfileEngine(
            ring_buffer=ring_buffer,
            bucket_count=config.get("data.vp_bucket_count", 50),
        )

        # 11. VelezMAModule
        velez_module = VelezMAModule(
            sma_20_period=config.get("velez.sma_20_period", 20),
            sma_200_period=config.get("velez.sma_200_period", 200),
            flat_200_slope_threshold=config.get("velez.flat_200_slope_threshold", 0.001),
            micro_trend_slope_threshold=config.get("velez.micro_trend_slope_threshold", 0.0005),
            elephant_bar_body_pct=config.get("scoring.tier2.elephant_bar_body_pct", 0.70),
            elephant_bar_range_mult=config.get("scoring.tier2.elephant_bar_range_mult", 1.3),
            elephant_bar_lookback=config.get("scoring.tier2.elephant_bar_lookback", 10),
        )

        # 12. SuddenMoveClassifier
        sudden_move = SuddenMoveClassifier(
            tick_velocity_threshold_pct=config.get("sudden_move.tick_velocity_threshold_pct", 400),
            range_expansion_threshold=config.get("sudden_move.range_expansion_threshold", 3.0),
            databento_latency_max_ms=config.get("sudden_move.databento_latency_max_ms", 500),
            broker_api_latency_max_ms=config.get("sudden_move.broker_api_latency_max_ms", 400),
        )

        # 13. EventCalendar
        event_calendar = EventCalendar(
            cooldown_seconds=config.get("sudden_move.type_a_cooldown_seconds", 180),
        )
        self._event_calendar = event_calendar  # Store ref for deferred year loading

        # 14. PredatorStateMachine
        killzones = []
        for kz_name in ["ny_am", "ny_pm", "london_ny_overlap"]:
            kz = config.get(f"killzones.{kz_name}")
            if kz and isinstance(kz, dict):
                killzones.append(kz)

        predator = PredatorStateMachine(
            proximity_halo_atr_mult=config.get("predator.proximity_halo_atr_mult", 1.5),
            tape_velocity_stalking_pct=config.get("predator.tape_velocity_stalking_pct", 300),
            kill_mode_ring_buffer_min=config.get("predator.kill_mode_ring_buffer_min", 30),
            killzones=killzones,
        )

        # 15. ConfluenceScorer
        scorer = ConfluenceScorer()

        # 16. PortfolioManager
        corr_groups = config.get("portfolio.correlation_groups", {})
        portfolio_manager = PortfolioManager(
            p1_max_total_exposure=config.get("portfolio.p1_max_total_exposure", 0.06),
            p2_max_per_group=config.get("portfolio.p2_max_per_group", 2),
            p3_daily_drawdown_limit=config.get("portfolio.p3_daily_drawdown_limit", -0.02),
            p4_max_loss_streak=config.get("portfolio.p4_max_loss_streak", 3),
            p5_lockout_seconds=config.get("portfolio.p5_lockout_seconds", 300),
            correlation_groups=corr_groups,
        )

        # 17. RiskOverlord
        risk_overlord = RiskOverlord(
            max_orders_per_minute=config.get("risk_overlord.max_orders_per_minute", 3),
            max_concurrent_positions=config.get("risk_overlord.max_concurrent_positions", 3),
            max_daily_drawdown_pct=config.get("risk_overlord.max_daily_drawdown_pct", -0.03),
            max_consecutive_losses=config.get("risk_overlord.max_consecutive_losses", 3),
            stale_data_countdown_seconds=config.get("risk_overlord.stale_data_countdown_seconds", 5),
            live_mode=False,
            event_bus=event_bus,
        )

        # Execution
        execution_manager = ExecutionManager(
            tick_size=config.get("execution.tick_size", 0.25),
            point_value=config.get("execution.point_value", 50.0),
            default_order_type=config.get("execution.default_order_type", "market_with_protection"),
        )

        trade_manager = TradeManager(
            tick_size=config.get("execution.tick_size", 0.25),
            point_value=config.get("execution.point_value", 50.0),
            phase1_target_r=config.get("phase1.target_r", 2.0),
            default_partial_pct=config.get("sizing.default_partial_pct", 0.50),
            a_plus_partial_pct=config.get("sizing.a_plus_partial_pct", 0.33),
            micro_trail_activation_r=config.get("stops.micro_trail_activation_r", 1.5),
            toxicity_timer_seconds=config.get("stops.toxicity_timer_seconds", 120),
            toxicity_delta_pct=config.get("stops.toxicity_delta_reversal_pct", 0.70),
        )

        # Fill engine
        self._fill_engine = PessimisticFillEngine(
            level=self._fill_level,
            tick_size=config.get("execution.tick_size", 0.25),
        )

        # Trade Logger
        self._trade_logger = TradeLogger(dsn=self._db_dsn)

        # 18. FlofStrategy
        self._strategy = FlofStrategy(
            config=config,
            event_bus=event_bus,
            ring_buffer=ring_buffer,
            infra_health=infra_health,
            sentinel_feed=sentinel_feed,
            poi_mapper=poi_mapper,
            session_profiler=session_profiler,
            order_flow_engine=order_flow_engine,
            volume_profile_engine=volume_profile_engine,
            velez_module=velez_module,
            sudden_move_classifier=sudden_move,
            event_calendar=event_calendar,
            predator=predator,
            scorer=scorer,
            execution_manager=execution_manager,
            trade_manager=trade_manager,
            portfolio_manager=portfolio_manager,
            risk_overlord=risk_overlord,
            trade_logger=self._trade_logger,
            fill_engine=self._fill_engine,
        )

        return self._strategy

    def run(self, bars: np.ndarray, ticks: np.ndarray | None = None) -> dict:
        """Run backtest on provided bar data, optionally with real trade ticks.

        Args:
            bars: NumPy structured array with BAR_DTYPE
            ticks: Optional TICK_DTYPE array of real trade ticks (from DataBento)

        Returns:
            Results dict with trade count, PnL summary, etc.
        """
        if self._strategy is None:
            self.setup()

        # Tell strategy whether to use real ticks or synthetic injection
        has_real_ticks = ticks is not None and len(ticks) > 0
        self._strategy._use_real_ticks = has_real_ticks

        # Build tick time index for O(log n) per-bar lookup
        if has_real_ticks:
            bar_ts = bars["timestamp_ns"]
            tick_ts = ticks["timestamp_ns"]
            tick_start = np.searchsorted(tick_ts, bar_ts, side="left")
            tick_end = np.searchsorted(tick_ts, bar_ts + 60_000_000_000, side="left")
            logger.info("Real ticks: %d total, feeding into %d bars", len(ticks), len(bars))

        self._strategy.on_start()

        # Derive year from first bar for event calendar (instead of hardcoded 2024)
        if len(bars) > 0 and hasattr(self, '_event_calendar'):
            from datetime import datetime, timezone
            first_ts_ns = int(bars[0]["timestamp_ns"])
            first_dt = datetime.fromtimestamp(first_ts_ns / 1_000_000_000, tz=timezone.utc)
            self._event_calendar.load_events(first_dt.year)
            logger.info("Event calendar loaded for year %d", first_dt.year)

        for i in range(len(bars)):
            # Feed real ticks for this bar BEFORE on_bar()
            if has_real_ticks:
                for t in ticks[tick_start[i]:tick_end[i]]:
                    self._strategy.on_trade_tick(
                        int(t["timestamp_ns"]), float(t["price"]),
                        float(t["size"]), int(t["side"]),
                    )

            bar = {
                "timestamp_ns": int(bars[i]["timestamp_ns"]),
                "open": float(bars[i]["open"]),
                "high": float(bars[i]["high"]),
                "low": float(bars[i]["low"]),
                "close": float(bars[i]["close"]),
                "volume": float(bars[i]["volume"]),
            }
            self._strategy.on_bar(bar)

        self._strategy.on_stop()

        # Flush trades to PostgreSQL if DSN is configured
        db_records = 0
        if self._trade_logger:
            db_records = self._trade_logger.flush_to_db_sync()

        return self._build_results(len(bars), db_records)

    def run_nautilus(self, bars: np.ndarray) -> dict:
        """Run backtest through NautilusTrader's BacktestEngine.

        Uses the real NautilusTrader event loop with a CME venue simulation.
        Our FlofStrategy is wrapped in a NautilusFlofStrategy adapter that
        receives bar events from the engine.

        Args:
            bars: NumPy structured array with BAR_DTYPE

        Returns:
            Results dict with trade count, PnL summary, engine stats, etc.
        """
        import pandas as pd
        from nautilus_trader.backtest.engine import BacktestEngine
        from nautilus_trader.config import BacktestEngineConfig
        from nautilus_trader.model.enums import (
            OmsType, AccountType, AssetClass,
            BarAggregation, PriceType, AggregationSource,
        )
        from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
        from nautilus_trader.model.objects import Price, Quantity, Currency, Money
        from nautilus_trader.model.instruments import FuturesContract
        from nautilus_trader.model.data import Bar, BarType, BarSpecification
        from flof_matrix.nautilus.nautilus_strategy import NautilusFlofStrategy

        # Setup FLOF modules (same as manual mode)
        if self._strategy is None:
            self.setup()

        # ── Create NautilusTrader Engine ──
        engine = BacktestEngine(config=BacktestEngineConfig())

        # ── CME Venue (margin account, hedging OMS for futures) ──
        engine.add_venue(
            venue=Venue("CME"),
            oms_type=OmsType.HEDGING,
            account_type=AccountType.MARGIN,
            starting_balances=[Money(100_000, Currency.from_str("USD"))],
            base_currency=Currency.from_str("USD"),
            default_leverage=Decimal("50"),
            bar_execution=True,
            bar_adaptive_high_low_ordering=True,
            frozen_account=True,  # FLOF manages its own equity tracking
        )

        # ── ES Futures Contract ──
        instrument_symbol = self._instrument or "ESH5"
        instrument_id = InstrumentId(Symbol(instrument_symbol), Venue("CME"))

        tick_size = self._strategy._config.get("execution.tick_size", 0.25)
        point_value = self._strategy._config.get("execution.point_value", 50.0)

        underlying = self._strategy._config.get("system.instrument", "ES")
        contract = FuturesContract(
            instrument_id=instrument_id,
            raw_symbol=Symbol(instrument_symbol),
            asset_class=AssetClass.INDEX,
            currency=Currency.from_str("USD"),
            price_precision=2,
            price_increment=Price.from_str(f"{tick_size:.2f}"),
            multiplier=Quantity.from_int(int(point_value)),
            lot_size=Quantity.from_int(1),
            underlying=underlying,
            activation_ns=int(pd.Timestamp("2024-01-01", tz="UTC").value),
            expiration_ns=int(pd.Timestamp("2025-03-21", tz="UTC").value),
            ts_event=0,
            ts_init=0,
        )
        engine.add_instrument(contract)

        # ── Convert numpy bars to NautilusTrader Bar objects ──
        bar_type = BarType(
            instrument_id,
            BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST),
            AggregationSource.EXTERNAL,
        )

        logger.info("Converting %d bars to NautilusTrader format...", len(bars))
        nt_bars = []
        for i in range(len(bars)):
            ts = int(bars[i]["timestamp_ns"])
            o = float(bars[i]["open"])
            h = float(bars[i]["high"])
            l = float(bars[i]["low"])
            c = float(bars[i]["close"])
            v = max(float(bars[i]["volume"]), 1.0)

            # Ensure OHLC consistency after rounding to 2 decimal places
            # NautilusTrader validates: high >= max(open, close), low <= min(open, close)
            h = max(h, o, c)
            l = min(l, o, c)

            nt_bar = Bar(
                bar_type=bar_type,
                open=Price.from_str(f"{o:.2f}"),
                high=Price.from_str(f"{h:.2f}"),
                low=Price.from_str(f"{l:.2f}"),
                close=Price.from_str(f"{c:.2f}"),
                volume=Quantity.from_str(f"{v:.0f}"),
                ts_event=ts,
                ts_init=ts,
            )
            nt_bars.append(nt_bar)

        engine.add_data(nt_bars)
        logger.info("Added %d bars to engine", len(nt_bars))

        # ── Wrap FlofStrategy in NautilusTrader adapter ──
        nt_strategy = NautilusFlofStrategy(
            flof_strategy=self._strategy,
            bar_type=bar_type,
        )
        engine.add_strategy(nt_strategy)

        # ── Run ──
        logger.info("Running NautilusTrader BacktestEngine...")
        engine.run()

        # ── Collect results ──
        result = engine.get_result()

        # Flush trades to PostgreSQL
        db_records = 0
        if self._trade_logger:
            db_records = self._trade_logger.flush_to_db_sync()

        # Build result dict
        results = self._build_results(nt_strategy._bar_count, db_records)
        results["engine"] = "nautilus"
        results["nautilus_result"] = {
            "run_id": str(result.run_id),
            "elapsed_time": result.elapsed_time,
            "iterations": result.iterations,
            "total_events": result.total_events,
            "total_orders": result.total_orders,
            "total_positions": result.total_positions,
        }

        engine.dispose()
        logger.info("NautilusTrader engine disposed")

        return results

    def _build_results(self, bars_processed: int, db_records: int) -> dict:
        """Build standardized results dict with PnL summary."""
        trades = self._strategy._trades
        total_pnl = sum(t.get("pnl_dollars", 0) for t in trades)
        r_values = [t.get("pnl_r_multiple", 0) for t in trades if t.get("exit_price", 0) != 0]
        wins = [t for t in trades if t.get("pnl_dollars", 0) > 0]
        closed = [t for t in trades if t.get("exit_price", 0) != 0]

        return {
            "bars_processed": bars_processed,
            "trade_count": self._strategy._trade_count,
            "fill_level": self._fill_engine.config.name if self._fill_engine else "unknown",
            "trades": trades,
            "rejections": self._strategy._rejections,
            "db_records_written": db_records,
            "total_pnl": total_pnl,
            "final_equity": self._strategy._equity,
            "win_rate": len(wins) / len(closed) if closed else 0.0,
            "avg_r_multiple": sum(r_values) / len(r_values) if r_values else 0.0,
            "equity_curve": [(ts, eq) for ts, eq in self._strategy._equity_curve],
            "max_drawdown": self._strategy._max_drawdown,
            "max_drawdown_pct": self._strategy._max_drawdown_pct,
            "peak_equity": self._strategy._peak_equity,
        }

    @staticmethod
    def load_catalog_bars(catalog_path: str | Path, instrument: str = "ESH5", venue: str = "CME") -> np.ndarray | None:
        """Load bars from a ParquetDataCatalog if available.

        Returns BAR_DTYPE array, or None if catalog not found/empty.
        """
        catalog_path = Path(catalog_path)
        if not catalog_path.exists():
            return None
        try:
            from nautilus_trader.persistence.catalog import ParquetDataCatalog
            from nautilus_trader.model.data import Bar

            catalog = ParquetDataCatalog(str(catalog_path))
            bars = catalog.bars()
            if bars is None or len(bars) == 0:
                return None

            result = np.zeros(len(bars), dtype=BAR_DTYPE)
            for i, bar in enumerate(bars):
                result[i]["timestamp_ns"] = bar.ts_event
                result[i]["open"] = float(bar.open)
                result[i]["high"] = float(bar.high)
                result[i]["low"] = float(bar.low)
                result[i]["close"] = float(bar.close)
                result[i]["volume"] = float(bar.volume)

            logger.info("Loaded %d bars from catalog at %s", len(result), catalog_path)
            return result
        except Exception:
            logger.warning("Could not load from catalog — falling back to direct data")
            return None

    def shutdown(self) -> None:
        """Shutdown in reverse initialization order."""
        if self._strategy:
            self._strategy.on_stop()
        ConfigManager.reset()
