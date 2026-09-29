"""Wraps cedar-solve's Tetra3 lost-in-space solver."""
from __future__ import annotations

import logging
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

    def solve(
        self,
        centroids: list[tuple[float, float]],
        image_size: tuple[int, int],
        timeout_ms: float | None = None,
    ) -> SolveResult | None:
        """timeout_ms overrides config.solve_timeout_ms for this call - the
        solve loop uses it to stop at the next frame's arrival."""
        if not centroids:
            return None

        # Already brightest-first (detect_client.py), so this keeps the best stars.
        centroids = centroids[: self._max_centroids]

        result = self._t3.solve_from_centroids(
            centroids,
            image_size,
            fov_estimate=self._config.fov_estimate_deg,
            solve_timeout=timeout_ms if timeout_ms is not None else self._config.solve_timeout_ms,
            match_max_error=self._config.match_max_error,
        )

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
