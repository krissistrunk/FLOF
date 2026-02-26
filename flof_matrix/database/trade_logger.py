"""Trade Logger — Async PostgreSQL writer for trade records.

Non-blocking, queue-based. Writes trade records, signal rejections,
and portfolio snapshots to PostgreSQL.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class TradeLogger:
    """Async trade logger with queue-based non-blocking writes.

    Falls back to in-memory storage when PostgreSQL is unavailable.
    """

    def __init__(
        self,
        dsn: str | None = None,
        max_queue_size: int = 1000,
    ) -> None:
        self._dsn = dsn
        self._max_queue_size = max_queue_size
        self._queue: asyncio.Queue | None = None
        self._running = False
        self._conn = None

        # In-memory fallback
        self._trades: list[dict] = []
        self._rejections: list[dict] = []
        self._snapshots: list[dict] = []

    @property
    def trades(self) -> list[dict]:
        return self._trades

    @property
    def rejections(self) -> list[dict]:
        return self._rejections

    async def start(self) -> None:
        """Start the async writer."""
        self._queue = asyncio.Queue(maxsize=self._max_queue_size)
        self._running = True

        if self._dsn:
            try:
                import psycopg
                self._conn = await psycopg.AsyncConnection.connect(self._dsn)
                logger.info("TradeLogger connected to PostgreSQL")
            except Exception:
                logger.warning("Could not connect to PostgreSQL — using in-memory storage")
                self._conn = None

    async def stop(self) -> None:
        """Stop the writer and flush remaining records."""
        self._running = False
        if self._conn:
            await self._conn.close()

    def log_trade(self, trade: dict) -> None:
        """Log a trade record (non-blocking)."""
        self._trades.append(trade)
        if self._queue and not self._queue.full():
            self._queue.put_nowait(("trade", trade))

    def log_rejection(self, rejection: dict) -> None:
        """Log a signal rejection."""
        self._rejections.append(rejection)

    def log_snapshot(self, snapshot: dict) -> None:
        """Log a portfolio snapshot."""
        self._snapshots.append(snapshot)

    async def _write_trade(self, trade: dict) -> None:
        """Write trade to PostgreSQL."""
        if not self._conn:
            return
        try:
            async with self._conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO flof_trades (
                        position_id, instrument, profile, direction,
                        grade, score_total, score_tier1, score_tier2, score_tier3,
                        entry_price, stop_price, target_price, exit_price,
                        risk_pct, contracts, pnl_dollars, pnl_r_multiple,
                        exit_reason, active_toggles
                    ) VALUES (
                        %(position_id)s, %(instrument)s, %(profile)s, %(direction)s,
                        %(grade)s, %(score_total)s, %(score_tier1)s, %(score_tier2)s, %(score_tier3)s,
                        %(entry_price)s, %(stop_price)s, %(target_price)s, %(exit_price)s,
                        %(risk_pct)s, %(contracts)s, %(pnl_dollars)s, %(pnl_r_multiple)s,
                        %(exit_reason)s, %(active_toggles)s
                    )
                    """,
                    trade,
                )
                await self._conn.commit()
        except Exception:
            logger.exception("Failed to write trade to PostgreSQL")

    def flush_to_db_sync(self) -> int:
        """Synchronously flush in-memory trades and rejections to PostgreSQL.

        Used at backtest end to write all results at once.
        Returns number of records written.
        """
        if not self._dsn:
            logger.info("No DSN — skipping DB flush (%d trades in memory)", len(self._trades))
            return 0

        count = 0
        try:
            import psycopg
            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    for trade in self._trades:
                        clean = self._clean_for_db(trade)
                        try:
                            cur.execute(
                                """
                                INSERT INTO flof_trades (
                                    position_id, instrument, profile, direction,
                                    grade, score_total, score_tier1, score_tier2, score_tier3,
                                    entry_price, stop_price, target_price,
                                    exit_price, exit_reason,
                                    pnl_dollars, pnl_r_multiple,
                                    risk_pct, contracts,
                                    poi_type, active_toggles
                                ) VALUES (
                                    %(position_id)s, %(instrument)s, %(profile)s, %(direction)s,
                                    %(grade)s, %(score_total)s, %(score_tier1)s, %(score_tier2)s, %(score_tier3)s,
                                    %(entry_price)s, %(stop_price)s, %(target_price)s,
                                    %(exit_price)s, %(exit_reason)s,
                                    %(pnl_dollars)s, %(pnl_r_multiple)s,
                                    %(risk_pct)s, %(contracts)s,
                                    %(poi_type)s, %(active_toggles)s
                                )
                                """,
                                clean,
                            )
                            count += 1
                        except Exception:
                            logger.exception("Failed to insert trade %s", clean.get("position_id"))

                    for rejection in self._rejections:
                        clean = self._clean_for_db(rejection)
                        try:
                            cur.execute(
                                """
                                INSERT INTO signal_rejections (
                                    instrument, direction, rejection_gate,
                                    rejection_reason, score_at_rejection,
                                    poi_type, poi_price, context
                                ) VALUES (
                                    %(instrument)s, %(direction)s, %(rejection_gate)s,
                                    %(rejection_reason)s, %(score_at_rejection)s,
                                    %(poi_type)s, %(poi_price)s, %(context)s
                                )
                                """,
                                clean,
                            )
                            count += 1
                        except Exception:
                            pass  # Rejections are best-effort

                conn.commit()
                logger.info("Flushed %d records to PostgreSQL", count)
        except Exception:
            logger.exception("Failed to flush to PostgreSQL")

        return count

    def get_trade_summary(self) -> dict:
        """Generate summary stats from logged trades."""
        if not self._trades:
            return {"total_trades": 0}

        wins = [t for t in self._trades if t.get("pnl_dollars", 0) > 0]
        losses = [t for t in self._trades if t.get("pnl_dollars", 0) < 0]

        total_pnl = sum(t.get("pnl_dollars", 0) for t in self._trades)
        avg_r = sum(t.get("pnl_r_multiple", 0) for t in self._trades) / len(self._trades) if self._trades else 0

        return {
            "total_trades": len(self._trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(self._trades) if self._trades else 0,
            "total_pnl": total_pnl,
            "avg_r_multiple": avg_r,
            "grade_distribution": self._grade_distribution(),
        }

    @staticmethod
    def _clean_for_db(record: dict) -> dict:
        """Convert numpy types to Python native types for psycopg."""
        import numpy as np
        clean = {}
        for k, v in record.items():
            if isinstance(v, (np.integer,)):
                clean[k] = int(v)
            elif isinstance(v, (np.floating,)):
                clean[k] = float(v)
            elif isinstance(v, np.ndarray):
                clean[k] = v.tolist()
            elif isinstance(v, (np.bool_,)):
                clean[k] = bool(v)
            else:
                clean[k] = v
        return clean

    def _grade_distribution(self) -> dict:
        dist = {}
        for t in self._trades:
            grade = t.get("grade", "unknown")
            dist[grade] = dist.get(grade, 0) + 1
        return dist
