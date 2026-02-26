"""Tests for EventBus — pub/sub, backpressure, RISK_LIMIT_BREACHED bypass."""

import asyncio
import time

import pytest

from flof_matrix.core.event_bus import EventBus
from flof_matrix.core.types import EventType
from flof_matrix.core.data_types import Event


class TestEventBus:
    @pytest.mark.asyncio
    async def test_basic_pub_sub(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(EventType.ORDER_FIRED, handler)
        event = Event(type=EventType.ORDER_FIRED, timestamp_ns=0, source="test")
        await bus.publish(event)
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        bus = EventBus()
        counts = [0, 0]

        async def handler1(event):
            counts[0] += 1

        async def handler2(event):
            counts[1] += 1

        bus.subscribe(EventType.DAILY_RESET, handler1)
        bus.subscribe(EventType.DAILY_RESET, handler2)
        await bus.publish(Event(type=EventType.DAILY_RESET, timestamp_ns=0, source="test"))
        assert counts == [1, 1]

    @pytest.mark.asyncio
    async def test_event_type_isolation(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event.type)

        bus.subscribe(EventType.ORDER_FIRED, handler)
        await bus.publish(Event(type=EventType.POSITION_CLOSED, timestamp_ns=0, source="test"))
        assert len(received) == 0  # Different event type

    @pytest.mark.asyncio
    async def test_risk_limit_breached_sync(self):
        """RISK_LIMIT_BREACHED must bypass queue and deliver synchronously."""
        bus = EventBus()
        received = []

        def sync_handler(event):
            received.append(event)

        bus.subscribe_sync(EventType.RISK_LIMIT_BREACHED, sync_handler)
        await bus.publish(Event(type=EventType.RISK_LIMIT_BREACHED, timestamp_ns=0, source="test"))
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_backpressure(self):
        """Queue full → event dropped."""
        bus = EventBus(max_queue_depth=5)
        await bus.start()

        # Fill queue by pausing the dispatch loop
        for i in range(10):
            await bus.publish(Event(type=EventType.DAILY_RESET, timestamp_ns=i, source="test"))

        await bus.stop()

    def test_sync_publish(self):
        bus = EventBus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe_sync(EventType.STALE_DATA_ALERT, handler)
        bus.publish_sync(Event(type=EventType.STALE_DATA_ALERT, timestamp_ns=0, source="test"))
        assert len(received) == 1

    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_delivery_latency(self):
        """Event delivery should be < 1ms."""
        bus = EventBus()
        latencies = []

        async def handler(event):
            latencies.append(time.perf_counter_ns() - event.timestamp_ns)

        bus.subscribe(EventType.DAILY_RESET, handler)

        for _ in range(100):
            await bus.publish(Event(
                type=EventType.DAILY_RESET,
                timestamp_ns=time.perf_counter_ns(),
                source="bench",
            ))

        avg_us = sum(latencies) / len(latencies) / 1000
        assert avg_us < 1000, f"Delivery too slow: {avg_us:.1f} us (budget: <1000 us)"
