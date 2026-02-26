"""Trade Manager (M09) — Three-phase profit management.

Phase 1: Fixed Partial at ~2R (50% exit, stop to breakeven + 1 tick)
Phase 2: Structural Node Trail (runner behind 5m BOS + LVN moats)
Phase 3: Dynamic Climax Exit (absorption + delta stall detection)

Conditional exits: Tape Failure, Toxicity Timer, Toxicity Exit, EOD Flatten.
"""

from __future__ import annotations

import logging
import time

from flof_matrix.core.types import Grade, TradeDirection, TradePhase

logger = logging.getLogger(__name__)


class ManagedPosition:
    """Tracks a position through its 3-phase lifecycle."""

    def __init__(
        self,
        position_id: str,
        direction: TradeDirection,
        grade: Grade,
        entry_price: float,
        stop_price: float,
        target_price: float,
        total_contracts: int,
        entry_time_ns: int,
    ) -> None:
        self.position_id = position_id
        self.direction = direction
        self.grade = grade
        self.entry_price = entry_price
        self.stop_price = stop_price
        self.target_price = target_price
        self.total_contracts = total_contracts
        self.remaining_contracts = total_contracts
        self.entry_time_ns = entry_time_ns
        self.phase = TradePhase.PHASE1_INITIAL
        self.partial_filled = False
        self.breakeven_set = False
        self.original_risk: float = abs(entry_price - stop_price)
        self.highest_favorable: float = entry_price
        self.last_movement_ns: int = entry_time_ns

        # Exit tracking
        self.exit_price: float = 0.0
        self.exit_reason: str = ""
        self.exit_time_ns: int = 0
        self.pnl_dollars: float = 0.0
        self.pnl_r_multiple: float = 0.0
        self.partial_pnl_dollars: float = 0.0


class TradeManager:
    """Manages open positions through 3 phases with conditional exits."""

    def __init__(
        self,
        tick_size: float = 0.25,
        point_value: float = 50.0,
        # Phase 1
        phase1_target_r: float = 2.0,
        default_partial_pct: float = 0.50,
        a_plus_partial_pct: float = 0.33,
        # Micro trail
        micro_trail_activation_r: float = 1.0,
        # Phase 2
        trail_method: str = "structural_node",
        fixed_trail_r: float = 2.0,
        # Phase 3
        climax_absorption_threshold: float = 0.75,
        climax_delta_stall_pct: float = 0.30,
        climax_target_proximity_pct: float = 0.75,
        # Conditional exits
        tape_failure_delta: float = 0.80,
        tape_failure_tightened_delta: float = 0.65,
        toxicity_timer_seconds: float = 120.0,
        toxicity_delta_pct: float = 0.70,
        eod_flatten_time: str = "15:50",
    ) -> None:
        self._tick_size = tick_size
        self._point_value = point_value
        self._phase1_target_r = phase1_target_r
        self._default_partial = default_partial_pct
        self._aplus_partial = a_plus_partial_pct
        self._micro_trail_activation_r = micro_trail_activation_r
        self._trail_method = trail_method
        self._fixed_trail_r = fixed_trail_r
        self._climax_absorption = climax_absorption_threshold
        self._climax_delta_stall = climax_delta_stall_pct
        self._climax_target_proximity = climax_target_proximity_pct
        self._tape_failure_delta = tape_failure_delta
        self._tape_failure_tightened = tape_failure_tightened_delta
        self._toxicity_timer_ns = int(toxicity_timer_seconds * 1_000_000_000)
        self._toxicity_delta = toxicity_delta_pct
        self._eod_flatten_time = eod_flatten_time

        self._positions: dict[str, ManagedPosition] = {}

    @property
    def positions(self) -> dict[str, ManagedPosition]:
        return self._positions

    def add_position(self, pos: ManagedPosition) -> None:
        self._positions[pos.position_id] = pos

    def remove_position(self, position_id: str) -> ManagedPosition | None:
        return self._positions.pop(position_id, None)

    def evaluate_phase1(
        self,
        pos: ManagedPosition,
        current_price: float,
    ) -> dict | None:
        """Phase 1 (T23): Fixed partial at ~2R target.

        Returns action dict or None.
        """
        if pos.phase != TradePhase.PHASE1_INITIAL:
            return None
        if pos.partial_filled:
            return None

        risk = abs(pos.entry_price - pos.stop_price)
        if risk == 0:
            return None

        if pos.direction == TradeDirection.LONG:
            r_multiple = (current_price - pos.entry_price) / risk
        else:
            r_multiple = (pos.entry_price - current_price) / risk

        if r_multiple >= self._phase1_target_r:
            # Determine partial percentage
            if pos.grade == Grade.A_PLUS:
                partial_pct = self._aplus_partial  # T36: 33% for A+
            else:
                partial_pct = self._default_partial

            partial_contracts = max(1, int(pos.total_contracts * partial_pct))

            return {
                "action": "partial_exit",
                "contracts": partial_contracts,
                "price": current_price,
                "move_stop_to_breakeven": True,
                "breakeven_price": pos.entry_price + (self._tick_size if pos.direction == TradeDirection.LONG else -self._tick_size),
            }
        return None

    def apply_phase1_result(self, pos: ManagedPosition, result: dict) -> None:
        """Apply Phase 1 partial exit results."""
        pos.remaining_contracts -= result["contracts"]
        pos.partial_filled = True
        pos.stop_price = result["breakeven_price"]
        pos.breakeven_set = True
        pos.phase = TradePhase.PHASE2_RUNNER
        logger.info("Phase 1 partial: %s exited %d contracts, BE set", pos.position_id, result["contracts"])

    def check_micro_trail(
        self,
        pos: ManagedPosition,
        current_price: float,
    ) -> dict | None:
        """Micro trailing stop: once price reaches +1R, move stop to breakeven.

        Activates before Phase 1 partial. Prevents winners from becoming losers.
        Only fires once (sets breakeven_set flag). Does NOT change phase.
        """
        if pos.breakeven_set:
            return None
        if pos.phase != TradePhase.PHASE1_INITIAL:
            return None

        risk = abs(pos.entry_price - pos.stop_price)
        if risk == 0:
            return None

        if pos.direction == TradeDirection.LONG:
            r_multiple = (current_price - pos.entry_price) / risk
        else:
            r_multiple = (pos.entry_price - current_price) / risk

        if r_multiple >= self._micro_trail_activation_r:
            be_price = pos.entry_price + (
                self._tick_size if pos.direction == TradeDirection.LONG else -self._tick_size
            )
            return {"action": "micro_trail", "new_stop": self._round_to_tick(be_price)}
        return None

    def apply_micro_trail(self, pos: ManagedPosition, result: dict) -> None:
        """Apply micro trail result — move stop to breakeven."""
        pos.stop_price = result["new_stop"]
        pos.breakeven_set = True
        logger.info("Micro trail: %s stop moved to BE %s", pos.position_id, result["new_stop"])

    def evaluate_phase2(
        self,
        pos: ManagedPosition,
        current_price: float,
        bos_level: float | None = None,
        lvn_moat: float | None = None,
        sma_health_ok: bool = True,
    ) -> dict | None:
        """Phase 2 (T19): Structural Node Trail.

        Trail behind 5m BOS + LVN moats. RBI/GBI hold filter (T20).
        """
        if pos.phase != TradePhase.PHASE2_RUNNER:
            return None

        # Update highest favorable
        if pos.direction == TradeDirection.LONG:
            pos.highest_favorable = max(pos.highest_favorable, current_price)
        else:
            pos.highest_favorable = min(pos.highest_favorable, current_price)

        # Structural trail: behind BOS level + LVN moat
        new_stop = None
        if self._trail_method == "structural_node" and bos_level is not None:
            if pos.direction == TradeDirection.LONG:
                candidate = bos_level
                if lvn_moat is not None:
                    candidate = min(candidate, lvn_moat)
                if candidate > pos.stop_price:
                    new_stop = candidate
            else:
                candidate = bos_level
                if lvn_moat is not None:
                    candidate = max(candidate, lvn_moat)
                if candidate < pos.stop_price:
                    new_stop = candidate
        else:
            # Fixed trail fallback — use original entry risk, not current
            # (after Phase 1, stop is at breakeven so entry-stop would be ~1 tick)
            risk = pos.original_risk
            if risk <= 0:
                risk = abs(pos.entry_price - pos.stop_price)
            if pos.direction == TradeDirection.LONG:
                candidate = pos.highest_favorable - self._fixed_trail_r * risk
                if candidate > pos.stop_price:
                    new_stop = candidate
            else:
                candidate = pos.highest_favorable + self._fixed_trail_r * risk
                if candidate < pos.stop_price:
                    new_stop = candidate

        if new_stop is not None:
            return {"action": "update_stop", "new_stop": self._round_to_tick(new_stop)}
        return None

    def evaluate_phase3(
        self,
        pos: ManagedPosition,
        absorption_score: float,
        delta_pct: float,
        current_price: float = 0.0,
        near_200sma: bool = False,
    ) -> dict | None:
        """Phase 3: Dynamic Climax Exit.

        Exit when: price near target + absorption > threshold + delta stall.
        Only fires when price has traveled >= 75% of entry→target distance.
        T22: 200 SMA watch zone lowers thresholds.
        """
        if pos.phase != TradePhase.PHASE2_RUNNER:
            return None

        # Target proximity gate: only check climax near the target zone
        if current_price != 0.0 and self._climax_target_proximity > 0:
            total_distance = abs(pos.target_price - pos.entry_price)
            if total_distance > 0:
                if pos.direction == TradeDirection.LONG:
                    traveled = current_price - pos.entry_price
                else:
                    traveled = pos.entry_price - current_price
                progress = traveled / total_distance
                if progress < self._climax_target_proximity:
                    return None

        absorption_threshold = self._climax_absorption
        delta_threshold = self._climax_delta_stall

        # T22: Lower thresholds near 200 SMA
        if near_200sma:
            absorption_threshold *= 0.8
            delta_threshold *= 1.2

        if absorption_score >= absorption_threshold and abs(delta_pct) <= delta_threshold:
            return {
                "action": "climax_exit",
                "reason": "absorption_climax",
                "absorption": absorption_score,
                "delta": delta_pct,
            }
        return None

    def check_tape_failure(
        self,
        pos: ManagedPosition,
        sell_delta_pct: float,
        sma_health_ok: bool = True,
    ) -> dict | None:
        """T18: Conditional Tape Failure Exit.

        80% sell delta → exit. T21: Tightened to 65% when 20 SMA health fails.
        """
        threshold = self._tape_failure_delta if sma_health_ok else self._tape_failure_tightened

        if sell_delta_pct >= threshold:
            return {
                "action": "tape_failure_exit",
                "sell_delta": sell_delta_pct,
                "threshold": threshold,
                "tightened": not sma_health_ok,
            }
        return None

    def check_toxicity_timer(
        self,
        pos: ManagedPosition,
        now_ns: int,
    ) -> dict | None:
        """T35: Exit if no favorable movement within 120 seconds."""
        elapsed = now_ns - pos.last_movement_ns
        if elapsed >= self._toxicity_timer_ns:
            return {
                "action": "toxicity_timer_exit",
                "elapsed_seconds": elapsed / 1_000_000_000,
            }
        return None

    def check_toxicity_exit(
        self,
        pos: ManagedPosition,
        adverse_delta_pct: float,
    ) -> dict | None:
        """T48: Immediate exit if 70% adverse delta."""
        if adverse_delta_pct >= self._toxicity_delta:
            return {
                "action": "toxicity_exit",
                "adverse_delta": adverse_delta_pct,
            }
        return None

    def check_eod_flatten(self, current_time_str: str) -> bool:
        """Check if it's time for EOD flatten."""
        return current_time_str >= self._eod_flatten_time

    def _round_to_tick(self, price: float) -> float:
        return round(price / self._tick_size) * self._tick_size
