"""Portfolio Manager (M16, Component) — Pre-execution gate with 5 risk gates.

Evaluation order (cheapest-first): P3 → P4 → P5 → P1 → P2

All 5 gates must pass for a new entry. Position Ledger: pre-allocated,
cached running totals for O(1) gate checks. All 5 gates < 1ms total.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from flof_matrix.core.types import TradeDirection

logger = logging.getLogger(__name__)


@dataclass
class PositionLedgerEntry:
    """Tracks a position for portfolio risk calculations."""

    position_id: str
    instrument: str
    correlation_group: str
    direction: TradeDirection
    risk_pct: float  # % of equity at risk
    contracts: int
    is_open: bool = True


class PortfolioManager:
    """Pre-execution risk gate. 5 gates evaluated cheapest-first.

    Maintains a Position Ledger with cached aggregates for O(1) checks.
    """

    def __init__(
        self,
        p1_max_total_exposure: float = 0.06,
        p2_max_per_group: int = 2,
        p3_daily_drawdown_limit: float = -0.02,
        p4_max_loss_streak: int = 3,
        p5_lockout_seconds: float = 300.0,
        correlation_groups: dict[str, list[str]] | None = None,
    ) -> None:
        self._p1_max_exposure = p1_max_total_exposure
        self._p2_max_per_group = p2_max_per_group
        self._p3_drawdown_limit = p3_daily_drawdown_limit
        self._p4_max_streak = p4_max_loss_streak
        self._p5_lockout_ns = int(p5_lockout_seconds * 1_000_000_000)
        self._correlation_groups = correlation_groups or {}
        self._instrument_to_group: dict[str, str] = {}
        self._build_instrument_map()

        # Position Ledger — cached aggregates
        self._positions: dict[str, PositionLedgerEntry] = {}
        self._total_exposure: float = 0.0
        self._group_counts: dict[str, int] = {}

        # State
        self._daily_pnl_pct: float = 0.0
        self._consecutive_losses: int = 0
        self._nuclear_flatten_time_ns: int | None = None

    def _build_instrument_map(self) -> None:
        for group_name, instruments in self._correlation_groups.items():
            for inst in instruments:
                self._instrument_to_group[inst] = group_name

    def evaluate_gates(
        self,
        instrument: str,
        risk_pct: float,
        now_ns: int,
    ) -> tuple[bool, str]:
        """Evaluate all 5 gates. Returns (passed, rejection_reason).

        Order: P3 → P4 → P5 → P1 → P2 (cheapest-first).
        """
        # P3: Daily drawdown
        if self._daily_pnl_pct <= self._p3_drawdown_limit:
            return False, f"P3_daily_drawdown: {self._daily_pnl_pct:.2%} <= {self._p3_drawdown_limit:.2%}"

        # P4: Loss streak
        if self._consecutive_losses >= self._p4_max_streak:
            return False, f"P4_loss_streak: {self._consecutive_losses} >= {self._p4_max_streak}"

        # P5: Post-nuclear lockout
        if self._nuclear_flatten_time_ns is not None:
            elapsed = now_ns - self._nuclear_flatten_time_ns
            if elapsed < self._p5_lockout_ns:
                remaining_s = (self._p5_lockout_ns - elapsed) / 1_000_000_000
                return False, f"P5_nuclear_lockout: {remaining_s:.0f}s remaining"

        # P1: Total exposure
        projected_exposure = self._total_exposure + risk_pct
        if projected_exposure > self._p1_max_exposure:
            return False, f"P1_total_exposure: {projected_exposure:.2%} > {self._p1_max_exposure:.2%}"

        # P2: Correlation group limit
        group = self._instrument_to_group.get(instrument, "default")
        current_count = self._group_counts.get(group, 0)
        if current_count >= self._p2_max_per_group:
            return False, f"P2_group_limit: group '{group}' has {current_count} >= {self._p2_max_per_group}"

        return True, "all_gates_passed"

    def add_position(self, entry: PositionLedgerEntry) -> None:
        """Add position and update cached aggregates."""
        self._positions[entry.position_id] = entry
        self._total_exposure += entry.risk_pct
        group = self._instrument_to_group.get(entry.instrument, "default")
        entry.correlation_group = group
        self._group_counts[group] = self._group_counts.get(group, 0) + 1

    def remove_position(self, position_id: str) -> None:
        """Remove position and update cached aggregates."""
        entry = self._positions.pop(position_id, None)
        if entry is None:
            return
        self._total_exposure = max(0.0, self._total_exposure - entry.risk_pct)
        group = entry.correlation_group
        self._group_counts[group] = max(0, self._group_counts.get(group, 0) - 1)

    def update_daily_pnl(self, pnl_pct: float) -> None:
        self._daily_pnl_pct = pnl_pct

    def record_loss(self) -> None:
        self._consecutive_losses += 1

    def record_win(self) -> None:
        self._consecutive_losses = 0

    def record_nuclear_flatten(self, now_ns: int) -> None:
        self._nuclear_flatten_time_ns = now_ns

    @property
    def total_exposure(self) -> float:
        return self._total_exposure

    @property
    def open_position_count(self) -> int:
        return len(self._positions)

    def reset_daily(self) -> None:
        """Reset daily state."""
        self._daily_pnl_pct = 0.0
        self._consecutive_losses = 0
        self._nuclear_flatten_time_ns = None
