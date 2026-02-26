"""Session Profiler (M13, Actor) — Value Area, VWAP, and Chop Detection.

G3 gate: blocks directional entries when market is choppy.
"""

from __future__ import annotations

import numpy as np


class SessionProfiler:
    """Calculates session-level metrics: Value Area, VWAP, chop detection."""

    def __init__(self) -> None:
        self._vwap_cum_vol: float = 0.0
        self._vwap_cum_pv: float = 0.0
        self._vwap_cum_pv2: float = 0.0
        self._vwap: float = 0.0
        self._vwap_upper_1sd: float = 0.0
        self._vwap_lower_1sd: float = 0.0
        self._vwap_upper_2sd: float = 0.0
        self._vwap_lower_2sd: float = 0.0

    @property
    def vwap(self) -> float:
        return self._vwap

    @property
    def vwap_bands(self) -> dict[str, float]:
        return {
            "vwap": self._vwap,
            "upper_1sd": self._vwap_upper_1sd,
            "lower_1sd": self._vwap_lower_1sd,
            "upper_2sd": self._vwap_upper_2sd,
            "lower_2sd": self._vwap_lower_2sd,
        }

    def calculate_value_area(
        self,
        bars: np.ndarray,
        va_pct: float = 0.70,
    ) -> tuple[float, float, float]:
        """Calculate POC, VA High, VA Low from volume profile.

        Returns: (poc, va_high, va_low)
        """
        if len(bars) == 0:
            return 0.0, 0.0, 0.0

        prices = (bars["high"] + bars["low"] + bars["close"]) / 3.0  # Typical price
        volumes = bars["volume"] if "volume" in bars.dtype.names else np.ones(len(bars))

        price_min = float(np.min(bars["low"]))
        price_max = float(np.max(bars["high"]))

        if price_max == price_min:
            return price_min, price_min, price_min

        # Build volume profile with 50 buckets
        n_buckets = 50
        bucket_size = (price_max - price_min) / n_buckets
        profile = np.zeros(n_buckets)

        for j in range(len(bars)):
            bucket = int((prices[j] - price_min) / bucket_size)
            bucket = min(bucket, n_buckets - 1)
            profile[bucket] += volumes[j]

        # POC: highest volume bucket
        poc_bucket = int(np.argmax(profile))
        poc = price_min + (poc_bucket + 0.5) * bucket_size

        # Value Area: expand from POC until va_pct of volume is captured
        total_vol = float(np.sum(profile))
        if total_vol == 0:
            return poc, price_max, price_min

        target_vol = total_vol * va_pct
        va_vol = profile[poc_bucket]
        lo_idx = poc_bucket
        hi_idx = poc_bucket

        while va_vol < target_vol and (lo_idx > 0 or hi_idx < n_buckets - 1):
            expand_up = profile[hi_idx + 1] if hi_idx < n_buckets - 1 else 0.0
            expand_down = profile[lo_idx - 1] if lo_idx > 0 else 0.0

            if expand_up >= expand_down and hi_idx < n_buckets - 1:
                hi_idx += 1
                va_vol += profile[hi_idx]
            elif lo_idx > 0:
                lo_idx -= 1
                va_vol += profile[lo_idx]
            else:
                hi_idx += 1
                va_vol += profile[hi_idx]

        va_high = price_min + (hi_idx + 1) * bucket_size
        va_low = price_min + lo_idx * bucket_size

        return poc, va_high, va_low

    def detect_chop(
        self,
        va_width: float,
        atr: float,
        sma_slope: float,
        chop_va_atr_ratio: float = 1.5,
        slope_threshold: float = 0.01,
    ) -> bool:
        """G3 gate (T42): Chop if VA_width < ratio × ATR AND slope < threshold."""
        if atr <= 0:
            return False
        return (va_width / atr) < chop_va_atr_ratio and abs(sma_slope) < slope_threshold

    def update_vwap(self, typical_price: float, volume: float) -> None:
        """Update session VWAP with ±1/±2 SD bands. Call per bar."""
        self._vwap_cum_vol += volume
        self._vwap_cum_pv += typical_price * volume
        self._vwap_cum_pv2 += typical_price * typical_price * volume

        if self._vwap_cum_vol > 0:
            self._vwap = self._vwap_cum_pv / self._vwap_cum_vol
            variance = (self._vwap_cum_pv2 / self._vwap_cum_vol) - self._vwap ** 2
            sd = variance ** 0.5 if variance > 0 else 0.0
            self._vwap_upper_1sd = self._vwap + sd
            self._vwap_lower_1sd = self._vwap - sd
            self._vwap_upper_2sd = self._vwap + 2 * sd
            self._vwap_lower_2sd = self._vwap - 2 * sd

    def reset_vwap(self) -> None:
        """Reset VWAP at session open."""
        self._vwap_cum_vol = 0.0
        self._vwap_cum_pv = 0.0
        self._vwap_cum_pv2 = 0.0
        self._vwap = 0.0
        self._vwap_upper_1sd = 0.0
        self._vwap_lower_1sd = 0.0
        self._vwap_upper_2sd = 0.0
        self._vwap_lower_2sd = 0.0

    def check_vwap_confluence(
        self,
        poi_price: float,
        vwap: float | None = None,
        sd_band: float | None = None,
    ) -> bool:
        """Tier 3 scoring (T36): POI near VWAP SD band."""
        if vwap is None:
            vwap = self._vwap
        if sd_band is None:
            sd_band = self._vwap_upper_1sd - self._vwap if self._vwap > 0 else 0.0

        if sd_band <= 0:
            return False

        # POI within 0.5 SD of any VWAP band
        for band in [self._vwap_upper_1sd, self._vwap_lower_1sd,
                      self._vwap_upper_2sd, self._vwap_lower_2sd]:
            if abs(poi_price - band) <= 0.5 * sd_band:
                return True
        return False
