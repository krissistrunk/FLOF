"""Sudden Move Classifier (M12, Component) — Chameleon Protocol.

Classification order: Type C (infra) → Type A (calendar) → Type B (cascade) → NONE.
Thresholds from flof_base.toml section 11.
"""

from __future__ import annotations

from flof_matrix.core.types import SuddenMoveType
from flof_matrix.core.data_types import HealthReport


# Default thresholds (overridden by config)
DEFAULT_THRESHOLDS = {
    "tick_velocity_threshold_pct": 400,
    "range_expansion_threshold": 3.0,
    "databento_latency_max_ms": 500,
    "broker_api_latency_max_ms": 400,
    "heartbeat_timeout_es_seconds": 5,
    "spread_quarantine_es_ticks": 3,
}


class SuddenMoveClassifier:
    """Classifies sudden market moves into Type A/B/C.

    Priority: C (infra) → A (calendar) → B (cascade) → NONE.
    """

    def __init__(
        self,
        tick_velocity_threshold_pct: float = 400,
        range_expansion_threshold: float = 3.0,
        databento_latency_max_ms: float = 500,
        broker_api_latency_max_ms: float = 400,
        spread_quarantine_ticks: int = 3,
    ) -> None:
        self._tick_velocity_threshold = tick_velocity_threshold_pct
        self._range_expansion_threshold = range_expansion_threshold
        self._databento_latency_max = databento_latency_max_ms
        self._broker_latency_max = broker_api_latency_max_ms
        self._spread_quarantine = spread_quarantine_ticks

    def classify(
        self,
        health: HealthReport | None,
        has_calendar_event: bool,
        tape_velocity_pct: float,
        spread_current: float,
        spread_baseline: float,
    ) -> SuddenMoveType:
        """Classify current market conditions.

        Priority: Type C → Type A → Type B → NONE
        """
        # Type C: Infrastructure degradation
        if health is not None and not health.is_healthy:
            return SuddenMoveType.TYPE_C

        # Type A: Scheduled event
        if has_calendar_event and tape_velocity_pct > self._tick_velocity_threshold:
            return SuddenMoveType.TYPE_A

        # Type B: Organic cascade
        if (
            tape_velocity_pct > self._tick_velocity_threshold
            and spread_baseline > 0
            and spread_current > self._spread_quarantine * spread_baseline
        ):
            return SuddenMoveType.TYPE_B

        return SuddenMoveType.NONE

    def get_response(self, move_type: SuddenMoveType) -> dict:
        """Return protocol response for each sudden move type."""
        if move_type == SuddenMoveType.TYPE_A:
            return {
                "action": "cooldown",
                "cooldown_seconds": 180,
                "position_size_mult": 1.0,
                "description": "Scheduled event — 3-min cooldown after event",
            }
        elif move_type == SuddenMoveType.TYPE_B:
            return {
                "action": "reduce_size",
                "cooldown_seconds": 300,
                "position_size_mult": 0.50,
                "min_ring_buffer_seconds": 30,
                "description": "Organic cascade — 50% size, 5-min cooldown",
            }
        elif move_type == SuddenMoveType.TYPE_C:
            return {
                "action": "full_shutdown",
                "cooldown_seconds": 60,  # health_window
                "position_size_mult": 0.0,
                "description": "Infrastructure degradation — full shutdown",
            }
        else:
            return {
                "action": "none",
                "cooldown_seconds": 0,
                "position_size_mult": 1.0,
                "description": "Normal conditions",
            }
