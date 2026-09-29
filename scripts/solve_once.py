#!/usr/bin/env python3
"""Single-shot capture -> detect -> solve -> print, for validating the
pipeline on the Pi without SkySafari or the TCP server involved at all.

Run this first after SETUP.md, pointed at open sky, before trying to
connect SkySafari - it tells you directly whether the camera exposure is
usable and whether cedar-detect/cedar-solve are wired up correctly.
"""
from __future__ import annotations

import argparse
import logging
import sys

from binoc_solve.camera import Camera
from binoc_solve.config import Config
from binoc_solve.detect_client import DetectClient
from binoc_solve.solver import Solver


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    config = Config.load(args.config)
    camera = Camera(config.camera)
    detect = DetectClient(
        config.cedar_detect.address, config.solver.sigma, config.cedar_detect.binning
    )
    solver = Solver(config.solver)

    try:
        print("Capturing...")
        image = camera.capture_gray()
        print(f"Captured {image.shape[1]}x{image.shape[0]} frame.")

        print("Extracting centroids via cedar-detect...")
        detection = detect.extract_centroids(image)
        centroids = detection.centroids
        print(
            f"Found {len(centroids)} star candidates "
            f"(peak={detection.peak_star_pixel}, noise={detection.noise_estimate:.2f})."
        )
        if not centroids:
            print("No stars detected - check exposure/gain/focus and that the lens cap is off.")
            return 1

        print("Solving via cedar-solve...")
        result = solver.solve(centroids, (config.camera.height, config.camera.width))
        if result is None:
            print("No solve. Try a longer exposure, wider fov_estimate_deg, or more open sky.")
            return 1

        print(
            f"SOLVED: RA={result.ra_deg:.4f} Dec={result.dec_deg:.4f} "
            f"Roll={result.roll_deg:.2f} FOV={result.fov_deg:.2f} "
            f"matches={result.num_matches}"
        )
        return 0
    finally:
        camera.close()


if __name__ == "__main__":
    sys.exit(main())
