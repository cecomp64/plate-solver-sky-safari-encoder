import time

from binoc_solve.state import LatestFix


def test_no_fix_initially():
    latest = LatestFix()
    assert latest.get() is None
    assert latest.age_seconds() is None


def test_update_and_get_roundtrip():
    latest = LatestFix()
    latest.update(alt_deg=12.5, az_deg=200.0)
    fix = latest.get()
    assert fix is not None
    assert fix.alt_deg == 12.5
    assert fix.az_deg == 200.0


def test_age_increases_over_time():
    latest = LatestFix()
    latest.update(alt_deg=0.0, az_deg=0.0)
    time.sleep(0.05)
    age = latest.age_seconds()
    assert age is not None
    assert age >= 0.05


def test_update_overwrites_previous_fix():
    latest = LatestFix()
    latest.update(alt_deg=1.0, az_deg=1.0)
    latest.update(alt_deg=2.0, az_deg=2.0)
    fix = latest.get()
    assert fix.alt_deg == 2.0
    assert fix.az_deg == 2.0
