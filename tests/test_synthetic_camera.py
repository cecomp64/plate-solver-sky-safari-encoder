import numpy as np
from PIL import Image

from binoc_solve.synthetic_camera import SyntheticImageCamera


def _write_image(path, fill_value):
    Image.fromarray(np.full((4, 4), fill_value, dtype=np.uint8), mode="L").save(path)


def test_serves_first_image_at_t_zero(tmp_path):
    _write_image(tmp_path / "a.png", 10)
    _write_image(tmp_path / "b.png", 20)
    camera = SyntheticImageCamera(tmp_path, interval_s=1.0, clock=lambda: 0.0)
    image = camera.capture_gray()
    assert image.dtype == np.uint8
    assert (image == 10).all()


def test_advances_to_next_image_after_interval(tmp_path):
    _write_image(tmp_path / "a.png", 10)
    _write_image(tmp_path / "b.png", 20)
    clock = {"t": 0.0}
    camera = SyntheticImageCamera(tmp_path, interval_s=1.0, clock=lambda: clock["t"])
    assert (camera.capture_gray() == 10).all()
    clock["t"] = 1.2
    assert (camera.capture_gray() == 20).all()


def test_wraps_around_after_last_image(tmp_path):
    _write_image(tmp_path / "a.png", 10)
    _write_image(tmp_path / "b.png", 20)
    clock = {"t": 0.0}
    camera = SyntheticImageCamera(tmp_path, interval_s=1.0, clock=lambda: clock["t"])
    clock["t"] = 2.1  # two full intervals -> back to image 0
    assert (camera.capture_gray() == 10).all()


def test_images_walked_in_sorted_filename_order(tmp_path):
    _write_image(tmp_path / "b.png", 20)
    _write_image(tmp_path / "a.png", 10)
    clock = {"t": 0.0}
    camera = SyntheticImageCamera(tmp_path, interval_s=1.0, clock=lambda: clock["t"])
    assert (camera.capture_gray() == 10).all()  # a.png sorts first
    clock["t"] = 1.0
    assert (camera.capture_gray() == 20).all()


def test_missing_directory_returns_blank_frame_instead_of_raising(tmp_path):
    camera = SyntheticImageCamera(tmp_path / "does_not_exist", interval_s=1.0)
    image = camera.capture_gray()
    assert image.shape == (16, 16)
    assert (image == 0).all()


def test_empty_directory_returns_blank_frame_instead_of_raising(tmp_path):
    camera = SyntheticImageCamera(tmp_path, interval_s=1.0)
    image = camera.capture_gray()
    assert image.shape == (16, 16)


def test_non_image_files_are_ignored(tmp_path):
    _write_image(tmp_path / "a.png", 10)
    (tmp_path / "readme.txt").write_text("not an image")
    camera = SyntheticImageCamera(tmp_path, interval_s=1.0, clock=lambda: 0.0)
    assert (camera.capture_gray() == 10).all()


def test_close_is_a_no_op(tmp_path):
    _write_image(tmp_path / "a.png", 10)
    camera = SyntheticImageCamera(tmp_path, interval_s=1.0)
    camera.close()  # must not raise
