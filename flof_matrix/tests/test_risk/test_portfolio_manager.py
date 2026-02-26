"""Tests for PortfolioManager — all 5 gates, ledger updates, latency."""

import time

import pytest

from flof_matrix.risk.portfolio_manager import PortfolioManager, PositionLedgerEntry
from flof_matrix.core.types import TradeDirection


class TestPortfolioManager:
    def make_pm(self):
        return PortfolioManager(
            p1_max_total_exposure=0.06,
            p2_max_per_group=2,
            p3_daily_drawdown_limit=-0.02,
            p4_max_loss_streak=3,
            p5_lockout_seconds=300.0,
            correlation_groups={"A": ["ES", "NQ", "YM"]},
        )

    def test_all_gates_pass(self):
        pm = self.make_pm()
        passed, reason = pm.evaluate_gates("ES", 0.02, now_ns=0)
        assert passed

    def test_p3_daily_drawdown(self):
        pm = self.make_pm()
        pm.update_daily_pnl(-0.025)
        passed, reason = pm.evaluate_gates("ES", 0.02, now_ns=0)
        assert not passed
        assert "P3" in reason

    def test_p4_loss_streak(self):
        pm = self.make_pm()
        for _ in range(3):
            pm.record_loss()
        passed, reason = pm.evaluate_gates("ES", 0.02, now_ns=0)
        assert not passed
        assert "P4" in reason

    def test_p5_nuclear_lockout(self):
        pm = self.make_pm()
        pm.record_nuclear_flatten(now_ns=1000)
        passed, reason = pm.evaluate_gates("ES", 0.02, now_ns=2000)
        assert not passed
        assert "P5" in reason

    def test_p5_lockout_expired(self):
        pm = self.make_pm()
        pm.record_nuclear_flatten(now_ns=1000)
        # 301 seconds later
        passed, reason = pm.evaluate_gates("ES", 0.02, now_ns=301_000_000_001)
        assert passed

    def test_p1_total_exposure(self):
        pm = self.make_pm()
        pm.add_position(PositionLedgerEntry(
            position_id="p1", instrument="ES", correlation_group="A",
            direction=TradeDirection.LONG, risk_pct=0.05, contracts=3,
        ))
        # Adding 0.02 would exceed 0.06 limit
        passed, reason = pm.evaluate_gates("NQ", 0.02, now_ns=0)
        assert not passed
        assert "P1" in reason

    def test_p2_correlation_group(self):
        pm = self.make_pm()
        pm.add_position(PositionLedgerEntry(
            position_id="p1", instrument="ES", correlation_group="A",
            direction=TradeDirection.LONG, risk_pct=0.01, contracts=1,
        ))
        pm.add_position(PositionLedgerEntry(
            position_id="p2", instrument="NQ", correlation_group="A",
            direction=TradeDirection.LONG, risk_pct=0.01, contracts=1,
        ))
        passed, reason = pm.evaluate_gates("YM", 0.01, now_ns=0)
        assert not passed
        assert "P2" in reason

    def test_remove_position(self):
        pm = self.make_pm()
        pm.add_position(PositionLedgerEntry(
            position_id="p1", instrument="ES", correlation_group="A",
            direction=TradeDirection.LONG, risk_pct=0.02, contracts=2,
        ))
        assert pm.total_exposure == 0.02
        pm.remove_position("p1")
        assert pm.total_exposure == 0.0
        assert pm.open_position_count == 0

    def test_gate_evaluation_order(self):
        """Gates should be evaluated P3→P4→P5→P1→P2 (cheapest first)."""
        pm = self.make_pm()
        # Set up multiple failures
        pm.update_daily_pnl(-0.025)  # P3 fail
        for _ in range(3):
            pm.record_loss()  # P4 fail
        passed, reason = pm.evaluate_gates("ES", 0.02, now_ns=0)
        assert not passed
        assert "P3" in reason  # P3 should be checked first

    @pytest.mark.benchmark
    def test_gate_latency(self):
        """All 5 gates must evaluate in < 1ms."""
        pm = self.make_pm()
        pm.add_position(PositionLedgerEntry(
            position_id="p1", instrument="ES", correlation_group="A",
            direction=TradeDirection.LONG, risk_pct=0.01, contracts=1,
        ))
        iterations = 10_000
        start = time.perf_counter_ns()
        for _ in range(iterations):
            pm.evaluate_gates("NQ", 0.015, now_ns=1_000_000_000)
        avg_us = (time.perf_counter_ns() - start) / iterations / 1000
        assert avg_us < 1000, f"Gates too slow: {avg_us:.1f} us"
