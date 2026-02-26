"""Integration test: Fix A — Schema shifting and ring buffer filling.

Verifies: Killzone opens → buffer fills → Halo → buffer ready.
"""

import pytest

from flof_matrix.core.ring_buffer import RingBuffer
from flof_matrix.data.sentinel_feed import SentinelFeed, SchemaLevel


class TestFixASchemaShifting:
    @pytest.mark.integration
    def test_killzone_fills_buffer_before_stalking(self):
        """Fix A: Ring buffer starts filling at Killzone entry, not Halo breach."""
        rb = RingBuffer(capacity=10_000)
        feed = SentinelFeed(ring_buffer=rb, backtest_mode=True)
        feed.on_start()

        # 1. Outside Killzone — ticks ignored
        assert feed.schema_level == SchemaLevel.BASE
        feed.on_trade_tick(1_000_000_000, 5000.0, 10.0, 1)
        assert rb.count == 0

        # 2. Killzone opens — Fix A activates
        feed.activate_killzone_schema()
        assert feed.schema_level == SchemaLevel.KILLZONE
        assert feed.is_filling_buffer

        # 3. Simulate 60+ seconds of ticks
        base_ts = 1_000_000_000_000
        for i in range(6000):  # 6000 ticks at 10ms = 60s
            feed.on_trade_tick(
                base_ts + i * 10_000_000,
                5000.0 + (i % 20) * 0.25,
                10.0,
                1 if i % 3 else -1,
            )

        # 4. Buffer should have 60+ seconds of data
        assert rb.count == 6000
        assert rb.is_ready(30.0)  # At least 30s required for Kill
        assert rb.is_ready(59.0)  # Should have ~60s

        # 5. Halo breach → already have data (no waiting!)
        # This is the key Fix A assertion

        # 6. Kill mode adds depth
        feed.activate_kill_schema()
        assert feed.schema_level == SchemaLevel.KILL
        assert rb.count == 6000  # Buffer preserved

        # 7. Killzone close flushes
        feed.deactivate_killzone_schema()
        assert feed.schema_level == SchemaLevel.BASE
        assert rb.count == 0
