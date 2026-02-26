"""NautilusFlofStrategy — NautilusTrader Strategy adapter for FLOF Matrix.

Subclasses nautilus_trader.trading.Strategy and delegates bar processing
to our FlofStrategy orchestrator. This bridges the NautilusTrader engine's
event-driven architecture with our existing module composition.
"""

from __future__ import annotations

import logging

from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType

from flof_matrix.nautilus.flof_strategy import FlofStrategy

logger = logging.getLogger(__name__)


class NautilusFlofStrategy(Strategy):
    """NautilusTrader Strategy that delegates to FlofStrategy.

    Subscribes to bar data via the engine, converts NautilusTrader Bar
    objects to dicts, and forwards them to FlofStrategy.on_bar().
    """

    def __init__(
        self,
        flof_strategy: FlofStrategy,
        bar_type: BarType,
        config: StrategyConfig | None = None,
    ) -> None:
        super().__init__(
            config or StrategyConfig(
                strategy_id="FLOF-001",
                order_id_tag="FLOF",
            ),
        )
        self._flof = flof_strategy
        self._bar_type = bar_type
        self._bar_count = 0

    @property
    def flof(self) -> FlofStrategy:
        """Access the underlying FlofStrategy."""
        return self._flof

    def on_start(self) -> None:
        """Subscribe to bar data and initialize FLOF modules."""
        self.subscribe_bars(self._bar_type)
        self._flof.on_start()
        logger.info("NautilusFlofStrategy started — subscribed to %s", self._bar_type)

    def on_bar(self, bar: Bar) -> None:
        """Convert NT Bar to dict and forward to FlofStrategy."""
        self._bar_count += 1
        bar_dict = {
            "timestamp_ns": bar.ts_event,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
        }
        self._flof.on_bar(bar_dict)

    def on_stop(self) -> None:
        """Clean shutdown."""
        self._flof.on_stop()
        logger.info(
            "NautilusFlofStrategy stopped — %d bars processed, %d trades",
            self._bar_count,
            self._flof._trade_count,
        )
