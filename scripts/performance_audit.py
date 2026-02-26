#!/usr/bin/env python3
"""Performance audit helper for FLOF strategy quality diagnostics.

This script gives a "why are results bad?" overview by combining:
1) Strategy configuration pressure points (gates, risk limits, OF thresholds)
2) Backtest outputs (trades + gate rejection distribution), when provided.

Usage:
    python scripts/performance_audit.py \
      --config flof_matrix/config/flof_base.toml \
      --profile futures \
      --results results/backtest_result.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from flof_matrix.config.config_manager import ConfigManager


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit FLOF performance bottlenecks")
    p.add_argument("--config", default="flof_matrix/config/flof_base.toml", help="Path to base TOML")
    p.add_argument("--profile", default="futures", help="Profile override name")
    p.add_argument("--instrument", default=None, help="Optional instrument override")
    p.add_argument("--results", default=None, help="Optional backtest JSON path")
    p.add_argument(
        "--top-gates",
        type=int,
        default=10,
        help="How many top rejection gates to print when --results is provided",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Optional path to write machine-readable audit JSON",
    )
    return p.parse_args()


def load_config(path: str, profile: str, instrument: str | None) -> ConfigManager:
    cfg = ConfigManager()
    cfg.load(path, profile, instrument)
    return cfg


def config_pressure_points(cfg: ConfigManager) -> list[tuple[str, str, str]]:
    """Return (severity, area, finding)."""
    findings: list[tuple[str, str, str]] = []

    if cfg.get("gates.g2_inducement_required", True):
        findings.append(("HIGH", "Entry Gates", "G2 inducement is required; unswept POIs are hard-rejected."))

    tier1_min = cfg.get("scoring.tier1.gate_minimum", 7)
    if tier1_min >= 7:
        findings.append((
            "HIGH",
            "Scoring",
            f"Tier-1 minimum is {tier1_min}/10 before Tier-2/3 can help; this can choke trade count.",
        ))

    if cfg.get("gates.g3_chop_detector_enabled", True):
        chop_ratio = cfg.get("gates.g3_chop_va_atr_ratio", 1.5)
        findings.append(("MED", "Entry Gates", f"Chop detector enabled at VA/ATR<{chop_ratio}; directional entries blocked in ranges."))

    if cfg.is_toggle_enabled("T10"):
        findings.append(("MED", "Timing", "Killzone gate is enabled; off-hours opportunities are ignored."))

    absorb_vol = cfg.get("order_flow.absorption_volume_threshold", 2.0)
    absorb_disp = cfg.get("order_flow.absorption_displacement_max", 0.3)
    whale_mult = cfg.get("order_flow.whale_print_multiplier", 5.0)
    findings.append((
        "MED",
        "Order Flow",
        (
            "Order-flow confirmation is strict "
            f"(absorption>{absorb_vol}x expected volume, displacement<{absorb_disp} ATR, whale>{whale_mult}x avg)."
        ),
    ))

    max_orders_per_min = cfg.get("risk_overlord.max_orders_per_minute", 3)
    max_losses = cfg.get("risk_overlord.max_consecutive_losses", 3)
    dd_limit = cfg.get("risk_overlord.max_daily_drawdown_pct", -0.03)
    findings.append((
        "MED",
        "Risk Controls",
        (
            f"RiskOverlord throttles at {max_orders_per_min}/min, lock after {max_losses} losses, "
            f"and flatten around {dd_limit:.1%} daily drawdown."
        ),
    ))

    if cfg.is_toggle_enabled("T48"):
        findings.append(("MED", "Trade Management", "T48 toxicity exit is ON; adverse flow can cut runners early."))

    return findings


def analyze_results(results: dict) -> list[str]:
    lines: list[str] = []
    trades = results.get("trades", [])
    rejections = results.get("rejections", [])

    lines.append(f"Trades: {len(trades)}")
    lines.append(f"Rejections: {len(rejections)}")

    if rejections:
        by_gate = Counter(r.get("rejection_gate", "unknown") for r in rejections)
        lines.append("Top rejection gates:")
        for gate, cnt in by_gate.most_common(8):
            lines.append(f"  - {gate}: {cnt}")

    if trades:
        win_rate = sum(1 for t in trades if t.get("pnl_dollars", 0) > 0) / len(trades)
        avg_r = mean(t.get("pnl_r_multiple", 0.0) for t in trades)
        grades = Counter(t.get("grade", "unknown") for t in trades)
        lines.append(f"Win rate: {win_rate:.1%}")
        lines.append(f"Average R: {avg_r:.2f}")
        lines.append("Grade mix:")
        for g, c in grades.most_common():
            lines.append(f"  - {g}: {c}")

    return lines


def gate_funnel(results: dict) -> list[dict]:
    """Build a compact funnel view from rejection/trade data."""
    rejections = results.get("rejections", [])
    trades = results.get("trades", [])
    by_gate = Counter(r.get("rejection_gate", "unknown") for r in rejections)

    families = {
        "G1_premium_discount": "G1 premium/discount",
        "G2_inducement": "G2 inducement",
        "G3_chop_detector": "G3 chop detector",
        "T1_gate_minimum": "Tier-1 minimum",
        "grade_C": "Grade threshold",
        "OF_gate_rejection_block": "Order-flow RB gate",
    }

    total_candidates = len(rejections) + len(trades)
    rows: list[dict] = []

    for raw_name, label in families.items():
        count = by_gate.get(raw_name, 0)
        rows.append(
            {
                "stage": label,
                "count": count,
                "pct_of_candidates": (count / total_candidates) if total_candidates > 0 else 0.0,
            }
        )

    portfolio_like = sum(
        c
        for gate, c in by_gate.items()
        if gate not in families and any(k in gate.lower() for k in ["portfolio", "risk", "drawdown", "loss", "exposure"])
    )
    rows.append(
        {
            "stage": "Portfolio/Risk gates",
            "count": portfolio_like,
            "pct_of_candidates": (portfolio_like / total_candidates) if total_candidates > 0 else 0.0,
        }
    )
    rows.append(
        {
            "stage": "Executed trades",
            "count": len(trades),
            "pct_of_candidates": (len(trades) / total_candidates) if total_candidates > 0 else 0.0,
        }
    )
    return rows


def biggest_bottleneck(results: dict) -> tuple[str, int]:
    rejections = results.get("rejections", [])
    if not rejections:
        return "none", 0
    gate, count = Counter(r.get("rejection_gate", "unknown") for r in rejections).most_common(1)[0]
    return gate, count


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config, args.profile, args.instrument)

    print("=" * 72)
    print("FLOF Performance Audit Overview")
    print("=" * 72)
    print("\nConfiguration pressure points")
    print("-" * 72)

    pressure = config_pressure_points(cfg)
    for severity, area, finding in pressure:
        print(f"[{severity}] {area}: {finding}")

    audit_payload: dict = {
        "config_pressure_points": [
            {"severity": severity, "area": area, "finding": finding}
            for severity, area, finding in pressure
        ],
        "results_summary": None,
        "gate_funnel": None,
        "biggest_bottleneck": None,
    }

    if args.results:
        results_path = Path(args.results)
        print("\nBacktest result diagnostics")
        print("-" * 72)
        if not results_path.exists():
            print(f"Results file not found: {results_path}")
        else:
            with results_path.open() as f:
                results = json.load(f)

            summary = analyze_results(results)
            for line in summary:
                print(line)
            audit_payload["results_summary"] = summary

            top_gate, top_count = biggest_bottleneck(results)
            audit_payload["biggest_bottleneck"] = {"gate": top_gate, "count": top_count}
            print(f"\nBiggest bottleneck: {top_gate} ({top_count})")

            funnel = gate_funnel(results)
            audit_payload["gate_funnel"] = funnel
            print("\nApproximate gate funnel")
            print("-" * 72)
            for row in funnel:
                print(f"{row['stage']:<22} {row['count']:>6}  ({row['pct_of_candidates']:.1%})")

            by_gate = Counter(r.get("rejection_gate", "unknown") for r in results.get("rejections", []))
            if by_gate:
                print("\nTop rejection gates")
                print("-" * 72)
                for gate, count in by_gate.most_common(max(args.top_gates, 1)):
                    print(f"{gate:<35} {count:>6}")
    else:
        print("\nBacktest result diagnostics")
        print("-" * 72)
        print("No --results provided. Pass a backtest_result.json to audit gate funnel.")

    print("\nRecommended next checks")
    print("-" * 72)
    print("1) Measure gate funnel: G1/G2/G3/Tier1/Portfolio/Risk rejection percentages.")
    print("2) Compare baseline vs relaxed config (tier1 gate 7->6, optional G2 OFF) with same data.")
    print("3) Verify tick density; sparse synthetic ticks can suppress order-flow confirmation.")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            json.dump(audit_payload, f, indent=2)
        print(f"\nAudit JSON saved to {out_path}")


if __name__ == "__main__":
    main()
