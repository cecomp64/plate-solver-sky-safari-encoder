"""Thread-safe on/off flag switching the solve loop's data source
between the real camera/cedar-detect/cedar-solve pipeline and the
canned solutions in fakes.py.

Pure logic, no GPIO - see simulator_selector.py for the button/LED
wiring that drives this. Kept separate for the same reason as
locations.py/location_selector.py: unit-testable without hardware.

Deliberately not persisted across restarts, unlike LocationStore: a
fresh process should always start on the real pipeline, so a forgotten
toggle can't silently keep serving canned positions to SkySafari after
a power cycle in the field.
"""
from __future__ import annotations

import threading


class SimulatorToggle:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._enabled = False

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def toggle(self) -> bool:
        """Flips the flag and returns the new value."""
        with self._lock:
            self._enabled = not self._enabled
            return self._enabled
