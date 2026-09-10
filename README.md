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

## Setup

See [SETUP.md](SETUP.md) for the full Pi bring-up walkthrough (OS image,
dependencies, building cedar-detect/cedar-solve from source, systemd
services, Wi-Fi AP, SkySafari configuration).

## Repo layout

- `src/binoc_solve/` - the application: camera capture, the cedar-detect
  gRPC client, the cedar-solve wrapper, RA/Dec->Alt/Az conversion, the
  SkySafari TCP server, and the main solve loop.
- `scripts/solve_once.py` - single-shot capture+solve+print, for
  validating the pipeline on the Pi before ever involving SkySafari.
- `scripts/build_database.py` - builds a Tetra3 star database matched to
  your camera's actual field of view (faster/more reliable solves than
  the generic bundled database).
- `systemd/` - service units for `cedar-detect-server` and the main app.
- `config/config.example.yaml` - copy to `config/config.yaml` and fill in
  your site location.
- `tests/` - unit tests for the coordinate math and the SkySafari wire
  protocol; run with `pytest` on any machine, no Pi/camera required.

## Background

The original setup guide this project is based on (targeting a Pi Zero
2W, Bookworm 32-bit, and a QHY PoleMaster camera) is linked in project
notes - the Pi 5 target here needs none of that guide's 512MB-RAM build
tuning (forced 32-bit OS, `-j1` compiles, swap expansion), which SETUP.md
reflects.

[cedar-detect]: https://github.com/smroid/cedar-detect
[cedar-solve]: https://github.com/smroid/cedar-solve
[SkySafari]: https://simulationcurriculum.com/skysafari.html
