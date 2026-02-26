"""Tests for Session Profiler — VA, VWAP, chop detection."""

import numpy as np
import pytest

from flof_matrix.structure.session_profiler import SessionProfiler


BAR_DTYPE = np.dtype([
    ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"), ("volume", "f8"),
])


class TestSessionProfiler:
    def test_vwap_update(self):
        sp = SessionProfiler()
        sp.update_vwap(5000.0, 100.0)
        assert sp.vwap == 5000.0

        sp.update_vwap(5010.0, 200.0)
        expected = (5000.0 * 100 + 5010.0 * 200) / 300
        assert abs(sp.vwap - expected) < 0.01

    def test_vwap_bands(self):
        sp = SessionProfiler()
        # Add multiple data points
        for price in [5000, 5005, 5010, 4995, 5002]:
            sp.update_vwap(price, 100.0)
        bands = sp.vwap_bands
        assert bands["upper_1sd"] > bands["vwap"]
        assert bands["lower_1sd"] < bands["vwap"]
        assert bands["upper_2sd"] > bands["upper_1sd"]

    def test_vwap_reset(self):
        sp = SessionProfiler()
        sp.update_vwap(5000.0, 100.0)
        sp.reset_vwap()
        assert sp.vwap == 0.0

    def test_detect_chop_true(self):
        sp = SessionProfiler()
        # VA width < 1.5 * ATR and slope < 0.01
        assert sp.detect_chop(va_width=5.0, atr=10.0, sma_slope=0.001)

    def test_detect_chop_false_wide_va(self):
        sp = SessionProfiler()
        assert not sp.detect_chop(va_width=20.0, atr=10.0, sma_slope=0.001)

    def test_detect_chop_false_strong_slope(self):
        sp = SessionProfiler()
        assert not sp.detect_chop(va_width=5.0, atr=10.0, sma_slope=0.05)

    def test_value_area(self):
        bars = np.zeros(50, dtype=BAR_DTYPE)
        for i in range(50):
            bars[i] = (5000 + i, 5005 + i, 4995 + i, 5002 + i, 100 + i * 10)
        sp = SessionProfiler()
        poc, va_high, va_low = sp.calculate_value_area(bars)
        assert va_low < poc < va_high
        assert va_high > 5000

    def test_value_area_empty(self):
        sp = SessionProfiler()
        poc, va_high, va_low = sp.calculate_value_area(np.zeros(0, dtype=BAR_DTYPE))
        assert poc == 0.0

    def test_vwap_confluence(self):
        sp = SessionProfiler()
        for price in [5000, 5005, 5010, 4995, 5002, 5008, 5003, 5007]:
            sp.update_vwap(price, 100.0)
        # Check a price near VWAP bands
        bands = sp.vwap_bands
        # POI at upper 1SD should have confluence
        assert sp.check_vwap_confluence(bands["upper_1sd"])
