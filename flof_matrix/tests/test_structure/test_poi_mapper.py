"""Tests for POI Mapper — each POI type, tagging, freshness, halo."""

import numpy as np
import pytest

from flof_matrix.structure.poi_mapper import POIMapper
from flof_matrix.core.types import POIType, TradeDirection
from flof_matrix.core.data_types import POI


BAR_DTYPE = np.dtype([("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8")])


def make_displacement_bars():
    """Create bars with a clear bullish displacement for OB detection.

    OB detection loop runs range(2, len-2), so the OB pair needs to be
    at indices where i and i+1 are both within that range.
    """
    bars = np.zeros(12, dtype=BAR_DTYPE)
    # Normal bars with tight range (~4 pts ATR)
    for i in range(8):
        bars[i] = (5000 + i, 5002 + i, 4998 + i, 5001 + i)
    # Bearish candle at index 8 (OB candidate) — within range(2, 10)
    bars[8] = (5010, 5012, 5005, 5006)  # bearish: close < open
    # Strong bullish displacement at index 9 — body=18 > 1.5*ATR(~4)=6
    bars[9] = (5006, 5025, 5005, 5024)  # huge bullish
    # Padding bars so len-2=10 > 9
    bars[10] = (5024, 5026, 5022, 5025)
    bars[11] = (5025, 5027, 5023, 5026)
    return bars


class TestPOIMapper:
    def test_map_order_blocks_bullish(self):
        mapper = POIMapper()
        bars = make_displacement_bars()
        pois = mapper.map_order_blocks(bars, "1H")
        long_obs = [p for p in pois if p.direction == TradeDirection.LONG]
        assert len(long_obs) > 0
        assert long_obs[0].type == POIType.ORDER_BLOCK

    def test_map_fvgs(self):
        mapper = POIMapper()
        bars = np.zeros(5, dtype=BAR_DTYPE)
        # Create bullish FVG: bar[0].high < bar[2].low
        bars[0] = (5000, 5002, 4998, 5001)
        bars[1] = (5001, 5010, 5000, 5009)  # big candle
        bars[2] = (5009, 5012, 5005, 5011)  # low > bar[0].high = FVG
        bars[3] = (5011, 5013, 5010, 5012)
        bars[4] = (5012, 5014, 5011, 5013)
        pois = mapper.map_fvgs(bars, "1H")
        bullish_fvgs = [p for p in pois if p.direction == TradeDirection.LONG]
        assert len(bullish_fvgs) > 0
        assert bullish_fvgs[0].type == POIType.FVG

    def test_detect_liquidity_sweep_pdh(self):
        mapper = POIMapper()
        bars = np.zeros(1, dtype=BAR_DTYPE)
        # Price went above PDH (5050) but closed below it
        bars[0] = (5045, 5055, 5040, 5048)
        pois = mapper.detect_liquidity_sweep(
            bars, pdh=5050, pdl=4950, session_high=5040, session_low=4960
        )
        short_sweeps = [p for p in pois if p.direction == TradeDirection.SHORT]
        assert len(short_sweeps) > 0
        assert short_sweeps[0].is_sweep_zone

    def test_detect_liquidity_sweep_pdl(self):
        mapper = POIMapper()
        bars = np.zeros(1, dtype=BAR_DTYPE)
        # Price went below PDL (4950) but closed above it
        bars[0] = (4955, 4960, 4945, 4952)
        pois = mapper.detect_liquidity_sweep(
            bars, pdh=5050, pdl=4950, session_high=5040, session_low=4960
        )
        long_sweeps = [p for p in pois if p.direction == TradeDirection.LONG]
        assert len(long_sweeps) > 0

    def test_detect_rejection_block(self):
        mapper = POIMapper()
        bars = np.zeros(3, dtype=BAR_DTYPE)
        # Bar with upper wick >= 2x body (bearish rejection)
        bars[0] = (5000, 5020, 4998, 5003)  # body=3, upper_wick=17
        bars[1] = (5003, 5005, 5000, 5002)
        bars[2] = (5002, 5004, 5000, 5001)
        pois = mapper.detect_rejection_block(bars, "1H")
        assert len(pois) > 0

    def test_proximity_halo(self):
        mapper = POIMapper()
        poi = POI(
            type=POIType.ORDER_BLOCK, price=5000.0,
            zone_high=5002.0, zone_low=4998.0,
            timeframe="1H", direction=TradeDirection.LONG,
        )
        # Within halo (1.5 * 5.0 = 7.5 points)
        assert mapper.calculate_proximity_halo(4995.0, poi, atr=5.0, halo_mult=1.5)
        # Outside halo
        assert not mapper.calculate_proximity_halo(4980.0, poi, atr=5.0, halo_mult=1.5)

    def test_track_freshness(self):
        mapper = POIMapper()
        poi = POI(
            type=POIType.FVG, price=5000.0,
            zone_high=5002.0, zone_low=4998.0,
            timeframe="1H", direction=TradeDirection.LONG,
            is_fresh=True,
        )
        # Price enters zone
        mitigated = mapper.track_freshness(poi, 5000.0)
        assert not mitigated.is_fresh

        # Price outside zone
        still_fresh = mapper.track_freshness(poi, 5010.0)
        assert still_fresh.is_fresh

    def test_scan_inducement(self):
        mapper = POIMapper()
        sweep_poi = POI(
            type=POIType.LIQUIDITY_POOL, price=5050.0,
            zone_high=5055.0, zone_low=5050.0,
            timeframe="D", direction=TradeDirection.SHORT,
            is_sweep_zone=True,
        )
        assert mapper.scan_inducement(5000.0, [sweep_poi])
        assert not mapper.scan_inducement(5000.0, [])

    def test_extreme_vs_decisional_tagging(self):
        mapper = POIMapper()
        bars = make_displacement_bars()
        pois = mapper.map_order_blocks(bars, "1H")
        # At least one should have extreme or decisional set
        for p in pois:
            assert p.is_extreme or p.is_decisional
