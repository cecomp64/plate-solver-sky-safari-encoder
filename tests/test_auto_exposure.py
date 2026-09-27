import pytest

from binoc_solve.auto_exposure import AutoExposureController
from binoc_solve.config import AutoExposureConfig


def _config(**overrides) -> AutoExposureConfig:
    defaults = dict(
        enabled=True,
        min_exposure_ms=100,
        max_exposure_ms=1500,
        min_gain=1.0,
        max_gain=16.0,
        min_centroids=15,
        saturation_peak=250,
        low_streak=2,
        high_streak=2,
        adjustment_factor=2.0,
        cooldown_cycles=1,
    )
    defaults.update(overrides)
    return AutoExposureConfig(**defaults)


def test_disabled_never_adjusts():
    controller = AutoExposureController(_config(enabled=False), initial_exposure_ms=1000, initial_gain=4.0)
    for _ in range(10):
        assert controller.observe(num_centroids=0, peak_star_pixel=0) is None


def test_healthy_frame_never_adjusts():
    controller = AutoExposureController(_config(), initial_exposure_ms=1000, initial_gain=4.0)
    for _ in range(10):
        assert controller.observe(num_centroids=20, peak_star_pixel=180) is None


def test_starved_streak_raises_exposure_first():
    controller = AutoExposureController(_config(), initial_exposure_ms=500, initial_gain=4.0)
    assert controller.observe(num_centroids=2, peak_star_pixel=50) is None  # 1st, under low_streak
    settings = controller.observe(num_centroids=2, peak_star_pixel=50)  # 2nd, hits low_streak
    assert settings is not None
    assert settings.exposure_ms == 1000
    assert settings.gain == 4.0


def test_starved_moves_to_gain_once_exposure_pinned_at_max():
    controller = AutoExposureController(
        _config(max_exposure_ms=500), initial_exposure_ms=500, initial_gain=4.0
    )
    controller.observe(num_centroids=2, peak_star_pixel=50)
    settings = controller.observe(num_centroids=2, peak_star_pixel=50)
    assert settings is not None
    assert settings.exposure_ms == 500  # already at max, unchanged
    assert settings.gain == 8.0


def test_saturated_streak_lowers_exposure_first():
    controller = AutoExposureController(_config(), initial_exposure_ms=1000, initial_gain=4.0)
    controller.observe(num_centroids=20, peak_star_pixel=255)
    settings = controller.observe(num_centroids=20, peak_star_pixel=255)
    assert settings is not None
    assert settings.exposure_ms == 500
    assert settings.gain == 4.0


def test_saturated_moves_to_gain_once_exposure_pinned_at_min():
    controller = AutoExposureController(
        _config(min_exposure_ms=1000), initial_exposure_ms=1000, initial_gain=4.0
    )
    controller.observe(num_centroids=20, peak_star_pixel=255)
    settings = controller.observe(num_centroids=20, peak_star_pixel=255)
    assert settings is not None
    assert settings.exposure_ms == 1000  # already at min, unchanged
    assert settings.gain == 2.0


def test_pinned_on_both_bounds_returns_none():
    controller = AutoExposureController(
        _config(min_exposure_ms=1000, min_gain=4.0), initial_exposure_ms=1000, initial_gain=4.0
    )
    controller.observe(num_centroids=20, peak_star_pixel=255)
    assert controller.observe(num_centroids=20, peak_star_pixel=255) is None


def test_cooldown_suppresses_evaluation_right_after_an_adjustment():
    controller = AutoExposureController(_config(cooldown_cycles=2), initial_exposure_ms=500, initial_gain=4.0)
    controller.observe(num_centroids=2, peak_star_pixel=50)
    settings = controller.observe(num_centroids=2, peak_star_pixel=50)
    assert settings is not None  # adjustment fires, cooldown now armed

    # Even wildly starved readings during cooldown are ignored.
    assert controller.observe(num_centroids=0, peak_star_pixel=0) is None
    assert controller.observe(num_centroids=0, peak_star_pixel=0) is None
    # Cooldown has elapsed - starved streak starts accumulating again.
    assert controller.observe(num_centroids=0, peak_star_pixel=0) is None
    settings = controller.observe(num_centroids=0, peak_star_pixel=0)
    assert settings is not None


def test_healthy_frame_resets_streak():
    controller = AutoExposureController(_config(), initial_exposure_ms=500, initial_gain=4.0)
    controller.observe(num_centroids=2, peak_star_pixel=50)  # 1st starved reading
    controller.observe(num_centroids=20, peak_star_pixel=180)  # healthy - resets streak
    assert controller.observe(num_centroids=2, peak_star_pixel=50) is None  # back to 1st again
