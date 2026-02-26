#!/usr/bin/env python3
"""Analyze shadow scoring backtest results.

Reads backtest results with shadow_gates_failed tags and computes:
- Overall split: clean trades vs shadow-rejected trades
- Per-gate marginal value (avg R of rejected vs clean)
- Gate ranking sorted by marginal value
- Multi-gate analysis

Usage:
    python scripts/analyze_shadow.py --results results/backtest_result.json
    python scripts/analyze_shadow.py --results results/backtest_result.json --out shadow_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Analyze shadow scoring backtest results")
    parser.add_argument("--results", type=str, required=True,
                        help="Path to backtest_result.json")
    parser.add_argument("--out", type=str, default=None,
                        help="Optional output path for JSON report")
    return parser.parse_args()


def load_trades(results_path: str) -> list[dict]:
    """Load trades from backtest result JSON."""
    with open(results_path) as f:
        data = json.load(f)

    trades = data.get("trades", [])
    if not trades:
        print("ERROR: No trades found in results file.")
        print("  Make sure you ran the backtest with --shadow flag.")
        sys.exit(1)

    # Check if shadow data is present
    has_shadow = any(t.get("shadow_gates_failed") for t in trades)
    if not has_shadow:
        print("WARNING: No trades have shadow_gates_failed populated.")
        print("  This may be a normal (non-shadow) backtest result.")

    return trades


def compute_stats(trades: list[dict]) -> dict:
    """Compute PnL stats for a group of trades."""
    if not trades:
        return {"count": 0, "pnl": 0.0, "avg_r": 0.0, "win_rate": 0.0, "wins": 0, "losses": 0}

    pnl = sum(t.get("pnl_dollars", 0) or 0 for t in trades)
    r_values = [t.get("pnl_r_multiple", 0) or 0 for t in trades]
    avg_r = sum(r_values) / len(r_values) if r_values else 0.0
    wins = sum(1 for r in r_values if r > 0)
    losses = sum(1 for r in r_values if r < 0)
    total_decided = wins + losses
    win_rate = wins / total_decided if total_decided > 0 else 0.0

    return {
        "count": len(trades),
        "pnl": round(pnl, 2),
        "avg_r": round(avg_r, 3),
        "win_rate": round(win_rate, 4),
        "wins": wins,
        "losses": losses,
    }


def analyze(trades: list[dict]) -> dict:
    """Run full shadow analysis."""
    # Split into clean vs shadow-rejected
    clean = [t for t in trades if not t.get("shadow_gates_failed")]
    shadow = [t for t in trades if t.get("shadow_gates_failed")]

    # Closed trades only (have exit data)
    clean_closed = [t for t in clean if t.get("exit_price") is not None]
    shadow_closed = [t for t in shadow if t.get("exit_price") is not None]
    all_closed = clean_closed + shadow_closed

    overall = {
        "total_trades": len(trades),
        "clean_trades": len(clean),
        "shadow_rejected_trades": len(shadow),
        "clean_closed": compute_stats(clean_closed),
        "shadow_closed": compute_stats(shadow_closed),
        "all_closed": compute_stats(all_closed),
    }

    # Per-gate analysis
    gate_trades: dict[str, list[dict]] = defaultdict(list)
    for t in shadow_closed:
        for gate in t.get("shadow_gates_failed", []):
            gate_trades[gate].append(t)

    clean_avg_r = overall["clean_closed"]["avg_r"]

    gate_analysis = {}
    for gate, g_trades in sorted(gate_trades.items()):
        stats = compute_stats(g_trades)
        marginal_r = stats["avg_r"] - clean_avg_r
        # Positive marginal = gate rejects worse trades = gate is valuable
        # Negative marginal = gate rejects better trades = gate is costly
        if abs(marginal_r) < 0.05:
            verdict = "NEUTRAL"
        elif marginal_r < 0:
            # Rejected trades perform BETTER than clean → gate is costly
            verdict = "COSTLY"
        else:
            # Rejected trades perform WORSE than clean → gate is valuable
            verdict = "VALUABLE"

        gate_analysis[gate] = {
            **stats,
            "marginal_r": round(marginal_r, 3),
            "verdict": verdict,
        }

    # Sort by marginal value (most valuable first = most negative avg_r for rejects)
    gate_ranking = sorted(gate_analysis.items(), key=lambda x: -x[1]["marginal_r"])

    # Multi-gate analysis
    single_gate = [t for t in shadow_closed if len(t.get("shadow_gates_failed", [])) == 1]
    multi_gate = [t for t in shadow_closed if len(t.get("shadow_gates_failed", [])) >= 2]

    multi_gate_analysis = {
        "single_gate_rejects": compute_stats(single_gate),
        "multi_gate_rejects": compute_stats(multi_gate),
    }

    return {
        "overall": overall,
        "gate_analysis": dict(gate_ranking),
        "multi_gate_analysis": multi_gate_analysis,
    }


def print_report(report: dict) -> None:
    """Print formatted report to stdout."""
    overall = report["overall"]

    print("=" * 72)
    print("  SHADOW SCORING ANALYSIS")
    print("=" * 72)
    print()

    # Overall split
    print(f"  Total trades executed:  {overall['total_trades']}")
    print(f"  Clean (all gates pass): {overall['clean_trades']}")
    print(f"  Shadow-rejected:        {overall['shadow_rejected_trades']}")
    print()

    print("-" * 72)
    print(f"  {'Group':<22} {'Count':>6} {'PnL':>10} {'Avg R':>8} {'WR':>7} {'W/L':>8}")
    print("-" * 72)

    for label, key in [("Clean trades", "clean_closed"),
                       ("Shadow-rejected", "shadow_closed"),
                       ("All trades", "all_closed")]:
        s = overall[key]
        wl = f"{s['wins']}/{s['losses']}"
        print(f"  {label:<22} {s['count']:>6} {s['pnl']:>10.2f} {s['avg_r']:>8.3f} {s['win_rate']:>6.1%} {wl:>8}")

    print()
    print("=" * 72)
    print("  PER-GATE MARGINAL VALUE")
    print("  (marginal_r = gate_rejected_avg_r - clean_avg_r)")
    print("  Positive = gate rejects worse trades (VALUABLE)")
    print("  Negative = gate rejects better trades (COSTLY)")
    print("=" * 72)
    print()
    print(f"  {'Gate':<30} {'Count':>6} {'Avg R':>8} {'Marg R':>8} {'WR':>7} {'Verdict':<10}")
    print("-" * 72)

    for gate, stats in report["gate_analysis"].items():
        print(f"  {gate:<30} {stats['count']:>6} {stats['avg_r']:>8.3f} "
              f"{stats['marginal_r']:>+8.3f} {stats['win_rate']:>6.1%} {stats['verdict']:<10}")

    print()
    print("=" * 72)
    print("  MULTI-GATE ANALYSIS")
    print("=" * 72)
    print()
    multi = report["multi_gate_analysis"]
    for label, key in [("Single-gate rejects", "single_gate_rejects"),
                       ("Multi-gate rejects (2+)", "multi_gate_rejects")]:
        s = multi[key]
        if s["count"] > 0:
            wl = f"{s['wins']}/{s['losses']}"
            print(f"  {label:<26} {s['count']:>6} trades  Avg R: {s['avg_r']:>+.3f}  WR: {s['win_rate']:.1%}  {wl}")
        else:
            print(f"  {label:<26}      0 trades")

    print()
    print("=" * 72)


def main():
    args = parse_args()

    results_path = Path(args.results)
    if not results_path.exists():
        print(f"ERROR: Results file not found: {results_path}")
        sys.exit(1)

    trades = load_trades(str(results_path))
    report = analyze(trades)
    print_report(report)

    if args.out:
        out_path = Path(args.out)
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"  JSON report saved to: {out_path}")
        print()


if __name__ == "__main__":
    main()
