"""Tests for HTF Structure Mapper."""

import numpy as np
import pytest

from flof_matrix.structure.htf_structure_mapper import (
    evaluate_macro_bias,
    evaluate_premium_discount,
    calculate_regime,
    generate_synthetic_poi,
    compute_sma,
)
from flof_matrix.core.types import POIType, TradeDirection


BAR_DTYPE = np.dtype([("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8")])


class TestHTFStructure:
    def test_premium_above_midpoint(self):
        assert evaluate_premium_discount(5150, 5200, 5000) == "premium"

    def test_discount_below_midpoint(self):
        assert evaluate_premium_discount(5050, 5200, 5000) == "discount"

    def test_neutral_equal_range(self):
        assert evaluate_premium_discount(5000, 5000, 5000) == "neutral"

    def test_regime_aligned(self):
        # Price well above both SMAs
        weekly = np.full(250, 4800.0)
        monthly = np.full(250, 4700.0)
        assert calculate_regime(weekly, monthly, 5000.0) == "aligned"

    def test_regime_conflicted(self):
        # Price above weekly SMA but below monthly SMA
        weekly = np.full(250, 4900.0)
        monthly = np.full(250, 5100.0)
        assert calculate_regime(weekly, monthly, 5000.0) == "conflicted"

    def test_regime_insufficient_data(self):
        weekly = np.array([5000.0])
        monthly = np.array([5000.0])
        assert calculate_regime(weekly, monthly, 5000.0) == "neutral"

    def test_synthetic_poi(self):
        poi = generate_synthetic_poi(5000.0, 20.0, TradeDirection.LONG, zone_width_mult=1.5)
        assert poi.type == POIType.SYNTHETIC_MA
        assert poi.zone_high == 5030.0
        assert poi.zone_low == 4970.0
        assert poi.direction == TradeDirection.LONG

    def test_compute_sma_sufficient_data(self):
        data = np.arange(200, dtype=float) + 5000
        sma = compute_sma(data, 200)
        assert sma is not None
        assert abs(sma - 5099.5) < 0.01

    def test_compute_sma_insufficient_data(self):
        data = np.array([1.0, 2.0, 3.0])
        assert compute_sma(data, 200) is None

    def test_macro_bias_bullish(self):
        # Higher highs and higher lows
        bars = np.zeros(10, dtype=BAR_DTYPE)
        for i in range(10):
            bars[i] = (5000 + i * 10, 5010 + i * 10, 4990 + i * 10, 5005 + i * 10)
        bias = evaluate_macro_bias(bars, bars)
        assert bias == TradeDirection.LONG

    def test_macro_bias_bearish(self):
        # Lower lows and lower highs
        bars = np.zeros(10, dtype=BAR_DTYPE)
        for i in range(10):
            bars[i] = (5100 - i * 10, 5110 - i * 10, 5090 - i * 10, 5095 - i * 10)
        bias = evaluate_macro_bias(bars, bars)
        assert bias == TradeDirection.SHORT

    def test_macro_bias_insufficient(self):
        bars = np.zeros(2, dtype=BAR_DTYPE)
        assert evaluate_macro_bias(bars, bars) is None
