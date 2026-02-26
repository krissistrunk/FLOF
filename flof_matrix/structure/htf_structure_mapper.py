"""HTF Structure Mapper (M03, Actor) — Daily/4H bias detection and regime analysis.

Toggles: T01 (HTF structure), T02 (regime filter), T03 (synthetic MA POI).
"""

from __future__ import annotations

import numpy as np

from flof_matrix.core.types import Grade, POIType, TradeDirection
from flof_matrix.core.data_types import POI


def evaluate_macro_bias(
    bars_4h: np.ndarray,
    bars_daily: np.ndarray,
) -> TradeDirection | None:
    """Daily/4H BOS-based directional bias (T01).

    Detects Break of Structure on Daily and 4H timeframes.
    Returns the directional bias, or None if no clear bias.

    bars should have columns: open, high, low, close
    """
    if len(bars_daily) < 3 or len(bars_4h) < 3:
        return None

    # Daily BOS: compare recent swing highs/lows
    daily_highs = bars_daily["high"]
    daily_lows = bars_daily["low"]
    daily_close = bars_daily["close"]

    # Simple BOS: higher highs + higher lows = bullish, lower lows + lower highs = bearish
    recent_high = daily_highs[-1]
    prev_high = np.max(daily_highs[-5:-1]) if len(daily_highs) >= 5 else daily_highs[-2]
    recent_low = daily_lows[-1]
    prev_low = np.min(daily_lows[-5:-1]) if len(daily_lows) >= 5 else daily_lows[-2]

    daily_bullish = recent_high > prev_high and recent_low > prev_low
    daily_bearish = recent_low < prev_low and recent_high < prev_high

    # 4H confirmation
    h4_highs = bars_4h["high"]
    h4_lows = bars_4h["low"]
    h4_recent_high = h4_highs[-1]
    h4_prev_high = np.max(h4_highs[-6:-1]) if len(h4_highs) >= 6 else h4_highs[-2]
    h4_recent_low = h4_lows[-1]
    h4_prev_low = np.min(h4_lows[-6:-1]) if len(h4_lows) >= 6 else h4_lows[-2]

    h4_bullish = h4_recent_high > h4_prev_high and h4_recent_low > h4_prev_low
    h4_bearish = h4_recent_low < h4_prev_low and h4_recent_high < h4_prev_high

    if daily_bullish and h4_bullish:
        return TradeDirection.LONG
    elif daily_bearish and h4_bearish:
        return TradeDirection.SHORT

    # Partial alignment — use daily as primary
    if daily_bullish:
        return TradeDirection.LONG
    elif daily_bearish:
        return TradeDirection.SHORT

    return None


def calculate_regime(
    weekly_close: np.ndarray,
    monthly_close: np.ndarray,
    current_price: float,
    weekly_sma_period: int = 200,
    monthly_sma_period: int = 200,
) -> str:
    """Price vs Weekly/Monthly 200 SMA regime (T02).

    Returns: 'aligned', 'conflicted', or 'neutral'
    """
    weekly_sma = compute_sma(weekly_close, weekly_sma_period)
    monthly_sma = compute_sma(monthly_close, monthly_sma_period)

    if weekly_sma is None and monthly_sma is None:
        return "neutral"

    above_weekly = current_price > weekly_sma if weekly_sma is not None else None
    above_monthly = current_price > monthly_sma if monthly_sma is not None else None

    if above_weekly is None:
        return "aligned" if above_monthly else "conflicted"
    if above_monthly is None:
        return "aligned" if above_weekly else "conflicted"

    if above_weekly == above_monthly:
        return "aligned"
    else:
        return "conflicted"


def evaluate_premium_discount(
    price: float,
    range_high: float,
    range_low: float,
) -> str:
    """G1 gate: premium/discount classification.

    Returns 'premium' if above 50% of range, 'discount' if below.
    """
    if range_high == range_low:
        return "neutral"
    midpoint = (range_high + range_low) / 2.0
    if price > midpoint:
        return "premium"
    else:
        return "discount"


def generate_synthetic_poi(
    ma_value: float,
    daily_atr: float,
    direction: TradeDirection,
    zone_width_mult: float = 1.5,
) -> POI:
    """T03: Create SYNTHETIC_MA POI at Weekly/Monthly 200 SMA.

    Zone = MA +/- (zone_width_mult x daily ATR). Capped at B grade.
    """
    half_zone = zone_width_mult * daily_atr
    return POI(
        type=POIType.SYNTHETIC_MA,
        price=ma_value,
        zone_high=ma_value + half_zone,
        zone_low=ma_value - half_zone,
        timeframe="W",
        direction=direction,
        is_fresh=True,
    )


def compute_sma(data: np.ndarray, period: int) -> float | None:
    """Compute simple moving average. Returns None if insufficient data."""
    if len(data) < period:
        return None
    return float(np.mean(data[-period:]))


def compute_weekly_200sma(weekly_close: np.ndarray) -> float | None:
    """Standard 200-period SMA on weekly closes (T02)."""
    return compute_sma(weekly_close, 200)


def compute_monthly_200sma(monthly_close: np.ndarray) -> float | None:
    """Standard 200-period SMA on monthly closes (T02)."""
    return compute_sma(monthly_close, 200)
