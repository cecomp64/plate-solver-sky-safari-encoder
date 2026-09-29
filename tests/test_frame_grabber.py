import threading
import time

import numpy as np
import pytest

from binoc_solve.frame_grabber import LatestFrameGrabber


class _CountingCamera:
    """Each frame's pixel value is its capture number, so tests can tell
    which frame they got."""

    def __init__(self, delay_s: float = 0.0) -> None:
        self.count = 0
        self.delay_s = delay_s

    def capture_gray(self) -> np.ndarray:
        time.sleep(self.delay_s)
        self.count += 1
        return np.full((2, 2), self.count % 256, dtype=np.uint8)


def test_returns_frames_in_order_tagged_with_source():
    camera = _CountingCamera()
    grabber = LatestFrameGrabber(lambda: ("real", camera), min_interval_s=0.01)
    grabber.start()
    try:
        first = grabber.wait_for_frame(0, timeout=2)
        second = grabber.wait_for_frame(first.seq, timeout=2)
    finally:
        grabber.stop(timeout=2)
    assert first.source == "real"
    assert second.seq > first.seq


def test_slow_consumer_gets_newest_frame_not_a_backlog():
    camera = _CountingCamera()
    grabber = LatestFrameGrabber(lambda: ("real", camera), min_interval_s=0.01)
    grabber.start()
    try:
        first = grabber.wait_for_frame(0, timeout=2)
        time.sleep(0.2)  # a slow solve - several frames arrive meanwhile
        newest = grabber.wait_for_frame(first.seq, timeout=2)
    finally:
        grabber.stop(timeout=2)
    assert newest.seq >= first.seq + 3


def test_on_new_frame_fires_per_frame():
    calls = []
    grabber = LatestFrameGrabber(
        lambda: ("real", _CountingCamera()), min_interval_s=0.01, on_new_frame=lambda: calls.append(1)
    )
    grabber.start()
    try:
        grabber.wait_for_frame(3, timeout=2)
    finally:
        grabber.stop(timeout=2)
    assert len(calls) >= 4


def test_source_is_reread_each_capture():
    tag = ["real"]
    grabber = LatestFrameGrabber(lambda: (tag[0], _CountingCamera()), min_interval_s=0.01)
    grabber.start()
    try:
        first = grabber.wait_for_frame(0, timeout=2)
        tag[0] = "simulator"
        frame = first
        deadline = time.monotonic() + 2
        while frame.source != "simulator" and time.monotonic() < deadline:
            frame = grabber.wait_for_frame(frame.seq, timeout=2)
    finally:
        grabber.stop(timeout=2)
    assert frame.source == "simulator"


def test_capture_failure_is_raised_to_the_consumer():
    class _Broken:
        def capture_gray(self):
            raise OSError("camera unplugged")

    grabber = LatestFrameGrabber(lambda: ("real", _Broken()), min_interval_s=0.01)
    grabber.start()
    try:
        with pytest.raises(RuntimeError) as excinfo:
            grabber.wait_for_frame(0, timeout=2)
        assert isinstance(excinfo.value.__cause__, OSError)
    finally:
        grabber.stop(timeout=2)


def test_timeout_returns_none_and_stop_ends_capture():
    camera = _CountingCamera(delay_s=0.3)
    grabber = LatestFrameGrabber(lambda: ("real", camera), min_interval_s=0.0)
    grabber.start()
    assert grabber.wait_for_frame(0, timeout=0.05) is None
    grabber.stop(timeout=2)
    assert not any(t.name == "frame-grabber" and t.is_alive() for t in threading.enumerate())
