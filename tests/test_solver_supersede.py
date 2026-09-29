"""Solver.supersede() against a stub Tetra3 - the real one needs the
cedar-solve install and a star database, and its cancel mechanism is just
a flag its solve loop polls, which the stub mimics."""
import threading
import time

from binoc_solve.config import SolverConfig
from binoc_solve.solver import Solver


class _StubTetra3:
    def __init__(self, solve_s: float) -> None:
        self.solve_s = solve_s
        self._cancelled = False
        self.statuses: list[str] = []

    def cancel_solve(self) -> None:
        self._cancelled = True

    def solve_from_centroids(self, centroids, size, **kwargs):
        deadline = time.monotonic() + self.solve_s
        while time.monotonic() < deadline:
            if self._cancelled:
                self._cancelled = False
                self.statuses.append("cancelled")
                return {"status": 4}
            time.sleep(0.005)
        self.statuses.append("done")
        return {"status": 2}


def _solver(solve_s: float, supersede_after_ms: int) -> Solver:
    solver = object.__new__(Solver)  # skip loading a real database
    solver._config = SolverConfig(
        database_path=None, fov_estimate_deg=53.5, sigma=8.0, solve_timeout_ms=1000,
        match_max_error=0.005, supersede_after_ms=supersede_after_ms,
    )
    solver._t3 = _StubTetra3(solve_s)
    solver._max_centroids = 150
    solver._lock = threading.Lock()
    solver._solve_id = 0
    solver._solve_started = None
    solver._pending_timer = None
    return solver


def _solve_in_background(solver):
    t = threading.Thread(target=solver.solve, args=([(1.0, 1.0)] * 10, (100, 100)))
    t.start()
    time.sleep(0.02)  # let it start
    return t


def test_supersede_after_floor_cancels_immediately():
    solver = _solver(solve_s=2.0, supersede_after_ms=0)
    t = _solve_in_background(solver)
    start = time.monotonic()
    solver.supersede()
    t.join(timeout=3)
    assert solver._t3.statuses == ["cancelled"]
    assert time.monotonic() - start < 0.5


def test_supersede_before_floor_waits_for_it():
    solver = _solver(solve_s=2.0, supersede_after_ms=300)
    t = _solve_in_background(solver)
    start = time.monotonic()
    solver.supersede()
    t.join(timeout=3)
    elapsed = time.monotonic() - start
    assert solver._t3.statuses == ["cancelled"]
    assert 0.2 < elapsed < 1.0


def test_solve_finishing_before_floor_is_not_cancelled():
    solver = _solver(solve_s=0.1, supersede_after_ms=500)
    t = _solve_in_background(solver)
    solver.supersede()
    t.join(timeout=3)
    time.sleep(0.6)  # past when the deferred cancel would have fired
    assert solver._t3.statuses == ["done"]
    assert solver._t3._cancelled is False


def test_supersede_while_idle_does_not_poison_next_solve():
    solver = _solver(solve_s=0.05, supersede_after_ms=0)
    solver.supersede()
    solver.solve([(1.0, 1.0)] * 10, (100, 100))
    assert solver._t3.statuses == ["done"]
