"""A cyclable list of named observing locations, with the active one
persisted to disk so it survives a power cycle.

Pure logic, no GPIO - see location_selector.py for the button/LED wiring
that drives this. Kept separate so it's unit-testable without hardware.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NamedLocation:
    name: str
    latitude_deg: float
    longitude_deg: float
    elevation_m: float


def blink_count_for_index(index: int) -> int:
    """1-indexed: location 0 blinks once, location 1 blinks twice, etc."""
    return index + 1


class LocationStore:
    """Thread-safe: advance() is called from the button's GPIO callback
    thread; current() is read from the solve loop thread every cycle."""

    def __init__(self, locations: list[NamedLocation], state_file: str | Path) -> None:
        if not locations:
            raise ValueError("At least one location must be configured")
        self._locations = locations
        self._state_file = Path(state_file)
        self._lock = threading.Lock()
        self._index = self._load_index()

    def _load_index(self) -> int:
        try:
            index = int(self._state_file.read_text().strip())
        except (FileNotFoundError, ValueError):
            return 0
        if 0 <= index < len(self._locations):
            return index
        logger.warning("Saved location index %d out of range, starting at 0", index)
        return 0

    def _save_index(self) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(str(self._index))
        except OSError:
            logger.exception("Failed to persist active location index")

    def current(self) -> NamedLocation:
        with self._lock:
            return self._locations[self._index]

    def current_index(self) -> int:
        with self._lock:
            return self._index

    def advance(self) -> NamedLocation:
        """Moves to the next location (wrapping around), persists it, and
        returns it."""
        with self._lock:
            self._index = (self._index + 1) % len(self._locations)
            self._save_index()
            location = self._locations[self._index]
        logger.info(
            "Active location -> [%d] %s (lat=%.4f lon=%.4f)",
            self._index + 1, location.name, location.latitude_deg, location.longitude_deg,
        )
        return location
