"""Tests for RiskOverlord — all 4 pillars, Nuclear Flatten sequence."""

import pytest

from flof_matrix.risk.risk_overlord import RiskOverlord


class MockStrategy:
    def __init__(self):
        self.orders_cancelled = False
        self.positions_flattened = False
        self.forced_dormant = False

    def cancel_all_orders(self):
        self.orders_cancelled = True

    def flatten_all_positions(self):
        self.positions_flattened = True

    def force_dormant(self):
        self.forced_dormant = True


class TestRiskOverlord:
    def make_ro(self, **overrides):
        defaults = dict(
            max_orders_per_minute=3,
            max_concurrent_positions=3,
            max_daily_drawdown_pct=-0.03,
            max_consecutive_losses=3,
            stale_data_countdown_seconds=5.0,
            live_mode=False,
        )
        defaults.update(overrides)
        return RiskOverlord(**defaults)

    def test_initial_ok(self):
        ro = self.make_ro()
        result = ro.check(now_ns=1_000_000_000_000)
        assert result["status"] == "ok"

    def test_t25_anti_spam(self):
        ro = self.make_ro()
        now = 1_000_000_000_000
        for i in range(5):
            ro.record_order(now + i * 1_000_000)
        result = ro.check(now + 100_000_000)
        assert result["status"] == "breach"
        assert result["pillar"] == "T25_anti_spam"

    def test_t26_fat_finger(self):
        ro = self.make_ro()
        ro.update_positions(4)  # Above limit of 3
        result = ro.check(1_000_000_000_000)
        assert result["status"] == "breach"
        assert result["pillar"] == "T26_fat_finger"

    def test_t27_daily_drawdown(self):
        ro = self.make_ro()
        ro.update_daily_pnl(-0.04)  # Below -3%
        result = ro.check(1_000_000_000_000)
        assert result["status"] == "breach"
        assert result["pillar"] == "T27_daily_drawdown"

    def test_consecutive_losses(self):
        ro = self.make_ro()
        for _ in range(3):
            ro.record_loss()
        result = ro.check(1_000_000_000_000)
        assert result["status"] == "breach"
        assert result["pillar"] == "consecutive_losses"

    def test_t28_stale_data(self):
        ro = self.make_ro()
        ro.on_stale_data_alert(1_000_000_000_000)
        # 6 seconds later (> 5s countdown)
        result = ro.check(1_006_000_000_000)
        assert result["status"] == "breach"
        assert result["pillar"] == "T28_stale_data"

    def test_stale_data_before_countdown(self):
        ro = self.make_ro()
        ro.on_stale_data_alert(1_000_000_000_000)
        # 3 seconds later (< 5s)
        result = ro.check(1_003_000_000_000)
        assert result["status"] == "ok"

    def test_nuclear_flatten_sequence(self):
        strategy = MockStrategy()
        ro = self.make_ro()
        ro.set_strategy(strategy)
        ro.update_daily_pnl(-0.04)
        ro.check(1_000_000_000_000)
        assert ro.is_flattened
        assert strategy.orders_cancelled
        assert strategy.positions_flattened
        assert strategy.forced_dormant

    def test_flattened_stays_flattened(self):
        ro = self.make_ro()
        ro.update_daily_pnl(-0.04)
        ro.check(1_000_000_000_000)
        assert ro.is_flattened
        result = ro.check(2_000_000_000_000)
        assert result["status"] == "flattened"

    def test_reset_daily(self):
        ro = self.make_ro()
        ro.update_daily_pnl(-0.04)
        ro.check(1_000_000_000_000)
        assert ro.is_flattened
        ro.reset_daily()
        assert not ro.is_flattened

    def test_win_resets_streak(self):
        ro = self.make_ro()
        ro.record_loss()
        ro.record_loss()
        ro.record_win()
        result = ro.check(1_000_000_000_000)
        assert result["status"] == "ok"
