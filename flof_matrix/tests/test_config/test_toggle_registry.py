"""Tests for ToggleRegistry."""

import pytest

from flof_matrix.config.toggle_registry import ToggleRegistry, TOGGLE_DEPENDENCIES, SAFETY_TOGGLES


def make_getter(overrides=None):
    """Create a config getter that returns True for all toggles by default."""
    defaults = {
        "toggles.structure.T01_htf_structure_mapper": True,
        "toggles.structure.T02_htf_regime_filter": True,
        "toggles.structure.T03_synthetic_ma_poi": True,
        "toggles.execution.T07_order_flow_confirmation": True,
        "toggles.execution.T08_absorption_detection": True,
        "toggles.execution.T09_whale_watch_filter": True,
        "toggles.velez.T16_all_velez_layers": True,
        "toggles.velez.T12_20sma_halt_confluence": True,
        "toggles.velez.T13_flat_200sma_confluence": True,
        "toggles.velez.T14_elephant_bar_confirmation": True,
        "toggles.velez.T15_20sma_micro_trend": True,
        "toggles.risk.T18_conditional_tape_failure": True,
        "toggles.risk.T19_structural_node_trail": True,
        "toggles.risk.T20_rbi_gbi_hold_filter": True,
        "toggles.risk.T21_20sma_health_check": True,
        "toggles.safety.T24_oco_bracket_enforcement": True,
        "toggles.safety.T25_anti_spam_rate_limiter": True,
        "toggles.safety.T26_fat_finger_position_limit": True,
        "toggles.safety.T27_daily_drawdown_breaker": True,
        "toggles.safety.T28_stale_data_monitor": True,
        "toggles.safety.T29_sudden_move_classifier": True,
        "toggles.safety.T30_cascade_position_override": True,
        "toggles.structure.T31_mtf_poi_hierarchy": True,
        "toggles.structure.T32_poi_clustering": True,
        "toggles.options.T46_options_routing": False,
        "toggles.options.T47_gex_aware_selling": False,
    }
    if overrides:
        defaults.update(overrides)

    def getter(key, default=None):
        return defaults.get(key, default)

    return getter


class TestToggleRegistry:
    def test_basic_enabled(self):
        reg = ToggleRegistry(make_getter())
        assert reg.is_enabled("T01") is True

    def test_parent_off_cascades(self):
        """T01 OFF → T02 forced OFF → T03 forced OFF."""
        getter = make_getter({"toggles.structure.T01_htf_structure_mapper": False})
        reg = ToggleRegistry(getter)
        assert reg.is_enabled("T01") is False
        assert reg.is_enabled("T02") is False  # Parent T01 is OFF
        assert reg.is_enabled("T03") is False  # Grandparent chain

    def test_t07_cascade(self):
        """T07 OFF → T08, T09, T18 all OFF."""
        getter = make_getter({"toggles.execution.T07_order_flow_confirmation": False})
        reg = ToggleRegistry(getter)
        assert reg.is_enabled("T07") is False
        assert reg.is_enabled("T08") is False
        assert reg.is_enabled("T09") is False
        assert reg.is_enabled("T18") is False

    def test_t16_velez_cascade(self):
        """T16 OFF → T12, T13, T14, T15 all OFF."""
        getter = make_getter({"toggles.velez.T16_all_velez_layers": False})
        reg = ToggleRegistry(getter)
        assert reg.is_enabled("T12") is False
        assert reg.is_enabled("T13") is False
        assert reg.is_enabled("T14") is False
        assert reg.is_enabled("T15") is False

    def test_t21_and_dependency(self):
        """T21 requires BOTH T18 AND T19."""
        # Both parents ON
        reg = ToggleRegistry(make_getter())
        assert reg.is_enabled("T21") is True

        # T18 OFF
        getter = make_getter({"toggles.risk.T18_conditional_tape_failure": False})
        reg = ToggleRegistry(getter)
        assert reg.is_enabled("T21") is False

        # T19 OFF
        getter = make_getter({"toggles.risk.T19_structural_node_trail": False})
        reg = ToggleRegistry(getter)
        assert reg.is_enabled("T21") is False

    def test_safety_toggles_forced_in_live_mode(self):
        """Safety toggles T24-T28 forced ON in live mode."""
        getter = make_getter({
            "toggles.safety.T24_oco_bracket_enforcement": False,
            "toggles.safety.T25_anti_spam_rate_limiter": False,
        })
        reg = ToggleRegistry(getter, live_mode=True)
        assert reg.is_enabled("T24") is True  # Forced ON
        assert reg.is_enabled("T25") is True  # Forced ON

    def test_safety_toggles_can_be_off_in_backtest(self):
        getter = make_getter({
            "toggles.safety.T24_oco_bracket_enforcement": False,
        })
        reg = ToggleRegistry(getter, live_mode=False)
        assert reg.is_enabled("T24") is False  # Can be OFF in backtest

    def test_validate_clean(self):
        reg = ToggleRegistry(make_getter())
        errors = reg.validate()
        assert len(errors) == 0

    def test_t46_t47_cascade(self):
        """T46 OFF → T47 OFF."""
        getter = make_getter({"toggles.options.T46_options_routing": False})
        reg = ToggleRegistry(getter)
        assert reg.is_enabled("T47") is False
