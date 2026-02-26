"""Pessimistic Fill Engine — 3-level fill model for backtesting.

Level 1 (Optimistic): Fills at touch, no slippage.
Level 2 (Standard): 1-tick slippage, through-fill required, 85% fill rate.
Level 3 (Conservative): 2-tick slippage, 65% fill rate.

From flof_base.toml section 18.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FillConfig:
    """Fill engine configuration for a specific pessimism level."""

    name: str
    level: int
    slippage_ticks: int
    require_through_fill: bool
    partial_fill_rate: float


# Pre-built fill configs from TOML
FILL_LEVELS = {
    1: FillConfig(
        name="Optimistic",
        level=1,
        slippage_ticks=0,
        require_through_fill=False,
        partial_fill_rate=1.0,
    ),
    2: FillConfig(
        name="Standard",
        level=2,
        slippage_ticks=1,
        require_through_fill=True,
        partial_fill_rate=0.85,
    ),
    3: FillConfig(
        name="Conservative",
        level=3,
        slippage_ticks=2,
        require_through_fill=True,
        partial_fill_rate=0.65,
    ),
}


class PessimisticFillEngine:
    """Simulates realistic fill behavior for backtesting.

    Applies slippage, through-fill requirements, and partial fill rates.
    """

    def __init__(self, level: int = 2, tick_size: float = 0.25) -> None:
        self._config = FILL_LEVELS.get(level, FILL_LEVELS[2])
        self._tick_size = tick_size

    @property
    def config(self) -> FillConfig:
        return self._config

    def apply_slippage(self, price: float, is_buy: bool) -> float:
        """Apply tick-based slippage to fill price."""
        slippage = self._config.slippage_ticks * self._tick_size
        if is_buy:
            return price + slippage  # Buy fills higher
        else:
            return price - slippage  # Sell fills lower

    def would_fill(
        self,
        order_price: float,
        market_high: float,
        market_low: float,
        is_buy: bool,
    ) -> bool:
        """Check if a limit order would fill given the bar's price range.

        Through-fill: price must trade THROUGH the order price, not just touch it.
        """
        if self._config.require_through_fill:
            if is_buy:
                return market_low < order_price  # Must trade below buy limit
            else:
                return market_high > order_price  # Must trade above sell limit
        else:
            if is_buy:
                return market_low <= order_price
            else:
                return market_high >= order_price

    def apply_partial_fill(self, requested_qty: int) -> int:
        """Apply partial fill rate to requested quantity."""
        import math
        filled = math.floor(requested_qty * self._config.partial_fill_rate)
        return max(filled, 1) if requested_qty > 0 else 0
