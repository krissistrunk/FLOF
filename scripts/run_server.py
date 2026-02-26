#!/usr/bin/env python3
"""Start the FLOF Matrix Command Center server."""

import argparse
import logging
import sys
import threading
from pathlib import Path

import numpy as np
import uvicorn


def run_initial_backtest(data_file: str | None = None, tick_data: str | None = None,
                         fill_level: int = 2, profile: str = "backtest"):
    """Run a backtest on startup to populate the dashboard."""
    from flof_matrix.nautilus.backtest_runner import BacktestRunner, BAR_DTYPE
    from flof_matrix.server.state import FlofState

    logger = logging.getLogger("startup")
    state = FlofState()

    config_path = Path("flof_matrix/config/flof_base.toml")
    data_dir = Path("data")

    # Find bar data
    bars = None
    if data_file:
        p = Path(data_file)
        if p.exists():
            bars = np.load(str(p))
            logger.info("Loaded %d bars from %s", len(bars), p)

    if bars is None and data_dir.exists():
        npy_files = sorted(data_dir.glob("*.npy"))
        if npy_files:
            bars = np.load(str(npy_files[0]))
            logger.info("Auto-loaded %d bars from %s", len(bars), npy_files[0])

    if bars is None:
        logger.warning("No bar data found in data/. Dashboard will be empty.")
        return

    # Load tick data if provided
    ticks = None
    if tick_data:
        from flof_matrix.data.databento_adapter import DataBentoAdapter
        adapter = DataBentoAdapter()
        ticks = adapter.load_trades(tick_data)
        if ticks is not None:
            logger.info("Loaded %d trade ticks from %s", len(ticks), tick_data)

    logger.info("Running startup backtest (%d bars, profile=%s, fill_level=%d)...", len(bars), profile, fill_level)

    runner = BacktestRunner(
        config_path=config_path,
        profile=profile,
        fill_level=fill_level,
    )
    strategy = runner.setup()
    state.strategy = strategy
    state.runner = runner

    results = runner.run(bars, ticks=ticks)

    logger.info(
        "Backtest complete: %d trades, PnL $%.0f, Win Rate %.1f%%, Equity $%.0f",
        results["trade_count"],
        results["total_pnl"],
        results["win_rate"] * 100,
        results["final_equity"],
    )


def main():
    parser = argparse.ArgumentParser(description="FLOF Matrix Command Center")
    parser.add_argument("--port", type=int, default=8015, help="Server port (default: 8015)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    parser.add_argument("--backtest", action="store_true", help="Run a backtest on startup to populate dashboard")
    parser.add_argument("--data", type=str, default=None, help="Path to .npy bar data file")
    parser.add_argument("--fill-level", type=int, default=2, help="Fill level 1/2/3 (default: 2)")
    parser.add_argument("--profile", type=str, default="backtest", help="Config profile (default: backtest)")
    parser.add_argument("--tick-data", type=str, default=None, help="Path to .dbn.zst trade tick file")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.backtest:
        run_initial_backtest(data_file=args.data, tick_data=args.tick_data,
                             fill_level=args.fill_level, profile=args.profile)

    print(f"\n  FLOF Matrix Command Center")
    print(f"  API:       http://{args.host}:{args.port}")
    print(f"  WebSocket: ws://{args.host}:{args.port}/ws")
    print(f"  Docs:      http://{args.host}:{args.port}/docs\n")

    uvicorn.run(
        "flof_matrix.server.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
