"""Predator State Machine (M05, Component) — DORMANT → SCOUTING → STALKING → KILL.

State transitions:
  DORMANT → SCOUTING: Killzone opens (triggers Fix A schema activation)
  SCOUTING → STALKING: Proximity Halo breached (1.5 × ATR) OR tape velocity > 300%
  STALKING → KILL: POI tapped + 1m CHOCH detected + Ring Buffer >= 30s
  KILL → DORMANT: Trade executed/rejected OR Killzone ends
  ANY → DORMANT: Killzone close, Type C, Nuclear Flatten
"""

from __future__ import annotations

import logging
from datetime import datetime, time as dt_time

from flof_matrix.core.types import PredatorState, SuddenMoveType

logger = logging.getLogger(__name__)


class PredatorStateMachine:
    """Manages trading state transitions and Killzone awareness."""

    def __init__(
        self,
        proximity_halo_atr_mult: float = 1.5,
        tape_velocity_stalking_pct: float = 300.0,
        kill_mode_ring_buffer_min: float = 30.0,
        killzones: list[dict] | None = None,
    ) -> None:
        self._state = PredatorState.DORMANT
        self._proximity_halo_mult = proximity_halo_atr_mult
        self._tape_velocity_threshold = tape_velocity_stalking_pct
        self._kill_buffer_min = kill_mode_ring_buffer_min
        self._killzones = killzones or []
        self._transition_callbacks: list = []

    @property
    def state(self) -> PredatorState:
        return self._state

    def register_transition_callback(self, callback) -> None:
        """Register callback for state transitions. Called with (old_state, new_state)."""
        self._transition_callbacks.append(callback)

    def transition_to(self, new_state: PredatorState) -> None:
        """Force a state transition."""
        if new_state == self._state:
            return
        old_state = self._state
        self._state = new_state
        logger.info("Predator: %s → %s", old_state.name, new_state.name)
        for cb in self._transition_callbacks:
            cb(old_state, new_state)

    def evaluate_state(
        self,
        current_time: datetime,
        current_price: float,
        atr: float,
        poi_price: float | None = None,
        has_choch: bool = False,
        ring_buffer_ready: bool = False,
        tape_velocity_pct: float = 0.0,
        sudden_move: SuddenMoveType = SuddenMoveType.NONE,
        trade_executed: bool = False,
    ) -> PredatorState:
        """Evaluate and potentially transition state.

        Returns the new state.
        """
        # Emergency transitions: ANY → DORMANT
        if sudden_move == SuddenMoveType.TYPE_C:
            self.transition_to(PredatorState.DORMANT)
            return self._state

        in_killzone = self.check_killzone(current_time)

        # Killzone ended: any state → DORMANT
        if not in_killzone and self._state != PredatorState.DORMANT:
            self.transition_to(PredatorState.DORMANT)
            return self._state

        if self._state == PredatorState.DORMANT:
            if in_killzone:
                self.transition_to(PredatorState.SCOUTING)

        elif self._state == PredatorState.SCOUTING:
            # Check Proximity Halo OR tape velocity
            if poi_price is not None:
                proximity = self.calculate_proximity(current_price, poi_price, atr)
                if proximity:
                    self.transition_to(PredatorState.STALKING)
                    return self._state

            velocity = self.calculate_tape_velocity(tape_velocity_pct)
            if velocity:
                self.transition_to(PredatorState.STALKING)

        elif self._state == PredatorState.STALKING:
            # POI tapped + CHOCH + Ring Buffer ready
            if poi_price is not None and has_choch and ring_buffer_ready:
                poi_tapped = abs(current_price - poi_price) <= atr * 0.5
                if poi_tapped:
                    self.transition_to(PredatorState.KILL)

        elif self._state == PredatorState.KILL:
            if trade_executed or not in_killzone:
                self.transition_to(PredatorState.DORMANT)

        return self._state

    def check_killzone(self, current_time: datetime) -> bool:
        """Check if current time is within any killzone window."""
        if not self._killzones:
            return True  # No killzones configured = always active

        ct = current_time.time()
        for kz in self._killzones:
            start = self._parse_time(kz.get("start", "00:00"))
            end = self._parse_time(kz.get("end", "23:59"))
            if start <= ct <= end:
                return True
        return False

    def calculate_proximity(
        self,
        current_price: float,
        poi_price: float,
        atr: float,
    ) -> bool:
        """Check if price is within proximity halo of POI."""
        halo = self._proximity_halo_mult * atr
        return abs(current_price - poi_price) <= halo

    def calculate_tape_velocity(self, velocity_pct: float) -> bool:
        """Check if tape velocity exceeds stalking threshold."""
        return velocity_pct >= self._tape_velocity_threshold

    def force_dormant(self) -> None:
        """Nuclear flatten / emergency shutdown."""
        self.transition_to(PredatorState.DORMANT)

    @staticmethod
    def _parse_time(time_str: str) -> dt_time:
        parts = time_str.split(":")
        return dt_time(int(parts[0]), int(parts[1]))
