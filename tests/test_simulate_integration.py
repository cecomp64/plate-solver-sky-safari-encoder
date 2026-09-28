"""End-to-end check that the simulator's wiring actually works: a fake
solve result flows through the real solve loop, the real RA/Dec->Alt/Az
conversion, and the real encoder TCP server, and a genuine socket client
gets back the tick values that fix implies - exactly what
scripts/simulate_skysafari.py relies on for testing SkySafari.
"""
import socket
import threading
import time

from binoc_solve.config import (
    AutoExposureConfig,
    CameraConfig,
    CedarDetectConfig,
    Config,
    EncoderConfig,
    LocationSelectorConfig,
    LoopConfig,
    SimulatorSelectorConfig,
    SolverConfig,
    SyntheticCameraConfig,
)
from binoc_solve.encoder_server import EncoderTCPServer, _alt_deg_to_ticks, _az_deg_to_ticks
from binoc_solve.fakes import CannedSolution, FakeCamera, FakeDetectClient, FakeSolver
from binoc_solve.locations import LocationStore, NamedLocation
from binoc_solve.main import _solve_loop
from binoc_solve.pipeline_mode import Mode, ModeStore
from binoc_solve.state import LatestFix


def _build_config(tmp_path) -> Config:
    return Config(
        locations=[NamedLocation("Test Site", latitude_deg=40.0, longitude_deg=-105.0, elevation_m=1600.0)],
        location_selector=LocationSelectorConfig(
            button_gpio=17, led_name="PWR", state_file=str(tmp_path / "active_location.txt"),
            bounce_time_s=0.05, blink_on_s=0.1, blink_off_s=0.1, blink_repeat_pause_s=0.5, blink_repeats=1,
        ),
        simulator_selector=SimulatorSelectorConfig(
            button_gpio=27, led_name="ACT",
            bounce_time_s=0.05, blink_on_s=0.1, blink_off_s=0.1, blink_repeat_pause_s=0.5, blink_repeats=1,
        ),
        camera=CameraConfig(exposure_ms=1000, gain=1.0, width=16, height=16),
        auto_exposure=AutoExposureConfig(
            enabled=False, min_exposure_ms=100, max_exposure_ms=1500, min_gain=1.0, max_gain=16.0,
            min_centroids=15, saturation_peak=250, low_streak=3, high_streak=2,
            adjustment_factor=1.4, cooldown_cycles=2,
        ),
        synthetic_camera=SyntheticCameraConfig(image_dir=str(tmp_path / "test_images"), interval_s=1.5),
        solver=SolverConfig(database_path=None, fov_estimate_deg=30.0, sigma=8.0, solve_timeout_ms=1000),
        cedar_detect=CedarDetectConfig(address="localhost:50051"),
        encoder=EncoderConfig(
            bind_host="127.0.0.1", bind_port=0, az_resolution=36000, alt_resolution=36000,
            flip_azimuth=False, flip_altitude=False,
        ),
        loop=LoopConfig(min_interval_s=0.05, stale_fix_warn_s=10.0),
    )


def test_simulated_solve_reaches_skysafari_over_real_socket(tmp_path):
    config = _build_config(tmp_path)
    location_store = LocationStore(config.locations, config.location_selector.state_file)
    solver = FakeSolver([CannedSolution("Test Star", ra_deg=123.0, dec_deg=15.0)])
    latest_fix = LatestFix()

    server = EncoderTCPServer(config.encoder, latest_fix, config.loop.stale_fix_warn_s)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    stop_event = threading.Event()
    camera, detect = FakeCamera(), FakeDetectClient()
    pipelines = {Mode.REAL: (camera, detect, solver)}
    solve_thread = threading.Thread(
        target=_solve_loop,
        args=(config, pipelines, location_store, ModeStore(), latest_fix, stop_event),
        daemon=True,
    )
    solve_thread.start()

    try:
        deadline = time.monotonic() + 3.0
        while latest_fix.get() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        fix = latest_fix.get()
        assert fix is not None, "solve loop never produced a fix from the fake solver"

        sock = socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=2)
        try:
            sock.sendall(b"Q")
            reply = sock.recv(64)
        finally:
            sock.close()

        expected_az_ticks = _az_deg_to_ticks(fix.az_deg, config.encoder.az_resolution, flip=False)
        expected_alt_ticks = _alt_deg_to_ticks(fix.alt_deg, config.encoder.alt_resolution, flip=False)
        expected = f"{expected_az_ticks:+06d}\t{expected_alt_ticks:+06d}\r".encode("ascii")
        assert reply == expected
    finally:
        stop_event.set()
        server.shutdown()
        server.server_close()


def test_switching_solutions_changes_the_served_fix(tmp_path):
    config = _build_config(tmp_path)
    location_store = LocationStore(config.locations, config.location_selector.state_file)
    solver = FakeSolver(
        [
            CannedSolution("Star A", ra_deg=10.0, dec_deg=10.0),
            CannedSolution("Star B", ra_deg=200.0, dec_deg=-30.0),
        ]
    )
    latest_fix = LatestFix()
    stop_event = threading.Event()
    camera, detect = FakeCamera(), FakeDetectClient()
    pipelines = {Mode.REAL: (camera, detect, solver)}
    solve_thread = threading.Thread(
        target=_solve_loop,
        args=(config, pipelines, location_store, ModeStore(), latest_fix, stop_event),
        daemon=True,
    )
    solve_thread.start()

    try:
        deadline = time.monotonic() + 3.0
        while latest_fix.get() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        fix_a = latest_fix.get()
        assert fix_a is not None

        solver.next()
        time.sleep(0.3)  # a couple of solve_loop cycles at min_interval_s=0.05
        fix_b = latest_fix.get()

        assert (fix_a.alt_deg, fix_a.az_deg) != (fix_b.alt_deg, fix_b.az_deg)
    finally:
        stop_event.set()
