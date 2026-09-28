"""Saves the occasional real-camera frame that failed to solve, for
diagnosing field failures after the fact.

The log only says "No solve this cycle (N centroids)" - it can't tell
motion blur from sky glow from cloud. A saved frame can, and it can be
replayed offline through the same detect/solve pipeline with
scripts/solve_image.py. Rate-limited and capped on file count so a whole
night of failures can't fill the SD card.
"""
from __future__ import annotations

import datetime as dt
import logging
import time
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from binoc_solve.config import FailedFramesConfig

logger = logging.getLogger(__name__)


class FailedFrameRecorder:
    def __init__(
        self,
        config: FailedFramesConfig,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._dir = Path(config.dir)
        self._clock = clock
        self._last_saved: float | None = None

    def maybe_save(self, image: np.ndarray, num_centroids: int) -> Path | None:
        """Saves image if enabled and at least min_interval_s has passed
        since the last save. Returns the saved path, else None. Never
        raises - a full or read-only disk mustn't stop the solve loop."""
        cfg = self._config
        if not cfg.enabled:
            return None
        now = self._clock()
        if self._last_saved is not None and now - self._last_saved < cfg.min_interval_s:
            return None
        self._last_saved = now

        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self._dir / f"fail-{stamp}-{num_centroids}c.png"
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            Image.fromarray(image).save(path)
            self._prune()
        except OSError:
            logger.exception("Failed to save failed-solve frame to %s", path)
            return None
        logger.info("Saved failed-solve frame: %s", path)
        return path

    def _prune(self) -> None:
        # Timestamped names sort chronologically, so the oldest go first.
        files = sorted(self._dir.glob("fail-*.png"))
        for old in files[: max(0, len(files) - self._config.max_files)]:
            old.unlink(missing_ok=True)
