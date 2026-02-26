"""FlofState — Singleton that holds the live FlofStrategy instance and provides API snapshots."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from flof_matrix.config.toggle_registry import TOGGLE_KEY_MAP, TOGGLE_DEPENDENCIES, SAFETY_TOGGLES
from flof_matrix.core.types import PredatorState


class BacktestJob:
    """Tracks a running backtest."""

    def __init__(self, job_id: str, params: dict) -> None:
        self.job_id = job_id
        self.params = params
        self.status: str = "running"  # running, completed, failed
        self.progress: int = 0
        self.total_bars: int = 0
        self.results: dict | None = None
        self.error: str | None = None


class FlofState:
    """Singleton holding strategy state + backtest job tracking."""

    _instance: FlofState | None = None
    _lock = threading.Lock()

    def __new__(cls) -> FlofState:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self.strategy = None  # FlofStrategy | None
        self.runner = None  # BacktestRunner | None
        self.jobs: dict[str, BacktestJob] = {}
        self._initialized = True

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def create_job(self, params: dict) -> BacktestJob:
        job_id = str(uuid.uuid4())[:8]
        job = BacktestJob(job_id, params)
        self.jobs[job_id] = job
        return job

    def snapshot_dashboard(self) -> dict[str, Any]:
        s = self.strategy
        if s is None:
            return {
                "state": "idle",
                "equity": 0,
                "peak_equity": 0,
                "max_drawdown": 0,
                "max_drawdown_pct": 0,
                "current_price": 0,
                "atr": 0,
                "trade_count": 0,
                "open_positions": 0,
                "predator_state": "DORMANT",
                "macro_bias": None,
                "regime": "neutral",
                "win_rate": 0,
                "profit_factor": 0,
                "total_pnl": 0,
            }

        trades = s._trades
        closed = [t for t in trades if t.get("exit_price", 0) != 0]
        wins = [t for t in closed if t.get("pnl_dollars", 0) > 0]
        losses = [t for t in closed if t.get("pnl_dollars", 0) < 0]
        gross_profit = sum(t["pnl_dollars"] for t in wins) if wins else 0
        gross_loss = abs(sum(t["pnl_dollars"] for t in losses)) if losses else 0

        return {
            "state": "active",
            "equity": s._equity,
            "peak_equity": s._peak_equity,
            "max_drawdown": s._max_drawdown,
            "max_drawdown_pct": s._max_drawdown_pct,
            "current_price": s._current_price,
            "atr": s._atr,
            "trade_count": s._trade_count,
            "open_positions": len(s._trade_manager.positions),
            "predator_state": s._predator.state.name,
            "macro_bias": s._macro_bias.name if s._macro_bias else None,
            "regime": s._regime,
            "win_rate": len(wins) / len(closed) if closed else 0,
            "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0,
            "total_pnl": sum(t.get("pnl_dollars", 0) for t in trades),
        }

    def snapshot_positions(self) -> list[dict[str, Any]]:
        s = self.strategy
        if s is None:
            return []

        positions = []
        for pid, pos in s._trade_manager.positions.items():
            positions.append({
                "position_id": pos.position_id,
                "direction": pos.direction.name,
                "grade": pos.grade.value,
                "entry_price": pos.entry_price,
                "stop_price": pos.stop_price,
                "target_price": pos.target_price,
                "total_contracts": pos.total_contracts,
                "remaining_contracts": pos.remaining_contracts,
                "phase": pos.phase.name,
                "partial_filled": pos.partial_filled,
                "breakeven_set": pos.breakeven_set,
                "highest_favorable": pos.highest_favorable,
                "entry_time_ns": pos.entry_time_ns,
                "pnl_dollars": pos.pnl_dollars,
                "pnl_r_multiple": pos.pnl_r_multiple,
                "partial_pnl_dollars": pos.partial_pnl_dollars,
            })
        return positions

    def snapshot_trades(self) -> list[dict[str, Any]]:
        s = self.strategy
        if s is None:
            return []

        result = []
        for t in s._trades:
            result.append({
                "position_id": t.get("position_id", ""),
                "direction": t.get("direction", ""),
                "grade": t.get("grade", ""),
                "score_total": t.get("score_total", 0),
                "score_tier1": t.get("score_tier1", 0),
                "score_tier2": t.get("score_tier2", 0),
                "score_tier3": t.get("score_tier3", 0),
                "entry_price": t.get("entry_price", 0),
                "stop_price": t.get("stop_price", 0),
                "target_price": t.get("target_price", 0),
                "exit_price": t.get("exit_price", 0),
                "contracts": t.get("contracts", 0),
                "pnl_dollars": t.get("pnl_dollars", 0),
                "pnl_r_multiple": t.get("pnl_r_multiple", 0),
                "exit_reason": t.get("exit_reason", ""),
                "poi_type": t.get("poi_type", ""),
                "timestamp_ns": t.get("timestamp_ns", 0),
                "exit_time_ns": t.get("exit_time_ns", 0),
            })
        return result

    def snapshot_scoring(self) -> dict[str, Any]:
        s = self.strategy
        if s is None:
            return {"trades": [], "rejections": [], "grade_distribution": {}}

        trades = s._trades
        grade_dist = {"A+": 0, "A": 0, "B": 0, "C": 0}
        for t in trades:
            g = t.get("grade", "C")
            if g in grade_dist:
                grade_dist[g] += 1

        return {
            "trades": self.snapshot_trades()[-20:],  # Last 20
            "rejections": [
                {
                    "reason": r.get("reason", ""),
                    "gate": r.get("gate", ""),
                    "timestamp_ns": r.get("timestamp_ns", 0),
                    "direction": r.get("direction", ""),
                    "score": r.get("score", 0),
                }
                for r in (s._rejections[-20:] if s._rejections else [])
            ],
            "grade_distribution": grade_dist,
        }

    def snapshot_risk(self) -> dict[str, Any]:
        s = self.strategy
        if s is None:
            return {"pillars": {}, "gates": {}, "is_flattened": False}

        ro = s._risk_overlord
        pm = s._portfolio_manager

        return {
            "pillars": {
                "T25_rate_limit": {
                    "name": "Anti-Spam Rate Limiter",
                    "status": "ok",
                    "current_positions": ro._current_positions,
                },
                "T26_position_limit": {
                    "name": "Fat Finger Position Limit",
                    "status": "ok",
                },
                "T27_daily_drawdown": {
                    "name": "Daily Drawdown Breaker",
                    "daily_pnl_pct": ro._daily_pnl_pct,
                },
                "T28_stale_data": {
                    "name": "Stale Data Monitor",
                    "status": "ok" if ro._stale_alert_start_ns is None else "alert",
                },
            },
            "gates": {
                "P1_total_exposure": {
                    "name": "Max Total Exposure",
                    "current": pm.total_exposure,
                    "limit": pm._p1_max_total_exposure,
                },
                "P2_group_limit": {
                    "name": "Correlation Group Limit",
                },
                "P3_daily_drawdown": {
                    "name": "Daily Drawdown Gate",
                },
                "P4_loss_streak": {
                    "name": "Loss Streak Gate",
                    "consecutive_losses": ro._consecutive_losses,
                },
                "P5_lockout": {
                    "name": "Post-Nuclear Lockout",
                },
            },
            "is_flattened": ro.is_flattened,
            "consecutive_losses": ro._consecutive_losses,
        }

    def snapshot_config(self) -> dict[str, Any]:
        s = self.strategy
        if s is None:
            return {}
        return s._config.raw

    def snapshot_toggles(self) -> list[dict[str, Any]]:
        s = self.strategy
        if s is None:
            return []

        toggles = []
        config = s._config

        # Category mapping
        categories = {
            "structure": ["T01", "T02", "T03", "T04", "T05", "T31", "T32", "T39", "T40"],
            "execution": ["T06", "T07", "T08", "T09", "T10", "T11", "T33", "T34"],
            "velez": ["T12", "T13", "T14", "T15", "T16"],
            "risk": ["T17", "T18", "T19", "T20", "T21", "T22", "T23", "T35", "T36", "T48"],
            "safety": ["T24", "T25", "T26", "T27", "T28", "T29", "T30"],
            "multi_asset": ["T37", "T38", "T41", "T42", "T43", "T44", "T45"],
            "options": ["T46", "T47", "T49", "T50"],
        }

        # Toggle names (short labels)
        toggle_names = {
            "T01": "HTF Structure Mapper",
            "T02": "HTF Regime Filter",
            "T03": "Synthetic MA POI",
            "T04": "POI Freshness Tracking",
            "T05": "Liquidity Sweep Detection",
            "T06": "1m CHOCH Detection",
            "T07": "Order Flow Confirmation",
            "T08": "Absorption Detection",
            "T09": "Whale Watch Filter",
            "T10": "Killzone Time Gate",
            "T11": "Fast Move Switch",
            "T12": "20 SMA Halt Confluence",
            "T13": "Flat 200 SMA Confluence",
            "T14": "Elephant Bar Confirmation",
            "T15": "20 SMA Micro-Trend",
            "T16": "All Velez Layers",
            "T17": "HVN/LVN Stop Placement",
            "T18": "Conditional Tape Failure",
            "T19": "Structural Node Trail",
            "T20": "RBI/GBI Hold Filter",
            "T21": "20 SMA Health Check",
            "T22": "200 SMA Exit Watch Zone",
            "T23": "Phase 1 Fixed Partial",
            "T24": "OCO Bracket Enforcement",
            "T25": "Anti-Spam Rate Limiter",
            "T26": "Fat Finger Position Limit",
            "T27": "Daily Drawdown Breaker",
            "T28": "Stale Data Monitor",
            "T29": "Sudden Move Classifier",
            "T30": "Cascade Position Override",
            "T31": "MTF POI Hierarchy",
            "T32": "POI Clustering",
            "T33": "DataBento Schema Shifting",
            "T34": "Proximity Halo Dynamic",
            "T35": "Toxicity Timer",
            "T36": "A+ Scale-Out Override",
            "T37": "Cross-Asset Correlation",
            "T38": "Macro Dump Detector",
            "T39": "Extreme/Decisional Tagging",
            "T40": "Unicorn POI Detection",
            "T41": "Equities Earnings Shield",
            "T42": "Crypto Funding Rate",
            "T43": "Crypto OI Delta Tracker",
            "T44": "Forex Session Overlap",
            "T45": "Multi-Exchange Arb",
            "T46": "Options Routing",
            "T47": "GEX-Aware Selling",
            "T48": "Toxicity Exit",
            "T49": "Forex Carry Trade",
            "T50": "Iron Condor Chop",
        }

        for category, ids in categories.items():
            for tid in ids:
                key = TOGGLE_KEY_MAP.get(tid)
                if key is None:
                    continue
                parents = TOGGLE_DEPENDENCIES.get(tid, [])
                toggles.append({
                    "id": tid,
                    "name": toggle_names.get(tid, tid),
                    "category": category,
                    "enabled": config.is_toggle_enabled(tid),
                    "raw_value": config.get(key, False),
                    "is_safety": tid in SAFETY_TOGGLES,
                    "parents": parents,
                    "key": key,
                })
        return toggles

    def snapshot_equity_curve(self) -> list[dict[str, Any]]:
        s = self.strategy
        if s is None:
            return []
        return [{"timestamp_ns": ts, "equity": eq} for ts, eq in s._equity_curve]

    def snapshot_pois(self) -> list[dict[str, Any]]:
        s = self.strategy
        if s is None:
            return []

        return [
            {
                "type": poi.type.name,
                "price": poi.price,
                "zone_high": poi.zone_high,
                "zone_low": poi.zone_low,
                "timeframe": poi.timeframe,
                "direction": poi.direction.name,
                "is_extreme": poi.is_extreme,
                "is_decisional": poi.is_decisional,
                "is_flip_zone": poi.is_flip_zone,
                "is_sweep_zone": poi.is_sweep_zone,
                "is_unicorn": poi.is_unicorn,
                "has_inducement": poi.has_inducement,
                "is_fresh": poi.is_fresh,
            }
            for poi in s._active_pois
        ]
