"""Entrypoint: wires camera -> cedar-detect -> cedar-solve -> astro ->
encoder server, and runs the solve loop until interrupted.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import signal
import threading
import time

from binoc_solve.astro import radec_to_altaz
from binoc_solve.auto_exposure import AutoExposureController
from binoc_solve.camera import Camera
from binoc_solve.config import Config, SolverConfig
from binoc_solve.detect_client import DetectClient
from binoc_solve.encoder_server import EncoderTCPServer
from binoc_solve.failed_frames import FailedFrameRecorder
from binoc_solve.fakes import FakeCamera, FakeDetectClient, SlewingFakeSolver
from binoc_solve.frame_grabber import Frame, LatestFrameGrabber
from binoc_solve.location_selector import LocationSelector
from binoc_solve.locations import LocationStore
from binoc_solve.pipeline_mode import Mode, ModeStore
from binoc_solve.simulator_selector import SimulatorSelector
from binoc_solve.solver import Solver
from binoc_solve.state import LatestFix
from binoc_solve.synthetic_camera import SyntheticImageCamera

logger = logging.getLogger(__name__)

# camera, detect, solver - duck-typed the same way across the real
# pipeline and both fakes, so any (Camera|FakeCamera|SyntheticImageCamera,
# DetectClient|FakeDetectClient, Solver|FakeSolver|SlewingFakeSolver)
# triple works here.
Pipeline = tuple[object, object, object]


def _solve_loop(
    config: Config,
    pipelines: dict[Mode, Pipeline],
    location_store: LocationStore,
    mode_store: ModeStore,
    latest_fix: LatestFix,
    stop_event: threading.Event,
    auto_exposure: AutoExposureController | None = None,
    failed_frames: FailedFrameRecorder | None = None,
) -> None:
    def _current_camera() -> tuple[Mode, object]:
        # Re-read every capture, same reasoning as location_store.current()
        # below: a button press mid-session should take effect on the
        # very next frame, not just at startup.
        mode = mode_store.current()
        return mode, pipelines[mode][0]

    grabber = LatestFrameGrabber(_current_camera, config.loop.min_interval_s)
    grabber.start()
    try:
        last_seq = 0
        last_cut_short = False
        while not stop_event.is_set():
            frame = grabber.wait_for_frame(last_seq, timeout=0.5)
            if frame is None:
                continue
            last_seq = frame.seq
            timeout_ms = _solve_budget_ms(
                frame.captured_at, grabber.frame_interval_s, time.monotonic(), config.solver,
                last_cut_short,
            )
            solved, solve_ms = _process_frame(
                frame, timeout_ms, pipelines, location_store, latest_fix,
                auto_exposure, failed_frames,
            )
            # Ran out its whole budget but that budget was the next-frame
            # deadline, not the hard timeout - see _solve_budget_ms().
            last_cut_short = (
                not solved and timeout_ms < config.solver.solve_timeout_ms
                and solve_ms >= 0.95 * timeout_ms
            )
    finally:
        grabber.stop()


def _solve_budget_ms(
    captured_at: float,
    frame_interval_s: float | None,
    now: float,
    cfg: SolverConfig,
    last_cut_short: bool = False,
) -> float:
    """How long to let this frame's solve run: until the next frame is due,
    since a newer frame beats finishing an old one (after a slew, the old
    one was likely exposed while moving). Never less than
    supersede_after_ms, so slow but genuine solves on faint frames (seen
    needing ~0.3-0.6s) survive a fast camera; never more than
    solve_timeout_ms.

    If the previous solve was cut off by that deadline, this one gets the
    full solve_timeout_ms instead: otherwise a sky where every genuine
    solve takes longer than a frame would never solve at all. At worst
    that alternates cut-short and full-length solves."""
    if frame_interval_s is None or last_cut_short:
        return cfg.solve_timeout_ms
    until_next_ms = (captured_at + frame_interval_s - now) * 1000
    return min(cfg.solve_timeout_ms, max(cfg.supersede_after_ms, until_next_ms))


def _process_frame(
    frame: Frame,
    timeout_ms: float,
    pipelines: dict[Mode, Pipeline],
    location_store: LocationStore,
    latest_fix: LatestFix,
    auto_exposure: AutoExposureController | None,
    failed_frames: FailedFrameRecorder | None,
) -> tuple[bool, float]:
    """Returns (solved, milliseconds the solve took)."""
    mode = frame.source
    camera, detect, solver = pipelines[mode]
    image = frame.image
    image_size = image.shape[:2]

    detection = detect.extract_centroids(image)
    centroids = detection.centroids
    logger.debug("Frame %d: %d star centroids", frame.seq, len(centroids))

    # Only the real camera's own captures say anything about real sky
    # brightness - the simulator/synthetic modes' images aren't fed
    # back into exposure control.
    if auto_exposure is not None and mode == Mode.REAL:
        new_settings = auto_exposure.observe(len(centroids), detection.peak_star_pixel)
        if new_settings is not None:
            camera.set_exposure(new_settings.exposure_ms, new_settings.gain)

    solve_start = time.monotonic()
    result = solver.solve(centroids, image_size, timeout_ms=timeout_ms)
    solve_ms = (time.monotonic() - solve_start) * 1000
    if result is None:
        logger.info(
            "No solve this cycle (%d centroids, %.0f/%.0fms)", len(centroids), solve_ms, timeout_ms
        )
        # Real captures only - simulator/synthetic frames aren't field evidence.
        if failed_frames is not None and mode == Mode.REAL:
            failed_frames.maybe_save(image, len(centroids))
    else:
        location = location_store.current()
        when_utc = dt.datetime.now(dt.timezone.utc)
        alt_deg, az_deg = radec_to_altaz(
            result.ra_deg,
            result.dec_deg,
            location.latitude_deg,
            location.longitude_deg,
            location.elevation_m,
            when_utc,
        )
        latest_fix.update(alt_deg=alt_deg, az_deg=az_deg)
        tag = f" [{mode.value.upper()}]" if mode != Mode.REAL else ""
        logger.info(
            "Solved%s (%s): RA=%.3f Dec=%.3f (%d matches, %.0fms) -> Alt=%.2f Az=%.2f",
            tag, location.name, result.ra_deg, result.dec_deg, result.num_matches, solve_ms,
            alt_deg, az_deg,
        )
    return result is not None, solve_ms


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = Config.load(args.config)

    location_store = LocationStore(config.locations, config.location_selector.state_file)
    # astropy loads its time/Earth-orientation tables on the first
    # conversion (~0.8s on the Pi) - do it now rather than delaying the
    # first fix after every restart.
    loc = location_store.current()
    radec_to_altaz(
        0.0, 0.0, loc.latitude_deg, loc.longitude_deg, loc.elevation_m,
        dt.datetime.now(dt.timezone.utc),
    )
    location_selector = LocationSelector(config.location_selector, location_store)

    mode_store = ModeStore()
    simulator_selector = SimulatorSelector(config.simulator_selector, mode_store)

    real_camera = Camera(config.camera)
    auto_exposure = AutoExposureController(
        config.auto_exposure, config.camera.exposure_ms, config.camera.gain
    )
    failed_frames = FailedFrameRecorder(config.failed_frames)
    real_detect = DetectClient(
        config.cedar_detect.address, config.solver.sigma, config.cedar_detect.binning
    )
    real_solver = Solver(config.solver)
    fake_camera = FakeCamera()
    fake_detect = FakeDetectClient()
    fake_solver = SlewingFakeSolver()
    synthetic_camera = SyntheticImageCamera(
        config.synthetic_camera.image_dir, config.synthetic_camera.interval_s
    )
    latest_fix = LatestFix()

    pipelines: dict[Mode, Pipeline] = {
        Mode.REAL: (real_camera, real_detect, real_solver),
        Mode.SIMULATOR: (fake_camera, fake_detect, fake_solver),
        # Reuses the real detect/solver (not fakes) - the point of this
        # mode is a genuine solve, just against a pre-rendered image
        # instead of a live capture. Also avoids loading a second copy of
        # the Tetra3 star database.
        Mode.SYNTHETIC: (synthetic_camera, real_detect, real_solver),
    }

    encoder_server = EncoderTCPServer(config.encoder, latest_fix, config.loop.stale_fix_warn_s)
    server_thread = threading.Thread(target=encoder_server.serve_forever, daemon=True)
    server_thread.start()
    logger.info(
        "SkySafari encoder server listening on %s:%s",
        config.encoder.bind_host, config.encoder.bind_port,
    )

    stop_event = threading.Event()

    def _handle_signal(signum, _frame):
        logger.info("Received signal %s, shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        _solve_loop(
            config, pipelines, location_store, mode_store, latest_fix, stop_event, auto_exposure,
            failed_frames,
        )
    finally:
        encoder_server.shutdown()
        encoder_server.server_close()
        real_camera.close()
        location_selector.close()
        simulator_selector.close()


if __name__ == "__main__":
    main()
