"""Tests for VolumeProfileEngine stop placement and stop floor."""

from __future__ import annotations

import numpy as np
import pytest

from flof_matrix.core.ring_buffer import RingBuffer
from flof_matrix.order_flow.volume_profile_engine import VolumeProfileEngine


class TestStopFloor:
    """Stop floor prevents stops tighter than min_stop_atr_mult × ATR."""

    def make_vpe(self) -> VolumeProfileEngine:
        rb = RingBuffer(capacity=1000)
        return VolumeProfileEngine(rb, bucket_count=50)

    def test_atr_fallback_respects_floor(self):
        """ATR fallback of 2x ATR already exceeds 1.5x floor — no change."""
        vpe = self.make_vpe()
        # Long: entry 5000, ATR 2.0, fallback 2x ATR = stop at 4996
        stop = vpe.calculate_stop_price(5000.0, 1, atr=2.0, use_vp=False)
        assert stop == pytest.approx(4996.0)  # 2 * 2.0 = 4.0 below entry

    def test_stop_floor_enforced_long(self):
        """When calculated stop is too tight, floor widens it for longs."""
        vpe = self.make_vpe()
        # Long: entry 5000, ATR 3.0, but force a tight fallback of 0.3x ATR
        stop = vpe.calculate_stop_price(
            5000.0, 1, atr=3.0, use_vp=False,
            atr_fallback_mult=0.3,  # Would give 0.9 pts — too tight
            min_stop_atr_mult=1.5,  # Floor: 4.5 pts minimum
        )
        assert stop == pytest.approx(4995.5)  # 5000 - 1.5*3.0

    def test_stop_floor_enforced_short(self):
        """When calculated stop is too tight, floor widens it for shorts."""
        vpe = self.make_vpe()
        # Short: entry 5000, ATR 3.0, tight fallback
        stop = vpe.calculate_stop_price(
            5000.0, -1, atr=3.0, use_vp=False,
            atr_fallback_mult=0.3,  # Would give 0.9 pts — too tight
            min_stop_atr_mult=1.5,  # Floor: 4.5 pts minimum
        )
        assert stop == pytest.approx(5004.5)  # 5000 + 1.5*3.0

    def test_wide_stop_not_affected_by_floor(self):
        """A stop already wider than the floor is left unchanged."""
        vpe = self.make_vpe()
        stop = vpe.calculate_stop_price(
            5000.0, 1, atr=2.0, use_vp=False,
            atr_fallback_mult=2.0,  # 4.0 pts
            min_stop_atr_mult=1.5,  # Floor: 3.0 pts — already exceeded
        )
        assert stop == pytest.approx(4996.0)  # Unchanged: 2x2.0 = 4.0 > 3.0
