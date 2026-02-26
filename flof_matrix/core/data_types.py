"""Frozen dataclasses for FLOF Matrix data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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


@dataclass(frozen=True)
class POI:
    """Point of Interest — structural level where price is likely to react."""

    type: POIType
    price: float
    zone_high: float
    zone_low: float
    timeframe: str
    direction: TradeDirection
    is_extreme: bool = False
    is_decisional: bool = False
    is_flip_zone: bool = False
    is_sweep_zone: bool = False
    is_unicorn: bool = False
    has_inducement: bool = False
    is_fresh: bool = True


@dataclass(frozen=True)
class TradeSignal:
    """Signal produced by ConfluenceScorer when all gates pass."""

    direction: TradeDirection
    poi: POI
    entry_price: float
    stop_price: float
    target_price: float
    grade: Grade
    score_total: int
    score_tier1: int
    score_tier2: int
    score_tier3: int
    position_size_pct: float
    order_type: OrderType


@dataclass(frozen=True)
class PositionRecord:
    """Tracks an open or closed position."""

    position_id: str
    profile: str
    instrument: str
    correlation_group: str
    direction: TradeDirection
    grade: Grade
    entry_price: float
    stop_price: float
    target_price: float
    risk_pct: float
    contracts: int
    phase: TradePhase
    opened_at: int  # timestamp_ns


@dataclass(frozen=True)
class HealthReport:
    """Infrastructure health snapshot from InfraHealth monitor."""

    databento_latency_ms: float
    broker_latency_ms: float
    last_heartbeat_age_ms: float
    is_healthy: bool


@dataclass(frozen=True)
class Event:
    """Event bus message."""

    type: EventType
    timestamp_ns: int
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
