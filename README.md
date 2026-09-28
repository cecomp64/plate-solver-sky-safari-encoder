# Binocular Plate-Solver Push-To

A push-to finder for astro binoculars: a Raspberry Pi 5 with a CSI camera
plate-solves the star field it's pointed at (via [cedar-detect] +
[cedar-solve], the Rust/Python solver stack behind the Cedar project) and
reports the resulting sky position to [SkySafari] over Wi-Fi, so SkySafari
shows a live crosshair on its sky chart - no motors, no physical encoders,
no manual 2-star alignment drift.

This replaces an earlier IMU-based version of the same idea
([`esp32_push_to`](../esp32_push_to)), which measured *relative*
orientation with an MPU-9250 and needed SkySafari's 2-star align to map
that onto the sky. A plate solver instead gets an *absolute* fix from the
stars themselves every cycle - no drift, and only a single 1-star sync
per session rather than a 2-star align (see "Configure SkySafari" in
[SETUP.md](SETUP.md) - SkySafari's Sky Commander/Basic Encoder System
protocol turns out to still need one sync to learn its tick-to-sky
offset, even though every report we send is already an absolute fix).

## How it works

```
CSI camera --> cedar-detect (Rust, star centroids)
                   --> cedar-solve / Tetra3 (RA/Dec plate solve)
                          --> astropy (RA/Dec + site + time -> Alt/Az)
                                 --> TCP :4030, SkySafari "Basic Encoder
                                     System" protocol --> SkySafari (phone)
```

The TCP protocol is ported byte-for-byte from `esp32_push_to`'s
already-debugged implementation (see
[`src/binoc_solve/encoder_server.py`](src/binoc_solve/encoder_server.py)),
so an existing SkySafari scope profile pointed at the ESP32 keeps working
unchanged if you just point it at the Pi instead - same IP, same port,
same 36000 steps/rev.

## Hardware

| Component | Notes |
| :-- | :-- |
| Raspberry Pi 5 | 64-bit Raspberry Pi OS (Bookworm). Needs a decent USB-C power bank for field use - the Pi 5 draws noticeably more than a Pi Zero. |
| CSI camera module (5MP, OV5647-based) | Ribbon-cable camera, not USB. Check the ribbon's connector pitch matches the Pi 5's camera port (small pitch) - some of these modules ship with the older large-pitch ribbon; a cheap adapter cable fixes either way. |
| microSD card | 16GB+ |
| USB-C power bank | Sized for a night's session; the Pi 5 has no built-in battery. |
| Momentary pushbutton | Cycles between your configured observing locations. No extra LED needed - it reuses the Pi's built-in power LED as the indicator. See [SETUP.md](SETUP.md) for wiring. |
| Second momentary pushbutton | Toggles the solve loop between the real camera/cedar-detect/cedar-solve pipeline and a canned solver, for demoing/testing the SkySafari integration without pointing at open sky. Uses the Pi's ACT LED as the indicator (distinct from the location button's power LED). See [SETUP.md](SETUP.md) for wiring. |

Not used in v1 (per current scope): GPS module, on-device display, the
Arduino Mega/Uno/Nano boards (they're 8-bit AVR MCUs - can't run this
software stack at all).

**No GPS/display means:**
- Your observing sites' latitude/longitude are fixed values you set in
  `config/config.yaml` by hand (see below), not auto-detected. If you
  observe from more than one site, a button (wired to the Pi's GPIO)
  lets you switch between your configured locations in the field: press
  to cycle, the Pi's built-in power LED blinks out (1-indexed) which one
  is now active, and the selection is remembered across power cycles.
  See [SETUP.md](SETUP.md) for wiring.
- The Pi's system clock must be correct **before** you disconnect from
  the internet to go observe - it hosts its own Wi-Fi access point in
  the field (mirroring `esp32_push_to`'s setup), so it can't reach an
  NTP server once deployed. Leave it on your home Wi-Fi for a minute
  before heading out; a Pi 5 without a battery-backed RTC will drift a
  few seconds over a session, which is well within push-to tolerance.

## Camera field of view

The camera is an OV5647 sensor (5MP, 1/4" optical format, 1.4um pixels,
2592x1944) on the stock fixed-focus 3.6mm M12 lens that ships on
essentially every OV5647-based Raspberry Pi Camera Module v1 clone,
including this one. FOV from the standard pinhole formula
`2*atan(sensor_dimension / (2*focal_length))`:

| | |
| :-- | :-- |
| Horizontal FOV | **53.5 deg** |
| Vertical FOV | 41.4 deg |
| Diagonal FOV | 64.4 deg |
| Plate scale | ~74 arcsec/pixel |

**This matters more than it might look**: cedar-solve's bundled
`default_database` only covers 10-30 deg FOV. At 53.5 deg this camera's
stock lens is well outside that range, so `config.yaml`'s
`solver.database_path: null` (the bundled default) will fail to solve
real images from it, not just solve them slower - see SETUP.md step 12,
building a matched database with `scripts/build_database.py` isn't
optional here. `solver.fov_estimate_deg` in `config.example.yaml` is
already set to 53.5 to match.

To verify the solve pipeline actually works at this FOV before ever
pointing the camera at a real sky - or before your database build is
even done - `scripts/generate_test_image.py` renders a synthetic
star-field image at this exact camera geometry from a real star catalog
(known ground-truth RA/Dec, so you can check the solver's answer against
a value you already know is right), and `scripts/solve_image.py` runs it
through the real cedar-detect/cedar-solve pipeline:

```
python scripts/generate_test_image.py --field orion       # writes test_images/synthetic_orion.png
python scripts/solve_image.py test_images/synthetic_orion.png
```

`--field` also takes `ursa-major` (northern) or `crux` (southern) - see
SETUP.md step 11 for verifying a from-scratch database solves correctly
in both hemispheres, not just at the default equator-straddling field.

## Setup

See [SETUP.md](SETUP.md) for the full Pi bring-up walkthrough (OS image,
dependencies, building cedar-detect/cedar-solve from source, systemd
services, Wi-Fi AP, SkySafari configuration).

## Repo layout

- `src/binoc_solve/` - the application:
  - `camera.py`, `detect_client.py`, `solver.py` - the real
    camera/cedar-detect/cedar-solve pipeline.
  - `astro.py` - RA/Dec -> Alt/Az conversion (astropy).
  - `locations.py`, `location_selector.py`, `power_led.py` - the
    multi-site button/LED selector (built-in power LED as the indicator).
  - `encoder_server.py` - the SkySafari TCP server.
  - `synthetic_sky.py` - the gnomonic-projection math behind the
    synthetic test image generator.
  - `fakes.py` - drop-in fake camera/detect/solver for testing the
    SkySafari link without hardware (see `scripts/simulate_skysafari.py`).
  - `synthetic_camera.py` - a camera stand-in that walks `test_images/`
    on a timer, feeding the *real* cedar-detect/cedar-solve pipeline
    instead of a live capture.
  - `pipeline_mode.py`, `simulator_selector.py` - the second button/LED
    (activity LED as the indicator) that cycles the solve loop through
    real / simulator (`fakes.py`) / synthetic (`synthetic_camera.py`).
  - `main.py` - wires it all together; the solve loop + entrypoint.
- `scripts/`:
  - `solve_once.py` - single-shot capture+solve+print from the real
    camera, for validating the pipeline on the Pi before involving
    SkySafari.
  - `solve_image.py` - like `solve_once.py` but on a static image file
    (synthetic or real) instead of a live camera capture.
  - `generate_test_image.py` - renders a synthetic star-field image at
    this camera's real FOV from a real star catalog, with a known
    ground-truth solution. `--field orion|ursa-major|crux` picks a
    built-in northern/southern/equatorial test field.
  - `build_database.py` - builds a Tetra3 star database matched to your
    camera's actual field of view (required at this camera's ~53.5deg
    FOV - see "Camera field of view" above).
  - `simulate_skysafari.py` - runs the real encoder server with a
    switchable set of canned solve results instead of a camera, for
    testing the SkySafari link end-to-end from a laptop.
- `data/bright_stars.csv` - real star catalog (HYG Database, CC BY-SA
  4.0) used by `generate_test_image.py`; see `data/README.md`.
- `systemd/` - service units for `cedar-detect-server` and the main app.
- `config/config.example.yaml` - copy to `config/config.yaml` and fill in
  your site location(s).
- `tests/` - unit tests for the coordinate math, the SkySafari wire
  protocol, the location selector, and the synthetic-image projection
  (cross-checked against astropy independently); run with `pytest` on
  any machine, no Pi/camera required.

## Background

The original setup guide this project is based on (targeting a Pi Zero
2W, Bookworm 32-bit, and a QHY PoleMaster camera) is linked in project
notes - the Pi 5 target here needs none of that guide's 512MB-RAM build
tuning (forced 32-bit OS, `-j1` compiles, swap expansion), which SETUP.md
reflects.

[cedar-detect]: https://github.com/smroid/cedar-detect
[cedar-solve]: https://github.com/smroid/cedar-solve
[SkySafari]: https://simulationcurriculum.com/skysafari.html
