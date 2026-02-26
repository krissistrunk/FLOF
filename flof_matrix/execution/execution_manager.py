"""Execution Manager (M08) — Order placement with Fix B (no raw Market Orders).

Fix B: ES Futures uses Market With Protection (MWP), never raw Market Orders.
Every entry gets an exchange-native OCO bracket (Stop With Protection + Limit TP).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from flof_matrix.core.types import Grade, OrderType, TradeDirection
from flof_matrix.core.data_types import TradeSignal

logger = logging.getLogger(__name__)


@dataclass
class OrderTicket:
    """Represents an order to be submitted."""

    order_type: OrderType
    direction: TradeDirection
    price: float
    size: int  # contracts
    protection_ticks: int = 3
    label: str = ""


@dataclass
class OCOBracket:
    """Exchange-native OCO bracket: Stop + Take Profit."""

    entry: OrderTicket
    stop_loss: OrderTicket
    take_profit: OrderTicket


class ExecutionManager:
    """Manages order creation with Fix B safety (MWP, no raw Market Orders).

    Position sizing: contracts = floor((equity × risk_pct) / (stop_distance × point_value))
    """

    def __init__(
        self,
        tick_size: float = 0.25,
        point_value: float = 50.0,
        mwp_protection_ticks: int = 3,
        default_order_type: str = "market_with_protection",
    ) -> None:
        self._tick_size = tick_size
        self._point_value = point_value
        self._mwp_ticks = mwp_protection_ticks
        self._default_order_type = default_order_type

    def calculate_position_size(
        self,
        equity: float,
        risk_pct: float,
        entry_price: float,
        stop_price: float,
    ) -> int:
        """Calculate number of contracts.

        contracts = floor((equity × risk_pct) / (stop_distance × point_value))
        """
        stop_distance = abs(entry_price - stop_price)
        if stop_distance == 0 or self._point_value == 0:
            return 0
        risk_dollars = equity * risk_pct
        contracts = math.floor(risk_dollars / (stop_distance * self._point_value))
        return max(contracts, 0)

    def create_entry_order(self, signal: TradeSignal) -> OrderTicket:
        """Create entry order. Fix B: Always MWP, never raw Market."""
        order_type = self._resolve_order_type(signal.order_type)
        return OrderTicket(
            order_type=order_type,
            direction=signal.direction,
            price=signal.entry_price,
            size=0,  # Set by caller after position sizing
            protection_ticks=self._mwp_ticks,
            label=f"ENTRY_{signal.grade.value}_{signal.direction.name}",
        )

    def create_oco_bracket(
        self,
        signal: TradeSignal,
        contracts: int,
        target_r: float = 2.0,
    ) -> OCOBracket:
        """Create OCO bracket: entry + stop (SWP) + take profit (Limit).

        T24: Every entry MUST have exchange-native OCO.
        """
        entry = OrderTicket(
            order_type=self._resolve_order_type(signal.order_type),
            direction=signal.direction,
            price=signal.entry_price,
            size=contracts,
            protection_ticks=self._mwp_ticks,
            label=f"ENTRY_{signal.grade.value}",
        )

        stop_loss = OrderTicket(
            order_type=OrderType.STOP_WITH_PROTECTION,
            direction=self._opposite_direction(signal.direction),
            price=signal.stop_price,
            size=contracts,
            protection_ticks=self._mwp_ticks,
            label="OCO_STOP",
        )

        # Take profit at ~2R
        risk = abs(signal.entry_price - signal.stop_price)
        if signal.direction == TradeDirection.LONG:
            tp_price = signal.entry_price + risk * target_r
        else:
            tp_price = signal.entry_price - risk * target_r

        # Round to tick
        tp_price = self._round_to_tick(tp_price)

        take_profit = OrderTicket(
            order_type=OrderType.LIMIT,
            direction=self._opposite_direction(signal.direction),
            price=tp_price,
            size=contracts,
            label="OCO_TP",
        )

        return OCOBracket(entry=entry, stop_loss=stop_loss, take_profit=take_profit)

    def execute_signal(
        self,
        signal: TradeSignal,
        equity: float,
    ) -> OCOBracket | None:
        """Full execution: size → entry → OCO bracket.

        Returns OCOBracket or None if sizing fails.
        """
        contracts = self.calculate_position_size(
            equity=equity,
            risk_pct=signal.position_size_pct,
            entry_price=signal.entry_price,
            stop_price=signal.stop_price,
        )

        if contracts <= 0:
            logger.warning("Position size is 0 contracts — signal rejected")
            return None

        bracket = self.create_oco_bracket(signal, contracts)
        logger.info(
            "Order created: %s %d contracts @ %.2f, SL=%.2f, TP=%.2f",
            signal.direction.name,
            contracts,
            signal.entry_price,
            bracket.stop_loss.price,
            bracket.take_profit.price,
        )
        return bracket

    def _resolve_order_type(self, requested: OrderType) -> OrderType:
        """Fix B: Ensure no raw Market Orders. Always use MWP for ES."""
        if self._default_order_type == "market_with_protection":
            return OrderType.MWP
        return requested

    def _opposite_direction(self, direction: TradeDirection) -> TradeDirection:
        return TradeDirection.SHORT if direction == TradeDirection.LONG else TradeDirection.LONG

    def _round_to_tick(self, price: float) -> float:
        return round(price / self._tick_size) * self._tick_size
