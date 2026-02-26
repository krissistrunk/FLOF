"""Tests for NautilusTrader BacktestEngine integration."""

from __future__ import annotations

import numpy as np
import pytest

from flof_matrix.nautilus.backtest_runner import BacktestRunner, BAR_DTYPE


@pytest.fixture
def synthetic_bars():
    """Create a small set of synthetic bars for testing."""
    n_bars = 100
    bars = np.zeros(n_bars, dtype=BAR_DTYPE)
    base_ts = 1704205800_000_000_000  # 2024-01-02 09:30 ET in nanos

    price = 5000.0
    rng = np.random.default_rng(42)
    for i in range(n_bars):
        move = rng.normal(0, 2)
        o = price
        c = price + move
        h = max(o, c) + rng.uniform(0, 3)
        l = min(o, c) - rng.uniform(0, 3)

        bars[i]["timestamp_ns"] = base_ts + (i * 60_000_000_000)
        bars[i]["open"] = o
        bars[i]["high"] = h
        bars[i]["low"] = l
        bars[i]["close"] = c
        bars[i]["volume"] = rng.uniform(100, 2000)
        price = c

    return bars


@pytest.fixture
def runner():
    """Create a BacktestRunner configured for testing."""
    return BacktestRunner(
        config_path="flof_matrix/config/flof_base.toml",
        profile="futures",
        fill_level=2,
    )


class TestManualEngine:
    """Test the manual bar-loop engine."""

    def test_manual_run_produces_results(self, runner, synthetic_bars):
        result = runner.run(synthetic_bars)
        assert result["bars_processed"] == len(synthetic_bars)
        assert "trade_count" in result
        assert "fill_level" in result
        assert result["fill_level"] == "Standard"

    def test_manual_run_trade_count_non_negative(self, runner, synthetic_bars):
        result = runner.run(synthetic_bars)
        assert result["trade_count"] >= 0


class TestNautilusEngine:
    """Test the NautilusTrader BacktestEngine integration."""

    def test_nautilus_run_produces_results(self, runner, synthetic_bars):
        result = runner.run_nautilus(synthetic_bars)
        assert result["engine"] == "nautilus"
        assert result["bars_processed"] == len(synthetic_bars)
        assert "trade_count" in result
        assert "nautilus_result" in result

    def test_nautilus_result_has_engine_stats(self, runner, synthetic_bars):
        result = runner.run_nautilus(synthetic_bars)
        nt = result["nautilus_result"]
        assert "run_id" in nt
        assert "elapsed_time" in nt
        assert "iterations" in nt
        assert nt["iterations"] == len(synthetic_bars)

    def test_nautilus_fill_level(self, runner, synthetic_bars):
        result = runner.run_nautilus(synthetic_bars)
        assert result["fill_level"] == "Standard"


class TestEngineConsistency:
    """Verify both engines produce consistent results."""

    def test_both_engines_same_trade_count(self, synthetic_bars):
        """Both engines should produce the same number of trades from same data."""
        runner1 = BacktestRunner(
            config_path="flof_matrix/config/flof_base.toml",
            profile="futures",
            fill_level=2,
        )
        manual_result = runner1.run(synthetic_bars)
        runner1.shutdown()

        runner2 = BacktestRunner(
            config_path="flof_matrix/config/flof_base.toml",
            profile="futures",
            fill_level=2,
        )
        nautilus_result = runner2.run_nautilus(synthetic_bars)
        runner2.shutdown()

        assert manual_result["trade_count"] == nautilus_result["trade_count"]
        assert manual_result["bars_processed"] == nautilus_result["bars_processed"]
