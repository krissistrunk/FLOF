"""Tests for Velez MA Module — direction-aware T12, T13, T14 signals."""

import numpy as np
import pytest

from flof_matrix.strategy.velez_ma_module import VelezMAModule


@pytest.fixture
def velez():
    return VelezMAModule()


# ── T12: check_20sma_halt direction-aware ────────────────────────────


class TestT12DirectionAware:
    """20 SMA halt must confirm direction: LONG needs price > SMA, SHORT needs price < SMA."""

    def test_long_price_above_sma(self, velez):
        """LONG with price above SMA (SMA is support below) → True."""
        assert velez.check_20sma_halt(
            sma_20=5000.0, poi_zone_high=5002.0, poi_zone_low=4998.0,
            direction=1, current_price=5001.0,
        ) is True

    def test_long_price_below_sma(self, velez):
        """LONG with price below SMA (SMA is overhead resistance) → False."""
        assert velez.check_20sma_halt(
            sma_20=5000.0, poi_zone_high=5002.0, poi_zone_low=4998.0,
            direction=1, current_price=4999.0,
        ) is False

    def test_short_price_below_sma(self, velez):
        """SHORT with price below SMA (SMA is resistance above) → True."""
        assert velez.check_20sma_halt(
            sma_20=5000.0, poi_zone_high=5002.0, poi_zone_low=4998.0,
            direction=-1, current_price=4999.0,
        ) is True

    def test_short_price_above_sma(self, velez):
        """SHORT with price above SMA (SMA is support below, bad for short) → False."""
        assert velez.check_20sma_halt(
            sma_20=5000.0, poi_zone_high=5002.0, poi_zone_low=4998.0,
            direction=-1, current_price=5001.0,
        ) is False

    def test_sma_outside_zone_still_false(self, velez):
        """SMA outside POI zone → False regardless of direction."""
        assert velez.check_20sma_halt(
            sma_20=5100.0, poi_zone_high=5002.0, poi_zone_low=4998.0,
            direction=1, current_price=5101.0,
        ) is False

    def test_no_direction_legacy(self, velez):
        """direction=0 (legacy) → only zone check, no price filter."""
        assert velez.check_20sma_halt(
            sma_20=5000.0, poi_zone_high=5002.0, poi_zone_low=4998.0,
            direction=0, current_price=4999.0,
        ) is True


# ── T13: check_flat_200sma direction-aware ───────────────────────────


def _flat_closes(center: float, n: int = 220) -> np.ndarray:
    """Generate flat closes centered around `center` with tiny noise."""
    rng = np.random.RandomState(42)
    return center + rng.uniform(-0.01, 0.01, size=n)


class TestT13DirectionAware:
    """Flat 200 SMA must confirm direction: LONG needs price > SMA, SHORT needs price < SMA."""

    def test_long_above_flat_200(self, velez):
        """LONG with price above flat 200 SMA → True."""
        closes = _flat_closes(5000.0)
        # Put the SMA (~5000) inside the zone
        result = velez.check_flat_200sma(
            closes, poi_zone_high=5002.0, poi_zone_low=4998.0,
            direction=1, current_price=5001.0,
        )
        assert result is True

    def test_long_below_flat_200(self, velez):
        """LONG with price below flat 200 SMA → False."""
        closes = _flat_closes(5000.0)
        result = velez.check_flat_200sma(
            closes, poi_zone_high=5002.0, poi_zone_low=4998.0,
            direction=1, current_price=4999.0,
        )
        assert result is False

    def test_short_below_flat_200(self, velez):
        """SHORT with price below flat 200 SMA → True."""
        closes = _flat_closes(5000.0)
        result = velez.check_flat_200sma(
            closes, poi_zone_high=5002.0, poi_zone_low=4998.0,
            direction=-1, current_price=4999.0,
        )
        assert result is True

    def test_short_above_flat_200(self, velez):
        """SHORT with price above flat 200 SMA → False."""
        closes = _flat_closes(5000.0)
        result = velez.check_flat_200sma(
            closes, poi_zone_high=5002.0, poi_zone_low=4998.0,
            direction=-1, current_price=5001.0,
        )
        assert result is False

    def test_no_direction_legacy(self, velez):
        """direction=0 (legacy) → only flat + zone check."""
        closes = _flat_closes(5000.0)
        result = velez.check_flat_200sma(
            closes, poi_zone_high=5002.0, poi_zone_low=4998.0,
            direction=0, current_price=4999.0,
        )
        assert result is True


# ── T14: elephant bar direction (inline logic) ──────────────────────


class TestT14ElephantDirection:
    """Elephant bar should only confirm when bar color matches trade direction."""

    @staticmethod
    def _elephant_check(direction_int: int, bar_open: float, bar_close: float) -> bool:
        """Reproduce the inline elephant bar logic from flof_strategy.py."""
        last = {"open": bar_open, "close": bar_close, "high": max(bar_open, bar_close) + 1, "low": min(bar_open, bar_close) - 1}
        body = abs(last["close"] - last["open"])
        bar_rng = last["high"] - last["low"]
        # Assume size_ok is True (we're testing color logic)
        size_ok = True
        if direction_int > 0:
            color_ok = last["close"] > last["open"]
        else:
            color_ok = last["close"] < last["open"]
        return size_ok and color_ok

    def test_long_bullish_bar(self):
        """LONG + bullish elephant bar → True."""
        assert self._elephant_check(1, bar_open=5000.0, bar_close=5010.0) is True

    def test_long_bearish_bar(self):
        """LONG + bearish elephant bar → False."""
        assert self._elephant_check(1, bar_open=5010.0, bar_close=5000.0) is False

    def test_short_bearish_bar(self):
        """SHORT + bearish elephant bar → True."""
        assert self._elephant_check(-1, bar_open=5010.0, bar_close=5000.0) is True

    def test_short_bullish_bar(self):
        """SHORT + bullish elephant bar → False."""
        assert self._elephant_check(-1, bar_open=5000.0, bar_close=5010.0) is False
