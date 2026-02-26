"""Shared fixtures for FLOF Matrix tests."""

from __future__ import annotations

import numpy as np
import pytest

from flof_matrix.config.config_manager import ConfigManager
from flof_matrix.core.ring_buffer import RingBuffer, TICK_DTYPE
from flof_matrix.core.types import Grade, OrderType, POIType, TradeDirection
from flof_matrix.core.data_types import POI, TradeSignal


CONFIG_PATH = "/home/kris/tradestar/flof/flof_matrix/config/flof_base.toml"

BAR_DTYPE = np.dtype([
    ("timestamp_ns", np.int64),
    ("open", np.float64),
    ("high", np.float64),
    ("low", np.float64),
    ("close", np.float64),
    ("volume", np.float64),
])


@pytest.fixture
def config():
    """Loaded ConfigManager with futures profile."""
    ConfigManager.reset()
    cm = ConfigManager()
    cm.load(CONFIG_PATH, profile="futures")
    yield cm
    ConfigManager.reset()


@pytest.fixture
def ring_buffer():
    """Pre-filled ring buffer with 100 ticks spanning 1 second."""
    rb = RingBuffer(capacity=10_000)
    base_ts = 1_000_000_000_000
    for i in range(100):
        side = 1 if i % 3 != 0 else -1
        rb.push(base_ts + i * 10_000_000, 5000.0 + i * 0.25, 10.0, side)
    return rb


@pytest.fixture
def empty_ring_buffer():
    """Empty ring buffer."""
    return RingBuffer(capacity=10_000)


@pytest.fixture
def sample_poi_long():
    """Sample bullish POI at 5000."""
    return POI(
        type=POIType.ORDER_BLOCK,
        price=5000.0,
        zone_high=5002.0,
        zone_low=4998.0,
        timeframe="1H",
        direction=TradeDirection.LONG,
        has_inducement=True,
        is_fresh=True,
    )


@pytest.fixture
def sample_poi_short():
    """Sample bearish POI at 5100."""
    return POI(
        type=POIType.ORDER_BLOCK,
        price=5100.0,
        zone_high=5102.0,
        zone_low=5098.0,
        timeframe="1H",
        direction=TradeDirection.SHORT,
        has_inducement=True,
        is_fresh=True,
    )


@pytest.fixture
def sample_signal_a(sample_poi_long):
    """Sample A-grade long signal."""
    return TradeSignal(
        direction=TradeDirection.LONG,
        poi=sample_poi_long,
        entry_price=5000.0,
        stop_price=4990.0,
        target_price=5020.0,
        grade=Grade.A,
        score_total=12,
        score_tier1=8,
        score_tier2=3,
        score_tier3=1,
        position_size_pct=0.015,
        order_type=OrderType.MWP,
    )


@pytest.fixture
def synthetic_bars():
    """Generate 200 synthetic 1-min bars."""
    n = 200
    bars = np.zeros(n, dtype=BAR_DTYPE)
    price = 5000.0
    base_ts = 1_000_000_000_000

    for i in range(n):
        bars[i]["timestamp_ns"] = base_ts + i * 60_000_000_000
        bars[i]["open"] = price
        change = np.random.uniform(-2, 2)
        bars[i]["high"] = price + abs(change) + np.random.uniform(0, 1)
        bars[i]["low"] = price - abs(change) - np.random.uniform(0, 1)
        bars[i]["close"] = price + change
        bars[i]["volume"] = np.random.uniform(100, 500)
        price = bars[i]["close"]

    return bars
