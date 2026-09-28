"""Camera stand-in that serves pre-rendered synthetic star-field images
from test_images/ (see scripts/generate_test_image.py) instead of a live
capture, advancing to the next one every interval_s.

Unlike fakes.FakeCamera (a blank image paired with FakeDetectClient/
FakeSolver, which never actually solve anything), this is meant to run
through the *real* cedar-detect/cedar-solve pipeline - see
pipeline_mode.py's SYNTHETIC mode - so a genuine solve happens against
genuine (if synthetic) star positions, exercising the same code path a
real night-sky capture would, without needing to point at open sky.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")


class SyntheticImageCamera:
    def __init__(
        self,
        image_dir: str | Path,
        interval_s: float = 1.5,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._image_dir = Path(image_dir)
        self._paths = (
            sorted(p for p in self._image_dir.iterdir() if p.suffix.lower() in _IMAGE_EXTENSIONS)
            if self._image_dir.is_dir() else []
        )
        if not self._paths:
            # Not fatal - main.py constructs this pipeline unconditionally
            # regardless of which mode is active at startup, same as the
            # real Camera and fakes.FakeCamera, so an empty/missing
            # test_images/ shouldn't crash the service over a mode nobody
            # may ever select.
            logger.warning(
                "No images found in %s - synthetic mode will report a blank frame until some "
                "exist (see scripts/generate_test_image.py)", self._image_dir,
            )
        self._interval_s = interval_s
        self._clock = clock
        self._start = clock()
        self._last_index: int | None = None

    def capture_gray(self) -> np.ndarray:
        if not self._paths:
            return np.zeros((16, 16), dtype=np.uint8)

        elapsed = self._clock() - self._start
        index = int(elapsed // self._interval_s) % len(self._paths)
        path = self._paths[index]
        if index != self._last_index:
            logger.info("Synthetic camera -> %s", path.name)
            self._last_index = index

        with Image.open(path) as img:
            return np.asarray(img.convert("L"), dtype=np.uint8)

    def close(self) -> None:
        pass
