"""NumPy pre-allocated circular buffer for trade ticks.

Performance budget: push < 5 microseconds (O(1)).
Fix A: Buffer starts filling at Killzone entry (not Halo breach),
so by the time Stalking starts, it has 60+ seconds of data.
"""

from __future__ import annotations

import numpy as np

# Structured dtype for trade ticks
TICK_DTYPE = np.dtype([
    ("timestamp_ns", np.int64),
    ("price", np.float64),
    ("size", np.float64),
    ("side", np.int8),      # 1 = buy, -1 = sell
    ("flags", np.uint8),
])


class RingBuffer:
    """NumPy pre-allocated circular buffer for trade tick data.

    All operations are O(1) or O(n) on the window size, never on capacity.
    """

    def __init__(self, capacity: int = 500_000) -> None:
        self._capacity = capacity
        self._buffer = np.zeros(capacity, dtype=TICK_DTYPE)
        self._head = 0       # next write position
        self._count = 0      # total records in buffer (capped at capacity)

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def count(self) -> int:
        return self._count

    def push(self, timestamp_ns: int, price: float, size: float, side: int, flags: int = 0) -> None:
        """Push a single record. O(1), budget < 5 microseconds."""
        idx = self._head
        self._buffer[idx]["timestamp_ns"] = timestamp_ns
        self._buffer[idx]["price"] = price
        self._buffer[idx]["size"] = size
        self._buffer[idx]["side"] = side
        self._buffer[idx]["flags"] = flags
        self._head = (idx + 1) % self._capacity
        if self._count < self._capacity:
            self._count += 1

    def push_array(self, records: np.ndarray) -> None:
        """Push multiple records at once. More efficient for bulk loads."""
        n = len(records)
        if n == 0:
            return
        if n >= self._capacity:
            # Only keep the last capacity records
            records = records[-self._capacity:]
            n = self._capacity

        end = self._head + n
        if end <= self._capacity:
            self._buffer[self._head:end] = records
        else:
            first = self._capacity - self._head
            self._buffer[self._head:self._capacity] = records[:first]
            self._buffer[:n - first] = records[first:]

        self._head = end % self._capacity
        self._count = min(self._count + n, self._capacity)

    def window(self, seconds: float) -> np.ndarray:
        """Return records within the last N seconds.

        Uses the most recent record's timestamp as reference.
        Returns a contiguous copy for vectorized operations.
        """
        if self._count == 0:
            return np.zeros(0, dtype=TICK_DTYPE)

        # Get all valid data
        data = self._get_ordered_data()
        if len(data) == 0:
            return np.zeros(0, dtype=TICK_DTYPE)

        latest_ts = data[-1]["timestamp_ns"]
        cutoff = latest_ts - int(seconds * 1_000_000_000)

        mask = data["timestamp_ns"] >= cutoff
        return data[mask].copy()

    def window_ns(self, nanoseconds: int) -> np.ndarray:
        """Return records within the last N nanoseconds (avoids float conversion)."""
        if self._count == 0:
            return np.zeros(0, dtype=TICK_DTYPE)

        data = self._get_ordered_data()
        if len(data) == 0:
            return np.zeros(0, dtype=TICK_DTYPE)

        latest_ts = data[-1]["timestamp_ns"]
        cutoff = latest_ts - nanoseconds
        mask = data["timestamp_ns"] >= cutoff
        return data[mask].copy()

    def is_ready(self, min_seconds: float) -> bool:
        """True if buffer has >= min_seconds of data.

        Fix A: Called to verify buffer readiness before state transitions.
        """
        if self._count < 2:
            return False
        data = self._get_ordered_data()
        span_ns = int(data[-1]["timestamp_ns"]) - int(data[0]["timestamp_ns"])
        return span_ns >= int(min_seconds * 1_000_000_000)

    def latest(self) -> np.void | None:
        """Return the most recently pushed record, or None if empty."""
        if self._count == 0:
            return None
        idx = (self._head - 1) % self._capacity
        return self._buffer[idx]

    def clear(self) -> None:
        """Reset buffer without reallocation."""
        self._head = 0
        self._count = 0
        # No need to zero the array — count tracks validity

    def _get_ordered_data(self) -> np.ndarray:
        """Return all valid records in chronological order."""
        if self._count == 0:
            return np.zeros(0, dtype=TICK_DTYPE)

        if self._count < self._capacity:
            # Buffer hasn't wrapped yet
            return self._buffer[:self._count]
        else:
            # Buffer has wrapped: oldest data starts at head
            return np.concatenate([
                self._buffer[self._head:],
                self._buffer[:self._head],
            ])
