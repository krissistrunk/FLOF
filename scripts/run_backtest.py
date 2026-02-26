#!/usr/bin/env python3
"""Run FLOF Matrix backtest.

Usage:
    python scripts/run_backtest.py --config config/flof_base.toml --profile futures \\
        --start 2024-01-01 --end 2024-01-31 --fill-level 2
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from flof_matrix.nautilus.backtest_runner import BacktestRunner, BAR_DTYPE
from flof_matrix.config.config_manager import ConfigManager


def parse_args():
    parser = argparse.ArgumentParser(description="FLOF Matrix Backtest Runner")
    parser.add_argument("--config", type=str, default="flof_matrix/config/flof_base.toml",
                        help="Path to base config TOML")
    parser.add_argument("--profile", type=str, default="futures",
                        help="Asset class profile (futures, crypto, etc.)")
    parser.add_argument("--instrument", type=str, default=None,
                        help="Instrument override (e.g. ES, NQ)")
    parser.add_argument("--start", type=str, default="2024-01-01",
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default="2024-01-31",
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--fill-level", type=int, default=2, choices=[1, 2, 3],
                        help="Fill pessimism level (1=Optimistic, 2=Standard, 3=Conservative)")
    parser.add_argument("--data-dir", type=str, default="data/",
                        help="Directory containing .dbn data files")
    parser.add_argument("--output", type=str, default="results/",
                        help="Output directory for results")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable debug logging")
    parser.add_argument("--db-dsn", type=str, default=None,
                        help="PostgreSQL DSN (e.g. postgresql://flof:pass@localhost:5433/flof)")
    parser.add_argument("--engine", type=str, default="manual", choices=["manual", "nautilus"],
                        help="Backtest engine: 'manual' (Python loop) or 'nautilus' (NautilusTrader)")
    parser.add_argument("--tick-data", type=str, default=None,
                        help="Path to .dbn.zst trade tick file (auto-discovers *trades*.dbn.zst in data dir if omitted)")
    return parser.parse_args()


def load_data(data_dir: str, start: str, end: str) -> np.ndarray:
    """Load bar data from .npy, .dbn files, or generate synthetic data.

    Priority:
    1. .npy files (synthetic generator output)
    2. .dbn files (DataBento downloads)
    3. On-the-fly synthetic generation
    """
    data_path = Path(data_dir)

    # Look for .npy files first (from download_data.py synthetic generator)
    npy_files = sorted(data_path.glob("*.npy"))
    if npy_files:
        bars = np.load(str(npy_files[0]))
        logging.info("Loaded %d bars from %s", len(bars), npy_files[0])
        return bars

    # Look for .dbn files
    dbn_files = list(data_path.glob("*.dbn*"))
    if dbn_files:
        try:
            from flof_matrix.data.databento_adapter import DataBentoAdapter
            adapter = DataBentoAdapter()
            store = adapter.load_dbn(dbn_files[0])
            if store is not None:
                logging.info("Loaded data from %s", dbn_files[0])
                # Convert DBNStore to BAR_DTYPE
                df = store.to_df()
                bars = np.zeros(len(df), dtype=BAR_DTYPE)
                bars["timestamp_ns"] = df.index.astype(np.int64)
                bars["open"] = df["open"].values
                bars["high"] = df["high"].values
                bars["low"] = df["low"].values
                bars["close"] = df["close"].values
                bars["volume"] = df["volume"].values
                return bars
        except Exception as e:
            logging.warning("Could not load .dbn file: %s", e)

    # Fallback: generate synthetic data on-the-fly
    logging.info("No data files found — generating synthetic ES data")
    logging.info("  Tip: run 'python scripts/download_data.py --start %s --end %s' first", start, end)

    sys.path.insert(0, str(Path(__file__).parent))
    from download_data import generate_synthetic_es
    filepath = generate_synthetic_es(start, end, data_dir)
    bars = np.load(str(filepath))
    logging.info("Generated and loaded %d bars", len(bars))
    return bars


def load_ticks(tick_path: str | None, data_dir: str) -> np.ndarray | None:
    """Load trade tick data from .dbn.zst file.

    If tick_path is None, auto-discovers *trades*.dbn.zst in data_dir.
    """
    from flof_matrix.data.databento_adapter import DataBentoAdapter

    if tick_path:
        p = Path(tick_path)
        if not p.exists():
            logging.warning("Tick data file not found: %s", p)
            return None
    else:
        # Auto-discover trade tick files
        data_path = Path(data_dir)
        candidates = sorted(data_path.glob("*trades*.dbn.zst"))
        if not candidates:
            return None
        p = candidates[0]
        logging.info("Auto-discovered tick data: %s", p)

    adapter = DataBentoAdapter()
    ticks = adapter.load_trades(p)
    if ticks is not None:
        logging.info("Loaded %d trade ticks from %s", len(ticks), p)
    return ticks


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config_path = Path(args.config)
    if not config_path.exists():
        logging.error("Config file not found: %s", config_path)
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    logging.info("FLOF Matrix Backtest")
    logging.info("  Config: %s", args.config)
    logging.info("  Profile: %s", args.profile)
    logging.info("  Period: %s to %s", args.start, args.end)
    logging.info("  Fill Level: %d", args.fill_level)
    logging.info("  Engine: %s", args.engine)

    # Load data
    bars = load_data(args.data_dir, args.start, args.end)
    logging.info("  Bars loaded: %d", len(bars))

    # Load tick data (optional)
    ticks = load_ticks(args.tick_data, args.data_dir)
    if ticks is not None:
        logging.info("  Ticks loaded: %d", len(ticks))
    else:
        logging.info("  Ticks: none (synthetic injection)")

    if args.db_dsn:
        logging.info("  DB DSN: %s", args.db_dsn.split("@")[-1] if "@" in args.db_dsn else "(configured)")

    # Run backtest
    runner = BacktestRunner(
        config_path=str(config_path),
        profile=args.profile,
        instrument=args.instrument,
        fill_level=args.fill_level,
        db_dsn=args.db_dsn,
    )

    if args.engine == "nautilus":
        result = runner.run_nautilus(bars)
    else:
        result = runner.run(bars, ticks=ticks)
    runner.shutdown()

    # Save results
    result_path = output_dir / "backtest_result.json"
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)

    logging.info("Results saved to %s", result_path)
    logging.info("Backtest complete: %s", result)


if __name__ == "__main__":
    main()
