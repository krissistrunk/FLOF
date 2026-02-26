#!/usr/bin/env python3
"""Plot FLOF Matrix backtest results.

Usage:
    python scripts/plot_results.py --results results/backtest_result.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_args():
    parser = argparse.ArgumentParser(description="Plot FLOF Matrix backtest results")
    parser.add_argument("--results", type=str, default="results/backtest_result.json",
                        help="Path to results JSON")
    parser.add_argument("--output", type=str, default="results/plots",
                        help="Output directory for PNG plots")
    return parser.parse_args()


def plot_equity_curve(equity_curve: list, output_dir: Path) -> None:
    """1. Equity curve line chart."""
    import matplotlib.pyplot as plt

    if not equity_curve:
        return

    timestamps = [datetime.utcfromtimestamp(ts / 1e9) for ts, _ in equity_curve]
    equity = [eq for _, eq in equity_curve]

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(timestamps, equity, color="#2196F3", linewidth=1.5)
    ax.set_title("Equity Curve", fontsize=14, fontweight="bold")
    ax.set_ylabel("Equity ($)")
    ax.set_xlabel("Time")
    ax.grid(True, alpha=0.3)
    ax.axhline(y=100_000, color="gray", linestyle="--", alpha=0.5, label="Starting Equity")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / "equity_curve.png", dpi=150)
    plt.close(fig)


def plot_drawdown(equity_curve: list, output_dir: Path) -> None:
    """2. Drawdown underwater chart."""
    import matplotlib.pyplot as plt

    if not equity_curve:
        return

    timestamps = [datetime.utcfromtimestamp(ts / 1e9) for ts, _ in equity_curve]
    equity = np.array([eq for _, eq in equity_curve])

    peak = np.maximum.accumulate(equity)
    drawdown_pct = (equity - peak) / peak * 100

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.fill_between(timestamps, drawdown_pct, 0, color="#F44336", alpha=0.4)
    ax.plot(timestamps, drawdown_pct, color="#F44336", linewidth=1)
    ax.set_title("Drawdown", fontsize=14, fontweight="bold")
    ax.set_ylabel("Drawdown (%)")
    ax.set_xlabel("Time")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_dir / "drawdown.png", dpi=150)
    plt.close(fig)


def plot_grade_distribution(trades: list, output_dir: Path) -> None:
    """3. Grade distribution bar chart."""
    import matplotlib.pyplot as plt

    if not trades:
        return

    grade_counts = {}
    for t in trades:
        g = t.get("grade", "unknown")
        grade_counts[g] = grade_counts.get(g, 0) + 1

    grade_order = ["A+", "A", "B", "C"]
    grades = [g for g in grade_order if g in grade_counts]
    counts = [grade_counts[g] for g in grades]
    colors = {"A+": "#4CAF50", "A": "#8BC34A", "B": "#FF9800", "C": "#F44336"}
    bar_colors = [colors.get(g, "#9E9E9E") for g in grades]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(grades, counts, color=bar_colors)
    ax.set_title("Grade Distribution", fontsize=14, fontweight="bold")
    ax.set_ylabel("Trade Count")
    ax.set_xlabel("Grade")
    for i, (g, c) in enumerate(zip(grades, counts)):
        ax.text(i, c + 0.5, str(c), ha="center", fontweight="bold")
    fig.tight_layout()
    fig.savefig(output_dir / "grade_distribution.png", dpi=150)
    plt.close(fig)


def plot_trade_scatter(trades: list, output_dir: Path) -> None:
    """4. Trade entry/exit scatter on price."""
    import matplotlib.pyplot as plt

    closed_trades = [t for t in trades if t.get("exit_price", 0) != 0]
    if not closed_trades:
        return

    fig, ax = plt.subplots(figsize=(12, 6))

    for t in closed_trades:
        entry = t["entry_price"]
        exit_p = t["exit_price"]
        pnl = t.get("pnl_dollars", 0)
        color = "#4CAF50" if pnl > 0 else "#F44336"
        idx = closed_trades.index(t)

        ax.scatter(idx, entry, color="#2196F3", marker="^" if t["direction"] == "LONG" else "v", s=60, zorder=3)
        ax.scatter(idx, exit_p, color=color, marker="o", s=40, zorder=3)
        ax.plot([idx, idx], [entry, exit_p], color=color, alpha=0.5, linewidth=1)

    ax.set_title("Trade Entry/Exit Scatter", fontsize=14, fontweight="bold")
    ax.set_ylabel("Price")
    ax.set_xlabel("Trade #")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_dir / "trade_scatter.png", dpi=150)
    plt.close(fig)


def plot_gate_rejections(rejections: list, output_dir: Path) -> None:
    """5. Gate rejection breakdown."""
    import matplotlib.pyplot as plt

    if not rejections:
        return

    gate_counts = {}
    for r in rejections:
        gate = r.get("rejection_gate", "unknown")
        gate_counts[gate] = gate_counts.get(gate, 0) + 1

    gates = sorted(gate_counts.keys(), key=lambda g: gate_counts[g], reverse=True)
    counts = [gate_counts[g] for g in gates]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.barh(gates, counts, color="#9C27B0", alpha=0.7)
    ax.set_title("Gate Rejection Breakdown", fontsize=14, fontweight="bold")
    ax.set_xlabel("Rejection Count")
    for i, c in enumerate(counts):
        ax.text(c + 0.5, i, str(c), va="center")
    fig.tight_layout()
    fig.savefig(output_dir / "gate_rejections.png", dpi=150)
    plt.close(fig)


def plot_pnl_distribution(trades: list, output_dir: Path) -> None:
    """6. PnL distribution histogram."""
    import matplotlib.pyplot as plt

    pnls = [t.get("pnl_dollars", 0) for t in trades if t.get("exit_price", 0) != 0]
    if not pnls:
        return

    fig, ax = plt.subplots(figsize=(10, 5))
    colors = ["#4CAF50" if p > 0 else "#F44336" for p in sorted(pnls)]
    ax.hist(pnls, bins=min(30, max(5, len(pnls) // 3)), color="#2196F3", alpha=0.7, edgecolor="white")
    ax.axvline(x=0, color="red", linestyle="--", alpha=0.7)
    ax.axvline(x=np.mean(pnls), color="#4CAF50", linestyle="--", alpha=0.7, label=f"Mean: ${np.mean(pnls):.0f}")
    ax.set_title("PnL Distribution", fontsize=14, fontweight="bold")
    ax.set_xlabel("PnL ($)")
    ax.set_ylabel("Frequency")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / "pnl_distribution.png", dpi=150)
    plt.close(fig)


def main():
    args = parse_args()

    results_path = Path(args.results)
    if not results_path.exists():
        print(f"Results file not found: {results_path}")
        sys.exit(1)

    with open(results_path) as f:
        results = json.load(f)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    trades = results.get("trades", [])
    rejections = results.get("rejections", [])
    equity_curve = results.get("equity_curve", [])

    try:
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend
    except ImportError:
        print("matplotlib not installed. Install with: pip install matplotlib")
        sys.exit(1)

    plot_equity_curve(equity_curve, output_dir)
    plot_drawdown(equity_curve, output_dir)
    plot_grade_distribution(trades, output_dir)
    plot_trade_scatter(trades, output_dir)
    plot_gate_rejections(rejections, output_dir)
    plot_pnl_distribution(trades, output_dir)

    print(f"Plots saved to {output_dir}/")
    for f in sorted(output_dir.glob("*.png")):
        print(f"  {f.name}")


if __name__ == "__main__":
    main()
