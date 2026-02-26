"""Velez MA Module — Tier 2 scoring: 20/200 SMA on 2m bars.

Provides: 20 SMA Halt, Flat 200 SMA, Elephant Bar, Micro-Trend alignment.
Also provides RBI/GBI hold filter and 20 SMA health check for trade management.
"""

from __future__ import annotations

import numpy as np


class VelezMAModule:
    """Velez momentum layer calculations on 2-minute bars."""

    def __init__(
        self,
        sma_20_period: int = 20,
        sma_200_period: int = 200,
        flat_200_slope_threshold: float = 0.001,
        micro_trend_slope_threshold: float = 0.0005,
        elephant_bar_body_pct: float = 0.70,
        elephant_bar_range_mult: float = 1.3,
        elephant_bar_lookback: int = 10,
    ) -> None:
        self._sma_20_period = sma_20_period
        self._sma_200_period = sma_200_period
        self._flat_slope = flat_200_slope_threshold
        self._micro_slope = micro_trend_slope_threshold
        self._eb_body_pct = elephant_bar_body_pct
        self._eb_range_mult = elephant_bar_range_mult
        self._eb_lookback = elephant_bar_lookback

    def compute_20sma(self, closes: np.ndarray) -> float | None:
        """Compute 20 SMA on 2m closes."""
        if len(closes) < self._sma_20_period:
            return None
        return float(np.mean(closes[-self._sma_20_period:]))

    def compute_200sma(self, closes: np.ndarray) -> float | None:
        """Compute 200 SMA on 2m closes."""
        if len(closes) < self._sma_200_period:
            return None
        return float(np.mean(closes[-self._sma_200_period:]))

    def check_20sma_halt(
        self,
        sma_20: float,
        poi_zone_high: float,
        poi_zone_low: float,
        direction: int = 0,
        current_price: float = 0.0,
    ) -> bool:
        """T12: 2m 20 SMA is within POI zone, direction-aware.

        direction: 1 = long (require price > SMA = support below),
                  -1 = short (require price < SMA = resistance above),
                   0 = legacy/no direction check.
        """
        if not (poi_zone_low <= sma_20 <= poi_zone_high):
            return False
        if direction > 0:
            return current_price > sma_20
        elif direction < 0:
            return current_price < sma_20
        return True

    def check_flat_200sma(
        self,
        closes: np.ndarray,
        poi_zone_high: float,
        poi_zone_low: float,
        direction: int = 0,
        current_price: float = 0.0,
    ) -> bool:
        """T13: Flat 2m 200 SMA within POI zone, direction-aware.

        direction: 1 = long (require price > SMA), -1 = short (require price < SMA),
                   0 = legacy/no direction check.
        """
        sma = self.compute_200sma(closes)
        if sma is None:
            return False

        # Check flatness: slope over last 10 periods
        if len(closes) < self._sma_200_period + 10:
            return False

        sma_recent = float(np.mean(closes[-self._sma_200_period:]))
        sma_prior = float(np.mean(closes[-(self._sma_200_period + 10):-10]))

        if sma_prior == 0:
            return False
        slope = abs(sma_recent - sma_prior) / sma_prior

        is_flat = slope < self._flat_slope
        is_in_zone = poi_zone_low <= sma <= poi_zone_high

        if not (is_flat and is_in_zone):
            return False

        if direction > 0:
            return current_price > sma
        elif direction < 0:
            return current_price < sma
        return True

    def check_elephant_bar(self, bars: np.ndarray) -> bool:
        """T14: Body >= 70% of range AND range >= 1.3x average of prior N."""
        if len(bars) < self._eb_lookback + 1:
            return False

        current = bars[-1]
        body = abs(current["close"] - current["open"])
        rng = current["high"] - current["low"]

        if rng == 0:
            return False

        body_pct = body / rng
        if body_pct < self._eb_body_pct:
            return False

        prior = bars[-(self._eb_lookback + 1):-1]
        avg_range = float(np.mean(prior["high"] - prior["low"]))

        if avg_range == 0:
            return False

        return rng >= self._eb_range_mult * avg_range

    def check_micro_trend(
        self,
        closes: np.ndarray,
        direction: int,
    ) -> bool:
        """T15: 20 SMA slope + price position alignment.

        direction: 1 = long, -1 = short
        """
        if len(closes) < self._sma_20_period + 5:
            return False

        sma_now = float(np.mean(closes[-self._sma_20_period:]))
        sma_5_ago = float(np.mean(closes[-(self._sma_20_period + 5):-5]))

        if sma_5_ago == 0:
            return False

        slope = (sma_now - sma_5_ago) / sma_5_ago
        price = float(closes[-1])

        if direction > 0:
            return slope > self._micro_slope and price > sma_now
        else:
            return slope < -self._micro_slope and price < sma_now

    def check_rbi_gbi_hold(
        self,
        bar_open: float,
        bar_close: float,
        bar_high: float,
        bar_low: float,
        direction: int,
    ) -> bool:
        """T20: RBI/GBI hold filter for runner management.

        RBI (Red Bar Ignored): In a long, ignore a red candle if wick > 50% of range.
        GBI (Green Bar Ignored): In a short, ignore a green candle if wick > 50% of range.
        """
        rng = bar_high - bar_low
        if rng == 0:
            return True  # No range = hold

        if direction > 0 and bar_close < bar_open:
            # Red candle in long position
            lower_wick = min(bar_open, bar_close) - bar_low
            return lower_wick > 0.5 * rng  # Strong rejection = hold
        elif direction < 0 and bar_close > bar_open:
            # Green candle in short position
            upper_wick = bar_high - max(bar_open, bar_close)
            return upper_wick > 0.5 * rng  # Strong rejection = hold

        return True  # Same-direction candle = always hold

    def check_20sma_health(
        self,
        closes: np.ndarray,
        breach_count_threshold: int = 3,
    ) -> bool:
        """T21: 20 SMA health check. Returns True if healthy (no tightening needed).

        Unhealthy = 3+ consecutive closes below 20 SMA (for longs) or above (shorts).
        """
        sma = self.compute_20sma(closes)
        if sma is None:
            return True

        # Check last few candles for breaches
        breaches = 0
        for i in range(-1, -min(breach_count_threshold + 1, len(closes)) - 1, -1):
            if closes[i] < sma:
                breaches += 1
            else:
                break

        return breaches < breach_count_threshold
