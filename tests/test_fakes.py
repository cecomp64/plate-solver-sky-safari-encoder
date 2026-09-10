import numpy as np
import pytest

from binoc_solve.fakes import CannedSolution, FakeCamera, FakeDetectClient, FakeSolver

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
