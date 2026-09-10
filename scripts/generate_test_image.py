#!/usr/bin/env python3
"""Renders a synthetic star-field test image matching this project's
camera (OV5647, stock 3.6mm M12 lens: ~53.5 x 41.4 deg FOV, 2592x1944),
from real star positions/magnitudes in data/bright_stars.csv.

Use this to test the actual solve pipeline (cedar-detect + cedar-solve)
end-to-end with scripts/solve_image.py, without needing a real night-sky
capture - and because it has a known ground-truth RA/Dec/FOV, you can
check the solver's answer against a value you already know is right,
rather than guessing whether an unfamiliar real photo "looks about
right".

Default field is Orion - bright, unmistakable, and near the celestial
equator so it's visible from most latitudes. Pass --ra/--dec for a
different field.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

from binoc_solve.synthetic_sky import (
    DEFAULT_CATALOG,
    DEFAULT_DEC_DEG,
    DEFAULT_RA_DEG,
    SENSOR_HEIGHT_PX,
    SENSOR_WIDTH_PX,
    horizontal_fov_deg,
    load_catalog,
    render,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ra", type=float, default=DEFAULT_RA_DEG, help="Field center RA, degrees")
    parser.add_argument("--dec", type=float, default=DEFAULT_DEC_DEG, help="Field center Dec, degrees")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--out", type=Path, default=Path("test_images/synthetic_test.png"))
    parser.add_argument("--max-mag", type=float, default=6.5, help="Faintest star magnitude to include")
    args = parser.parse_args()

    catalog = load_catalog(args.catalog, max_mag=args.max_mag)
    if not catalog:
        print(f"No catalog stars at mag<={args.max_mag} - check --catalog path.", file=sys.stderr)
        return 1

    image, placed = render(args.ra, args.dec, catalog)
    if not placed:
        print(
            f"Warning: 0 stars fell inside the frame for RA={args.ra} Dec={args.dec} - "
            "is that field center correct?",
            file=sys.stderr,
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image, mode="L").save(args.out)

    print(f"Wrote {args.out} ({SENSOR_WIDTH_PX}x{SENSOR_HEIGHT_PX}, {len(placed)} stars placed)")
    print(f"Ground truth: RA={args.ra:.4f} Dec={args.dec:.4f}  FOV={horizontal_fov_deg():.1f} deg (horizontal)")
    print("Brightest stars placed:")
    for star in sorted(placed, key=lambda p: p.mag)[:10]:
        label = star.name or "(unnamed)"
        print(f"  {label:20s} mag={star.mag:5.2f}  pixel=({star.x_px:7.1f}, {star.y_px:7.1f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
