"""Tests for OrderFlowEngine — CVD, divergence, absorption (3 conditions), whale."""

import numpy as np
import pytest

from flof_matrix.core.ring_buffer import RingBuffer
from flof_matrix.order_flow.order_flow_engine import OrderFlowEngine


class TestOrderFlowEngine:
    def _make_engine(self, buffer_data=None):
        rb = RingBuffer(capacity=10_000)
        if buffer_data:
            for ts, price, size, side in buffer_data:
                rb.push(ts, price, size, side)
        ofe = OrderFlowEngine(ring_buffer=rb)
        ofe.set_session_averages(avg_volume=100.0, avg_trade_size=10.0)
        ofe.set_atr(5.0)
        return ofe, rb

    def test_cvd_positive(self):
        """Buy-heavy flow should produce positive CVD."""
        data = [(1_000_000_000_000 + i * 10_000_000, 5000.0, 10.0, 1) for i in range(100)]
        ofe, _ = self._make_engine(data)
        cvd = ofe.calculate_cvd(window_seconds=2)
        assert cvd > 0

    def test_cvd_negative(self):
        """Sell-heavy flow should produce negative CVD."""
        data = [(1_000_000_000_000 + i * 10_000_000, 5000.0, 10.0, -1) for i in range(100)]
        ofe, _ = self._make_engine(data)
        cvd = ofe.calculate_cvd(window_seconds=2)
        assert cvd < 0

    def test_cvd_empty(self):
        ofe, _ = self._make_engine()
        assert ofe.calculate_cvd() == 0.0

    def test_absorption_all_conditions(self):
        """Fix C: Absorption needs volume, duration, and low displacement."""
        base_ts = 1_000_000_000_000
        # High volume, stable price over 5 seconds
        data = []
        for i in range(500):
            data.append((base_ts + i * 10_000_000, 5000.0 + (i % 3) * 0.01, 50.0, 1))
        ofe, _ = self._make_engine(data)
        ofe.set_session_averages(avg_volume=10.0, avg_trade_size=10.0)
        result = ofe.detect_absorption(window_seconds=5)
        assert result is True

    def test_absorption_fails_low_volume(self):
        """Absorption fails if volume < 2x session average."""
        base_ts = 1_000_000_000_000
        data = [(base_ts + i * 10_000_000, 5000.0, 1.0, 1) for i in range(500)]
        ofe, _ = self._make_engine(data)
        ofe.set_session_averages(avg_volume=1000.0, avg_trade_size=10.0)
        assert ofe.detect_absorption(window_seconds=5) is False

    def test_absorption_fails_high_displacement(self):
        """Absorption fails if price moves too much."""
        base_ts = 1_000_000_000_000
        data = [(base_ts + i * 10_000_000, 5000.0 + i * 0.1, 50.0, 1) for i in range(500)]
        ofe, _ = self._make_engine(data)
        ofe.set_session_averages(avg_volume=1.0, avg_trade_size=10.0)
        ofe.set_atr(1.0)  # Small ATR makes displacement large relative
        assert ofe.detect_absorption(window_seconds=5) is False

    def test_whale_detection(self):
        """T09: Detect cluster of 3+ large trades."""
        base_ts = 1_000_000_000_000
        data = []
        # Normal trades
        for i in range(50):
            data.append((base_ts + i * 100_000_000, 5000.0, 10.0, 1))
        # Whale cluster: 3 large trades close together
        for i in range(3):
            data.append((base_ts + 60 * 100_000_000 + i * 1_000_000_000, 5005.0, 100.0, 1))
        ofe, _ = self._make_engine(data)
        ofe.set_session_averages(avg_volume=100.0, avg_trade_size=10.0)
        whales = ofe.filter_whale_blocks(window_seconds=30)
        assert len(whales) > 0

    def test_no_whale_without_cluster(self):
        """Single large trade is not a whale block."""
        base_ts = 1_000_000_000_000
        data = [(base_ts + i * 10_000_000, 5000.0, 10.0, 1) for i in range(100)]
        data.append((base_ts + 101 * 10_000_000, 5000.0, 100.0, 1))
        ofe, _ = self._make_engine(data)
        ofe.set_session_averages(avg_volume=100.0, avg_trade_size=10.0)
        whales = ofe.filter_whale_blocks(window_seconds=30)
        assert len(whales) == 0

    def test_evaluate_order_flow(self):
        """evaluate_order_flow returns 0-2 score."""
        ofe, _ = self._make_engine()
        score, details = ofe.evaluate_order_flow()
        assert 0 <= score <= 2
        assert "cvd" in details
        assert "has_divergence" in details
