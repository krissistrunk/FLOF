"""Asyncio pub/sub event bus with backpressure protection.

Performance budget: delivery < 1ms.
RISK_LIMIT_BREACHED bypasses queue — synchronous direct callback.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Callable, Coroutine

from flof_matrix.core.types import EventType
from flof_matrix.core.data_types import Event

logger = logging.getLogger(__name__)

# Type alias for callbacks
EventCallback = Callable[[Event], Coroutine[Any, Any, None] | None]


class EventBus:
    """Asyncio event bus with per-type subscriber lists and backpressure.

    RISK_LIMIT_BREACHED events bypass the queue and invoke callbacks synchronously.
    """

    def __init__(self, max_queue_depth: int = 1000) -> None:
        self._subscribers: dict[EventType, list[EventCallback]] = defaultdict(list)
        self._sync_subscribers: dict[EventType, list[Callable[[Event], None]]] = defaultdict(list)
        self._max_queue_depth = max_queue_depth
        self._queue: asyncio.Queue[Event] | None = None
        self._running = False
        self._dispatch_task: asyncio.Task | None = None

    def subscribe(self, event_type: EventType, callback: EventCallback) -> None:
        """Register an async callback for an event type."""
        self._subscribers[event_type].append(callback)

    def subscribe_sync(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        """Register a synchronous callback (used for RISK_LIMIT_BREACHED)."""
        self._sync_subscribers[event_type].append(callback)

    async def publish(self, event: Event) -> None:
        """Publish an event. RISK_LIMIT_BREACHED is delivered synchronously."""
        # RISK_LIMIT_BREACHED bypasses queue — direct synchronous callback
        if event.type == EventType.RISK_LIMIT_BREACHED:
            self._deliver_sync(event)
            return

        # Normal async delivery
        if self._queue is not None:
            if self._queue.qsize() >= self._max_queue_depth:
                logger.warning(
                    "Event bus backpressure: queue full (%d), dropping %s",
                    self._max_queue_depth,
                    event.type.value,
                )
                return
            await self._queue.put(event)
        else:
            # No dispatch loop running — deliver directly
            await self._deliver_async(event)

    def publish_sync(self, event: Event) -> None:
        """Publish synchronously (for non-async contexts like RiskOverlord)."""
        if event.type == EventType.RISK_LIMIT_BREACHED:
            self._deliver_sync(event)
            return
        # For other events in sync context, deliver sync subscribers only
        self._deliver_sync(event)

    async def start(self) -> None:
        """Start the background dispatch loop."""
        if self._running:
            return
        self._queue = asyncio.Queue(maxsize=self._max_queue_depth)
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())

    async def stop(self) -> None:
        """Stop the dispatch loop and drain remaining events."""
        self._running = False
        if self._dispatch_task is not None:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
            self._dispatch_task = None
        self._queue = None

    async def _dispatch_loop(self) -> None:
        """Background loop that processes queued events."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                await self._deliver_async(event)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _deliver_async(self, event: Event) -> None:
        """Deliver event to all async subscribers."""
        callbacks = self._subscribers.get(event.type, [])
        for callback in callbacks:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Error in event handler for %s", event.type.value)

        # Also deliver to sync subscribers
        self._deliver_sync(event)

    def _deliver_sync(self, event: Event) -> None:
        """Deliver event to synchronous subscribers."""
        callbacks = self._sync_subscribers.get(event.type, [])
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                logger.exception("Error in sync event handler for %s", event.type.value)
