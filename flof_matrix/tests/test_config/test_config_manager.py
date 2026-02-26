"""Tests for ConfigManager."""

import pytest

from flof_matrix.config.config_manager import ConfigManager


CONFIG_PATH = "/home/kris/tradestar/flof/flof_matrix/config/flof_base.toml"


@pytest.fixture(autouse=True)
def reset_singleton():
    ConfigManager.reset()
    yield
    ConfigManager.reset()


class TestConfigManager:
    def test_base_only_load(self):
        cm = ConfigManager()
        cm.load(CONFIG_PATH)
        assert cm.get("system.live_mode") is False
        assert cm.get("system.profile") == "futures"

    def test_profile_override(self):
        cm = ConfigManager()
        cm.load(CONFIG_PATH, profile="futures")
        # profile_futures.toml overrides max_concurrent_positions to 3
        assert cm.get("risk_overlord.max_concurrent_positions") == 3
        assert cm.get("execution.tick_size") == 0.25
        assert cm.get("execution.point_value") == 50.0

    def test_dot_notation_access(self):
        cm = ConfigManager()
        cm.load(CONFIG_PATH, profile="futures")
        assert cm.get("scoring.tier1.gate_minimum") == 6
        assert cm.get("grading.a_plus_min") == 14
        assert cm.get("grading.a_min") == 12
        assert cm.get("grading.b_min") == 9

    def test_default_value(self):
        cm = ConfigManager()
        cm.load(CONFIG_PATH)
        assert cm.get("nonexistent.key", "fallback") == "fallback"

    def test_toggle_enabled(self):
        cm = ConfigManager()
        cm.load(CONFIG_PATH, profile="futures")
        assert cm.is_toggle_enabled("T01") is True
        assert cm.is_toggle_enabled("T07") is True

    def test_toggle_cascade(self):
        cm = ConfigManager()
        cm.load(CONFIG_PATH, profile="futures")
        # T01 → T02 → T03 chain
        assert cm.is_toggle_enabled("T02") is True  # T01 is ON
        assert cm.is_toggle_enabled("T03") is True  # T02 is ON

    def test_validate_toggles(self):
        cm = ConfigManager()
        cm.load(CONFIG_PATH, profile="futures")
        errors = cm.validate_toggles()
        assert isinstance(errors, list)

    def test_hot_reload(self):
        cm = ConfigManager()
        cm.load(CONFIG_PATH, profile="futures")
        cm.reload()
        assert cm.get("scoring.tier1.gate_minimum") == 6

    def test_hot_reload_blocked_in_live_mode(self):
        cm = ConfigManager()
        cm.load(CONFIG_PATH, profile="futures")
        # Manually set live_mode
        cm._config["system"]["live_mode"] = True
        with pytest.raises(RuntimeError, match="live mode"):
            cm.reload()

    def test_singleton_behavior(self):
        cm1 = ConfigManager()
        cm1.load(CONFIG_PATH)
        cm2 = ConfigManager()
        assert cm1 is cm2
        assert cm2.get("system.profile") == "futures"

    def test_deep_merge(self):
        cm = ConfigManager()
        cm.load(CONFIG_PATH, profile="futures")
        # Base has max_concurrent_positions=5, futures overrides to 3
        assert cm.get("risk_overlord.max_concurrent_positions") == 3
        # Base values that aren't overridden should persist
        assert cm.get("scoring.tier1.trend_alignment_full") == 2
