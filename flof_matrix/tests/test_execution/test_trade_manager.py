"""Tests for TradeManager — Phase 1/2/3, tape failure, toxicity, EOD flatten."""

import pytest

from flof_matrix.execution.trade_manager import TradeManager, ManagedPosition
from flof_matrix.core.types import Grade, TradeDirection, TradePhase


def make_position(**overrides):
    defaults = dict(
        position_id="test-1",
        direction=TradeDirection.LONG,
        grade=Grade.A,
        entry_price=5000.0,
        stop_price=4990.0,
        target_price=5020.0,
        total_contracts=4,
        entry_time_ns=0,
    )
    defaults.update(overrides)
    return ManagedPosition(**defaults)


class TestTradeManager:
    def make_tm(self):
        return TradeManager(
            tick_size=0.25,
            point_value=50.0,
            phase1_target_r=2.0,
            default_partial_pct=0.50,
            a_plus_partial_pct=0.33,
            toxicity_timer_seconds=120.0,
            toxicity_delta_pct=0.70,
        )

    def test_phase1_partial_at_2r(self):
        tm = self.make_tm()
        pos = make_position()
        # At 2R target: entry=5000, stop=4990, risk=10, target=5020
        result = tm.evaluate_phase1(pos, 5020.0)
        assert result is not None
        assert result["action"] == "partial_exit"
        assert result["contracts"] == 2  # 50% of 4

    def test_phase1_not_triggered_below_target(self):
        tm = self.make_tm()
        pos = make_position()
        result = tm.evaluate_phase1(pos, 5015.0)
        assert result is None

    def test_phase1_a_plus_33_percent(self):
        tm = self.make_tm()
        pos = make_position(grade=Grade.A_PLUS, total_contracts=3)
        result = tm.evaluate_phase1(pos, 5020.0)
        assert result["contracts"] == 1  # max(1, floor(3 * 0.33))

    def test_apply_phase1_result(self):
        tm = self.make_tm()
        pos = make_position()
        result = tm.evaluate_phase1(pos, 5020.0)
        tm.apply_phase1_result(pos, result)
        assert pos.phase == TradePhase.PHASE2_RUNNER
        assert pos.remaining_contracts == 2
        assert pos.breakeven_set
        assert pos.stop_price == 5000.25  # BE + 1 tick

    def test_phase2_trail_update(self):
        tm = self.make_tm()
        pos = make_position()
        pos.phase = TradePhase.PHASE2_RUNNER
        pos.stop_price = 5000.0
        result = tm.evaluate_phase2(pos, 5030.0, bos_level=5010.0)
        assert result is not None
        assert result["action"] == "update_stop"
        assert result["new_stop"] >= 5010.0

    def test_tape_failure_exit_80(self):
        tm = self.make_tm()
        pos = make_position()
        result = tm.check_tape_failure(pos, sell_delta_pct=0.85, sma_health_ok=True)
        assert result is not None
        assert result["action"] == "tape_failure_exit"

    def test_tape_failure_tightened_65(self):
        """T21: Tightened to 65% when 20 SMA health fails."""
        tm = self.make_tm()
        pos = make_position()
        result = tm.check_tape_failure(pos, sell_delta_pct=0.70, sma_health_ok=False)
        assert result is not None
        assert result["tightened"] is True

    def test_tape_failure_no_trigger(self):
        tm = self.make_tm()
        pos = make_position()
        result = tm.check_tape_failure(pos, sell_delta_pct=0.50, sma_health_ok=True)
        assert result is None

    def test_toxicity_timer(self):
        """T35: Exit if no movement in 120s."""
        tm = self.make_tm()
        pos = make_position(entry_time_ns=0)
        pos.last_movement_ns = 0
        result = tm.check_toxicity_timer(pos, now_ns=200_000_000_000)
        assert result is not None
        assert result["action"] == "toxicity_timer_exit"

    def test_toxicity_timer_not_triggered(self):
        tm = self.make_tm()
        pos = make_position()
        pos.last_movement_ns = 100_000_000_000
        result = tm.check_toxicity_timer(pos, now_ns=150_000_000_000)
        assert result is None

    def test_toxicity_exit(self):
        """T48: 70% adverse delta → exit."""
        tm = self.make_tm()
        pos = make_position()
        result = tm.check_toxicity_exit(pos, adverse_delta_pct=0.75)
        assert result is not None
        assert result["action"] == "toxicity_exit"

    def test_micro_trail_at_1r(self):
        """Once price reaches +1R, stop moves to breakeven."""
        tm = self.make_tm()
        pos = make_position()  # entry=5000, stop=4990, risk=10
        # At +1R = 5010
        result = tm.check_micro_trail(pos, 5010.0)
        assert result is not None
        assert result["action"] == "micro_trail"
        assert result["new_stop"] == 5000.25  # BE + 1 tick

    def test_micro_trail_not_triggered_below_1r(self):
        tm = self.make_tm()
        pos = make_position()
        result = tm.check_micro_trail(pos, 5008.0)  # +0.8R
        assert result is None

    def test_micro_trail_short(self):
        """Micro trail for SHORT: entry=5000, stop=5010, +1R = 4990."""
        tm = self.make_tm()
        pos = make_position(
            direction=TradeDirection.SHORT,
            entry_price=5000.0,
            stop_price=5010.0,
            target_price=4980.0,
        )
        result = tm.check_micro_trail(pos, 4990.0)
        assert result is not None
        assert result["new_stop"] == 4999.75  # BE - 1 tick for short

    def test_micro_trail_only_once(self):
        """Micro trail does not re-fire after breakeven is already set."""
        tm = self.make_tm()
        pos = make_position()
        result = tm.check_micro_trail(pos, 5010.0)
        assert result is not None
        tm.apply_micro_trail(pos, result)
        # Second call should return None
        result2 = tm.check_micro_trail(pos, 5015.0)
        assert result2 is None

    def test_micro_trail_not_in_phase2(self):
        """Micro trail only applies in Phase 1."""
        tm = self.make_tm()
        pos = make_position()
        pos.phase = TradePhase.PHASE2_RUNNER
        result = tm.check_micro_trail(pos, 5010.0)
        assert result is None

    def test_phase2_fixed_trail_fallback(self):
        """Phase 2 uses fixed 2R trail when no BOS/LVN available."""
        tm = self.make_tm()
        pos = make_position()
        pos.phase = TradePhase.PHASE2_RUNNER
        pos.stop_price = 4990.0  # original stop (risk=10)
        pos.highest_favorable = 5030.0  # went to 3R
        # No bos_level → fixed trail: 5030 - 2*10 = 5010, above 4990 → update
        result = tm.evaluate_phase2(pos, 5025.0)
        assert result is not None
        assert result["new_stop"] == 5010.0

    def test_phase2_uses_original_risk_after_breakeven(self):
        """Phase 2 trail uses original risk, not breakeven risk."""
        tm = self.make_tm()
        pos = make_position()  # entry=5000, stop=4990, original_risk=10
        # Simulate Phase 1: stop moved to BE+1tick
        pos.phase = TradePhase.PHASE2_RUNNER
        pos.stop_price = 5000.25  # breakeven
        pos.highest_favorable = 5030.0
        # Trail should use original_risk=10: 5030 - 2*10 = 5010
        # NOT breakeven risk of 0.25: 5030 - 2*0.25 = 5029.5
        result = tm.evaluate_phase2(pos, 5025.0)
        assert result is not None
        assert result["new_stop"] == 5010.0  # uses original risk

    def test_phase3_blocked_when_far_from_target(self):
        """Phase 3 climax doesn't fire when price is < 75% to target."""
        tm = self.make_tm()
        pos = make_position()  # entry=5000, target=5020, distance=20
        pos.phase = TradePhase.PHASE2_RUNNER
        # Price at 5010 = 50% of way to target → blocked
        result = tm.evaluate_phase3(pos, absorption_score=1.0, delta_pct=0.0, current_price=5010.0)
        assert result is None

    def test_phase3_fires_near_target(self):
        """Phase 3 climax fires when price is >= 75% to target."""
        tm = self.make_tm()
        pos = make_position()  # entry=5000, target=5020, distance=20
        pos.phase = TradePhase.PHASE2_RUNNER
        # Price at 5016 = 80% of way to target → allowed
        result = tm.evaluate_phase3(pos, absorption_score=1.0, delta_pct=0.0, current_price=5016.0)
        assert result is not None
        assert result["action"] == "climax_exit"

    def test_eod_flatten(self):
        tm = self.make_tm()
        assert tm.check_eod_flatten("15:55")
        assert not tm.check_eod_flatten("15:45")
