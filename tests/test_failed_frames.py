import numpy as np

from binoc_solve.config import FailedFramesConfig
from binoc_solve.failed_frames import FailedFrameRecorder


def _config(tmp_path, **overrides) -> FailedFramesConfig:
    defaults = dict(enabled=True, dir=str(tmp_path / "frames"), min_interval_s=30.0, max_files=3)
    defaults.update(overrides)
    return FailedFramesConfig(**defaults)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _image() -> np.ndarray:
    return np.zeros((10, 20), dtype=np.uint8)


def test_disabled_never_saves(tmp_path):
    recorder = FailedFrameRecorder(_config(tmp_path, enabled=False))
    assert recorder.maybe_save(_image(), 5) is None
    assert not (tmp_path / "frames").exists()


def test_saves_png_named_with_centroid_count(tmp_path):
    recorder = FailedFrameRecorder(_config(tmp_path))
    path = recorder.maybe_save(_image(), 812)
    assert path is not None and path.exists()
    assert path.name.endswith("-812c.png")


def test_rate_limited_by_min_interval(tmp_path):
    clock = _Clock()
    recorder = FailedFrameRecorder(_config(tmp_path), clock=clock)
    assert recorder.maybe_save(_image(), 1) is not None
    clock.now = 29.0
    assert recorder.maybe_save(_image(), 2) is None
    clock.now = 30.0
    assert recorder.maybe_save(_image(), 3) is not None


def test_keeps_only_newest_max_files(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    for i in range(5):
        (frames / f"fail-20260101-00000{i}-1c.png").write_bytes(b"")
    recorder = FailedFrameRecorder(_config(tmp_path, max_files=3))
    saved = recorder.maybe_save(_image(), 9)
    remaining = sorted(p.name for p in frames.glob("fail-*.png"))
    assert len(remaining) == 3
    assert saved.name in remaining
    assert "fail-20260101-000000-1c.png" not in remaining


def test_unwritable_dir_does_not_raise(tmp_path):
    blocker = tmp_path / "frames"
    blocker.write_text("a file where the directory should be")
    recorder = FailedFrameRecorder(_config(tmp_path))
    assert recorder.maybe_save(_image(), 1) is None
