#!/usr/bin/env python3
"""Download historical data from DataBento for FLOF Matrix backtesting.

Usage:
    # With DataBento API key:
    DATABENTO_API_KEY=your_key python scripts/download_data.py \\
        --symbol ES.FUT --schema ohlcv-1m --start 2024-01-01 --end 2024-01-31

    # Without API key (generates realistic synthetic ES data):
    python scripts/download_data.py --start 2024-01-01 --end 2024-01-31

The synthetic generator produces structurally realistic ES futures data with
proper session times, killzone volatility patterns, ICT-style market structure
(order blocks, FVGs, liquidity sweeps, BOS), and realistic volume profiles.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_args():
    parser = argparse.ArgumentParser(description="Download DataBento historical data")
    parser.add_argument("--symbol", type=str, default="ES.FUT",
                        help="Symbol to download")
    parser.add_argument("--schema", type=str, default="ohlcv-1m",
                        choices=["ohlcv-1m", "ohlcv-1d", "trades", "tbbo", "mbp-10"],
                        help="Data schema")
    parser.add_argument("--schemas", type=str, nargs="+", default=None,
                        help="Multiple schemas to download (e.g. ohlcv-1m ohlcv-1d)")
    parser.add_argument("--start", type=str, default="2024-01-01",
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default="2024-01-31",
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, default="data/",
                        help="Output directory")
    parser.add_argument("--dataset", type=str, default="GLBX.MDP3",
                        help="DataBento dataset")
    parser.add_argument("--max-cost", type=float, default=50.0,
                        help="Maximum DataBento cost in USD (default: $50)")
    parser.add_argument("--force-synthetic", action="store_true",
                        help="Force synthetic data generation even if API key exists")
    return parser.parse_args()


# ═══════════════════════════════════════════════════════════════════════
# DataBento Download (requires DATABENTO_API_KEY)
# ═══════════════════════════════════════════════════════════════════════

def download_databento(args) -> Path | None:
    """Download from DataBento API with cost estimation."""
    from flof_matrix.data.databento_adapter import DataBentoAdapter

    adapter = DataBentoAdapter(dataset=args.dataset)
    schemas = args.schemas or [args.schema]
    total_cost = 0.0
    results = []

    for schema in schemas:
        logging.info("Downloading %s data for %s from DataBento", schema, args.symbol)
        logging.info("  Period: %s to %s", args.start, args.end)
        logging.info("  Dataset: %s", args.dataset)

        # Estimate cost first
        cost = adapter.estimate_cost(
            symbols=[args.symbol],
            schema=schema,
            start=args.start,
            end=args.end,
        )
        if cost is not None:
            logging.info("  Estimated cost: $%.2f", cost)
            total_cost += cost
            if total_cost > args.max_cost:
                logging.error("  Cost $%.2f exceeds max $%.2f — aborting", total_cost, args.max_cost)
                return None
        else:
            logging.warning("  Could not estimate cost — proceeding with download")

        result = adapter.download(
            symbols=[args.symbol],
            schema=schema,
            start=args.start,
            end=args.end,
            output_dir=args.output,
        )
        if result:
            results.append(result)

    logging.info("Total estimated cost: $%.2f", total_cost)
    return results[0] if results else None


# ═══════════════════════════════════════════════════════════════════════
# Realistic Synthetic ES Data Generator
# ═══════════════════════════════════════════════════════════════════════

BAR_DTYPE = np.dtype([
    ("timestamp_ns", np.int64),
    ("open", np.float64),
    ("high", np.float64),
    ("low", np.float64),
    ("close", np.float64),
    ("volume", np.float64),
])


def generate_synthetic_es(start_date: str, end_date: str, output_dir: str) -> Path:
    """Generate structurally realistic ES futures 1-minute bars.

    Produces data with:
    - Proper RTH session (09:30-16:00 ET) and ETH structure
    - NY AM / NY PM killzone volatility patterns
    - ICT-style market structure: trends, pullbacks, BOS, liquidity sweeps
    - Realistic order block / FVG patterns embedded in price action
    - Volume profile with session opens, killzone peaks
    - PDH/PDL levels that get swept
    - Mean-reverting microstructure within trending macro
    """
    from datetime import datetime, timedelta

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    rng = np.random.default_rng(42)  # Reproducible

    all_bars = []
    price = 4800.0
    day_count = 0

    current_day = start
    while current_day <= end:
        # Skip weekends
        if current_day.weekday() >= 5:
            current_day += timedelta(days=1)
            continue

        day_count += 1
        day_bars = _generate_trading_day(
            current_day, price, rng, day_count
        )
        if len(day_bars) > 0:
            price = day_bars[-1]["close"]
            all_bars.append(day_bars)

        current_day += timedelta(days=1)

    bars = np.concatenate(all_bars) if all_bars else np.array([], dtype=BAR_DTYPE)

    # Save
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    filepath = output_path / f"ES_synthetic_{start_date}_{end_date}.npy"
    np.save(str(filepath), bars)

    # Also save metadata
    meta = {
        "symbol": "ES",
        "start": start_date,
        "end": end_date,
        "bars": len(bars),
        "trading_days": day_count,
        "source": "synthetic",
        "generator_version": "2.0",
        "seed": 42,
    }
    meta_path = output_path / f"ES_synthetic_{start_date}_{end_date}_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    logging.info("Generated %d bars across %d trading days", len(bars), day_count)
    logging.info("Saved to %s", filepath)
    return filepath


def _generate_trading_day(
    day: "datetime",
    open_price: float,
    rng: np.random.Generator,
    day_num: int,
) -> np.ndarray:
    """Generate one full trading day of 1-minute ES bars.

    Session structure (Eastern Time):
    - ETH pre-market: 18:00 prev day - 09:30 (lower volatility)
    - RTH open: 09:30 (gap + opening range)
    - NY AM killzone: 09:30-11:30 (high volatility, trending)
    - Lunch: 11:30-13:30 (low volatility, choppy)
    - NY PM killzone: 13:30-15:30 (secondary trend move)
    - EOD: 15:30-16:00 (position squaring)

    We generate only RTH (09:30-16:00) = 390 bars for simplicity.
    """
    from datetime import datetime, timedelta

    # Day's structural parameters
    day_trend = rng.choice([-1.0, 1.0], p=[0.45, 0.55])  # Slight bullish bias
    day_range_atr = rng.uniform(8.0, 22.0)  # ES daily range in points
    base_volume = rng.uniform(200, 600)

    # Session open (09:30 ET) - gap from previous close
    gap = rng.normal(0, 2.0)  # Overnight gap
    price = open_price + gap

    # Previous day high/low for PDH/PDL sweep setups
    pdh = open_price + rng.uniform(3, 10)
    pdl = open_price - rng.uniform(3, 10)

    # Decide day type: trending (60%), ranging (25%), reversal (15%)
    day_type = rng.choice(["trending", "ranging", "reversal"], p=[0.60, 0.25, 0.15])

    bars = np.zeros(390, dtype=BAR_DTYPE)
    base_ts_ns = int(day.replace(hour=14, minute=30).timestamp()) * 1_000_000_000  # 09:30 ET = 14:30 UTC

    # Pre-generate the structural moves for the day
    moves = _generate_day_structure(day_type, day_trend, day_range_atr, rng)

    session_high = price
    session_low = price

    for i in range(390):
        minute = i
        ts_ns = base_ts_ns + i * 60_000_000_000

        # Time-of-day volatility multiplier
        vol_mult = _session_volatility(minute)

        # Base move from structural plan
        structural_move = moves[i] if i < len(moves) else 0.0

        # Microstructure noise
        noise = rng.normal(0, 0.5 * vol_mult)

        # Combined move
        move = structural_move + noise

        bar_open = price
        bar_close = price + move

        # Generate realistic high/low
        wick_up = abs(rng.normal(0, 0.3 * vol_mult)) + max(0, move)
        wick_down = abs(rng.normal(0, 0.3 * vol_mult)) + max(0, -move)
        bar_high = max(bar_open, bar_close) + wick_up
        bar_low = min(bar_open, bar_close) - wick_down

        # Volume based on time of day
        vol = base_volume * vol_mult * rng.uniform(0.5, 1.5)

        # PDH/PDL sweep mechanics: push through then reject
        if minute in range(30, 90):  # NY AM killzone
            if bar_high > pdh and rng.random() < 0.5:
                # Sweep PDH - rejection candle
                bar_high = pdh + rng.uniform(0.25, 2.0)
                bar_close = pdh - rng.uniform(0.5, 3.0)
                bar_low = min(bar_low, bar_close - rng.uniform(0, 1.0))
                vol *= 2.5  # Spike volume on sweep
            if bar_low < pdl and rng.random() < 0.5:
                bar_low = pdl - rng.uniform(0.25, 2.0)
                bar_close = pdl + rng.uniform(0.5, 3.0)
                bar_high = max(bar_high, bar_close + rng.uniform(0, 1.0))
                vol *= 2.5

        # PM killzone sweeps (session H/L)
        if minute in range(240, 330):
            if bar_high > session_high and rng.random() < 0.4:
                bar_high = session_high + rng.uniform(0.25, 1.5)
                bar_close = session_high - rng.uniform(0.5, 2.0)
                bar_low = min(bar_low, bar_close - rng.uniform(0, 0.5))
                vol *= 2.0
            if bar_low < session_low and rng.random() < 0.4:
                bar_low = session_low - rng.uniform(0.25, 1.5)
                bar_close = session_low + rng.uniform(0.5, 2.0)
                bar_high = max(bar_high, bar_close + rng.uniform(0, 0.5))
                vol *= 2.0

        bars[i]["timestamp_ns"] = ts_ns
        bars[i]["open"] = round(bar_open, 2)
        bars[i]["high"] = round(bar_high, 2)
        bars[i]["low"] = round(bar_low, 2)
        bars[i]["close"] = round(bar_close, 2)
        bars[i]["volume"] = round(vol, 0)

        session_high = max(session_high, bar_high)
        session_low = min(session_low, bar_low)
        price = bar_close

    return bars


def _generate_day_structure(
    day_type: str,
    trend_dir: float,
    atr: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate structural move plan for 390 1-min bars.

    Creates realistic ICT/SMC price action patterns:
    - Opening range establishment (first 15 min)
    - Killzone impulse moves with order blocks
    - FVG gaps (3-candle displacement moves)
    - Pullbacks to structural levels
    - Liquidity sweeps of prior highs/lows
    """
    moves = np.zeros(390)

    if day_type == "trending":
        moves = _trending_day(trend_dir, atr, rng)
    elif day_type == "ranging":
        moves = _ranging_day(atr, rng)
    else:
        moves = _reversal_day(trend_dir, atr, rng)

    return moves


def _trending_day(trend_dir: float, atr: float, rng: np.random.Generator) -> np.ndarray:
    """Trending day: directional move with pullbacks.

    Structure:
    1. Opening range (0-15): tight consolidation
    2. NY AM impulse (15-60): strong directional move with FVGs
    3. Pullback to OB (60-90): retrace ~38-50% of impulse
    4. Continuation (90-120): secondary push
    5. Lunch chop (120-240): low volatility consolidation
    6. NY PM impulse (240-330): final push in trend direction
    7. EOD squeeze (330-390): position squaring
    """
    moves = np.zeros(390)
    per_bar = atr / 390  # Distribute ATR across the day

    # Phase 1: Opening range (0-15 min)
    for i in range(15):
        moves[i] = rng.normal(0, per_bar * 0.5)

    # Phase 2: NY AM impulse (15-60 min) — strong directional move
    # Creates order blocks and FVGs
    impulse_strength = atr * 0.4  # 40% of daily range in first impulse
    for i in range(15, 60):
        progress = (i - 15) / 45.0
        # Acceleration then deceleration
        accel = np.sin(progress * np.pi)
        base_move = trend_dir * (impulse_strength / 45) * accel * 2
        moves[i] = base_move + rng.normal(0, per_bar * 0.3)

    # Insert FVG pattern: 3 consecutive strong bars in trend direction (around bar 30)
    fvg_start = 28 + rng.integers(0, 5)
    for j in range(3):
        moves[fvg_start + j] = trend_dir * atr * 0.04 * (1 + rng.uniform(0, 0.5))

    # Phase 3: Pullback to OB (60-90 min)
    pullback_depth = rng.uniform(0.30, 0.50)  # 30-50% retrace
    pullback_total = impulse_strength * pullback_depth
    for i in range(60, 90):
        progress = (i - 60) / 30.0
        moves[i] = -trend_dir * (pullback_total / 30) * (1 - progress) + rng.normal(0, per_bar * 0.4)

    # Phase 4: Continuation from OB (90-120 min) — starts with strong displacement bar
    continuation_strength = atr * 0.25
    # Displacement candle at start of continuation (signals OB entry)
    moves[90] = trend_dir * atr * 0.06
    moves[91] = trend_dir * atr * 0.05
    moves[92] = trend_dir * atr * 0.04
    for i in range(93, 120):
        progress = (i - 93) / 27.0
        moves[i] = trend_dir * (continuation_strength * 0.6 / 27) * np.sin(progress * np.pi * 0.5) + rng.normal(0, per_bar * 0.3)

    # Phase 5: Lunch chop (120-240 min) — consolidation
    for i in range(120, 240):
        moves[i] = rng.normal(0, per_bar * 0.3)

    # Phase 6: NY PM impulse (240-330 min)
    pm_strength = atr * 0.25
    for i in range(240, 330):
        progress = (i - 240) / 90.0
        moves[i] = trend_dir * (pm_strength / 90) * np.sin(progress * np.pi) + rng.normal(0, per_bar * 0.3)

    # Insert second FVG in PM session
    fvg2_start = 255 + rng.integers(0, 10)
    for j in range(3):
        if fvg2_start + j < 330:
            moves[fvg2_start + j] = trend_dir * atr * 0.03 * (1 + rng.uniform(0, 0.3))

    # Phase 7: EOD (330-390)
    for i in range(330, 390):
        moves[i] = rng.normal(0, per_bar * 0.4) - trend_dir * per_bar * 0.3  # Slight profit-taking

    return moves


def _ranging_day(atr: float, rng: np.random.Generator) -> np.ndarray:
    """Ranging day: oscillating between support/resistance.

    Creates mean-reverting structure with false breakouts.
    """
    moves = np.zeros(390)
    per_bar = atr / 390

    # Oscillate with a sine-like pattern
    half_range = atr * 0.3
    freq = rng.uniform(0.015, 0.025)  # oscillation frequency
    phase = rng.uniform(0, 2 * np.pi)

    cumulative = 0.0
    for i in range(390):
        target = half_range * np.sin(freq * i + phase)
        reversion = (target - cumulative) * 0.08  # Mean reversion strength
        noise = rng.normal(0, per_bar * 0.8)
        moves[i] = reversion + noise
        cumulative += moves[i]

    return moves


def _reversal_day(initial_dir: float, atr: float, rng: np.random.Generator) -> np.ndarray:
    """Reversal day: initial move then strong reversal.

    Creates a liquidity sweep pattern — initial push to take stops,
    then sharp reversal in opposite direction.
    """
    moves = np.zeros(390)
    per_bar = atr / 390

    # Phase 1: Initial move (0-60 min) — trap move
    trap_size = atr * 0.3
    for i in range(60):
        progress = i / 60.0
        moves[i] = initial_dir * (trap_size / 60) * (1 - progress * 0.3) + rng.normal(0, per_bar * 0.3)

    # Phase 2: Reversal signal (60-75 min) — absorption candles
    for i in range(60, 75):
        moves[i] = rng.normal(0, per_bar * 0.5)  # Stalling

    # Phase 3: Sharp reversal (75-150 min) — displacement move
    reversal_size = atr * 0.6
    for i in range(75, 150):
        progress = (i - 75) / 75.0
        moves[i] = -initial_dir * (reversal_size / 75) * np.sin(progress * np.pi * 0.5) * 2 + rng.normal(0, per_bar * 0.3)

    # Insert FVG in reversal
    fvg_start = 85 + rng.integers(0, 10)
    for j in range(3):
        if fvg_start + j < 150:
            moves[fvg_start + j] = -initial_dir * atr * 0.04

    # Phase 4: Continuation in reversal direction (150-330 min)
    cont_size = atr * 0.2
    for i in range(150, 330):
        progress = (i - 150) / 180.0
        moves[i] = -initial_dir * (cont_size / 180) + rng.normal(0, per_bar * 0.4)

    # Phase 5: EOD
    for i in range(330, 390):
        moves[i] = rng.normal(0, per_bar * 0.4)

    return moves


def _session_volatility(minute: int) -> float:
    """Time-of-day volatility multiplier for ES.

    Matches real ES intraday volatility pattern:
    - High at open (09:30)
    - Elevated through NY AM killzone (09:30-11:30)
    - Low during lunch (11:30-13:30)
    - Moderate NY PM killzone (13:30-15:30)
    - Spike at close (15:50-16:00)
    """
    if minute < 15:        # Opening 15 min
        return 2.5
    elif minute < 30:      # 09:45-10:00
        return 2.0
    elif minute < 120:     # NY AM killzone (10:00-11:30)
        return 1.6
    elif minute < 240:     # Lunch (11:30-13:30)
        return 0.6
    elif minute < 360:     # NY PM killzone (13:30-15:30)
        return 1.3
    elif minute < 380:     # EOD approach
        return 1.0
    else:                  # Final 10 min
        return 1.8


def generate_synthetic_nq(start_date: str, end_date: str, output_dir: str) -> Path:
    """Generate synthetic NQ futures data. Same structure as ES but different price/ATR."""
    from datetime import datetime, timedelta

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    rng = np.random.default_rng(99)  # Different seed from ES

    all_bars = []
    price = 17000.0  # NQ base price
    day_count = 0

    current_day = start
    while current_day <= end:
        if current_day.weekday() >= 5:
            current_day += timedelta(days=1)
            continue

        day_count += 1
        day_bars = _generate_trading_day(current_day, price, rng, day_count)
        if len(day_bars) > 0:
            # Scale to NQ price range (higher ATR)
            scale = 17000.0 / 4800.0
            day_bars["open"] *= scale
            day_bars["high"] *= scale
            day_bars["low"] *= scale
            day_bars["close"] *= scale
            price = day_bars[-1]["close"]
            all_bars.append(day_bars)

        current_day += timedelta(days=1)

    bars = np.concatenate(all_bars) if all_bars else np.array([], dtype=BAR_DTYPE)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    filepath = output_path / f"NQ_synthetic_{start_date}_{end_date}.npy"
    np.save(str(filepath), bars)

    meta = {
        "symbol": "NQ",
        "start": start_date,
        "end": end_date,
        "bars": len(bars),
        "trading_days": day_count,
        "source": "synthetic",
        "generator_version": "2.0",
        "seed": 99,
    }
    meta_path = output_path / f"NQ_synthetic_{start_date}_{end_date}_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    logging.info("Generated %d NQ bars across %d trading days", len(bars), day_count)
    logging.info("Saved to %s", filepath)
    return filepath


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    has_api_key = bool(os.environ.get("DATABENTO_API_KEY"))

    # Determine symbol type
    is_nq = "NQ" in args.symbol.upper()

    if has_api_key and not args.force_synthetic:
        logging.info("DataBento API key found — downloading real data")
        result = download_databento(args)
        if result:
            logging.info("Download complete: %s", result)
        else:
            logging.warning("Download failed — falling back to synthetic data")
            if is_nq:
                result = generate_synthetic_nq(args.start, args.end, args.output)
            else:
                result = generate_synthetic_es(args.start, args.end, args.output)
    else:
        if not has_api_key:
            logging.info("No DATABENTO_API_KEY found — generating synthetic data")
        else:
            logging.info("Forced synthetic mode — generating synthetic data")
        if is_nq:
            result = generate_synthetic_nq(args.start, args.end, args.output)
        else:
            result = generate_synthetic_es(args.start, args.end, args.output)

    logging.info("Data ready: %s", result)


if __name__ == "__main__":
    main()
