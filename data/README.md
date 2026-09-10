# data/

## bright_stars.csv

8,920 stars at Vmag <= 6.5 (naked-eye visible), columns
`ra_deg,dec_deg,mag,name,hip`, sorted brightest first. Extracted from the
[HYG Database](https://github.com/astronexus/HYG-Database) v40
(`hygdata_v40.csv`), which combines the Hipparcos, Yale Bright Star, and
Gliese catalogs.

License: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)
- attribution: HYG Database, astronexus (github.com/astronexus/HYG-Database).
- share-alike: derivatives of this data must carry the same license.

Used by `scripts/generate_test_image.py` to render synthetic star-field
test images with a known ground-truth solution, for exercising the
cedar-detect/cedar-solve pipeline without a camera or a real night-sky
capture.

## *.npz (gitignored)

Tetra3 star-pattern databases built by `scripts/build_database.py` -
these are machine/camera-specific outputs, not source, so they aren't
committed (see `.gitignore`).
