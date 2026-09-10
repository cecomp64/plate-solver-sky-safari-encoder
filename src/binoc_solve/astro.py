"""RA/Dec (ICRS, degrees) -> topocentric Alt/Az (degrees) conversion.

Uses astropy rather than skyfield: astropy's ICRS -> AltAz transform is
computed analytically (ERFA) from the observer's location and time plus
a bundled IERS Earth-orientation table - no multi-megabyte JPL ephemeris
download needed, since we're converting a fixed star/boresight position,
not looking up a solar-system body. That matters here because the device
hosts its own Wi-Fi AP in the field with no internet: astropy transparently
falls back to its bundled IERS_B table when it can't reach the network to
refresh, which is more than accurate enough for a push-to finder (the
extra source of error tops out well under an arcminute - not the limiting
factor next to plate-solve and mount-flex uncertainty).
"""
from __future__ import annotations

import datetime as dt
import warnings

from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time
from astropy.utils.iers import IERSWarning


def radec_to_altaz(
    ra_deg: float,
    dec_deg: float,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
    when_utc: dt.datetime,
) -> tuple[float, float]:
    """Converts an ICRS RA/Dec (as reported by cedar-solve) to Alt/Az.

    Args:
        ra_deg, dec_deg: Plate-solved position, degrees.
        latitude_deg, longitude_deg: Observer site, degrees (+E, +N).
        elevation_m: Observer site height above the WGS84 ellipsoid.
        when_utc: Timezone-aware (or naive-but-UTC) datetime of the
            observation. Must be accurate - see the README's note on
            syncing the Pi's clock before field use.

    Returns:
        (alt_deg, az_deg): Altitude above horizon and azimuth from true
        north (clockwise, i.e. compass convention), both in degrees.
    """
    location = EarthLocation(
        lat=latitude_deg * u.deg, lon=longitude_deg * u.deg, height=elevation_m * u.m
    )
    time = Time(when_utc)
    frame = AltAz(obstime=time, location=location)
    coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")

    with warnings.catch_warnings():
        # Expected/harmless when the Pi has no internet (see module
        # docstring) - IERSWarning (the base class) is what's actually
        # raised for a failed download attempt; its IERSStaleWarning
        # subclass only covers the separate case of proceeding with
        # data that's already on disk but out of date. Filtering only
        # the subclass let the download-failure warning leak through
        # on every single solve cycle once the Pi has no network.
        warnings.simplefilter("ignore", IERSWarning)
        altaz = coord.transform_to(frame)

    return float(altaz.alt.degree), float(altaz.az.degree)
