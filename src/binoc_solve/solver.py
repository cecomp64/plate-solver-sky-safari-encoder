"""Wraps cedar-solve's Tetra3 lost-in-space solver."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from binoc_solve.config import SolverConfig

logger = logging.getLogger(__name__)

# Mirrors the status constants tetra3.solve_from_centroids() returns in
# its 'status' field.
_MATCH_FOUND = "MATCH_FOUND"


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

    def solve(self, centroids: list[tuple[float, float]], image_size: tuple[int, int]) -> SolveResult | None:
        if not centroids:
            return None

        result = self._t3.solve_from_centroids(
            centroids,
            image_size,
            fov_estimate=self._config.fov_estimate_deg,
            solve_timeout=self._config.solve_timeout_ms,
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
