"""The solve loop's data-source mode: REAL (camera/cedar-detect/cedar-
solve), SIMULATOR (a smoothly slewing canned position - see fakes.py's
SlewingFakeSolver), or SYNTHETIC (the real cedar-detect/cedar-solve
pipeline fed pre-rendered test images from test_images/ instead of a
live capture, walking through them every few seconds - see
synthetic_camera.py).

Pure logic, no GPIO - see simulator_selector.py for the button/LED
wiring that drives this. Kept separate for the same reason as
locations.py/location_selector.py: unit-testable without hardware.

Deliberately not persisted across restarts, unlike LocationStore: a
fresh process should always start on REAL, so a forgotten mode can't
silently keep serving fake/synthetic positions to SkySafari after a
power cycle in the field.
"""
from __future__ import annotations

import threading
from enum import Enum


class Mode(Enum):
    REAL = "real"
    SIMULATOR = "simulator"
    SYNTHETIC = "synthetic"


_CYCLE = (Mode.REAL, Mode.SIMULATOR, Mode.SYNTHETIC)


class ModeStore:
    """Thread-safe: advance() is called from the button's GPIO callback
    thread; current() is read from the solve loop thread every cycle -
    same pattern as LocationStore."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._index = 0

    def current(self) -> Mode:
        with self._lock:
            return _CYCLE[self._index]

    def current_index(self) -> int:
        with self._lock:
            return self._index

    def advance(self) -> Mode:
        """Moves to the next mode (wrapping around) and returns it."""
        with self._lock:
            self._index = (self._index + 1) % len(_CYCLE)
            return _CYCLE[self._index]
