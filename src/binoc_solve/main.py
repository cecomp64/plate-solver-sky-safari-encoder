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
from binoc_solve.solver import Solver
from binoc_solve.state import LatestFix

logger = logging.getLogger(__name__)


def _solve_loop(
    config: Config,
    camera: Camera,
    detect: DetectClient,
    solver: Solver,
    latest_fix: LatestFix,
    stop_event: threading.Event,
) -> None:
    image_size = (config.camera.height, config.camera.width)

    while not stop_event.is_set():
        cycle_start = time.monotonic()

        image = camera.capture_gray()
        centroids = detect.extract_centroids(image)
        logger.debug("Captured frame, %d star centroids", len(centroids))

        result = solver.solve(centroids, image_size)
        if result is None:
            logger.info("No solve this cycle (%d centroids)", len(centroids))
        else:
            when_utc = dt.datetime.now(dt.timezone.utc)
            alt_deg, az_deg = radec_to_altaz(
                result.ra_deg,
                result.dec_deg,
                config.site.latitude_deg,
                config.site.longitude_deg,
                config.site.elevation_m,
                when_utc,
            )
            latest_fix.update(alt_deg=alt_deg, az_deg=az_deg)
            logger.info(
                "Solved: RA=%.3f Dec=%.3f (%d matches) -> Alt=%.2f Az=%.2f",
                result.ra_deg, result.dec_deg, result.num_matches, alt_deg, az_deg,
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

    camera = Camera(config.camera)
    detect = DetectClient(config.cedar_detect.address, config.solver.sigma)
    solver = Solver(config.solver)
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
        _solve_loop(config, camera, detect, solver, latest_fix, stop_event)
    finally:
        encoder_server.shutdown()
        encoder_server.server_close()
        camera.close()


if __name__ == "__main__":
    main()
