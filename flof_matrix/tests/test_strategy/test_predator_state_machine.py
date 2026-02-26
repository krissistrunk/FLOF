"""Tests for PredatorStateMachine — state transitions."""

from datetime import datetime

import pytest

from flof_matrix.strategy.predator_state_machine import PredatorStateMachine
from flof_matrix.core.types import PredatorState, SuddenMoveType


class TestPredatorStateMachine:
    def make_psm(self):
        return PredatorStateMachine(
            killzones=[{"start": "09:30", "end": "11:30"}],
            proximity_halo_atr_mult=1.5,
            tape_velocity_stalking_pct=300.0,
            kill_mode_ring_buffer_min=30.0,
        )

    def test_initial_state(self):
        psm = self.make_psm()
        assert psm.state == PredatorState.DORMANT

    def test_dormant_to_scouting(self):
        psm = self.make_psm()
        t = datetime(2024, 1, 15, 10, 0)  # Within killzone
        psm.evaluate_state(t, 5000.0, 5.0)
        assert psm.state == PredatorState.SCOUTING

    def test_dormant_stays_outside_killzone(self):
        psm = self.make_psm()
        t = datetime(2024, 1, 15, 8, 0)  # Before killzone
        psm.evaluate_state(t, 5000.0, 5.0)
        assert psm.state == PredatorState.DORMANT

    def test_scouting_to_stalking_proximity(self):
        psm = self.make_psm()
        t = datetime(2024, 1, 15, 10, 0)
        psm.evaluate_state(t, 5000.0, 5.0)  # → SCOUTING
        # POI at 5006, within halo (1.5 * 5.0 = 7.5)
        psm.evaluate_state(t, 5000.0, 5.0, poi_price=5006.0)
        assert psm.state == PredatorState.STALKING

    def test_scouting_to_stalking_velocity(self):
        psm = self.make_psm()
        t = datetime(2024, 1, 15, 10, 0)
        psm.evaluate_state(t, 5000.0, 5.0)  # → SCOUTING
        psm.evaluate_state(t, 5000.0, 5.0, tape_velocity_pct=350.0)
        assert psm.state == PredatorState.STALKING

    def test_stalking_to_kill(self):
        psm = self.make_psm()
        t = datetime(2024, 1, 15, 10, 0)
        psm.evaluate_state(t, 5000.0, 5.0)
        psm.evaluate_state(t, 5000.0, 5.0, poi_price=5006.0)
        # POI tapped + CHOCH + buffer ready
        psm.evaluate_state(t, 5009.5, 5.0, poi_price=5010.0, has_choch=True, ring_buffer_ready=True)
        assert psm.state == PredatorState.KILL

    def test_kill_to_dormant_trade_executed(self):
        psm = self.make_psm()
        t = datetime(2024, 1, 15, 10, 0)
        psm.transition_to(PredatorState.KILL)
        psm.evaluate_state(t, 5000.0, 5.0, trade_executed=True)
        assert psm.state == PredatorState.DORMANT

    def test_killzone_close_forces_dormant(self):
        psm = self.make_psm()
        t_in = datetime(2024, 1, 15, 10, 0)
        psm.evaluate_state(t_in, 5000.0, 5.0)  # → SCOUTING
        t_out = datetime(2024, 1, 15, 12, 0)  # After killzone
        psm.evaluate_state(t_out, 5000.0, 5.0)
        assert psm.state == PredatorState.DORMANT

    def test_type_c_forces_dormant(self):
        psm = self.make_psm()
        psm.transition_to(PredatorState.STALKING)
        t = datetime(2024, 1, 15, 10, 0)
        psm.evaluate_state(t, 5000.0, 5.0, sudden_move=SuddenMoveType.TYPE_C)
        assert psm.state == PredatorState.DORMANT

    def test_force_dormant(self):
        psm = self.make_psm()
        psm.transition_to(PredatorState.KILL)
        psm.force_dormant()
        assert psm.state == PredatorState.DORMANT

    def test_transition_callback(self):
        psm = self.make_psm()
        transitions = []
        psm.register_transition_callback(lambda old, new: transitions.append((old, new)))
        psm.transition_to(PredatorState.SCOUTING)
        assert transitions == [(PredatorState.DORMANT, PredatorState.SCOUTING)]
