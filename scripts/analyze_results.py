#!/usr/bin/env python3
"""Analyze FLOF Matrix backtest results.

Usage:
    python scripts/analyze_results.py --results results/backtest_result.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_args():
    parser = argparse.ArgumentParser(description="Analyze FLOF Matrix backtest results")
    parser.add_argument("--results", type=str, default="results/backtest_result.json",
                        help="Path to results JSON")
    return parser.parse_args()


def analyze(results: dict) -> dict:
    """Compute post-backtest analytics."""
    trades = results.get("trades", [])
    total = len(trades)

    if total == 0:
        return {
            "total_trades": 0,
            "message": "No trades executed in backtest period",
            "bars_processed": results.get("bars_processed", 0),
            "fill_level": results.get("fill_level", "unknown"),
        }

    wins = [t for t in trades if t.get("pnl_dollars", 0) > 0]
    losses = [t for t in trades if t.get("pnl_dollars", 0) < 0]

    total_pnl = sum(t.get("pnl_dollars", 0) for t in trades)
    win_pnl = sum(t.get("pnl_dollars", 0) for t in wins) if wins else 0
    loss_pnl = sum(t.get("pnl_dollars", 0) for t in losses) if losses else 0

    r_values = [t.get("pnl_r_multiple", 0) for t in trades]
    avg_r = sum(r_values) / total if total > 0 else 0

    # Profit factor
    profit_factor = abs(win_pnl / loss_pnl) if loss_pnl != 0 else float("inf")

    # Sharpe approximation (daily returns needed for proper Sharpe)
    returns = [t.get("pnl_pct", 0) for t in trades]
    import numpy as np
    if len(returns) > 1:
        sharpe = np.mean(returns) / np.std(returns) * (252 ** 0.5) if np.std(returns) > 0 else 0
    else:
        sharpe = 0

    # Grade distribution
    grade_dist = {}
    for t in trades:
        g = t.get("grade", "unknown")
        grade_dist[g] = grade_dist.get(g, 0) + 1

    # Gate rejection analysis
    rejections = results.get("rejections", [])
    rejection_by_gate = {}
    for r in rejections:
        gate = r.get("rejection_gate", "unknown")
        rejection_by_gate[gate] = rejection_by_gate.get(gate, 0) + 1

    # Equity curve metrics
    max_drawdown = results.get("max_drawdown", 0)
    max_drawdown_pct = results.get("max_drawdown_pct", 0)
    final_equity = results.get("final_equity", 100_000)
    starting_equity = 100_000
    total_return_pct = (final_equity - starting_equity) / starting_equity if starting_equity > 0 else 0

    # Calmar ratio = annualized return / max drawdown
    equity_curve = results.get("equity_curve", [])
    if equity_curve and len(equity_curve) >= 2:
        ts_range_days = (equity_curve[-1][0] - equity_curve[0][0]) / (1e9 * 86400)
        annualized_return = total_return_pct * (252 / max(ts_range_days, 1))
    else:
        annualized_return = 0
    calmar = annualized_return / max_drawdown_pct if max_drawdown_pct > 0 else 0

    return {
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / total if total > 0 else 0,
        "total_pnl": total_pnl,
        "avg_r_multiple": avg_r,
        "profit_factor": profit_factor,
        "sharpe_approx": sharpe,
        "grade_distribution": grade_dist,
        "gate_rejections": rejection_by_gate,
        "bars_processed": results.get("bars_processed", 0),
        "fill_level": results.get("fill_level", "unknown"),
        "final_equity": final_equity,
        "max_drawdown": max_drawdown,
        "max_drawdown_pct": max_drawdown_pct,
        "calmar_ratio": calmar,
    }


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    results_path = Path(args.results)
    if not results_path.exists():
        logging.error("Results file not found: %s", results_path)
        sys.exit(1)

    with open(results_path) as f:
        results = json.load(f)

    analysis = analyze(results)

    print("\n" + "=" * 60)
    print("  FLOF Matrix — Backtest Analysis Report")
    print("=" * 60)
    print(f"  Bars processed:    {analysis['bars_processed']}")
    print(f"  Fill level:        {analysis['fill_level']}")
    print(f"  Total trades:      {analysis['total_trades']}")

    if analysis["total_trades"] > 0:
        print(f"  Win rate:          {analysis['win_rate']:.1%}")
        print(f"  Avg R-multiple:    {analysis['avg_r_multiple']:.2f}")
        print(f"  Profit factor:     {analysis['profit_factor']:.2f}")
        print(f"  Sharpe (approx):   {analysis['sharpe_approx']:.2f}")
        print(f"  Total PnL:         ${analysis['total_pnl']:,.2f}")
        print(f"  Final equity:      ${analysis.get('final_equity', 0):,.2f}")
        print(f"  Max drawdown:      ${analysis.get('max_drawdown', 0):,.2f} ({analysis.get('max_drawdown_pct', 0):.2%})")
        print(f"  Calmar ratio:      {analysis.get('calmar_ratio', 0):.2f}")
        print(f"\n  Grade Distribution:")
        for grade, count in sorted(analysis["grade_distribution"].items()):
            print(f"    {grade}: {count}")
        if analysis["gate_rejections"]:
            print(f"\n  Gate Rejections:")
            for gate, count in sorted(analysis["gate_rejections"].items()):
                print(f"    {gate}: {count}")
    else:
        print(f"  {analysis.get('message', 'No trades')}")

    print("=" * 60 + "\n")

    # Save analysis
    output_path = results_path.parent / "analysis.json"
    with open(output_path, "w") as f:
        json.dump(analysis, f, indent=2, default=str)
    print(f"Analysis saved to {output_path}")


if __name__ == "__main__":
    main()
