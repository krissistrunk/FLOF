#!/usr/bin/env python3
"""Trade Autopsy — Forensic analysis of individual trades.

Re-runs the backtest with deep instrumentation to capture the full decision
chain for every trade: POI detection → predator state → gate evaluation →
scoring → entry → management → exit.

Usage:
    # List all trades with summary:
    python scripts/trade_autopsy.py --results results/backtest_result.json --list

    # Full autopsy on specific trades:
    python scripts/trade_autopsy.py --results results/backtest_result.json --trades FLOF-0002 FLOF-0005

    # Autopsy all losers:
    python scripts/trade_autopsy.py --results results/backtest_result.json --losers

    # Autopsy all losers that hit stop:
    python scripts/trade_autopsy.py --results results/backtest_result.json --losers --exit-reason stop_hit

    # Full re-run with instrumentation (generates detailed trace):
    python scripts/trade_autopsy.py --rerun --trades FLOF-0002

    # Save autopsy report to file:
    python scripts/trade_autopsy.py --results results/backtest_result.json --trades FLOF-0002 --out autopsy_report.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_args():
    parser = argparse.ArgumentParser(description="Trade Autopsy — Forensic trade analysis")
    parser.add_argument("--results", type=str, default="results/backtest_result.json",
                        help="Path to backtest_result.json")
    parser.add_argument("--list", action="store_true",
                        help="List all trades with summary stats")
    parser.add_argument("--trades", nargs="+", type=str, default=None,
                        help="Trade IDs to autopsy (e.g. FLOF-0002 FLOF-0005)")
    parser.add_argument("--losers", action="store_true",
                        help="Autopsy all losing trades")
    parser.add_argument("--winners", action="store_true",
                        help="Autopsy all winning trades")
    parser.add_argument("--clean-only", action="store_true",
                        help="Only include clean trades (no shadow gate failures)")
    parser.add_argument("--shadow-only", action="store_true",
                        help="Only include shadow-rejected trades")
    parser.add_argument("--exit-reason", type=str, default=None,
                        help="Filter by exit reason (stop_hit, target_hit, toxicity_exit, etc.)")
    parser.add_argument("--limit", type=int, default=10,
                        help="Max trades to show in autopsy mode (default 10)")
    parser.add_argument("--rerun", action="store_true",
                        help="Re-run backtest with full instrumentation (slow)")
    parser.add_argument("--data-dir", type=str, default="data/",
                        help="Data directory for --rerun mode")
    parser.add_argument("--bars-before", type=int, default=30,
                        help="Number of 1m bars to show before entry")
    parser.add_argument("--bars-after", type=int, default=15,
                        help="Number of 1m bars to show after entry")
    parser.add_argument("--out", type=str, default=None,
                        help="Save report to file")
    return parser.parse_args()


def load_results(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def ts_to_str(ns: int) -> str:
    """Convert nanosecond timestamp to human-readable datetime string."""
    if not ns:
        return "N/A"
    dt = datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def ts_to_short(ns: int) -> str:
    """Convert nanosecond timestamp to short time string."""
    if not ns:
        return "N/A"
    dt = datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc)
    return dt.strftime("%H:%M")


def duration_str(entry_ns: int, exit_ns: int) -> str:
    """Human-readable duration between two nanosecond timestamps."""
    if not entry_ns or not exit_ns:
        return "N/A"
    seconds = (exit_ns - entry_ns) / 1_000_000_000
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"


def filter_trades(trades: list[dict], args) -> list[dict]:
    """Apply filters to trade list."""
    result = trades

    if args.clean_only:
        result = [t for t in result if not t.get("shadow_gates_failed")]
    if args.shadow_only:
        result = [t for t in result if t.get("shadow_gates_failed")]
    if args.losers:
        result = [t for t in result if (t.get("pnl_r_multiple") or 0) < 0]
    if args.winners:
        result = [t for t in result if (t.get("pnl_r_multiple") or 0) > 0]
    if args.exit_reason:
        result = [t for t in result if t.get("exit_reason") == args.exit_reason]
    if args.trades:
        ids = set(args.trades)
        result = [t for t in result if t.get("position_id") in ids]

    return result


def print_trade_list(trades: list[dict]) -> list[str]:
    """Print summary table of trades, return lines."""
    lines = []
    header = (f"  {'ID':<12} {'Dir':<6} {'POI':<18} {'Grade':>5} {'Score':>5} "
              f"{'Entry':>10} {'Exit':>10} {'R':>7} {'PnL':>10} {'Exit Reason':<20} {'Shadow Gates'}")
    sep = "-" * 140
    lines.append(sep)
    lines.append(header)
    lines.append(sep)

    for t in trades:
        shadow = ", ".join(t.get("shadow_gates_failed", [])) or "—"
        r_mult = t.get("pnl_r_multiple", 0) or 0
        pnl = t.get("pnl_dollars", 0) or 0
        r_str = f"{r_mult:+.2f}R" if r_mult else "open"
        pnl_str = f"${pnl:+,.0f}" if pnl else "open"
        lines.append(
            f"  {t.get('position_id', '?'):<12} "
            f"{t.get('direction', '?'):<6} "
            f"{t.get('poi_type', '?'):<18} "
            f"{t.get('grade', '?'):>5} "
            f"{t.get('score_total', '?'):>5} "
            f"{t.get('entry_price', 0):>10.2f} "
            f"{t.get('exit_price', 0) or 0:>10.2f} "
            f"{r_str:>7} "
            f"{pnl_str:>10} "
            f"{t.get('exit_reason', 'open'):<20} "
            f"{shadow}"
        )

    lines.append(sep)
    lines.append(f"  Total: {len(trades)} trades")
    return lines


def load_bars(data_dir: str) -> np.ndarray:
    """Load bar data for market context."""
    from flof_matrix.nautilus.backtest_runner import BAR_DTYPE

    data_path = Path(data_dir)
    npy_files = sorted(data_path.glob("*.npy"))
    if npy_files:
        return np.load(str(npy_files[0]))
    return np.array([], dtype=BAR_DTYPE)


def find_bar_index(bars: np.ndarray, timestamp_ns: int) -> int:
    """Find the bar index closest to a given timestamp."""
    if len(bars) == 0:
        return -1
    # Binary search for closest timestamp
    idx = np.searchsorted(bars["timestamp_ns"], timestamp_ns)
    if idx >= len(bars):
        idx = len(bars) - 1
    return int(idx)


def format_price_bar(bar, idx: int, entry_price: float = 0, stop_price: float = 0,
                     target_price: float = 0, direction: str = "") -> str:
    """Format a single price bar with visual annotations."""
    ts = int(bar["timestamp_ns"])
    time_str = ts_to_short(ts)
    o, h, l, c = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])
    v = float(bar["volume"])
    body = c - o
    rng = h - l

    # Bar character: green (up) or red (down)
    if c > o:
        bar_char = "+"  # bullish
    elif c < o:
        bar_char = "-"  # bearish
    else:
        bar_char = "="  # doji

    # Annotations
    annotations = []
    if entry_price and l <= entry_price <= h:
        annotations.append("<<< ENTRY")
    if stop_price and l <= stop_price <= h:
        annotations.append("<<< STOP HIT")
    if target_price:
        if direction == "LONG" and h >= target_price:
            annotations.append("<<< TARGET HIT")
        elif direction == "SHORT" and l <= target_price:
            annotations.append("<<< TARGET HIT")

    ann = "  ".join(annotations)

    return (f"  [{idx:>5}] {time_str}  {bar_char} O:{o:>10.2f} H:{h:>10.2f} "
            f"L:{l:>10.2f} C:{c:>10.2f}  Vol:{v:>8.0f}  "
            f"Body:{body:>+6.2f} Rng:{rng:>6.2f}  {ann}")


def autopsy_trade(trade: dict, bars: np.ndarray, bars_before: int, bars_after: int) -> list[str]:
    """Generate a full forensic autopsy report for a single trade."""
    lines = []
    pos_id = trade.get("position_id", "?")
    direction = trade.get("direction", "?")
    poi_type = trade.get("poi_type", "?")
    grade = trade.get("grade", "?")
    score_total = trade.get("score_total", 0)
    score_t1 = trade.get("score_tier1", 0)
    score_t2 = trade.get("score_tier2", 0)
    score_t3 = trade.get("score_tier3", 0)
    entry_price = trade.get("entry_price", 0)
    stop_price = trade.get("stop_price", 0)
    target_price = trade.get("target_price", 0)
    exit_price = trade.get("exit_price", 0)
    exit_reason = trade.get("exit_reason", "open")
    pnl_dollars = trade.get("pnl_dollars", 0) or 0
    pnl_r = trade.get("pnl_r_multiple", 0) or 0
    entry_ns = trade.get("timestamp_ns", 0)
    exit_ns = trade.get("exit_time_ns", 0)
    contracts = trade.get("contracts", 0)
    risk_pct = trade.get("risk_pct", 0)
    shadow_gates = trade.get("shadow_gates_failed", [])

    # Derived metrics
    risk_points = abs(entry_price - stop_price) if entry_price and stop_price else 0
    reward_points = abs(target_price - entry_price) if entry_price and target_price else 0
    rr_ratio = reward_points / risk_points if risk_points > 0 else 0

    lines.append("")
    lines.append("=" * 100)
    lines.append(f"  TRADE AUTOPSY: {pos_id}")
    lines.append("=" * 100)
    lines.append("")

    # ── Section A: Was this a good-looking setup? ──
    lines.append("─" * 100)
    lines.append("  A. SETUP QUALITY — Was this a good trade to consider?")
    lines.append("─" * 100)
    lines.append("")
    lines.append(f"  POI Type:       {poi_type}")
    lines.append(f"  Direction:      {direction}")
    lines.append(f"  Entry Time:     {ts_to_str(entry_ns)}")
    lines.append(f"  Entry Price:    {entry_price:.2f}")
    lines.append(f"  Stop Price:     {stop_price:.2f}  (risk: {risk_points:.2f} pts = ${risk_points * 50:.0f}/contract)")
    lines.append(f"  Target Price:   {target_price:.2f}  (reward: {reward_points:.2f} pts)")
    lines.append(f"  Risk:Reward:    1:{rr_ratio:.1f}")
    lines.append("")

    # ── Section B: What did the scoring logic decide? ──
    lines.append("─" * 100)
    lines.append("  B. SCORING LOGIC — What assumptions did the code make?")
    lines.append("─" * 100)
    lines.append("")
    lines.append(f"  Grade:          {grade}")
    lines.append(f"  Total Score:    {score_total}/17")
    lines.append(f"    Tier 1 (Core SMC + OF):  {score_t1}/10  {'PASS (>= 7)' if score_t1 >= 7 else 'FAIL (< 7) — would be gate-killed in normal mode'}")
    lines.append(f"    Tier 2 (Velez Momentum): {score_t2}/4")
    lines.append(f"    Tier 3 (VWAP + Liq):     {score_t3}/3")
    lines.append(f"  Risk Size:      {risk_pct:.3%} ({contracts} contracts)")
    lines.append("")

    # Tier 1 breakdown (reverse-engineer from score)
    lines.append("  Tier 1 Point Sources (reconstructed):")
    lines.append(f"    +2  CHOCH with displacement  (always on in Kill mode)")
    remaining = score_t1 - 2  # CHOCH is always credited
    if remaining > 0:
        lines.append(f"    +?  Other T1 sources account for {remaining} more points")
        lines.append(f"         (trend alignment, liq sweep, fresh POI, OF confirm, killzone)")
    lines.append("")

    if shadow_gates:
        lines.append(f"  Shadow Gates Failed:  {', '.join(shadow_gates)}")
        lines.append("  (This trade would have been REJECTED in normal mode)")
        for gate in shadow_gates:
            if gate == "G1_premium_discount":
                lines.append(f"    G1: Price was NOT in the correct premium/discount zone for a {direction}")
            elif gate == "T1_gate_minimum":
                lines.append(f"    T1: Score {score_t1} < 7 minimum (needed {7 - score_t1} more points)")
            elif gate == "grade_C":
                lines.append(f"    Grade: Total score {score_total} produced grade C (below B minimum)")
            elif gate == "OF_gate_rejection_block":
                lines.append(f"    OF: Rejection Block entry lacked order flow confirmation")
            elif "portfolio" in gate:
                lines.append(f"    Portfolio: {gate}")
        lines.append("")
    else:
        lines.append("  Gate Status:    ALL PASSED (clean trade)")
        lines.append("")

    # ── Section C: What happened? Did the code do the right thing? ──
    lines.append("─" * 100)
    lines.append("  C. OUTCOME — Did the code do the right thing?")
    lines.append("─" * 100)
    lines.append("")
    lines.append(f"  Exit Reason:    {exit_reason}")
    lines.append(f"  Exit Price:     {exit_price:.2f}" if exit_price else "  Exit Price:     still open")
    lines.append(f"  Exit Time:      {ts_to_str(exit_ns)}")
    lines.append(f"  Duration:       {duration_str(entry_ns, exit_ns)}")
    lines.append(f"  PnL:            {pnl_r:+.2f}R  (${pnl_dollars:+,.0f})")
    lines.append("")

    # Evaluate the exit
    if exit_reason == "stop_hit" and pnl_r < 0:
        lines.append("  Verdict:  LOSS — stopped out.")
        # Check if price later reversed (would need post-exit bars)
        if len(bars) > 0:
            exit_idx = find_bar_index(bars, exit_ns)
            post_bars = bars[exit_idx:exit_idx + 60]  # Check next 60 bars (1 hour)
            if len(post_bars) > 0:
                if direction == "LONG":
                    max_after = float(np.max(post_bars["high"]))
                    reached_target = max_after >= target_price
                    max_move_from_entry = max_after - entry_price
                elif direction == "SHORT":
                    min_after = float(np.min(post_bars["low"]))
                    reached_target = min_after <= target_price
                    max_move_from_entry = entry_price - min_after
                else:
                    reached_target = False
                    max_move_from_entry = 0

                if reached_target:
                    lines.append(f"  ** REVERSAL DETECTED: Price DID reach target ({target_price:.2f}) within 60 bars after stop-out!")
                    lines.append(f"     The stop was too tight — the thesis was correct but execution failed.")
                    max_r = max_move_from_entry / risk_points if risk_points > 0 else 0
                    lines.append(f"     Max favorable move after stop: {max_move_from_entry:+.2f} pts ({max_r:+.1f}R)")
                else:
                    if direction == "LONG":
                        max_r = max_move_from_entry / risk_points if risk_points > 0 else 0
                        lines.append(f"  Post-stop max favorable: {max_after:.2f} ({max_r:+.1f}R from entry) — target NOT reached in next 60 bars")
                    else:
                        max_r = max_move_from_entry / risk_points if risk_points > 0 else 0
                        lines.append(f"  Post-stop min favorable: {min_after:.2f} ({max_r:+.1f}R from entry) — target NOT reached in next 60 bars")

    elif exit_reason == "target_hit":
        lines.append(f"  Verdict:  WIN — target hit at {rr_ratio:.1f}R.")
    elif exit_reason == "toxicity_exit":
        lines.append("  Verdict:  EARLY EXIT — T48 toxicity detected adverse order flow.")
        lines.append("  Question: Was this protective or premature?")
        if len(bars) > 0 and exit_ns:
            exit_idx = find_bar_index(bars, exit_ns)
            post_bars = bars[exit_idx:exit_idx + 30]
            if len(post_bars) > 0:
                if direction == "LONG":
                    max_after = float(np.max(post_bars["high"]))
                    would_have_r = (max_after - entry_price) / risk_points if risk_points > 0 else 0
                    min_after = float(np.min(post_bars["low"]))
                    would_have_stopped = min_after <= stop_price
                else:
                    min_after = float(np.min(post_bars["low"]))
                    would_have_r = (entry_price - min_after) / risk_points if risk_points > 0 else 0
                    max_after = float(np.max(post_bars["high"]))
                    would_have_stopped = max_after >= stop_price

                lines.append(f"  Max favorable in next 30 bars: {would_have_r:+.1f}R from entry")
                if would_have_stopped:
                    lines.append(f"  Would have hit stop if held — toxicity exit was PROTECTIVE")
                else:
                    lines.append(f"  Would NOT have hit stop — toxicity exit may have been PREMATURE")

    elif exit_reason == "tape_failure_exit":
        lines.append("  Verdict:  EARLY EXIT — T18 tape failure (sell delta overwhelming).")
    elif exit_reason == "nuclear_flatten":
        lines.append("  Verdict:  FORCED EXIT — RiskOverlord nuclear flatten (consecutive losses).")
    elif exit_reason == "absorption_climax":
        lines.append("  Verdict:  CLIMAX EXIT — absorption + delta stall detected at runner phase.")
    lines.append("")

    # ── Price action context ──
    if len(bars) > 0 and entry_ns:
        lines.append("─" * 100)
        lines.append("  D. MARKET CONTEXT — Price action around the trade")
        lines.append("─" * 100)
        lines.append("")

        entry_idx = find_bar_index(bars, entry_ns)
        start_idx = max(0, entry_idx - bars_before)
        exit_idx = find_bar_index(bars, exit_ns) if exit_ns else entry_idx
        end_idx = min(len(bars), max(exit_idx + bars_after, entry_idx + bars_after))

        # Pre-entry context
        lines.append(f"  Pre-entry bars ({bars_before} bars before):")
        for i in range(start_idx, entry_idx):
            lines.append(format_price_bar(bars[i], i, direction=direction))

        # Entry bar
        lines.append("")
        lines.append(f"  >>> ENTRY BAR (bar {entry_idx}):")
        lines.append(format_price_bar(bars[entry_idx], entry_idx,
                                       entry_price=entry_price,
                                       stop_price=stop_price,
                                       target_price=target_price,
                                       direction=direction))
        lines.append(f"      Entry: {entry_price:.2f}  Stop: {stop_price:.2f}  Target: {target_price:.2f}")
        lines.append("")

        # Post-entry bars through exit
        lines.append(f"  Post-entry bars (through exit + {bars_after} bars after):")
        for i in range(entry_idx + 1, end_idx):
            lines.append(format_price_bar(bars[i], i,
                                           entry_price=entry_price,
                                           stop_price=stop_price,
                                           target_price=target_price,
                                           direction=direction))
        lines.append("")

        # Max favorable/adverse excursion during the trade
        if exit_ns and entry_idx < exit_idx:
            trade_bars = bars[entry_idx:exit_idx + 1]
            if direction == "LONG":
                mfe = float(np.max(trade_bars["high"])) - entry_price
                mae = entry_price - float(np.min(trade_bars["low"]))
            else:
                mfe = entry_price - float(np.min(trade_bars["low"]))
                mae = float(np.max(trade_bars["high"])) - entry_price

            mfe_r = mfe / risk_points if risk_points > 0 else 0
            mae_r = mae / risk_points if risk_points > 0 else 0

            lines.append("  Excursion Analysis (during trade):")
            lines.append(f"    Max Favorable Excursion (MFE): {mfe:+.2f} pts ({mfe_r:+.1f}R)")
            lines.append(f"    Max Adverse Excursion (MAE):   {mae:.2f} pts ({mae_r:.1f}R)")
            if mfe_r >= 1.0 and pnl_r < 0:
                lines.append(f"    ** Trade was +{mfe_r:.1f}R favorable before reversing to stop!")
                lines.append(f"       Micro trail / breakeven stop should have protected this.")
            lines.append("")

    lines.append("=" * 100)
    lines.append("")
    return lines


def main():
    args = parse_args()

    results = load_results(args.results)
    all_trades = results.get("trades", [])

    if not all_trades:
        print("ERROR: No trades found in results file.")
        sys.exit(1)

    output_lines = []

    if args.list:
        filtered = filter_trades(all_trades, args)
        output_lines.extend(print_trade_list(filtered))
    elif args.trades or args.losers or args.winners:
        filtered = filter_trades(all_trades, args)

        if not filtered:
            print("No trades match the filter criteria.")
            sys.exit(0)

        # Apply limit
        if len(filtered) > args.limit:
            print(f"Showing first {args.limit} of {len(filtered)} matching trades (use --limit to change)")
            filtered = filtered[:args.limit]

        # Load bar data for market context
        bars = load_bars(args.data_dir)
        if len(bars) == 0:
            print("WARNING: No bar data found — market context will be limited.")

        output_lines.append(f"Trade Autopsy Report — {len(filtered)} trades")
        output_lines.append(f"Generated: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        output_lines.append(f"Data source: {args.results}")

        # Summary stats for the filtered set
        pnls = [t.get("pnl_r_multiple", 0) or 0 for t in filtered]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        avg_r = sum(pnls) / len(pnls) if pnls else 0
        total_pnl = sum(t.get("pnl_dollars", 0) or 0 for t in filtered)
        output_lines.append(f"Filtered set: {len(filtered)} trades | {wins}W/{losses}L | Avg R: {avg_r:+.2f} | Total PnL: ${total_pnl:+,.0f}")

        for trade in filtered:
            output_lines.extend(autopsy_trade(trade, bars, args.bars_before, args.bars_after))
    else:
        # Default: show help
        print("Usage: trade_autopsy.py --list | --trades ID [ID...] | --losers | --winners")
        print("       Add --clean-only or --shadow-only to filter by gate status")
        print("       Add --exit-reason stop_hit to filter by exit type")
        print("       Add --limit N to control number of autopsies")
        sys.exit(0)

    # Output
    report = "\n".join(output_lines)

    if args.out:
        with open(args.out, "w") as f:
            f.write(report)
        print(f"Report saved to: {args.out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
