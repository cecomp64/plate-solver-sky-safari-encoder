"""Entrypoint: wires camera -> cedar-detect -> cedar-solve -> astro ->
encoder server, and runs the solve loop until interrupted.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import signal
import threading

from binoc_solve.astro import radec_to_altaz
from binoc_solve.auto_exposure import AutoExposureController
from binoc_solve.camera import Camera
from binoc_solve.config import Config
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
    # Set while a solve is running, so a newer frame can supersede it.
    active_solver: list[object | None] = [None]

    def _supersede_active_solve() -> None:
        solver = active_solver[0]
        if solver is not None and hasattr(solver, "supersede"):  # the fakes don't
            solver.supersede()

    def _current_camera() -> tuple[Mode, object]:
        # Re-read every capture, same reasoning as location_store.current()
        # below: a button press mid-session should take effect on the
        # very next frame, not just at startup.
        mode = mode_store.current()
        return mode, pipelines[mode][0]

    grabber = LatestFrameGrabber(
        _current_camera, config.loop.min_interval_s, on_new_frame=_supersede_active_solve
    )
    grabber.start()
    try:
        last_seq = 0
        while not stop_event.is_set():
            frame = grabber.wait_for_frame(last_seq, timeout=0.5)
            if frame is None:
                continue
            last_seq = frame.seq
            _process_frame(
                frame, pipelines, location_store, latest_fix, active_solver,
                auto_exposure, failed_frames,
            )
    finally:
        grabber.stop()


def _process_frame(
    frame: Frame,
    pipelines: dict[Mode, Pipeline],
    location_store: LocationStore,
    latest_fix: LatestFix,
    active_solver: list[object | None],
    auto_exposure: AutoExposureController | None,
    failed_frames: FailedFrameRecorder | None,
) -> None:
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

    active_solver[0] = solver
    try:
        result = solver.solve(centroids, image_size)
    finally:
        active_solver[0] = None
    if result is None:
        logger.info("No solve this cycle (%d centroids)", len(centroids))
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
            "Solved%s (%s): RA=%.3f Dec=%.3f (%d matches) -> Alt=%.2f Az=%.2f",
            tag, location.name, result.ra_deg, result.dec_deg, result.num_matches, alt_deg, az_deg,
        )


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
