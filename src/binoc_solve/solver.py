"""Wraps cedar-solve's Tetra3 lost-in-space solver."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from binoc_solve.config import SolverConfig

logger = logging.getLogger(__name__)

# Mirrors tetra3.tetra3.MATCH_FOUND (not re-exported from the tetra3
# package's top-level __init__.py, so duplicated here rather than
# reaching into the private submodule). solve_from_centroids() returns
# this as an int (1), not the string "MATCH_FOUND" - comparing against
# the string here previously meant every solve, matched or not, was
# silently treated as a failure.
_MATCH_FOUND = 1


@dataclass(frozen=True)
class SolveResult:
    ra_deg: float
    dec_deg: float
    roll_deg: float
    fov_deg: float
    num_matches: int


class Solver:
    def __init__(self, config: SolverConfig) -> None:
        from tetra3 import Tetra3  # noqa: PLC0415 - only needed once cedar-solve is installed

        self._config = config
        # A bare string is looked up in cedar-solve's own tetra3/data dir
        # (the bundled default_database lives there); a Path is used as-is,
        # which is what scripts/build_database.py writes custom databases to.
        db = config.database_path
        load_arg = Path(db) if db is not None else "default_database"
        self._t3 = Tetra3(load_database=load_arg)
        # cedar-solve's solve_from_centroids() picks pattern stars from the
        # full centroid list but then truncates its own copy to this many,
        # so any pattern star past the cutoff raises IndexError and kills
        # the solve loop (seen with ~350 centroids against a 150 limit).
        # Truncating here first keeps both lists the same length.
        self._max_centroids = int(self._t3.database_properties["verification_stars_per_fov"])
        self._lock = threading.Lock()
        self._solve_id = 0
        self._solve_started: float | None = None  # monotonic; None while idle
        self._pending_timer: threading.Timer | None = None

    def supersede(self) -> None:
        """A newer frame has arrived: abandon the in-progress solve for it,
        once that solve has run supersede_after_ms. The floor keeps slow
        but valid solves on faint frames (they've been seen to need
        ~0.3-0.6s) from being thrown away just because the camera is
        quicker; doomed solves on smeared mid-slew frames are cut short
        instead of burning the whole solve_timeout_ms. Safe to call from
        any thread, and a no-op while idle."""
        with self._lock:
            if self._solve_started is None:
                return
            solve_id = self._solve_id
            wait_s = self._config.supersede_after_ms / 1000 - (time.monotonic() - self._solve_started)
            if wait_s <= 0:
                self._cancel_locked(solve_id)
            elif self._pending_timer is None:
                self._pending_timer = threading.Timer(wait_s, self._cancel_if_still, args=(solve_id,))
                self._pending_timer.daemon = True
                self._pending_timer.start()

    def _cancel_if_still(self, solve_id: int) -> None:
        with self._lock:
            self._pending_timer = None
            self._cancel_locked(solve_id)

    def _cancel_locked(self, solve_id: int) -> None:
        # Only the solve the request was aimed at - tetra3's cancel flag
        # otherwise persists and would abort the *next* solve instead.
        if self._solve_started is not None and self._solve_id == solve_id:
            logger.debug("Superseding solve %d with a newer frame", solve_id)
            self._t3.cancel_solve()

    def solve(self, centroids: list[tuple[float, float]], image_size: tuple[int, int]) -> SolveResult | None:
        if not centroids:
            return None

        # Already brightest-first (detect_client.py), so this keeps the best stars.
        centroids = centroids[: self._max_centroids]

        with self._lock:
            self._solve_id += 1
            self._solve_started = time.monotonic()
            # A cancel that landed just as the previous solve finished would
            # still be set on tetra3 and abort this one immediately.
            self._t3._cancelled = False
        try:
            result = self._t3.solve_from_centroids(
                centroids,
                image_size,
                fov_estimate=self._config.fov_estimate_deg,
                solve_timeout=self._config.solve_timeout_ms,
                match_max_error=self._config.match_max_error,
            )
        finally:
            with self._lock:
                self._solve_started = None
                if self._pending_timer is not None:
                    self._pending_timer.cancel()
                    self._pending_timer = None

        if result["status"] != _MATCH_FOUND:
            logger.debug("Solve failed: status=%s", result["status"])
            return None

        return SolveResult(
            ra_deg=result["RA"],
            dec_deg=result["Dec"],
            roll_deg=result["Roll"],
            fov_deg=result["FOV"],
            num_matches=result["Matches"],
        )
