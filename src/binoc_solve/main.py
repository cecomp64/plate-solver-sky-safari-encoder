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
from binoc_solve.camera import Camera
from binoc_solve.config import Config
from binoc_solve.detect_client import DetectClient
from binoc_solve.encoder_server import EncoderTCPServer
from binoc_solve.fakes import FakeCamera, FakeDetectClient, SlewingFakeSolver
from binoc_solve.location_selector import LocationSelector
from binoc_solve.locations import LocationStore
from binoc_solve.simulator_selector import SimulatorSelector
from binoc_solve.simulator_toggle import SimulatorToggle
from binoc_solve.solver import Solver
from binoc_solve.state import LatestFix

logger = logging.getLogger(__name__)


def _solve_loop(
    config: Config,
    real_camera: Camera,
    real_detect: DetectClient,
    real_solver: Solver,
    fake_camera: FakeCamera,
    fake_detect: FakeDetectClient,
    fake_solver: SlewingFakeSolver,
    location_store: LocationStore,
    simulator_toggle: SimulatorToggle,
    latest_fix: LatestFix,
    stop_event: threading.Event,
) -> None:
    image_size = (config.camera.height, config.camera.width)

    while not stop_event.is_set():
        cycle_start = time.monotonic()

        # Re-read every cycle, same reasoning as location_store.current()
        # below: a button press mid-session should take effect on the
        # very next cycle, not just at startup.
        simulating = simulator_toggle.enabled
        camera = fake_camera if simulating else real_camera
        detect = fake_detect if simulating else real_detect
        solver = fake_solver if simulating else real_solver

        image = camera.capture_gray()
        centroids = detect.extract_centroids(image)
        logger.debug("Captured frame, %d star centroids", len(centroids))

        result = solver.solve(centroids, image_size)
        if result is None:
            logger.info("No solve this cycle (%d centroids)", len(centroids))
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
            logger.info(
                "Solved%s (%s): RA=%.3f Dec=%.3f (%d matches) -> Alt=%.2f Az=%.2f",
                " [SIMULATED]" if simulating else "",
                location.name, result.ra_deg, result.dec_deg, result.num_matches, alt_deg, az_deg,
            )

        elapsed = time.monotonic() - cycle_start
        remaining = config.loop.min_interval_s - elapsed
        if remaining > 0:
            stop_event.wait(remaining)


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

    simulator_toggle = SimulatorToggle()
    simulator_selector = SimulatorSelector(config.simulator_selector, simulator_toggle)

    real_camera = Camera(config.camera)
    real_detect = DetectClient(config.cedar_detect.address, config.solver.sigma)
    real_solver = Solver(config.solver)
    fake_camera = FakeCamera()
    fake_detect = FakeDetectClient()
    fake_solver = SlewingFakeSolver()
    latest_fix = LatestFix()

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
            config,
            real_camera, real_detect, real_solver,
            fake_camera, fake_detect, fake_solver,
            location_store, simulator_toggle,
            latest_fix, stop_event,
        )
    finally:
        encoder_server.shutdown()
        encoder_server.server_close()
        real_camera.close()
        location_selector.close()
        simulator_selector.close()


if __name__ == "__main__":
    main()
