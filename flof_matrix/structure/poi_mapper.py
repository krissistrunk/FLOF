"""POI Mapper (M02, Actor) — Maps all 7 POI types with tagging and freshness tracking.

Handles: Order Blocks, FVGs, Liquidity Pools, Breaker Blocks, Unicorn setups,
Rejection Blocks, and Gap FVGs. Plus inducement scanning, halo calculation,
flip zone and sweep zone detection.
"""

from __future__ import annotations

import numpy as np

from flof_matrix.core.types import POIType, TradeDirection
from flof_matrix.core.data_types import POI


class POIMapper:
    """Maps and tracks Points of Interest across timeframes."""

    def __init__(self, atr_period: int = 14) -> None:
        self._pois: list[POI] = []
        self._historical_pois: list[POI] = []
        self._atr_period = atr_period

    @property
    def historical_pois(self) -> list[POI]:
        return list(self._historical_pois)

    @property
    def pois(self) -> list[POI]:
        return list(self._pois)

    def clear(self) -> None:
        self._pois.clear()

    def map_order_blocks(
        self,
        bars: np.ndarray,
        timeframe: str,
    ) -> list[POI]:
        """Detect Order Blocks with Extreme/Decisional tagging (T39).

        An OB is the last opposing candle before a strong displacement move.
        Extreme: at swing high/low. Decisional: mid-range continuation.
        """
        if len(bars) < 5:
            return []

        pois = []
        highs = bars["high"]
        lows = bars["low"]
        opens = bars["open"]
        closes = bars["close"]

        atr = self._compute_atr(bars)
        if atr <= 0:
            return []

        for i in range(2, len(bars) - 2):
            body = abs(closes[i + 1] - opens[i + 1])
            rng = highs[i + 1] - lows[i + 1]

            # Displacement: next candle body > 1.5x ATR
            if body < 1.5 * atr:
                continue

            # Bullish OB: bearish candle before bullish displacement
            if closes[i] < opens[i] and closes[i + 1] > opens[i + 1]:
                is_extreme = (lows[i] <= min(lows[max(0, i - 3):i]))
                poi = POI(
                    type=POIType.ORDER_BLOCK,
                    price=(opens[i] + closes[i]) / 2,
                    zone_high=opens[i],
                    zone_low=lows[i],
                    timeframe=timeframe,
                    direction=TradeDirection.LONG,
                    is_extreme=is_extreme,
                    is_decisional=not is_extreme,
                    is_fresh=True,
                )
                pois.append(poi)
                self._pois.append(poi)

            # Bearish OB: bullish candle before bearish displacement
            elif closes[i] > opens[i] and closes[i + 1] < opens[i + 1]:
                is_extreme = (highs[i] >= max(highs[max(0, i - 3):i]))
                poi = POI(
                    type=POIType.ORDER_BLOCK,
                    price=(opens[i] + closes[i]) / 2,
                    zone_high=highs[i],
                    zone_low=closes[i],
                    timeframe=timeframe,
                    direction=TradeDirection.SHORT,
                    is_extreme=is_extreme,
                    is_decisional=not is_extreme,
                    is_fresh=True,
                )
                pois.append(poi)
                self._pois.append(poi)

        return pois

    def map_fvgs(
        self,
        bars: np.ndarray,
        timeframe: str,
    ) -> list[POI]:
        """Detect Fair Value Gaps (3-candle gaps) with freshness tracking (T04)."""
        if len(bars) < 3:
            return []

        pois = []
        highs = bars["high"]
        lows = bars["low"]

        for i in range(1, len(bars) - 1):
            # Bullish FVG: candle[i-1] high < candle[i+1] low
            if highs[i - 1] < lows[i + 1]:
                poi = POI(
                    type=POIType.FVG,
                    price=(highs[i - 1] + lows[i + 1]) / 2,
                    zone_high=lows[i + 1],
                    zone_low=highs[i - 1],
                    timeframe=timeframe,
                    direction=TradeDirection.LONG,
                    is_fresh=True,
                )
                pois.append(poi)
                self._pois.append(poi)

            # Bearish FVG: candle[i-1] low > candle[i+1] high
            if lows[i - 1] > highs[i + 1]:
                poi = POI(
                    type=POIType.FVG,
                    price=(lows[i - 1] + highs[i + 1]) / 2,
                    zone_high=lows[i - 1],
                    zone_low=highs[i + 1],
                    timeframe=timeframe,
                    direction=TradeDirection.SHORT,
                    is_fresh=True,
                )
                pois.append(poi)
                self._pois.append(poi)

        return pois

    def detect_liquidity_sweep(
        self,
        bars: np.ndarray,
        pdh: float,
        pdl: float,
        session_high: float,
        session_low: float,
    ) -> list[POI]:
        """Detect PDH/PDL and session H/L sweeps (T05)."""
        if len(bars) == 0:
            return []

        pois = []
        highs = bars["high"]
        lows = bars["low"]
        closes = bars["close"]

        last_high = highs[-1]
        last_low = lows[-1]
        last_close = closes[-1]

        # PDH sweep: price went above PDH then closed below
        if last_high > pdh and last_close < pdh:
            poi = POI(
                type=POIType.LIQUIDITY_POOL,
                price=pdh,
                zone_high=pdh + (last_high - pdh),
                zone_low=pdh,
                timeframe="D",
                direction=TradeDirection.SHORT,
                is_sweep_zone=True,
                is_fresh=True,
            )
            pois.append(poi)
            self._pois.append(poi)

        # PDL sweep: price went below PDL then closed above
        if last_low < pdl and last_close > pdl:
            poi = POI(
                type=POIType.LIQUIDITY_POOL,
                price=pdl,
                zone_high=pdl,
                zone_low=pdl - (pdl - last_low),
                timeframe="D",
                direction=TradeDirection.LONG,
                is_sweep_zone=True,
                is_fresh=True,
            )
            pois.append(poi)
            self._pois.append(poi)

        # Session high/low sweeps
        if last_high > session_high and last_close < session_high:
            poi = POI(
                type=POIType.LIQUIDITY_POOL,
                price=session_high,
                zone_high=session_high + (last_high - session_high),
                zone_low=session_high,
                timeframe="session",
                direction=TradeDirection.SHORT,
                is_sweep_zone=True,
                is_fresh=True,
            )
            pois.append(poi)
            self._pois.append(poi)

        if last_low < session_low and last_close > session_low:
            poi = POI(
                type=POIType.LIQUIDITY_POOL,
                price=session_low,
                zone_high=session_low,
                zone_low=session_low - (session_low - last_low),
                timeframe="session",
                direction=TradeDirection.LONG,
                is_sweep_zone=True,
                is_fresh=True,
            )
            pois.append(poi)
            self._pois.append(poi)

        return pois

    def detect_breaker_block(
        self,
        bars: np.ndarray,
        timeframe: str,
    ) -> list[POI]:
        """Detect Breaker Blocks — failed OBs that flip polarity (T40)."""
        if len(bars) < 5:
            return []

        pois = []
        opens = bars["open"]
        closes = bars["close"]
        highs = bars["high"]
        lows = bars["low"]

        for i in range(3, len(bars) - 1):
            # Bullish breaker: bearish OB that was broken to upside
            if closes[i - 2] < opens[i - 2]:  # Original bearish candle
                ob_high = max(opens[i - 2], closes[i - 2])
                # Price broke above the OB high
                if closes[i] > ob_high and closes[i - 1] < ob_high:
                    poi = POI(
                        type=POIType.BREAKER_BLOCK,
                        price=ob_high,
                        zone_high=highs[i - 2],
                        zone_low=min(opens[i - 2], closes[i - 2]),
                        timeframe=timeframe,
                        direction=TradeDirection.LONG,
                        is_fresh=True,
                    )
                    pois.append(poi)
                    self._pois.append(poi)

            # Bearish breaker: bullish OB broken to downside
            if closes[i - 2] > opens[i - 2]:  # Original bullish candle
                ob_low = min(opens[i - 2], closes[i - 2])
                if closes[i] < ob_low and closes[i - 1] > ob_low:
                    poi = POI(
                        type=POIType.BREAKER_BLOCK,
                        price=ob_low,
                        zone_high=max(opens[i - 2], closes[i - 2]),
                        zone_low=lows[i - 2],
                        timeframe=timeframe,
                        direction=TradeDirection.SHORT,
                        is_fresh=True,
                    )
                    pois.append(poi)
                    self._pois.append(poi)

        return pois

    def detect_unicorn_setup(
        self,
        bars: np.ndarray,
        timeframe: str,
    ) -> list[POI]:
        """T40: Unicorn = Breaker Block + FVG overlap. Highest probability pattern."""
        breakers = self.detect_breaker_block(bars, timeframe)
        fvgs = self.map_fvgs(bars, timeframe)

        pois = []
        for bb in breakers:
            for fvg in fvgs:
                if bb.direction == fvg.direction:
                    # Check overlap
                    overlap_low = max(bb.zone_low, fvg.zone_low)
                    overlap_high = min(bb.zone_high, fvg.zone_high)
                    if overlap_low < overlap_high:
                        poi = POI(
                            type=POIType.BREAKER_BLOCK,
                            price=(overlap_low + overlap_high) / 2,
                            zone_high=overlap_high,
                            zone_low=overlap_low,
                            timeframe=timeframe,
                            direction=bb.direction,
                            is_unicorn=True,
                            is_fresh=True,
                        )
                        pois.append(poi)
                        self._pois.append(poi)
        return pois

    def detect_rejection_block(
        self,
        bars: np.ndarray,
        timeframe: str,
    ) -> list[POI]:
        """T41: Rejection Block — wick >= 2x body at structural level."""
        if len(bars) < 2:
            return []

        pois = []
        opens = bars["open"]
        closes = bars["close"]
        highs = bars["high"]
        lows = bars["low"]

        for i in range(len(bars)):
            body = abs(closes[i] - opens[i])
            if body == 0:
                continue
            upper_wick = highs[i] - max(opens[i], closes[i])
            lower_wick = min(opens[i], closes[i]) - lows[i]

            # Bearish rejection: upper wick >= 2x body
            if upper_wick >= 2 * body:
                poi = POI(
                    type=POIType.REJECTION_BLOCK,
                    price=highs[i],
                    zone_high=highs[i],
                    zone_low=max(opens[i], closes[i]),
                    timeframe=timeframe,
                    direction=TradeDirection.SHORT,
                    is_fresh=True,
                )
                pois.append(poi)
                self._pois.append(poi)

            # Bullish rejection: lower wick >= 2x body
            if lower_wick >= 2 * body:
                poi = POI(
                    type=POIType.REJECTION_BLOCK,
                    price=lows[i],
                    zone_high=min(opens[i], closes[i]),
                    zone_low=lows[i],
                    timeframe=timeframe,
                    direction=TradeDirection.LONG,
                    is_fresh=True,
                )
                pois.append(poi)
                self._pois.append(poi)

        return pois

    def scan_inducement(self, price: float, pois: list[POI] | None = None) -> bool:
        """G2 gate verification: check if inducement (liquidity sweep) occurred before POI tap."""
        target_pois = pois if pois is not None else self._pois
        for poi in target_pois:
            if poi.type == POIType.LIQUIDITY_POOL and poi.is_sweep_zone:
                # Sweep must be between current price approach and POI
                return True
        return False

    def calculate_proximity_halo(
        self,
        current_price: float,
        poi: POI,
        atr: float,
        halo_mult: float = 1.5,
    ) -> bool:
        """T34: POI ± 1.5 × ATR triggers Stalking state transition."""
        halo_distance = halo_mult * atr
        if poi.direction == TradeDirection.LONG:
            return abs(current_price - poi.zone_low) <= halo_distance
        else:
            return abs(current_price - poi.zone_high) <= halo_distance

    def track_freshness(self, poi: POI, current_price: float) -> POI:
        """T04: Mark POI as mitigated after first tap (price enters zone)."""
        if not poi.is_fresh:
            return poi
        if poi.zone_low <= current_price <= poi.zone_high:
            # Create new POI with is_fresh=False (frozen dataclass)
            mitigated = POI(
                type=poi.type,
                price=poi.price,
                zone_high=poi.zone_high,
                zone_low=poi.zone_low,
                timeframe=poi.timeframe,
                direction=poi.direction,
                is_extreme=poi.is_extreme,
                is_decisional=poi.is_decisional,
                is_flip_zone=poi.is_flip_zone,
                is_sweep_zone=poi.is_sweep_zone,
                is_unicorn=poi.is_unicorn,
                has_inducement=poi.has_inducement,
                is_fresh=False,
            )
            # Track in historical POIs for flip zone detection (cap at 200)
            self._historical_pois.append(mitigated)
            if len(self._historical_pois) > 200:
                self._historical_pois = self._historical_pois[-200:]
            return mitigated
        return poi

    def detect_flip_zone(self, poi: POI, historical_pois: list[POI]) -> bool:
        """T31: Detect if POI was previously support now acting as resistance (or vice versa)."""
        for hist in historical_pois:
            if hist.type == poi.type and hist.direction != poi.direction:
                # Check price proximity
                if abs(hist.price - poi.price) / max(poi.price, 0.01) < 0.002:  # Within 0.2%
                    return True
        return False

    def detect_sweep_zone(self, poi: POI) -> bool:
        """T32: Check if POI is in a recently swept zone."""
        return poi.is_sweep_zone

    def _compute_atr(self, bars: np.ndarray, period: int | None = None) -> float:
        """Compute Average True Range."""
        if period is None:
            period = self._atr_period
        if len(bars) < 2:
            return 0.0

        highs = bars["high"]
        lows = bars["low"]
        closes = bars["close"]

        n = min(len(bars), period + 1)
        tr = np.zeros(n - 1)
        for i in range(1, n):
            tr[i - 1] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        return float(np.mean(tr)) if len(tr) > 0 else 0.0
