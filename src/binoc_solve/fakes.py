"""Fake stand-ins for Camera/DetectClient/Solver, for testing the
SkySafari encoder integration end-to-end without a camera, without
cedar-detect/cedar-solve installed, and without even being on a
Raspberry Pi - see scripts/simulate_skysafari.py.

Each implements the same methods the real class does (capture_gray,
extract_centroids, solve) so they drop straight into main._solve_loop
unchanged: the simulator runs the exact same solve-loop, RA/Dec->Alt/Az
conversion, and encoder-server code a real deployment does, with only
the camera/cedar-detect/cedar-solve pipeline replaced.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from binoc_solve.detect_client import DetectionResult
from binoc_solve.solver import SolveResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CannedSolution:
    name: str
    ra_deg: float
    dec_deg: float


# A handful of bright, widely-spaced named stars (J2000 RA/Dec), so
# cycling through them visibly moves SkySafari's crosshair to different
# parts of the sky. Edit this list (or pass your own to FakeSolver) to
# test specific positions, e.g. near the horizon or near the pole.
DEFAULT_SOLUTIONS: list[CannedSolution] = [
    CannedSolution("Polaris", ra_deg=37.95, dec_deg=89.26),
    CannedSolution("Vega", ra_deg=279.23, dec_deg=38.78),
    CannedSolution("Betelgeuse", ra_deg=88.79, dec_deg=7.41),
    CannedSolution("Sirius", ra_deg=101.29, dec_deg=-16.72),
    CannedSolution("Achernar", ra_deg=24.43, dec_deg=-57.24),
]


class FakeCamera:
    """The fake solver never inspects the image content, so this just
    returns something cheap and correctly shaped instead of touching a
    real camera."""

    def capture_gray(self) -> np.ndarray:
        return np.zeros((16, 16), dtype=np.uint8)

    def close(self) -> None:
        pass


class FakeDetectClient:
    """No-op stand-in for DetectClient - FakeSolver ignores centroids
    entirely, so there's nothing for this to compute."""

    def extract_centroids(self, image: np.ndarray) -> DetectionResult:
        return DetectionResult(centroids=[], peak_star_pixel=0, noise_estimate=0.0)


class FakeSolver:
    """Cycles through a fixed list of canned RA/Dec "solutions" instead
    of actually solving anything. next()/select() change which one
    solve() returns next; all three are safe to call from different
    threads (e.g. solve() from the solve loop, next()/select() from a
    terminal-input control loop), guarded the same way LatestFix and
    LocationStore are.
    """

    def __init__(self, solutions: list[CannedSolution] | None = None) -> None:
        self._solutions = list(solutions) if solutions is not None else list(DEFAULT_SOLUTIONS)
        if not self._solutions:
            raise ValueError("At least one canned solution is required")
        self._lock = threading.Lock()
        self._index = 0

    def solve(
        self,
        centroids: list[tuple[float, float]],
        image_size: tuple[int, int],
        timeout_ms: float | None = None,
    ) -> SolveResult:
        with self._lock:
            solution = self._solutions[self._index]
        return SolveResult(
            ra_deg=solution.ra_deg,
            dec_deg=solution.dec_deg,
            roll_deg=0.0,
            fov_deg=30.0,
            num_matches=20,
        )

    def current_name(self) -> str:
        with self._lock:
            return self._solutions[self._index].name

    def next(self) -> str:
        with self._lock:
            self._index = (self._index + 1) % len(self._solutions)
            name = self._solutions[self._index].name
        logger.info("Simulated solve -> %s", name)
        return name

    def select(self, index: int) -> str:
        with self._lock:
            if not 0 <= index < len(self._solutions):
                raise IndexError(f"No solution at index {index}; have {len(self._solutions)}")
            self._index = index
            name = self._solutions[self._index].name
        logger.info("Simulated solve -> %s", name)
        return name

    def list_names(self) -> list[str]:
        return [s.name for s in self._solutions]


@dataclass(frozen=True)
class SlewCenter:
    name: str
    ra_deg: float
    dec_deg: float


# M31/Andromeda (J2000) - bright, widely recognized, and far enough from
# the celestial pole that a +-5 deg swing stays well clear of any RA
# wraparound or declination-clamping edge cases.
ANDROMEDA = SlewCenter("Andromeda (M31)", ra_deg=10.68, dec_deg=41.27)


class SlewingFakeSolver:
    """Continuously reports a smoothly moving RA/Dec that circles a fixed
    center - default Andromeda - swinging +-amplitude_deg east/west and
    north/south, tracing one full circuit every period_s seconds.

    Unlike FakeSolver's discrete named-star list, this needs no next()/
    select() calls to see the position change - it's driven by elapsed
    time alone. That's the point: SimulatorSelector's physical button
    only toggles the simulator on/off (see simulator_selector.py), with
    no keyboard in the field to cycle through canned stars, so a
    continuously moving position is what actually demonstrates the
    SkySafari crosshair tracking a solve.

    East/west motion is along RA, scaled by 1/cos(dec) so amplitude_deg
    means that many true angular degrees on the sky rather than degrees
    of RA (which compress toward the pole - RA degrees are worth less
    the higher the declination). North/south is Dec, a quarter period
    out of phase with RA, so the path traces a circle rather than
    retracing a straight line back and forth.
    """

    def __init__(
        self,
        center: SlewCenter = ANDROMEDA,
        amplitude_deg: float = 5.0,
        period_s: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._center = center
        self._amplitude_deg = amplitude_deg
        self._period_s = period_s
        self._clock = clock
        self._start = clock()

    def solve(
        self,
        centroids: list[tuple[float, float]],
        image_size: tuple[int, int],
        timeout_ms: float | None = None,
    ) -> SolveResult:
        elapsed = self._clock() - self._start
        phase = 2 * math.pi * (elapsed / self._period_s)

        ra_scale = 1.0 / math.cos(math.radians(self._center.dec_deg))
        ra_deg = (self._center.ra_deg + self._amplitude_deg * ra_scale * math.sin(phase)) % 360.0
        dec_deg = self._center.dec_deg + self._amplitude_deg * math.cos(phase)

        return SolveResult(
            ra_deg=ra_deg,
            dec_deg=dec_deg,
            roll_deg=0.0,
            fov_deg=30.0,
            num_matches=20,
        )

    def current_name(self) -> str:
        return f"{self._center.name} (slewing)"
