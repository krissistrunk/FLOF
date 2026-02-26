"""Risk Overlord (M10, Actor) — Independent safety monitor.

Runs every 100ms. Checks 4 safety pillars:
  T25: Anti-Spam — max orders/minute
  T26: Fat Finger — max concurrent positions
  T27: Daily Drawdown — triggers Nuclear Flatten at -3%
  T28: Stale Data — 5 seconds to Nuclear Flatten

Nuclear Flatten: DIRECT strategy access, NOT via event bus for kill actions.
"""

from __future__ import annotations

import logging
import os
import time

from flof_matrix.core.types import EventType, PredatorState
from flof_matrix.core.data_types import Event

logger = logging.getLogger(__name__)


class RiskOverlord:
    """Independent safety module. NEVER part of trading logic.

    Has direct access to strategy for Nuclear Flatten (bypasses event bus).
    """

    def __init__(
        self,
        max_orders_per_minute: int = 3,
        max_concurrent_positions: int = 3,
        max_daily_drawdown_pct: float = -0.03,
        max_consecutive_losses: int = 3,
        stale_data_countdown_seconds: float = 5.0,
        live_mode: bool = False,
        event_bus=None,
        strategy=None,
    ) -> None:
        self._max_orders_min = max_orders_per_minute
        self._max_positions = max_concurrent_positions
        self._max_drawdown = max_daily_drawdown_pct
        self._max_consec_losses = max_consecutive_losses
        self._stale_countdown_ns = int(stale_data_countdown_seconds * 1_000_000_000)
        self._live_mode = live_mode
        self._event_bus = event_bus
        self._strategy = strategy

        # State
        self._order_timestamps: list[int] = []  # ns timestamps of recent orders
        self._current_positions: int = 0
        self._daily_pnl_pct: float = 0.0
        self._consecutive_losses: int = 0
        self._stale_alert_start_ns: int | None = None
        self._is_flattened: bool = False

    @property
    def is_flattened(self) -> bool:
        return self._is_flattened

    def set_strategy(self, strategy) -> None:
        """Set strategy reference for Nuclear Flatten direct access."""
        self._strategy = strategy

    def update_positions(self, count: int) -> None:
        self._current_positions = count

    def update_daily_pnl(self, pnl_pct: float) -> None:
        self._daily_pnl_pct = pnl_pct

    def record_order(self, timestamp_ns: int) -> None:
        self._order_timestamps.append(timestamp_ns)

    def record_loss(self) -> None:
        self._consecutive_losses += 1

    def record_win(self) -> None:
        self._consecutive_losses = 0

    def on_stale_data_alert(self, timestamp_ns: int) -> None:
        """Called when InfraHealth detects stale data."""
        if self._stale_alert_start_ns is None:
            self._stale_alert_start_ns = timestamp_ns

    def clear_stale_alert(self) -> None:
        self._stale_alert_start_ns = None

    def check(self, now_ns: int) -> dict:
        """Run all 4 safety checks. Returns result dict.

        Should be called every 100ms.
        """
        if self._is_flattened:
            return {"status": "flattened", "pillar": None}

        result = {"status": "ok", "pillar": None}

        # T25: Anti-Spam
        if self._check_anti_spam(now_ns):
            result = {"status": "breach", "pillar": "T25_anti_spam"}

        # T26: Fat Finger
        elif self._check_fat_finger():
            result = {"status": "breach", "pillar": "T26_fat_finger"}

        # T27: Daily Drawdown
        elif self._check_daily_drawdown():
            result = {"status": "breach", "pillar": "T27_daily_drawdown"}

        # Consecutive losses
        elif self._check_consecutive_losses():
            result = {"status": "breach", "pillar": "consecutive_losses"}

        # T28: Stale Data
        elif self._check_stale_data(now_ns):
            result = {"status": "breach", "pillar": "T28_stale_data"}

        if result["status"] == "breach":
            logger.critical("RISK BREACH: %s — initiating Nuclear Flatten", result["pillar"])
            self._nuclear_flatten(now_ns, result["pillar"])

        return result

    def _check_anti_spam(self, now_ns: int) -> bool:
        """T25: Max orders per minute."""
        one_minute_ago = now_ns - 60_000_000_000
        recent = [ts for ts in self._order_timestamps if ts > one_minute_ago]
        self._order_timestamps = recent
        return len(recent) > self._max_orders_min

    def _check_fat_finger(self) -> bool:
        """T26: Max concurrent positions."""
        return self._current_positions > self._max_positions

    def _check_daily_drawdown(self) -> bool:
        """T27: Daily drawdown limit."""
        return self._daily_pnl_pct <= self._max_drawdown

    def _check_consecutive_losses(self) -> bool:
        """Consecutive loss limit."""
        return self._consecutive_losses >= self._max_consec_losses

    def _check_stale_data(self, now_ns: int) -> bool:
        """T28: Stale data countdown."""
        if self._stale_alert_start_ns is None:
            return False
        elapsed = now_ns - self._stale_alert_start_ns
        return elapsed >= self._stale_countdown_ns

    def _nuclear_flatten(self, now_ns: int, reason: str) -> None:
        """Execute Nuclear Flatten sequence.

        1. Cancel ALL working orders
        2. Market-exit ALL positions (net = 0)
        3. Publish RISK_LIMIT_BREACHED event
        4. Set bot to DORMANT
        5. Log critical alert
        6. If live_mode=true: os._exit(1)
        """
        self._is_flattened = True

        # Step 1-2: Direct strategy access (NOT via event bus)
        if self._strategy is not None:
            try:
                self._strategy.cancel_all_orders()
            except Exception:
                logger.exception("Failed to cancel orders during Nuclear Flatten")
            try:
                self._strategy.flatten_all_positions()
            except Exception:
                logger.exception("Failed to flatten positions during Nuclear Flatten")
            try:
                self._strategy.force_dormant()
            except Exception:
                logger.exception("Failed to set DORMANT during Nuclear Flatten")

        # Step 3: Publish event
        if self._event_bus is not None:
            event = Event(
                type=EventType.RISK_LIMIT_BREACHED,
                timestamp_ns=now_ns,
                source="RiskOverlord",
                payload={"reason": reason},
            )
            self._event_bus.publish_sync(event)

        # Step 5: Log
        logger.critical(
            "NUCLEAR FLATTEN EXECUTED — Reason: %s | PnL: %.2f%% | Positions: %d",
            reason,
            self._daily_pnl_pct * 100,
            self._current_positions,
        )

        # Step 6: Kill process in live mode
        if self._live_mode:
            logger.critical("LIVE MODE — os._exit(1)")
            os._exit(1)

    def reset_daily(self) -> None:
        """Reset daily state (called at DAILY_RESET event)."""
        self._daily_pnl_pct = 0.0
        self._consecutive_losses = 0
        self._order_timestamps.clear()
        self._stale_alert_start_ns = None
        self._is_flattened = False
