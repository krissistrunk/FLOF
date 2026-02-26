"""Tests for real trade tick pipeline — dbn_to_trades conversion and injection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from flof_matrix.core.ring_buffer import RingBuffer, TICK_DTYPE
from flof_matrix.data.databento_adapter import DataBentoAdapter

# ── Helpers ──

BAR_DTYPE = np.dtype([
    ("timestamp_ns", np.int64),
    ("open", np.float64),
    ("high", np.float64),
    ("low", np.float64),
    ("close", np.float64),
    ("volume", np.float64),
])


def _make_mock_dbn_store(n_ticks=100, base_price=5950.0, base_ts_ns=1_704_153_600_000_000_000):
    """Create a mock DBNStore that returns a DataFrame matching DataBento trade schema."""
    ts_events = pd.to_datetime(
        np.arange(base_ts_ns, base_ts_ns + n_ticks * 100_000_000, 100_000_000),
        unit="ns", utc=True,
    )
    prices = base_price + np.random.default_rng(42).uniform(-2, 2, n_ticks)
    sizes = np.random.default_rng(42).integers(1, 50, n_ticks).astype(np.uint32)
    sides = np.random.default_rng(42).choice(["A", "B", "N"], n_ticks)
    flags = np.zeros(n_ticks, dtype=np.uint8)

    df = pd.DataFrame({
        "ts_event": ts_events,
        "price": prices,
        "size": sizes,
        "side": sides,
        "flags": flags,
    })

    store = MagicMock()
    store.to_df.return_value = df
    return store, df


# ── Tests: dbn_to_trades conversion ──

class TestDbnToTrades:
    def test_side_mapping(self):
        """A → +1, B → -1, N → 0."""
        store, df = _make_mock_dbn_store(n_ticks=10)
        # Override sides to known values
        df["side"] = ["A", "B", "N", "A", "B", "N", "A", "A", "B", "N"]
        store.to_df.return_value = df

        ticks = DataBentoAdapter.dbn_to_trades(store)
        assert ticks[0]["side"] == 1    # A = buy
        assert ticks[1]["side"] == -1   # B = sell
        assert ticks[2]["side"] == 0    # N = unknown

    def test_price_passthrough_no_scaling(self):
        """Prices should pass through without 1e9 scaling."""
        store, df = _make_mock_dbn_store(n_ticks=5)
        df["price"] = [5950.25, 5950.50, 5950.00, 5949.75, 5950.25]
        store.to_df.return_value = df

        ticks = DataBentoAdapter.dbn_to_trades(store)
        np.testing.assert_array_almost_equal(
            ticks["price"], [5950.25, 5950.50, 5950.00, 5949.75, 5950.25]
        )

    def test_size_as_float64(self):
        """Sizes should be converted to float64."""
        store, df = _make_mock_dbn_store(n_ticks=3)
        df["size"] = pd.array([100, 200, 300], dtype="uint32")
        store.to_df.return_value = df

        ticks = DataBentoAdapter.dbn_to_trades(store)
        assert ticks["size"].dtype == np.float64
        np.testing.assert_array_equal(ticks["size"], [100.0, 200.0, 300.0])

    def test_timestamp_ns_conversion(self):
        """Timestamps should be int64 nanoseconds."""
        base_ts = 1_704_153_600_000_000_000
        store, df = _make_mock_dbn_store(n_ticks=3, base_ts_ns=base_ts)
        ticks = DataBentoAdapter.dbn_to_trades(store)
        assert ticks["timestamp_ns"].dtype == np.int64
        assert ticks[0]["timestamp_ns"] == base_ts

    def test_output_dtype(self):
        """Output should be TICK_DTYPE."""
        store, _ = _make_mock_dbn_store(n_ticks=5)
        ticks = DataBentoAdapter.dbn_to_trades(store)
        assert ticks.dtype == TICK_DTYPE

    def test_empty_on_exception(self):
        """Should return empty array on conversion failure."""
        store = MagicMock()
        store.to_df.side_effect = RuntimeError("corrupt data")
        ticks = DataBentoAdapter.dbn_to_trades(store)
        assert len(ticks) == 0
        assert ticks.dtype == TICK_DTYPE


# ── Tests: load_trades ──

class TestLoadTrades:
    def test_load_trades_returns_none_on_missing_file(self, tmp_path):
        adapter = DataBentoAdapter()
        result = adapter.load_trades(tmp_path / "nonexistent.dbn.zst")
        assert result is None

    def test_load_trades_returns_ticks(self):
        """load_trades should call load_dbn then dbn_to_trades."""
        store, _ = _make_mock_dbn_store(n_ticks=50)
        adapter = DataBentoAdapter()
        with patch.object(adapter, "load_dbn", return_value=store):
            ticks = adapter.load_trades("fake.dbn.zst")
        assert ticks is not None
        assert len(ticks) == 50
        assert ticks.dtype == TICK_DTYPE


# ── Tests: Tick injection into strategy ──

class TestTickInjectionPath:
    def test_on_trade_tick_pushes_in_killzone(self):
        """Ticks pushed via on_trade_tick should reach ring buffer in KILLZONE state."""
        from flof_matrix.data.sentinel_feed import SentinelFeed

        rb = RingBuffer(capacity=1000)
        sf = SentinelFeed(ring_buffer=rb, backtest_mode=True)
        sf.on_start()

        # In BASE mode, ticks are ignored
        sf.on_trade_tick(1_000_000_000, 5950.0, 10.0, 1)
        assert rb.count == 0

        # Activate killzone — ticks should push to buffer
        sf.activate_killzone_schema()
        sf.on_trade_tick(2_000_000_000, 5950.25, 15.0, -1)
        sf.on_trade_tick(3_000_000_000, 5950.50, 20.0, 1)
        assert rb.count == 2

        latest = rb.latest()
        assert latest["price"] == 5950.50
        assert latest["side"] == 1

    def test_on_trade_tick_pushes_in_kill(self):
        """Ticks also pushed in KILL schema."""
        from flof_matrix.data.sentinel_feed import SentinelFeed

        rb = RingBuffer(capacity=1000)
        sf = SentinelFeed(ring_buffer=rb, backtest_mode=True)
        sf.on_start()
        sf.activate_kill_schema()

        sf.on_trade_tick(1_000_000_000, 5950.0, 10.0, 1)
        assert rb.count == 1


# ── Tests: BacktestRunner tick integration ──

class TestBacktestRunnerTicks:
    def test_run_with_ticks_sets_flag(self):
        """run(bars, ticks) should set _use_real_ticks on strategy."""
        from flof_matrix.nautilus.backtest_runner import BacktestRunner

        runner = BacktestRunner(
            config_path="flof_matrix/config/flof_base.toml",
            profile="futures",
        )
        strategy = runner.setup()

        # Create minimal bars and ticks
        bars = np.zeros(2, dtype=BAR_DTYPE)
        base_ts = 1_704_153_600_000_000_000
        for i in range(2):
            bars[i] = (base_ts + i * 60_000_000_000, 5950.0, 5952.0, 5948.0, 5951.0, 1000.0)

        ticks = np.zeros(5, dtype=TICK_DTYPE)
        for i in range(5):
            ticks[i] = (base_ts + i * 10_000_000_000, 5950.0 + i * 0.25, 10.0, 1, 0)

        runner.run(bars, ticks=ticks)
        assert strategy._use_real_ticks is True

    def test_run_without_ticks_uses_synthetic(self):
        """run(bars) without ticks should leave _use_real_ticks False."""
        from flof_matrix.nautilus.backtest_runner import BacktestRunner

        runner = BacktestRunner(
            config_path="flof_matrix/config/flof_base.toml",
            profile="futures",
        )
        strategy = runner.setup()

        bars = np.zeros(2, dtype=BAR_DTYPE)
        base_ts = 1_704_153_600_000_000_000
        for i in range(2):
            bars[i] = (base_ts + i * 60_000_000_000, 5950.0, 5952.0, 5948.0, 5951.0, 1000.0)

        runner.run(bars)
        assert strategy._use_real_ticks is False


# ── Tests: OFE calibration wiring ──

class TestOFECalibration:
    def test_set_atr_called(self):
        """After 15+ bars, set_atr should be called on the OFE."""
        from flof_matrix.nautilus.backtest_runner import BacktestRunner

        runner = BacktestRunner(
            config_path="flof_matrix/config/flof_base.toml",
            profile="futures",
        )
        strategy = runner.setup()

        # Run enough bars for ATR computation
        bars = np.zeros(20, dtype=BAR_DTYPE)
        base_ts = 1_704_153_600_000_000_000
        for i in range(20):
            bars[i] = (base_ts + i * 60_000_000_000, 5950.0 + i, 5953.0 + i, 5947.0 + i, 5951.0 + i, 1000.0)

        runner.run(bars)
        # OFE should have ATR set (not the default 1.0)
        assert strategy._ofe._atr != 1.0
