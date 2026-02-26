"""Action endpoints — mutations (toggle changes, nuclear flatten, backtest runs)."""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from flof_matrix.config.config_manager import ConfigManager, _set_nested
from flof_matrix.config.toggle_registry import TOGGLE_KEY_MAP, SAFETY_TOGGLES
from flof_matrix.nautilus.backtest_runner import BacktestRunner, BAR_DTYPE
from flof_matrix.server.state import FlofState

router = APIRouter(prefix="/api", tags=["actions"])


class ToggleRequest(BaseModel):
    enabled: bool


class BacktestRequest(BaseModel):
    instrument: str = "ES"
    profile: str = "futures"
    fill_level: int = 2
    engine: str = "manual"
    data_file: str = ""


@router.post("/toggles/{toggle_id}")
def set_toggle(toggle_id: str, req: ToggleRequest):
    state = FlofState()
    if state.strategy is None:
        raise HTTPException(status_code=409, detail="No active strategy. Run a backtest first.")

    toggle_id = toggle_id.upper()
    if toggle_id not in TOGGLE_KEY_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown toggle: {toggle_id}")

    config = state.strategy._config
    if config.get("system.live_mode", False) and toggle_id in SAFETY_TOGGLES:
        raise HTTPException(status_code=403, detail=f"Safety toggle {toggle_id} is locked in live mode.")

    key = TOGGLE_KEY_MAP[toggle_id]
    _set_nested(config._config, key, req.enabled)

    return {
        "toggle_id": toggle_id,
        "enabled": config.is_toggle_enabled(toggle_id),
        "raw_value": req.enabled,
    }


@router.post("/nuclear-flatten")
def nuclear_flatten():
    state = FlofState()
    if state.strategy is None:
        raise HTTPException(status_code=409, detail="No active strategy.")

    state.strategy.flatten_all_positions()
    state.strategy.force_dormant()
    return {"status": "flattened", "positions_remaining": len(state.strategy._trade_manager.positions)}


@router.post("/backtest/run")
def run_backtest(req: BacktestRequest):
    state = FlofState()

    job = state.create_job(req.model_dump())

    def _run():
        try:
            config_path = Path("flof_matrix/config/flof_base.toml")
            runner = BacktestRunner(
                config_path=config_path,
                profile=req.profile,
                instrument=req.instrument if req.instrument != "ES" else None,
                fill_level=req.fill_level,
            )
            strategy = runner.setup()
            state.strategy = strategy
            state.runner = runner

            # Load data
            bars = _load_bars(req.data_file, req.instrument)
            if bars is None or len(bars) == 0:
                job.status = "failed"
                job.error = "No bar data found. Place .npy files in data/ directory."
                return

            job.total_bars = len(bars)

            # Run with progress tracking
            strategy.on_start()
            for i in range(len(bars)):
                bar = {
                    "timestamp_ns": int(bars[i]["timestamp_ns"]),
                    "open": float(bars[i]["open"]),
                    "high": float(bars[i]["high"]),
                    "low": float(bars[i]["low"]),
                    "close": float(bars[i]["close"]),
                    "volume": float(bars[i]["volume"]),
                }
                strategy.on_bar(bar)
                if i % 100 == 0:
                    job.progress = i + 1

            strategy.on_stop()
            job.progress = job.total_bars

            job.results = runner._build_results(len(bars), 0)
            job.status = "completed"
        except Exception as e:
            job.status = "failed"
            job.error = str(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return {"job_id": job.job_id, "status": "running"}


@router.get("/backtest/status/{job_id}")
def get_backtest_status(job_id: str):
    state = FlofState()
    job = state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    result = {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "total_bars": job.total_bars,
        "params": job.params,
    }
    if job.status == "completed" and job.results:
        result["summary"] = {
            "trade_count": job.results.get("trade_count", 0),
            "total_pnl": job.results.get("total_pnl", 0),
            "final_equity": job.results.get("final_equity", 0),
            "win_rate": job.results.get("win_rate", 0),
            "max_drawdown": job.results.get("max_drawdown", 0),
            "max_drawdown_pct": job.results.get("max_drawdown_pct", 0),
        }
    if job.error:
        result["error"] = job.error

    return result


@router.get("/backtest/jobs")
def list_jobs():
    state = FlofState()
    return [
        {
            "job_id": j.job_id,
            "status": j.status,
            "progress": j.progress,
            "total_bars": j.total_bars,
            "params": j.params,
        }
        for j in state.jobs.values()
    ]


def _load_bars(data_file: str, instrument: str) -> np.ndarray | None:
    """Load bar data from file or discover from data/ directory."""
    data_dir = Path("data")

    if data_file:
        p = Path(data_file)
        if p.exists() and p.suffix == ".npy":
            return np.load(str(p))

    # Auto-discover from data/
    if data_dir.exists():
        patterns = [f"{instrument}*.npy", "*.npy"]
        for pattern in patterns:
            files = sorted(data_dir.glob(pattern))
            if files:
                return np.load(str(files[0]))

    # Try catalog
    catalog_path = data_dir / "catalog"
    if catalog_path.exists():
        return BacktestRunner.load_catalog_bars(catalog_path, instrument=instrument)

    return None
