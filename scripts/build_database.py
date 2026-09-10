#!/usr/bin/env python3
"""Builds a Tetra3 star-pattern database matched to your camera+lens's
actual field of view, instead of relying on cedar-solve's bundled
default_database (which covers a wide FOV range generically and solves
slower as a result).

Before running this, measure your camera's real horizontal FOV (from the
sensor width and the lens's actual focal length, or empirically from a
captured frame of a known star field) and pass it as --max-fov.

Needs a star catalog download first - see cedar-solve's own README for
where to place it ('hip_main' is the recommended default catalog).
This can take from a couple of minutes (wide FOV) to hours (narrow FOV,
high star density) - run it once, at home, well before a session.
"""
from __future__ import annotations

import argparse
import logging


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-fov", type=float, required=True, help="Degrees, horizontal.")
    parser.add_argument("--min-fov", type=float, default=None)
    parser.add_argument("--star-catalog", default="hip_main", choices=["bsc5", "hip_main", "tyc_main"])
    parser.add_argument(
        "--save-as",
        required=True,
        help="Output path (without .npz suffix) - point solver.database_path in "
        "config.yaml at this same path.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from tetra3 import Tetra3  # noqa: PLC0415 - only needed once cedar-solve is installed

    t3 = Tetra3(load_database=None)
    t3.generate_database(
        max_fov=args.max_fov,
        min_fov=args.min_fov,
        star_catalog=args.star_catalog,
        save_as=args.save_as,
    )
    print(f"Database written to {args.save_as}.npz")


if __name__ == "__main__":
    main()
