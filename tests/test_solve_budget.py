from binoc_solve.config import SolverConfig
from binoc_solve.main import _solve_budget_ms


def _cfg(solve_timeout_ms=1000, supersede_after_ms=500) -> SolverConfig:
    return SolverConfig(
        database_path=None, fov_estimate_deg=53.5, sigma=8.0, solve_timeout_ms=solve_timeout_ms,
        match_max_error=0.005, supersede_after_ms=supersede_after_ms,
    )


def test_no_interval_history_uses_full_timeout():
    assert _solve_budget_ms(captured_at=10.0, frame_interval_s=None, now=10.0, cfg=_cfg()) == 1000


def test_runs_until_next_frame_is_due():
    # Captured at 10.0, next due at 10.8; detection took 20ms.
    assert abs(_solve_budget_ms(10.0, 0.8, now=10.02, cfg=_cfg()) - 780) < 1e-6


def test_never_below_supersede_floor():
    # 400ms frames would leave ~380ms - too short for faint-frame solves.
    assert _solve_budget_ms(10.0, 0.4, now=10.02, cfg=_cfg()) == 500


def test_never_above_solve_timeout():
    assert _solve_budget_ms(10.0, 1.5, now=10.02, cfg=_cfg()) == 1000


def test_after_a_cut_short_solve_next_gets_full_timeout():
    assert _solve_budget_ms(10.0, 0.8, now=10.02, cfg=_cfg(), last_cut_short=True) == 1000
