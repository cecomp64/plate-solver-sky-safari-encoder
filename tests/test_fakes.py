import math

import numpy as np
import pytest

from binoc_solve.fakes import (
    ANDROMEDA,
    CannedSolution,
    FakeCamera,
    FakeDetectClient,
    FakeSolver,
    SlewCenter,
    SlewingFakeSolver,
)

SOLUTIONS = [
    CannedSolution("A", ra_deg=10.0, dec_deg=1.0),
    CannedSolution("B", ra_deg=20.0, dec_deg=2.0),
    CannedSolution("C", ra_deg=30.0, dec_deg=3.0),
]


def test_solve_returns_first_solution_by_default():
    solver = FakeSolver(SOLUTIONS)
    result = solver.solve([], (100, 100))
    assert result.ra_deg == 10.0
    assert result.dec_deg == 1.0
    assert result.num_matches > 0


def test_next_cycles_and_wraps():
    solver = FakeSolver(SOLUTIONS)
    assert solver.next() == "B"
    assert solver.solve([], (100, 100)).ra_deg == 20.0
    assert solver.next() == "C"
    assert solver.next() == "A"  # wraps around
    assert solver.solve([], (100, 100)).ra_deg == 10.0


def test_select_jumps_to_index():
    solver = FakeSolver(SOLUTIONS)
    assert solver.select(2) == "C"
    assert solver.solve([], (100, 100)).dec_deg == 3.0


def test_select_out_of_range_raises():
    solver = FakeSolver(SOLUTIONS)
    with pytest.raises(IndexError):
        solver.select(99)


def test_current_name_reflects_selection():
    solver = FakeSolver(SOLUTIONS)
    assert solver.current_name() == "A"
    solver.next()
    assert solver.current_name() == "B"


def test_list_names():
    solver = FakeSolver(SOLUTIONS)
    assert solver.list_names() == ["A", "B", "C"]


def test_default_solutions_used_when_none_given():
    solver = FakeSolver()
    assert len(solver.list_names()) >= 2


def test_empty_solutions_raises():
    with pytest.raises(ValueError):
        FakeSolver([])


def test_fake_camera_returns_valid_gray_image():
    image = FakeCamera().capture_gray()
    assert image.ndim == 2
    assert image.dtype == np.uint8


def test_fake_detect_client_returns_no_centroids():
    centroids = FakeDetectClient().extract_centroids(np.zeros((4, 4), dtype=np.uint8))
    assert centroids == []


def test_slewing_solver_starts_at_north_extreme():
    solver = SlewingFakeSolver(clock=lambda: 0.0)
    result = solver.solve([], (100, 100))
    assert result.ra_deg == pytest.approx(ANDROMEDA.ra_deg, abs=1e-6)
    assert result.dec_deg == pytest.approx(ANDROMEDA.dec_deg + 5.0, abs=1e-6)


def test_slewing_solver_quarter_period_is_east_extreme():
    clock = {"t": 0.0}
    solver = SlewingFakeSolver(clock=lambda: clock["t"])
    clock["t"] = 5.0  # quarter of the default 20s period
    result = solver.solve([], (100, 100))
    assert result.dec_deg == pytest.approx(ANDROMEDA.dec_deg, abs=1e-6)
    expected_ra = ANDROMEDA.ra_deg + 5.0 / math.cos(math.radians(ANDROMEDA.dec_deg))
    assert result.ra_deg == pytest.approx(expected_ra, abs=1e-6)


def test_slewing_solver_half_period_is_south_extreme():
    clock = {"t": 0.0}
    solver = SlewingFakeSolver(clock=lambda: clock["t"])
    clock["t"] = 10.0
    result = solver.solve([], (100, 100))
    assert result.dec_deg == pytest.approx(ANDROMEDA.dec_deg - 5.0, abs=1e-6)
    assert result.ra_deg == pytest.approx(ANDROMEDA.ra_deg, abs=1e-6)


def test_slewing_solver_three_quarter_period_is_west_extreme():
    clock = {"t": 0.0}
    solver = SlewingFakeSolver(clock=lambda: clock["t"])
    clock["t"] = 15.0
    result = solver.solve([], (100, 100))
    assert result.dec_deg == pytest.approx(ANDROMEDA.dec_deg, abs=1e-6)
    expected_ra = ANDROMEDA.ra_deg - 5.0 / math.cos(math.radians(ANDROMEDA.dec_deg))
    assert result.ra_deg == pytest.approx(expected_ra, abs=1e-6)


def test_slewing_solver_returns_to_start_after_full_period():
    clock = {"t": 0.0}
    solver = SlewingFakeSolver(clock=lambda: clock["t"])
    clock["t"] = 20.0
    result = solver.solve([], (100, 100))
    assert result.ra_deg == pytest.approx(ANDROMEDA.ra_deg, abs=1e-6)
    assert result.dec_deg == pytest.approx(ANDROMEDA.dec_deg + 5.0, abs=1e-6)


def test_slewing_solver_respects_custom_center_amplitude_and_period():
    center = SlewCenter("Test", ra_deg=100.0, dec_deg=0.0)
    clock = {"t": 0.0}
    solver = SlewingFakeSolver(
        center=center, amplitude_deg=2.0, period_s=10.0, clock=lambda: clock["t"]
    )
    clock["t"] = 2.5  # quarter of the 10s period
    result = solver.solve([], (100, 100))
    assert result.dec_deg == pytest.approx(0.0, abs=1e-6)
    assert result.ra_deg == pytest.approx(102.0, abs=1e-6)  # cos(0)=1, no RA scaling


def test_slewing_solver_current_name_mentions_center():
    solver = SlewingFakeSolver()
    assert "Andromeda" in solver.current_name()
