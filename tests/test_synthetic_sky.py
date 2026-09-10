import math

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import SkyCoord

from binoc_solve.synthetic_sky import (
    FIELD_PRESETS,
    FOCAL_LENGTH_PX,
    SENSOR_HEIGHT_PX,
    SENSOR_WIDTH_PX,
    CatalogStar,
    horizontal_fov_deg,
    load_catalog,
    pixel_to_radec,
    radec_to_pixel,
    render,
)


def test_field_presets_span_both_hemispheres():
    assert "orion" in FIELD_PRESETS
    for ra_deg, dec_deg in FIELD_PRESETS.values():
        assert 0.0 <= ra_deg < 360.0
        assert -90.0 <= dec_deg <= 90.0
    assert FIELD_PRESETS["ursa-major"][1] > 0  # northern
    assert FIELD_PRESETS["crux"][1] < 0  # southern


def test_field_center_maps_to_image_center():
    x, y = radec_to_pixel(83.75, -1.5, 83.75, -1.5, SENSOR_WIDTH_PX, SENSOR_HEIGHT_PX, FOCAL_LENGTH_PX)
    assert x == pytest.approx(SENSOR_WIDTH_PX / 2, abs=1e-6)
    assert y == pytest.approx(SENSOR_HEIGHT_PX / 2, abs=1e-6)


def test_horizontal_fov_matches_computed_camera_spec():
    # OV5647 (1.4um pixels) + stock 3.6mm lens -> ~53.5deg horizontal FOV.
    assert horizontal_fov_deg() == pytest.approx(53.5, abs=0.1)


@pytest.mark.parametrize(
    "ra0,dec0,d_ra,d_dec",
    [
        (83.75, -1.5, 5.0, 0.0),
        (83.75, -1.5, -5.0, 3.0),
        (83.75, -1.5, 0.0, -8.0),
        (10.0, 60.0, 4.0, 2.0),  # near-pole field, larger cos(dec) effects
        (350.0, -20.0, 3.0, -1.0),  # RA wraparound near 360/0
    ],
)
def test_radial_distance_matches_astropy_angular_separation(ra0, dec0, d_ra, d_dec):
    # A gnomonic projection's defining property: a point's angular
    # separation `c` from the field center relates to its tangent-plane
    # radius `rho` by rho = tan(c). This checks that relationship against
    # astropy's own (independently implemented, well-tested) great-circle
    # separation, without needing to match any particular pixel/axis
    # convention - see pixel_to_radec's round-trip tests below for the
    # angular (not just radial) check.
    ra, dec = ra0 + d_ra, dec0 + d_dec
    x, y = radec_to_pixel(ra, dec, ra0, dec0, SENSOR_WIDTH_PX, SENSOR_HEIGHT_PX, FOCAL_LENGTH_PX)

    rho_px = math.hypot(x - SENSOR_WIDTH_PX / 2, y - SENSOR_HEIGHT_PX / 2)
    rho = rho_px / FOCAL_LENGTH_PX
    c_from_projection = math.degrees(math.atan(rho))

    c_from_astropy = SkyCoord(ra * u.deg, dec * u.deg).separation(SkyCoord(ra0 * u.deg, dec0 * u.deg)).degree

    assert c_from_projection == pytest.approx(c_from_astropy, abs=1e-6)


@pytest.mark.parametrize(
    "ra0,dec0,ra,dec",
    [
        (83.75, -1.5, 88.75, -1.5),
        (83.75, -1.5, 78.75, 1.5),
        (83.75, -1.5, 83.75, -9.5),
        (10.0, 60.0, 14.0, 62.0),
        (350.0, -20.0, 353.0, -21.0),
        (0.5, -89.0, 45.0, -85.0),  # near celestial pole
    ],
)
def test_pixel_to_radec_round_trips_with_radec_to_pixel(ra0, dec0, ra, dec):
    x, y = radec_to_pixel(ra, dec, ra0, dec0, SENSOR_WIDTH_PX, SENSOR_HEIGHT_PX, FOCAL_LENGTH_PX)
    ra_back, dec_back = pixel_to_radec(x, y, ra0, dec0, SENSOR_WIDTH_PX, SENSOR_HEIGHT_PX, FOCAL_LENGTH_PX)

    sep = SkyCoord(ra * u.deg, dec * u.deg).separation(SkyCoord(ra_back * u.deg, dec_back * u.deg)).arcsec
    assert sep < 0.01  # sub-hundredth-arcsecond round-trip error (floating point only)


def test_point_behind_camera_returns_none():
    result = radec_to_pixel(0.0, 0.0, 180.0, 0.0, SENSOR_WIDTH_PX, SENSOR_HEIGHT_PX, FOCAL_LENGTH_PX)
    assert result is None


def test_load_catalog_respects_max_mag(tmp_path):
    csv_path = tmp_path / "cat.csv"
    csv_path.write_text("ra_deg,dec_deg,mag,name,hip\n10,10,1.0,Bright,1\n10,10,8.0,Faint,2\n")
    stars = load_catalog(csv_path, max_mag=6.5)
    assert [s.name for s in stars] == ["Bright"]


def test_render_places_stars_near_expected_pixels():
    catalog = [
        CatalogStar(ra_deg=83.75, dec_deg=-1.5, mag=0.5, name="Center"),
        CatalogStar(ra_deg=200.0, dec_deg=50.0, mag=1.0, name="OutOfFrame"),
    ]
    image, placed = render(83.75, -1.5, catalog, width_px=200, height_px=200, focal_length_px=100.0)

    assert image.shape == (200, 200)
    assert image.dtype == np.uint8
    assert [p.name for p in placed] == ["Center"]
    assert placed[0].x_px == pytest.approx(100.0, abs=1.0)
    assert placed[0].y_px == pytest.approx(100.0, abs=1.0)
    # The rendered pixel at the star's location should be much brighter
    # than the background corner.
    assert image[100, 100] > image[5, 5] + 20


def test_render_is_deterministic_for_a_fixed_seed():
    catalog = [CatalogStar(ra_deg=83.75, dec_deg=-1.5, mag=2.0, name="X")]
    image1, _ = render(83.75, -1.5, catalog, width_px=64, height_px=64, focal_length_px=50.0, seed=42)
    image2, _ = render(83.75, -1.5, catalog, width_px=64, height_px=64, focal_length_px=50.0, seed=42)
    assert np.array_equal(image1, image2)
