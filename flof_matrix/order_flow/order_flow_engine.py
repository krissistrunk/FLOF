"""Order Flow Engine (M04, Actor) — CVD, absorption, whale detection.

Most performance-sensitive module. All operations on NumPy Ring Buffer arrays.
Vectorized operations — no Python loops in hot path.

Fix C incorporated: Absorption requires three simultaneous conditions.
"""

from __future__ import annotations

import numpy as np

from flof_matrix.core.ring_buffer import RingBuffer


class OrderFlowEngine:
    """Processes order flow data from Ring Buffer using vectorized NumPy operations."""

    def __init__(
        self,
        ring_buffer: RingBuffer,
        cvd_lookback_seconds: float = 30,
        absorption_volume_threshold: float = 2.0,
        absorption_displacement_max: float = 0.3,
        whale_print_multiplier: float = 5.0,
        whale_block_min_prints: int = 3,
        stacked_imbalance_min_levels: int = 3,
        stacked_imbalance_ratio: float = 3.0,
    ) -> None:
        self._ring_buffer = ring_buffer
        self._cvd_lookback = cvd_lookback_seconds
        self._absorption_vol_threshold = absorption_volume_threshold
        self._absorption_disp_max = absorption_displacement_max
        self._whale_mult = whale_print_multiplier
        self._whale_min_prints = whale_block_min_prints
        self._imbalance_min_levels = stacked_imbalance_min_levels
        self._imbalance_ratio = stacked_imbalance_ratio
        self._session_avg_volume: float = 0.0
        self._session_avg_trade_size: float = 0.0
        self._atr: float = 1.0

    def set_session_averages(self, avg_volume: float, avg_trade_size: float) -> None:
        """Update session average volume and trade size for threshold calculations."""
        self._session_avg_volume = avg_volume
        self._session_avg_trade_size = avg_trade_size

    def set_atr(self, atr: float) -> None:
        """Update ATR for displacement calculations."""
        self._atr = max(atr, 0.01)

    def calculate_cvd(self, window_seconds: float | None = None) -> float:
        """Cumulative Volume Delta: sum(size * side) over window.

        Positive CVD = buying pressure, Negative = selling pressure.
        """
        seconds = window_seconds or self._cvd_lookback
        data = self._ring_buffer.window(seconds)
        if len(data) == 0:
            return 0.0
        return float(np.sum(data["size"] * data["side"]))

    def detect_cvd_divergence(
        self,
        price_direction: int,
        window_seconds: float | None = None,
    ) -> bool:
        """T07: Price making new extreme but CVD declining.

        Args:
            price_direction: 1 = price making new high, -1 = new low
        """
        seconds = window_seconds or self._cvd_lookback
        data = self._ring_buffer.window(seconds)
        if len(data) < 10:
            return False

        # Split window into halves
        mid = len(data) // 2
        first_half = data[:mid]
        second_half = data[mid:]

        cvd_first = float(np.sum(first_half["size"] * first_half["side"]))
        cvd_second = float(np.sum(second_half["size"] * second_half["side"]))

        price_first = float(np.mean(first_half["price"]))
        price_second = float(np.mean(second_half["price"]))

        if price_direction > 0:
            # Price up but CVD declining = bearish divergence
            return price_second > price_first and cvd_second < cvd_first
        else:
            # Price down but CVD increasing = bullish divergence
            return price_second < price_first and cvd_second > cvd_first

    def detect_stacked_imbalance(
        self,
        window_seconds: float = 30,
        min_levels: int | None = None,
    ) -> bool:
        """T07: 3+ consecutive price levels with >300% buy/sell imbalance."""
        levels = min_levels or self._imbalance_min_levels
        data = self._ring_buffer.window(window_seconds)
        if len(data) < 10:
            return False

        # Bucket by price into tick levels
        prices = data["price"]
        sizes = data["size"]
        sides = data["side"]

        price_min = float(np.min(prices))
        price_max = float(np.max(prices))
        if price_max == price_min:
            return False

        tick = 0.25  # ES tick size
        n_buckets = max(1, int((price_max - price_min) / tick) + 1)
        n_buckets = min(n_buckets, 200)  # Cap bucket count

        bucket_size = (price_max - price_min) / n_buckets
        buy_vol = np.zeros(n_buckets)
        sell_vol = np.zeros(n_buckets)

        for j in range(len(data)):
            bucket = min(int((prices[j] - price_min) / bucket_size), n_buckets - 1)
            if sides[j] > 0:
                buy_vol[bucket] += sizes[j]
            else:
                sell_vol[bucket] += sizes[j]

        # Check for consecutive imbalanced levels
        consecutive = 0
        for i in range(n_buckets):
            if sell_vol[i] > 0 and buy_vol[i] / sell_vol[i] > self._imbalance_ratio:
                consecutive += 1
            elif buy_vol[i] > 0 and sell_vol[i] / buy_vol[i] > self._imbalance_ratio:
                consecutive += 1
            else:
                consecutive = 0

            if consecutive >= levels:
                return True

        return False

    def detect_absorption(self, window_seconds: float = 5) -> bool:
        """T08 (Fix C): Absorption requires three simultaneous conditions:
        1. Volume > 2x session average
        2. Sustained >= 3 seconds
        3. Price displacement < 0.3 × ATR
        """
        data = self._ring_buffer.window(window_seconds)
        if len(data) < 2:
            return False

        total_volume = float(np.sum(data["size"]))
        time_span_s = (int(data[-1]["timestamp_ns"]) - int(data[0]["timestamp_ns"])) / 1_000_000_000

        # Condition 1: Volume threshold
        if self._session_avg_volume <= 0:
            return False
        expected_volume = self._session_avg_volume * window_seconds
        if total_volume < self._absorption_vol_threshold * expected_volume:
            return False

        # Condition 2: Sustained duration (>= 3 seconds)
        if time_span_s < 3.0:
            return False

        # Condition 3: Price displacement < 0.3 × ATR
        price_range = float(np.max(data["price"]) - np.min(data["price"]))
        if price_range >= self._absorption_disp_max * self._atr:
            return False

        return True

    def filter_whale_blocks(self, window_seconds: float = 30) -> list[dict]:
        """T09: Detect trades > 5x average, cluster of 3+."""
        data = self._ring_buffer.window(window_seconds)
        if len(data) == 0:
            return []

        avg_size = self._session_avg_trade_size
        if avg_size <= 0:
            avg_size = float(np.mean(data["size"])) if len(data) > 0 else 1.0

        threshold = avg_size * self._whale_mult

        # Find whale prints
        whale_mask = data["size"] >= threshold
        whale_prints = data[whale_mask]

        if len(whale_prints) < self._whale_min_prints:
            return []

        # Check for clustering (within 5 seconds)
        clusters = []
        current_cluster = [whale_prints[0]]

        for i in range(1, len(whale_prints)):
            time_gap = (int(whale_prints[i]["timestamp_ns"]) - int(current_cluster[-1]["timestamp_ns"])) / 1_000_000_000
            if time_gap <= 5.0:
                current_cluster.append(whale_prints[i])
            else:
                if len(current_cluster) >= self._whale_min_prints:
                    clusters.append({
                        "count": len(current_cluster),
                        "total_volume": float(sum(r["size"] for r in current_cluster)),
                        "avg_price": float(np.mean([r["price"] for r in current_cluster])),
                        "direction": int(np.sign(sum(r["side"] for r in current_cluster))),
                    })
                current_cluster = [whale_prints[i]]

        # Check final cluster
        if len(current_cluster) >= self._whale_min_prints:
            clusters.append({
                "count": len(current_cluster),
                "total_volume": float(sum(r["size"] for r in current_cluster)),
                "avg_price": float(np.mean([r["price"] for r in current_cluster])),
                "direction": int(np.sign(sum(r["side"] for r in current_cluster))),
            })

        return clusters

    def calculate_sell_delta_pct(
        self, window_seconds: float = 30, min_ticks: int = 20
    ) -> float:
        """Percentage of volume that is sell-side over window.

        Returns 0.0-1.0. Values > 0.80 indicate heavy sell pressure.
        Returns 0.5 (neutral) if fewer than min_ticks in window to avoid
        noisy signals from sparse synthetic data.
        """
        data = self._ring_buffer.window(window_seconds)
        if len(data) < min_ticks:
            return 0.5  # Not enough data for reliable signal
        sides = data["side"]
        sizes = data["size"]
        buy_vol = float(np.sum(sizes[sides > 0]))
        sell_vol = float(np.sum(sizes[sides < 0]))
        total = buy_vol + sell_vol
        if total == 0:
            return 0.5
        return sell_vol / total

    def calculate_adverse_delta_pct(
        self, direction: int, window_seconds: float = 30, min_ticks: int = 20
    ) -> float:
        """Percentage of volume adverse to the position direction.

        For LONG (direction=1): adverse = sell pressure = sell_delta_pct
        For SHORT (direction=-1): adverse = buy pressure = 1 - sell_delta_pct
        Returns 0.5 (neutral) if insufficient tick data.
        """
        sell_pct = self.calculate_sell_delta_pct(window_seconds, min_ticks)
        if direction > 0:
            return sell_pct  # Longs hurt by selling
        else:
            return 1.0 - sell_pct  # Shorts hurt by buying

    def evaluate_directional_order_flow(
        self, trade_direction: int
    ) -> tuple[int, dict]:
        """Evaluate order flow confirmation for a specific trade direction.

        Unlike evaluate_order_flow(), this checks whether CVD divergence
        is directionally appropriate for the intended trade:
        - SHORT entry needs bearish divergence (price up, CVD declining)
        - LONG entry needs bullish divergence (price down, CVD rising)

        Args:
            trade_direction: 1 = LONG, -1 = SHORT

        Returns: (score 0/1/2, details dict)
        """
        cvd = self.calculate_cvd()
        # For a SHORT: we want bearish divergence → price_direction=1 (price up, CVD weak)
        # For a LONG: we want bullish divergence → price_direction=-1 (price down, CVD rising)
        divergence_price_dir = -trade_direction
        has_divergence = self.detect_cvd_divergence(divergence_price_dir)
        has_imbalance = self.detect_stacked_imbalance()
        has_absorption = self.detect_absorption()
        whale_blocks = self.filter_whale_blocks()

        details = {
            "cvd": cvd,
            "has_divergence": has_divergence,
            "has_imbalance": has_imbalance,
            "has_absorption": has_absorption,
            "whale_blocks": len(whale_blocks),
            "directional": True,
        }

        if has_divergence and has_imbalance:
            return 2, details
        if has_divergence:
            return 1, details
        return 0, details

    def evaluate_order_flow(self) -> tuple[int, dict]:
        """Evaluate order flow confirmation for scoring.

        Returns: (score 0/1/2, details dict)
        """
        cvd = self.calculate_cvd()
        has_divergence = self.detect_cvd_divergence(1 if cvd > 0 else -1)
        has_imbalance = self.detect_stacked_imbalance()
        has_absorption = self.detect_absorption()
        whale_blocks = self.filter_whale_blocks()

        details = {
            "cvd": cvd,
            "has_divergence": has_divergence,
            "has_imbalance": has_imbalance,
            "has_absorption": has_absorption,
            "whale_blocks": len(whale_blocks),
        }

        # Full confirmation: CVD divergence + stacked imbalances = +2
        if has_divergence and has_imbalance:
            return 2, details

        # Partial: CVD divergence alone = +1
        if has_divergence:
            return 1, details

        return 0, details
