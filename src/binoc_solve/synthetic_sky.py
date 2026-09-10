"""Renders a synthetic star-field image for a given sky field, using this
project's actual camera geometry and a real star catalog - so it has a
known ground-truth RA/Dec/FOV, unlike a real night-sky photo. See
scripts/generate_test_image.py for the CLI, and README.md for how the
camera's FOV/focal-length-in-pixels numbers below were derived.

Projection: gnomonic (tangent-plane, aka "TAN") - the standard ideal
pinhole-lens model, which is also what cedar-solve itself assumes absent
a distortion term. Verified against astropy.wcs's own TAN projection in
tests/test_synthetic_sky.py.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# OV5647 sensor (5MP, 1/4" optical format, 1.4um pixels) with the stock
# fixed-focus 3.6mm M12 lens shipped on this project's camera module (and
# essentially all OV5647-based Raspberry Pi Camera Module v1 clones).
SENSOR_WIDTH_PX = 2592
SENSOR_HEIGHT_PX = 1944
PIXEL_PITCH_MM = 1.4e-3
FOCAL_LENGTH_MM = 3.6
FOCAL_LENGTH_PX = FOCAL_LENGTH_MM / PIXEL_PITCH_MM  # ~2571.4 px

DATA_DIR = Path(__file__).parent.parent.parent / "data"
DEFAULT_CATALOG = DATA_DIR / "bright_stars.csv"

# Orion: bright, instantly recognizable, straddles the celestial equator
# so it's a reasonable test target from most latitudes.
DEFAULT_RA_DEG = 83.75
DEFAULT_DEC_DEG = -1.5


def horizontal_fov_deg(width_px: int = SENSOR_WIDTH_PX, focal_length_px: float = FOCAL_LENGTH_PX) -> float:
    return math.degrees(2 * math.atan((width_px / 2) / focal_length_px))


@dataclass(frozen=True)
class CatalogStar:
    ra_deg: float
    dec_deg: float
    mag: float
    name: str


def load_catalog(path: Path | str = DEFAULT_CATALOG, max_mag: float | None = None) -> list[CatalogStar]:
    stars = []
    with Path(path).open(newline="") as f:
        for row in csv.DictReader(f):
            mag = float(row["mag"])
            if max_mag is not None and mag > max_mag:
                continue
            stars.append(CatalogStar(float(row["ra_deg"]), float(row["dec_deg"]), mag, row["name"]))
    return stars


def radec_to_pixel(
    ra_deg: float,
    dec_deg: float,
    ra0_deg: float,
    dec0_deg: float,
    width_px: int,
    height_px: int,
    focal_length_px: float,
) -> tuple[float, float] | None:
    """Gnomonic projection of (ra_deg, dec_deg) onto an image centered on
    (ra0_deg, dec0_deg). Returns None for a point behind the camera
    (more than ~90deg from the field center)."""
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    ra0, dec0 = math.radians(ra0_deg), math.radians(dec0_deg)
    d_ra = ra - ra0

    cos_c = math.sin(dec0) * math.sin(dec) + math.cos(dec0) * math.cos(dec) * math.cos(d_ra)
    if cos_c <= 1e-6:
        return None

    xi = (math.cos(dec) * math.sin(d_ra)) / cos_c
    eta = (math.cos(dec0) * math.sin(dec) - math.sin(dec0) * math.cos(dec) * math.cos(d_ra)) / cos_c

    # +RA increases to the right, +Dec increases upward (smaller row index).
    x = width_px / 2.0 + xi * focal_length_px
    y = height_px / 2.0 - eta * focal_length_px
    return x, y


def pixel_to_radec(
    x_px: float,
    y_px: float,
    ra0_deg: float,
    dec0_deg: float,
    width_px: int,
    height_px: int,
    focal_length_px: float,
) -> tuple[float, float]:
    """Inverse gnomonic projection - the mathematical inverse of
    radec_to_pixel, derived independently (standard tangent-plane
    "standard coordinates" inversion) rather than by algebraically
    solving radec_to_pixel's own equations, so round-tripping through
    both is a genuine self-consistency check - see
    tests/test_synthetic_sky.py."""
    xi = (x_px - width_px / 2.0) / focal_length_px
    eta = (height_px / 2.0 - y_px) / focal_length_px

    dec0 = math.radians(dec0_deg)
    ra0 = math.radians(ra0_deg)
    rho = math.hypot(xi, eta)
    if rho < 1e-15:
        return ra0_deg, dec0_deg

    c = math.atan(rho)
    sin_c, cos_c = math.sin(c), math.cos(c)

    dec = math.asin(cos_c * math.sin(dec0) + (eta * sin_c * math.cos(dec0)) / rho)
    ra = ra0 + math.atan2(xi * sin_c, rho * math.cos(dec0) * cos_c - eta * math.sin(dec0) * sin_c)

    return math.degrees(ra) % 360.0, math.degrees(dec)


def _mag_to_peak_value(mag: float, peak_at_zero_mag: float = 255.0) -> float:
    """Each 1 magnitude is ~2.512x dimmer (the definition of the
    magnitude scale); floored so faint stars still register weakly in
    the synthetic image rather than vanishing outright."""
    value = peak_at_zero_mag * (10 ** (-0.4 * mag))
    return max(value, 8.0)


@dataclass(frozen=True)
class PlacedStar:
    name: str
    x_px: float
    y_px: float
    mag: float


def render(
    ra0_deg: float,
    dec0_deg: float,
    catalog: list[CatalogStar],
    width_px: int = SENSOR_WIDTH_PX,
    height_px: int = SENSOR_HEIGHT_PX,
    focal_length_px: float = FOCAL_LENGTH_PX,
    psf_sigma_px: float = 1.3,
    background: int = 12,
    noise_sigma: float = 3.0,
    seed: int = 0,
) -> tuple[np.ndarray, list[PlacedStar]]:
    """Returns (grayscale uint8 image, stars actually placed in-frame)."""
    rng = np.random.default_rng(seed)
    image = np.full((height_px, width_px), float(background))
    image += rng.normal(0, noise_sigma, image.shape)

    half_win = int(math.ceil(psf_sigma_px * 5))
    coords = np.arange(-half_win, half_win + 1)
    gx, gy = np.meshgrid(coords, coords)
    kernel_shape = np.exp(-(gx**2 + gy**2) / (2 * psf_sigma_px**2))

    placed: list[PlacedStar] = []
    for star in catalog:
        pixel = radec_to_pixel(star.ra_deg, star.dec_deg, ra0_deg, dec0_deg, width_px, height_px, focal_length_px)
        if pixel is None:
            continue
        x, y = pixel
        if not (0 <= x < width_px and 0 <= y < height_px):
            continue

        peak = _mag_to_peak_value(star.mag)
        xi, yi = int(round(x)), int(round(y))
        x0, x1 = max(0, xi - half_win), min(width_px, xi + half_win + 1)
        y0, y1 = max(0, yi - half_win), min(height_px, yi + half_win + 1)
        kx0, ky0 = x0 - (xi - half_win), y0 - (yi - half_win)
        patch = kernel_shape[ky0 : ky0 + (y1 - y0), kx0 : kx0 + (x1 - x0)] * peak
        image[y0:y1, x0:x1] += patch
        placed.append(PlacedStar(star.name, x, y, star.mag))

    return np.clip(image, 0, 255).astype(np.uint8), placed
