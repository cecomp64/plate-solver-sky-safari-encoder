#!/usr/bin/env python3
"""Runs a static image file through the real cedar-detect + cedar-solve
pipeline and prints the result. Use this with
scripts/generate_test_image.py's synthetic output (known ground truth,
so you can check the answer) or with a real photo of the night sky.

Needs cedar-detect-server running and cedar-solve installed, same as
solve_once.py - see SETUP.md. This is the counterpart to
scripts/simulate_skysafari.py: that one fakes the solver to test the
SkySafari link, this one runs the real solver to test *it*.
"""
from __future__ import annotations

import argparse
import logging
import sys

import numpy as np
from PIL import Image

from binoc_solve.config import Config
from binoc_solve.detect_client import DetectClient
from binoc_solve.solver import Solver


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="Path to a grayscale (or any PIL-readable) test image")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    config = Config.load(args.config)
    detect = DetectClient(
        config.cedar_detect.address, config.solver.sigma, config.cedar_detect.binning
    )
    solver = Solver(config.solver)

    with Image.open(args.image) as img:
        image = np.asarray(img.convert("L"), dtype=np.uint8)
    print(f"Loaded {args.image}: {image.shape[1]}x{image.shape[0]}")

    print("Extracting centroids via cedar-detect...")
    detection = detect.extract_centroids(image)
    centroids = detection.centroids
    print(
        f"Found {len(centroids)} star candidates "
        f"(peak={detection.peak_star_pixel}, noise={detection.noise_estimate:.2f})."
    )
    if not centroids:
        print("No stars detected.")
        return 1

    print("Solving via cedar-solve...")
    result = solver.solve(centroids, image.shape[:2])
    if result is None:
        print(
            "No solve. If this is a synthetic image from generate_test_image.py, check that "
            "solver.fov_estimate_deg in config.yaml is close to its printed ground-truth FOV, "
            "and that solver.database_path covers that FOV (see SETUP.md - the bundled "
            "default_database only covers 10-30deg, well short of this camera's ~53.5deg)."
        )
        return 1

    print(
        f"SOLVED: RA={result.ra_deg:.4f} Dec={result.dec_deg:.4f} "
        f"Roll={result.roll_deg:.2f} FOV={result.fov_deg:.2f} matches={result.num_matches}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
