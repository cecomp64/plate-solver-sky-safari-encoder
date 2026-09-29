"""Continuous capture on a background thread, keeping only the newest frame.

The solve loop used to capture, detect and solve strictly in turn, so a
slow or doomed solve (stars smeared mid-slew) delayed the next capture,
and the first frame solved after the mount stopped could be one exposed
while it was still moving. Capturing independently means the camera never
waits on the solver, the solver always starts on the freshest frame, and
frame_interval_s tells the solve loop when the next frame is due, so a
solve still grinding on an older frame can be given up at that point.

That deadline is enforced by the solver's own timeout rather than by this
thread signalling "new frame": tetra3 holds the GIL for long stretches,
and this thread was measured waking 0.1-0.25s late while a solve ran -
usually after the 1s timeout had already expired anyway.
"""
from __future__ import annotations

import logging
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Frame:
    seq: int
    source: object  # whatever source() returned alongside the camera, e.g. a Mode
    image: np.ndarray
    captured_at: float  # time.monotonic() when capture_gray() returned


class LatestFrameGrabber:
    def __init__(
        self,
        source: Callable[[], tuple[object, object]],
        min_interval_s: float,
    ) -> None:
        """source() returns (tag, camera) and is re-read before every
        capture, so a mode switch takes effect on the very next frame.
        min_interval_s paces cameras that return instantly (the fakes)."""
        self._source = source
        self._min_interval_s = min_interval_s
        # Recent capture-to-capture gaps. Median, not mean or min: a late
        # wake-up (see module docstring) stretches one gap and shrinks the
        # next as the queued frame is picked up straight away.
        self._intervals: deque[float] = deque(maxlen=9)
        self._cond = threading.Condition()
        self._latest: Frame | None = None
        self._error: BaseException | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="frame-grabber", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        """Returns once the in-flight capture (at most one exposure) ends,
        so the camera can then be closed safely."""
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        self._thread.join(timeout)

    @property
    def frame_interval_s(self) -> float | None:
        """Typical time between frames, or None until there's enough history."""
        with self._cond:
            if len(self._intervals) < 3:
                return None
            return statistics.median(self._intervals)

    def wait_for_frame(self, after_seq: int, timeout: float) -> Frame | None:
        """Newest frame with seq > after_seq, or None on timeout/stop.
        Re-raises a capture failure, so it isn't silently swallowed by the
        background thread - the service then exits and systemd restarts it,
        the same as when capture ran on the solve loop's own thread."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                if self._error is not None:
                    raise RuntimeError("camera capture failed") from self._error
                if self._latest is not None and self._latest.seq > after_seq:
                    return self._latest
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._stop.is_set():
                    return None
                self._cond.wait(remaining)

    def _run(self) -> None:
        seq = 0
        last_at: float | None = None
        while not self._stop.is_set():
            start = time.monotonic()
            try:
                tag, camera = self._source()
                image = camera.capture_gray()
            except BaseException as exc:  # noqa: BLE001 - handed to the consumer
                logger.exception("Camera capture failed")
                with self._cond:
                    self._error = exc
                    self._cond.notify_all()
                return
            seq += 1
            now = time.monotonic()
            with self._cond:
                if last_at is not None:
                    self._intervals.append(now - last_at)
                self._latest = Frame(seq=seq, source=tag, image=image, captured_at=now)
                self._cond.notify_all()
            last_at = now
            remaining = self._min_interval_s - (time.monotonic() - start)
            if remaining > 0:
                self._stop.wait(remaining)
