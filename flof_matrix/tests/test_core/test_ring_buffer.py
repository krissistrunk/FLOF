"""Tests for RingBuffer — push/overwrite, window, is_ready, latency benchmark."""

import time

import numpy as np
import pytest

from flof_matrix.core.ring_buffer import RingBuffer, TICK_DTYPE


class TestRingBuffer:
    def test_push_and_count(self):
        rb = RingBuffer(capacity=100)
        rb.push(1000, 5000.0, 10.0, 1)
        assert rb.count == 1

    def test_push_multiple(self):
        rb = RingBuffer(capacity=100)
        for i in range(50):
            rb.push(i * 10, 5000.0, 1.0, 1)
        assert rb.count == 50

    def test_overwrite_on_wrap(self):
        rb = RingBuffer(capacity=10)
        for i in range(15):
            rb.push(i * 1_000_000_000, 5000.0, 1.0, 1)
        assert rb.count == 10  # Capped at capacity

    def test_chronological_order_after_wrap(self):
        rb = RingBuffer(capacity=10)
        base_ts = 1_000_000_000_000
        for i in range(15):
            rb.push(base_ts + i * 10_000_000, 5000.0, 1.0, 1)
        data = rb.window(10.0)
        for i in range(len(data) - 1):
            assert data[i]["timestamp_ns"] <= data[i + 1]["timestamp_ns"]
        # Should have records 5-14 (last 10)
        assert data[0]["timestamp_ns"] == base_ts + 5 * 10_000_000

    def test_window_returns_correct_subset(self):
        rb = RingBuffer(capacity=1000)
        base_ts = 1_000_000_000_000
        for i in range(100):
            rb.push(base_ts + i * 100_000_000, 5000.0, 1.0, 1)  # 100ms apart
        # 10 second span total. Window of 5s should get ~50 records
        window = rb.window(5.0)
        assert len(window) >= 49  # Allow for boundary

    def test_is_ready_true(self):
        rb = RingBuffer(capacity=1000)
        base_ts = 1_000_000_000_000
        for i in range(100):
            rb.push(base_ts + i * 100_000_000, 5000.0, 1.0, 1)  # 10s total
        assert rb.is_ready(5.0)
        assert rb.is_ready(9.0)

    def test_is_ready_false(self):
        rb = RingBuffer(capacity=1000)
        base_ts = 1_000_000_000_000
        for i in range(10):
            rb.push(base_ts + i * 100_000_000, 5000.0, 1.0, 1)  # 1s total
        assert not rb.is_ready(5.0)

    def test_is_ready_empty(self):
        rb = RingBuffer(capacity=100)
        assert not rb.is_ready(1.0)

    def test_clear(self):
        rb = RingBuffer(capacity=100)
        for i in range(50):
            rb.push(i, 5000.0, 1.0, 1)
        rb.clear()
        assert rb.count == 0
        assert len(rb.window(100.0)) == 0

    def test_empty_window(self):
        rb = RingBuffer(capacity=100)
        assert len(rb.window(1.0)) == 0

    def test_latest(self):
        rb = RingBuffer(capacity=100)
        rb.push(1000, 5123.5, 42.0, -1, 3)
        latest = rb.latest()
        assert latest is not None
        assert latest["price"] == 5123.5
        assert latest["side"] == -1

    def test_latest_empty(self):
        rb = RingBuffer(capacity=100)
        assert rb.latest() is None

    def test_push_array(self):
        rb = RingBuffer(capacity=100)
        records = np.zeros(20, dtype=TICK_DTYPE)
        for i in range(20):
            records[i] = (i * 1_000_000, 5000.0 + i, 1.0, 1, 0)
        rb.push_array(records)
        assert rb.count == 20

    def test_push_array_overflow(self):
        rb = RingBuffer(capacity=10)
        records = np.zeros(15, dtype=TICK_DTYPE)
        for i in range(15):
            records[i] = (i * 1_000_000, 5000.0, 1.0, 1, 0)
        rb.push_array(records)
        assert rb.count == 10

    @pytest.mark.benchmark
    def test_push_latency(self):
        """Push must be < 5 microseconds on average."""
        rb = RingBuffer(capacity=500_000)
        base_ts = 1_000_000_000_000
        iterations = 50_000
        start = time.perf_counter_ns()
        for i in range(iterations):
            rb.push(base_ts + i, 5000.0, 1.0, 1)
        elapsed_ns = time.perf_counter_ns() - start
        avg_us = elapsed_ns / iterations / 1000
        # Allow 20us for CI environments (target <5us on dedicated hardware)
        assert avg_us < 20, f"Push too slow: {avg_us:.2f} us (budget: <5 us)"
