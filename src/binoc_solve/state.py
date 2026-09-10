"""Thread-safe holder for the most recent solved position.

One thread (the solve loop in main.py) writes to this; another (the
encoder TCP server, one thread per SkySafari connection) reads from it.
A plain lock is enough here - updates are infrequent (once per solve
cycle, at most a couple of Hz) and reads are cheap.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Fix:
    alt_deg: float
    az_deg: float
    timestamp: float  # time.monotonic() when this fix was computed


class LatestFix:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fix: Fix | None = None

    def update(self, alt_deg: float, az_deg: float) -> None:
        with self._lock:
            self._fix = Fix(alt_deg=alt_deg, az_deg=az_deg, timestamp=time.monotonic())

    def get(self) -> Fix | None:
        """Returns the last known fix, or None if a solve has never succeeded."""
        with self._lock:
            return self._fix

    def age_seconds(self) -> float | None:
        fix = self.get()
        if fix is None:
            return None
        return time.monotonic() - fix.timestamp
