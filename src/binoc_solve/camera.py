"""Thin wrapper around picamera2 for long-exposure still capture.

picamera2 is only installable via apt (it wraps libcamera, which has no
portable pip wheel), so this module is imported lazily - everything else
in this package stays importable (and unit-testable) on a machine without
it, e.g. for running tests/ off-Pi.
"""
from __future__ import annotations

import logging

import numpy as np

from binoc_solve.config import CameraConfig

logger = logging.getLogger(__name__)


class Camera:
    def __init__(self, config: CameraConfig) -> None:
        from picamera2 import Picamera2  # noqa: PLC0415 - see module docstring

        self._config = config
        self._picam2 = Picamera2()
        still_config = self._picam2.create_still_configuration(
            main={"size": (config.width, config.height), "format": "YUV420"},
            controls={
                "ExposureTime": config.exposure_ms * 1000,  # us
                "AnalogueGain": config.gain,
                "AeEnable": False,
                "AwbEnable": False,
            },
        )
        self._picam2.configure(still_config)
        self._picam2.start()
        logger.info(
            "Camera started: %sx%s, exposure=%sms, gain=%s",
            config.width, config.height, config.exposure_ms, config.gain,
        )

    def capture_gray(self) -> np.ndarray:
        """Captures one frame and returns an (height, width) uint8 array."""
        # YUV420's Y-plane is a plain grayscale image at full resolution -
        # exactly what cedar-detect wants, without needing a color->gray
        # conversion step.
        yuv = self._picam2.capture_array("main")
        height = self._config.height
        width = self._config.width
        y_plane = yuv[:height, :width]
        return np.ascontiguousarray(y_plane, dtype=np.uint8)

    def close(self) -> None:
        self._picam2.stop()
        self._picam2.close()
