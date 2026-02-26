"""Event Calendar — Loads scheduled events for Type A sudden move detection.

Events: CPI, FOMC, NFP, earnings, token unlocks.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class EventCalendar:
    """Manages scheduled economic events for Type A detection."""

    def __init__(self, cooldown_seconds: int = 180) -> None:
        self._events: list[dict] = []
        self._cooldown = timedelta(seconds=cooldown_seconds)

    def load_events(self, year: int) -> None:
        """Load events for a given year from data file, with built-in fallback."""
        data_path = Path(__file__).parent.parent.parent / "data" / f"events_{year}.json"
        if data_path.exists():
            self.load_from_json(data_path)
            return

        # Built-in fallback for 2024
        if year == 2024:
            self._events = _EVENTS_2024
            logger.info("Loaded %d built-in events for 2024", len(self._events))
        else:
            logger.warning("No event data for year %d", year)

    def load_from_json(self, path: str | Path) -> None:
        """Load events from JSON file.

        Expected format:
        [
            {"name": "CPI", "datetime": "2024-01-11T08:30:00", "impact": "high"},
            {"name": "FOMC", "datetime": "2024-01-31T14:00:00", "impact": "high"},
            ...
        ]
        """
        path = Path(path)
        if not path.exists():
            logger.warning("Event calendar file not found: %s", path)
            return

        with open(path) as f:
            self._events = json.load(f)
        logger.info("Loaded %d events from %s", len(self._events), path)

    def load_from_list(self, events: list[dict]) -> None:
        """Load events from a list of dicts."""
        self._events = events

    def has_active_event(self, current_time: datetime) -> bool:
        """Check if any scheduled event is within cooldown window."""
        for event in self._events:
            event_time = self._parse_datetime(event.get("datetime", ""))
            if event_time is None:
                continue

            # Event is "active" from event_time to event_time + cooldown
            if event_time <= current_time <= event_time + self._cooldown:
                return True

            # Also check pre-event window (2 minutes before)
            pre_event = event_time - timedelta(minutes=2)
            if pre_event <= current_time <= event_time:
                return True

        return False

    def get_next_event(self, current_time: datetime) -> dict | None:
        """Get the next upcoming event."""
        upcoming = []
        for event in self._events:
            event_time = self._parse_datetime(event.get("datetime", ""))
            if event_time and event_time > current_time:
                upcoming.append((event_time, event))

        if not upcoming:
            return None

        upcoming.sort(key=lambda x: x[0])
        return upcoming[0][1]

    @staticmethod
    def _parse_datetime(dt_str: str) -> datetime | None:
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str)
        except (ValueError, TypeError):
            return None


# Built-in 2024 macro events (FOMC, NFP, CPI)
_EVENTS_2024 = [
    # FOMC rate decisions
    {"name": "FOMC", "datetime": "2024-01-31T14:00:00", "impact": "high", "type": "FOMC"},
    {"name": "FOMC", "datetime": "2024-03-20T14:00:00", "impact": "high", "type": "FOMC"},
    {"name": "FOMC", "datetime": "2024-05-01T14:00:00", "impact": "high", "type": "FOMC"},
    {"name": "FOMC", "datetime": "2024-06-12T14:00:00", "impact": "high", "type": "FOMC"},
    {"name": "FOMC", "datetime": "2024-07-31T14:00:00", "impact": "high", "type": "FOMC"},
    {"name": "FOMC", "datetime": "2024-09-18T14:00:00", "impact": "high", "type": "FOMC"},
    {"name": "FOMC", "datetime": "2024-11-07T14:00:00", "impact": "high", "type": "FOMC"},
    {"name": "FOMC", "datetime": "2024-12-18T14:00:00", "impact": "high", "type": "FOMC"},
    # NFP (first Friday of each month, 08:30 ET)
    {"name": "NFP", "datetime": "2024-01-05T08:30:00", "impact": "high", "type": "NFP"},
    {"name": "NFP", "datetime": "2024-02-02T08:30:00", "impact": "high", "type": "NFP"},
    {"name": "NFP", "datetime": "2024-03-08T08:30:00", "impact": "high", "type": "NFP"},
    {"name": "NFP", "datetime": "2024-04-05T08:30:00", "impact": "high", "type": "NFP"},
    {"name": "NFP", "datetime": "2024-05-03T08:30:00", "impact": "high", "type": "NFP"},
    {"name": "NFP", "datetime": "2024-06-07T08:30:00", "impact": "high", "type": "NFP"},
    {"name": "NFP", "datetime": "2024-07-05T08:30:00", "impact": "high", "type": "NFP"},
    {"name": "NFP", "datetime": "2024-08-02T08:30:00", "impact": "high", "type": "NFP"},
    {"name": "NFP", "datetime": "2024-09-06T08:30:00", "impact": "high", "type": "NFP"},
    {"name": "NFP", "datetime": "2024-10-04T08:30:00", "impact": "high", "type": "NFP"},
    {"name": "NFP", "datetime": "2024-11-01T08:30:00", "impact": "high", "type": "NFP"},
    {"name": "NFP", "datetime": "2024-12-06T08:30:00", "impact": "high", "type": "NFP"},
    # CPI (typically mid-month, 08:30 ET)
    {"name": "CPI", "datetime": "2024-01-11T08:30:00", "impact": "high", "type": "CPI"},
    {"name": "CPI", "datetime": "2024-02-13T08:30:00", "impact": "high", "type": "CPI"},
    {"name": "CPI", "datetime": "2024-03-12T08:30:00", "impact": "high", "type": "CPI"},
    {"name": "CPI", "datetime": "2024-04-10T08:30:00", "impact": "high", "type": "CPI"},
    {"name": "CPI", "datetime": "2024-05-15T08:30:00", "impact": "high", "type": "CPI"},
    {"name": "CPI", "datetime": "2024-06-12T08:30:00", "impact": "high", "type": "CPI"},
    {"name": "CPI", "datetime": "2024-07-11T08:30:00", "impact": "high", "type": "CPI"},
    {"name": "CPI", "datetime": "2024-08-14T08:30:00", "impact": "high", "type": "CPI"},
    {"name": "CPI", "datetime": "2024-09-11T08:30:00", "impact": "high", "type": "CPI"},
    {"name": "CPI", "datetime": "2024-10-10T08:30:00", "impact": "high", "type": "CPI"},
    {"name": "CPI", "datetime": "2024-11-13T08:30:00", "impact": "high", "type": "CPI"},
    {"name": "CPI", "datetime": "2024-12-11T08:30:00", "impact": "high", "type": "CPI"},
]
