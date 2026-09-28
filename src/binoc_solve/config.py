"""Loads config.yaml into typed, validated config objects."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from binoc_solve.locations import NamedLocation


@dataclass(frozen=True)
class LocationSelectorConfig:
    button_gpio: int
    led_name: str
    state_file: str
    bounce_time_s: float
    blink_on_s: float
    blink_off_s: float
    blink_repeat_pause_s: float
    blink_repeats: int


@dataclass(frozen=True)
class SimulatorSelectorConfig:
    button_gpio: int
    led_name: str
    bounce_time_s: float
    blink_on_s: float
    blink_off_s: float
    blink_repeat_pause_s: float
    blink_repeats: int


@dataclass(frozen=True)
class CameraConfig:
    exposure_ms: int
    gain: float
    width: int
    height: int


@dataclass(frozen=True)
class AutoExposureConfig:
    enabled: bool
    min_exposure_ms: int
    max_exposure_ms: int
    min_gain: float
    max_gain: float
    min_centroids: int
    saturation_peak: int
    low_streak: int
    high_streak: int
    adjustment_factor: float
    cooldown_cycles: int


@dataclass(frozen=True)
class SyntheticCameraConfig:
    image_dir: str
    interval_s: float


@dataclass(frozen=True)
class SolverConfig:
    database_path: str | None
    fov_estimate_deg: float
    sigma: float
    solve_timeout_ms: int


@dataclass(frozen=True)
class CedarDetectConfig:
    address: str


@dataclass(frozen=True)
class EncoderConfig:
    bind_host: str
    bind_port: int
    az_resolution: int
    alt_resolution: int
    flip_azimuth: bool
    flip_altitude: bool


@dataclass(frozen=True)
class LoopConfig:
    min_interval_s: float
    stale_fix_warn_s: float


@dataclass(frozen=True)
class Config:
    locations: list[NamedLocation]
    location_selector: LocationSelectorConfig
    simulator_selector: SimulatorSelectorConfig
    camera: CameraConfig
    auto_exposure: AutoExposureConfig
    synthetic_camera: SyntheticCameraConfig
    solver: SolverConfig
    cedar_detect: CedarDetectConfig
    encoder: EncoderConfig
    loop: LoopConfig

    @staticmethod
    def load(path: str | Path) -> "Config":
        path = Path(path)
        with path.open("r") as f:
            raw = yaml.safe_load(f)
        return Config(
            locations=[NamedLocation(**loc) for loc in raw["locations"]],
            location_selector=LocationSelectorConfig(**raw["location_selector"]),
            simulator_selector=SimulatorSelectorConfig(**raw["simulator_selector"]),
            camera=CameraConfig(**raw["camera"]),
            auto_exposure=AutoExposureConfig(**raw["auto_exposure"]),
            synthetic_camera=SyntheticCameraConfig(**raw["synthetic_camera"]),
            solver=SolverConfig(**raw["solver"]),
            cedar_detect=CedarDetectConfig(**raw["cedar_detect"]),
            encoder=EncoderConfig(**raw["encoder"]),
            loop=LoopConfig(**raw["loop"]),
        )
