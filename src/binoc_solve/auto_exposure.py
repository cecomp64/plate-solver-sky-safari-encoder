"""Closed-loop exposure/gain control for unattended field use.

camera.exposure_ms/gain in config.yaml are just a starting point tuned
by hand (scripts/solve_once.py) under whatever sky conditions existed at
tuning time. In the field there's no laptop to re-tune against - moon
phase, haze, or light pollution different from the tuning night can
leave the camera starved (too few stars) or saturated (blown-out/
merged stars) for an entire session with no way to notice or correct.

This nudges ExposureTime/AnalogueGain at runtime instead, based on the
same signals scripts/solve_once.py's output already suggested checking
by hand: cedar-detect's centroid count (too few -> starved) and
peak_star_pixel (pinned near 255 -> saturated). Exposure moves first in
both directions - gain only takes over once exposure is pinned at its
configured bound - since gain amplifies read noise while exposure
(within its bound) doesn't. Callers on an untracked mount should keep
max_exposure_ms comfortably under the point where stars start trailing
into streaks cedar-detect can't centroid.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from binoc_solve.config import AutoExposureConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExposureSettings:
    exposure_ms: int
    gain: float


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class AutoExposureController:
    def __init__(
        self, config: AutoExposureConfig, initial_exposure_ms: int, initial_gain: float
    ) -> None:
        self._config = config
        self._exposure_ms = int(
            _clamp(initial_exposure_ms, config.min_exposure_ms, config.max_exposure_ms)
        )
        self._gain = _clamp(initial_gain, config.min_gain, config.max_gain)
        self._low_streak = 0
        self._high_streak = 0
        self._cooldown = 0

    def observe(self, num_centroids: int, peak_star_pixel: int) -> ExposureSettings | None:
        """Call once per solve-loop cycle with this cycle's detection
        stats. Returns new settings to apply via Camera.set_exposure()
        if warranted, else None."""
        cfg = self._config
        if not cfg.enabled:
            return None

        if self._cooldown > 0:
            # Give the last change one full cycle to show up in a fresh
            # capture before judging it - otherwise a single overshoot
            # correction can trigger an immediate opposite overcorrection.
            self._cooldown -= 1
            return None

        if peak_star_pixel >= cfg.saturation_peak:
            self._high_streak += 1
            self._low_streak = 0
        elif num_centroids < cfg.min_centroids:
            self._low_streak += 1
            self._high_streak = 0
        else:
            self._low_streak = 0
            self._high_streak = 0

        if self._high_streak >= cfg.high_streak:
            return self._step(raise_exposure=False, reason=f"saturated (peak={peak_star_pixel})")
        if self._low_streak >= cfg.low_streak:
            return self._step(raise_exposure=True, reason=f"starved ({num_centroids} centroids)")
        return None

    def _step(self, raise_exposure: bool, reason: str) -> ExposureSettings | None:
        cfg = self._config
        factor = cfg.adjustment_factor if raise_exposure else 1.0 / cfg.adjustment_factor

        new_exposure_ms = int(
            round(_clamp(self._exposure_ms * factor, cfg.min_exposure_ms, cfg.max_exposure_ms))
        )
        if new_exposure_ms != self._exposure_ms:
            new_gain = self._gain
        else:
            # Exposure is already pinned at its configured bound - move
            # gain instead.
            new_gain = _clamp(self._gain * factor, cfg.min_gain, cfg.max_gain)

        self._low_streak = 0
        self._high_streak = 0

        if new_exposure_ms == self._exposure_ms and new_gain == self._gain:
            # Pinned on both bounds - nothing left to try.
            return None

        logger.info(
            "Auto-exposure: %s -> exposure %sms->%sms, gain %.2f->%.2f",
            reason, self._exposure_ms, new_exposure_ms, self._gain, new_gain,
        )
        self._exposure_ms = new_exposure_ms
        self._gain = new_gain
        self._cooldown = cfg.cooldown_cycles
        return ExposureSettings(exposure_ms=new_exposure_ms, gain=new_gain)
