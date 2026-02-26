"""Core enums used across the FLOF Matrix system."""

from enum import Enum, auto


class PredatorState(Enum):
    DORMANT = auto()
    SCOUTING = auto()
    STALKING = auto()
    KILL = auto()


class Grade(Enum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"  # NO TRADE


class POIType(Enum):
    ORDER_BLOCK = auto()
    FVG = auto()
    LIQUIDITY_POOL = auto()
    SYNTHETIC_MA = auto()
    REJECTION_BLOCK = auto()
    BREAKER_BLOCK = auto()
    GAP_FVG = auto()


class TradeDirection(Enum):
    LONG = auto()
    SHORT = auto()


class TradePhase(Enum):
    PHASE1_INITIAL = auto()
    PHASE2_RUNNER = auto()
    PHASE3_CLIMAX = auto()


class SuddenMoveType(Enum):
    NONE = auto()
    TYPE_A = auto()  # Scheduled events (CPI, FOMC, NFP)
    TYPE_B = auto()  # Organic cascade (flash crash, liquidation)
    TYPE_C = auto()  # Infrastructure degradation


class OrderType(Enum):
    MWP = "market_with_protection"
    AGGRESSIVE_LIMIT = "aggressive_limit"
    LIMIT = "limit"
    STOP_WITH_PROTECTION = "stop_with_protection"


class EventType(Enum):
    ORDER_FIRED = "ORDER_FIRED"
    POSITION_CLOSED = "POSITION_CLOSED"
    RISK_LIMIT_BREACHED = "RISK_LIMIT_BREACHED"
    STALE_DATA_ALERT = "STALE_DATA_ALERT"
    MACRO_DUMP_DETECTED = "MACRO_DUMP_DETECTED"
    CHOP_DETECTED = "CHOP_DETECTED"
    CHOP_CLEARED = "CHOP_CLEARED"
    EOD_FLATTEN_WARNING = "EOD_FLATTEN_WARNING"
    EOD_FLATTEN_EXECUTE = "EOD_FLATTEN_EXECUTE"
    GEX_UPDATE = "GEX_UPDATE"
    DAILY_RESET = "DAILY_RESET"
