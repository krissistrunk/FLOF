"""WebSocket endpoint — streams dashboard updates and trade events."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from flof_matrix.server.state import FlofState

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections and broadcasts."""

    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)
        logger.info("WebSocket client connected (%d active)", len(self.active))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)
        logger.info("WebSocket client disconnected (%d active)", len(self.active))

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    state = FlofState()

    try:
        while True:
            # Wait for client messages (subscription, ping) or timeout for broadcast
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=0.5)
                # Client can send channel subscriptions (future use)
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                pass

            # Broadcast dashboard snapshot
            snapshot = state.snapshot_dashboard()
            await ws.send_json({"type": "dashboard", "data": snapshot})

            # Check for active backtest jobs and send progress
            for job_id, job in state.jobs.items():
                if job.status == "running":
                    await ws.send_json({
                        "type": "backtest_progress",
                        "data": {
                            "job_id": job.job_id,
                            "progress": job.progress,
                            "total_bars": job.total_bars,
                        },
                    })

    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        manager.disconnect(ws)
