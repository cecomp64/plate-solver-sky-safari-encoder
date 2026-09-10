import datetime as dt

from astropy.time import Time

from binoc_solve.astro import radec_to_altaz

WHEN = dt.datetime(2026, 1, 15, 4, 0, 0, tzinfo=dt.timezone.utc)


def test_zenith_star_reports_altitude_near_90():
    # A star whose RA equals the local apparent sidereal time, and whose Dec
    # equals the site latitude, sits at the zenith at that instant.
    lat_deg, lon_deg = 40.0, -105.0
    lst = Time(WHEN).sidereal_time("apparent", longitude=lon_deg * 1.0)
    ra_deg = lst.degree

    alt_deg, az_deg = radec_to_altaz(ra_deg, lat_deg, lat_deg, lon_deg, 1600.0, WHEN)
    assert alt_deg > 89.5


def test_polaris_altitude_tracks_latitude():
    # Polaris sits ~0.7deg from the celestial pole, so its altitude should
    # be within about 1 degree of the observer's latitude at any time.
    polaris_ra_deg = 37.95
    polaris_dec_deg = 89.26

    for lat_deg in (20.0, 40.0, 60.0):
        alt_deg, _az_deg = radec_to_altaz(
            polaris_ra_deg, polaris_dec_deg, lat_deg, -105.0, 1600.0, WHEN
        )
        assert abs(alt_deg - lat_deg) < 1.0


def test_azimuth_in_valid_range():
    alt_deg, az_deg = radec_to_altaz(180.0, 10.0, 40.0, -105.0, 1600.0, WHEN)
    assert 0.0 <= az_deg < 360.0
    assert -90.0 <= alt_deg <= 90.0
