"""Volume Profile Engine (M07, Component) — Micro VP, HVN/LVN, stop placement.

Pre-bucketed for performance. No per-tick recalculation.
"""

from __future__ import annotations

import numpy as np

from flof_matrix.core.ring_buffer import RingBuffer
from flof_matrix.core.data_types import POI


class VolumeProfileEngine:
    """Builds micro volume profiles from Ring Buffer data for stop placement and entry refinement."""

    def __init__(
        self,
        ring_buffer: RingBuffer,
        bucket_count: int = 50,
    ) -> None:
        self._ring_buffer = ring_buffer
        self._bucket_count = bucket_count

    def build_micro_vp(
        self,
        window_seconds: float = 60,
    ) -> dict:
        """Build 50-bucket volume profile from Ring Buffer.

        Returns dict with: prices (bucket centers), volumes, price_min, price_max, bucket_size
        """
        data = self._ring_buffer.window(window_seconds)
        if len(data) == 0:
            return {"prices": np.array([]), "volumes": np.array([]), "price_min": 0.0, "price_max": 0.0, "bucket_size": 0.0}

        prices = data["price"]
        sizes = data["size"]

        price_min = float(np.min(prices))
        price_max = float(np.max(prices))

        if price_max == price_min:
            return {
                "prices": np.array([price_min]),
                "volumes": np.array([float(np.sum(sizes))]),
                "price_min": price_min,
                "price_max": price_max,
                "bucket_size": 0.0,
            }

        bucket_size = (price_max - price_min) / self._bucket_count
        volumes = np.zeros(self._bucket_count)

        bucket_indices = np.minimum(
            ((prices - price_min) / bucket_size).astype(int),
            self._bucket_count - 1,
        )
        np.add.at(volumes, bucket_indices, sizes)

        bucket_centers = np.array([
            price_min + (i + 0.5) * bucket_size
            for i in range(self._bucket_count)
        ])

        return {
            "prices": bucket_centers,
            "volumes": volumes,
            "price_min": price_min,
            "price_max": price_max,
            "bucket_size": bucket_size,
        }

    def identify_hvn_lvn(
        self,
        vp: dict,
    ) -> tuple[list[float], list[float]]:
        """Identify High Volume Nodes and Low Volume Nodes.

        HVN: volume > 1.5x average
        LVN: volume < 0.5x average

        Returns: (hvn_prices, lvn_prices)
        """
        volumes = vp.get("volumes", np.array([]))
        prices = vp.get("prices", np.array([]))

        if len(volumes) == 0:
            return [], []

        avg_vol = float(np.mean(volumes))
        if avg_vol == 0:
            return [], []

        hvn_mask = volumes > 1.5 * avg_vol
        lvn_mask = (volumes < 0.5 * avg_vol) & (volumes > 0)

        hvn_prices = prices[hvn_mask].tolist()
        lvn_prices = prices[lvn_mask].tolist()

        return hvn_prices, lvn_prices

    def calculate_stop_price(
        self,
        entry_price: float,
        direction: int,  # 1 = long, -1 = short
        atr: float,
        use_vp: bool = True,
        atr_fallback_mult: float = 2.0,
        lvn_atr_buffer: float = 0.5,
        min_stop_atr_mult: float = 1.5,
        min_stop_absolute_pts: float = 0.0,
    ) -> float:
        """T17: Stop behind nearest LVN - (0.5 × ATR); fallback: 2× ATR.

        Two stop floors are enforced (whichever is wider wins):
        1. min_stop_atr_mult × ATR — relative to current volatility
        2. min_stop_absolute_pts — absolute minimum (e.g. 1.5 pts for ES)
        """
        if not use_vp:
            # Fallback: 2x ATR
            stop = entry_price - direction * atr_fallback_mult * atr
        else:
            vp = self.build_micro_vp(window_seconds=60)
            _, lvn_prices = self.identify_hvn_lvn(vp)

            if not lvn_prices:
                # No LVNs found, use ATR fallback
                stop = entry_price - direction * atr_fallback_mult * atr
            elif direction > 0:  # Long: stop below entry
                below_entry = [p for p in lvn_prices if p < entry_price]
                if below_entry:
                    nearest_lvn = max(below_entry)
                    stop = nearest_lvn - lvn_atr_buffer * atr
                else:
                    stop = entry_price - atr_fallback_mult * atr
            else:  # Short: stop above entry
                above_entry = [p for p in lvn_prices if p > entry_price]
                if above_entry:
                    nearest_lvn = min(above_entry)
                    stop = nearest_lvn + lvn_atr_buffer * atr
                else:
                    stop = entry_price + atr_fallback_mult * atr

        # Enforce stop floor: whichever is wider wins
        # 1. ATR-relative floor
        # 2. Absolute floor (prevents stops inside bid/ask noise)
        min_distance = max(min_stop_atr_mult * atr, min_stop_absolute_pts)
        actual_distance = abs(stop - entry_price)
        if actual_distance < min_distance:
            stop = entry_price - direction * min_distance

        return stop

    def refine_entry_with_vp(
        self,
        poi: POI,
        window_seconds: float = 60,
    ) -> float:
        """T38: Narrow entry zone within POI using Volume Profile.

        Returns refined entry price within the POI zone.
        """
        vp = self.build_micro_vp(window_seconds)
        prices = vp.get("prices", np.array([]))
        volumes = vp.get("volumes", np.array([]))

        if len(prices) == 0:
            return poi.price

        # Find buckets within POI zone
        in_zone = (prices >= poi.zone_low) & (prices <= poi.zone_high)
        zone_prices = prices[in_zone]
        zone_volumes = volumes[in_zone]

        if len(zone_prices) == 0:
            return poi.price

        # Find HVN within zone (highest activity = best entry)
        hvn_idx = int(np.argmax(zone_volumes))
        return float(zone_prices[hvn_idx])
