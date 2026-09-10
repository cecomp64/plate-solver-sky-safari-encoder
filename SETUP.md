# Pi 5 Setup

Adapted from the project's original reference guide, which targeted a Pi
Zero 2W (512MB RAM) and had to fight OOM errors during builds (forced
32-bit OS, single-threaded compiles, expanded swap). None of that is
needed on a Pi 5 - use 64-bit Raspberry Pi OS and normal parallel builds.

## 1. Flash the OS

Use Raspberry Pi Imager:
- **Raspberry Pi OS Lite (64-bit)**, Bookworm.
- In the imager's advanced options (gear icon): set hostname, enable SSH,
  and join your home Wi-Fi (needed for this whole setup, and to sync the
  clock before every field session - see below).

Boot the Pi, SSH in, then:

```
sudo apt update && sudo apt upgrade -y
```

## 2. Connect and test the camera

Attach the CSI ribbon cable (blue-tape-side matches the connector's
markings on both the Pi and the camera board). Check the ribbon's
connector pitch matches the Pi 5's camera port - if it doesn't, you need
a $2 adapter cable, not a different Pi.

```
rpicam-hello --list-cameras
rpicam-still -o ~/test.jpg --timeout 2000
```

If `rpicam-still` produces a real image, the camera is wired correctly.

## 3. Install dependencies

```
sudo apt install -y \
  python3-pip python3-venv python3-dev \
  python3-numpy python3-scipy python3-astropy python3-picamera2 \
  python3-gpiozero python3-lgpio \
  build-essential libopenblas-dev git protobuf-compiler curl
```

## 4. Wire the two buttons, and free up the power/activity LEDs

Two buttons need wiring - their indicators reuse the Pi's built-in power
(`PWR`) and activity (`ACT`) LEDs instead of separate ones:

- **Location button**: one leg to GPIO17 (BCM numbering, matching
  `config.example.yaml`'s `location_selector.button_gpio: 17` - change
  both if you use a different pin), the other leg to any GND pin.
- **Simulator button**: one leg to GPIO27 (matching
  `simulator_selector.button_gpio: 27`), the other leg to any GND pin.
  Toggles the solve loop between the real camera/cedar-detect/cedar-solve
  pipeline and a canned solver (`binoc_solve/fakes.py`), so you can
  demo/test the SkySafari integration without pointing at open sky - see
  `scripts/simulate_skysafari.py`'s docstring for the same idea run
  standalone off-Pi.

`gpiozero`'s `Button` uses an internal pull-up by default, so no external
resistor is needed for either.

Quick bench test before wiring them into the enclosure:

```
python3 -c "
from gpiozero import Button
from signal import pause
btn17 = Button(17)
btn27 = Button(27)
btn17.when_pressed = lambda: print('location button pressed')
btn27.when_pressed = lambda: print('simulator button pressed')
pause()
"
```

Press each button - you should see its line printed. Ctrl-C to exit.

Check which sysfs LED entries exist on your Pi (the red power LED is
commonly named `PWR`, the green activity LED `ACT`, but this varies by
board/OS version):

```
ls /sys/class/leds/
```

If nothing there contains "PWR"/"ACT", update `location_selector.led_name`/
`simulator_selector.led_name` in `config.yaml` (step 9) to whichever
names look right (e.g. `led0`/`led1`) once you get there.

Controlling either needs write access to its LED's sysfs files, which
aren't writable by a normal user by default. Add a udev rule once, for
all LEDs:

```
sudo tee /etc/udev/rules.d/99-status-led.rules <<'EOF'
SUBSYSTEM=="leds", ACTION=="add", RUN+="/bin/chmod 666 /sys/class/leds/%k/brightness /sys/class/leds/%k/trigger"
EOF
sudo udevadm control --reload-rules
sudo reboot
```

(A reboot is the simplest way to get the rule applied to LEDs that are
already present at boot; `udevadm trigger` alone doesn't always re-fire
for them.)

Note: while `binoc-solve.service` is running, the power LED shows the
active-location pattern and the activity LED shows the real/simulated
pipeline state, instead of their normal statuses - both are restored
automatically when the service stops cleanly.

## 5. Clone the repos

```
cd ~
git clone <this repo's URL> plate-solver-sky-safari-encoder
git clone https://github.com/smroid/cedar-solve.git
git clone https://github.com/smroid/cedar-detect.git
```

## 6. Python virtual environment

`--system-site-packages` is required so the venv can see the apt-installed
`picamera2`/`numpy`/`scipy`/`astropy`/`gpiozero` (picamera2 and gpiozero's
lgpio backend both wrap C libraries and have no portable pip wheel - they
must come from apt).

```
cd ~/plate-solver-sky-safari-encoder
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
```

## 7. Build cedar-solve (installs the `tetra3` package)

```
cd ~/cedar-solve
pip install -e ".[dev,cedar-detect]"
```

This also installs `grpcio`/`grpcio-tools` and gives you `tetra3`'s
already-generated gRPC stubs (`tetra3.cedar_detect_pb2` /
`cedar_detect_pb2_grpc`) for talking to cedar-detect-server - no manual
`protoc` step needed on the Python side.

## 8. Build cedar-detect (Rust)

```
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- --profile minimal
source ~/.cargo/env

cd ~/cedar-detect
cargo build --release
```

(No `-j1` needed - the Pi 5 has enough RAM/cores to build normally.)

## 9. Install this project

```
cd ~/plate-solver-sky-safari-encoder
source .venv/bin/activate
pip install -e .
cp config/config.example.yaml config/config.yaml
```

Edit `config/config.yaml`:
- `locations:` - rename/add an entry per site you'll observe from, with
  its `latitude_deg`/`longitude_deg`/`elevation_m`. **This is the one
  thing GPS would normally give you automatically; for v1 you set each
  site once here, then use the button in the field to switch between
  them** - see "Location button + LED" below.
- Leave `solver.database_path: null` for step 10 below (uses cedar-solve's
  bundled `default_database` until you build a real one).

## 10. Build a camera-matched database (required, not optional)

This camera's stock lens gives a horizontal FOV of ~53.5deg (see
README.md's "Camera field of view" for the math) - well outside the
10-30deg range cedar-solve's bundled `default_database` was built for.
Leaving `solver.database_path: null` will fail to solve real images from
this camera, not just solve them slower, so do this before step 11:

```
cd ~/plate-solver-sky-safari-encoder
source .venv/bin/activate
python scripts/build_database.py --max-fov 55 --save-as data/ov5647_stock_lens
```

Takes a few minutes. Then in `config.yaml`, set
`solver.database_path: data/ov5647_stock_lens`.

**This one database covers the whole sky, both hemispheres, with no
extra steps** - `generate_database()` always builds from the full star
catalog (RA 0-360, Dec -90 to +90); cedar-solve has no per-hemisphere or
per-region option to configure. You don't need to think about this again
even if you take the binoculars somewhere south of the equator - it's
step 11 below that actually proves it, rather than just taking that on
faith.

(If you later swap in a different lens, rebuild with `--max-fov` set to
that lens's actual FOV and repeat step 11 below - a database built for
one FOV won't solve images at a substantially different one.)

## 11. Verify the solver on synthetic test images (both hemispheres)

Before ever pointing the camera at real sky, confirm cedar-detect and
cedar-solve are wired up correctly and the database from step 10
actually solves at this camera's geometry - using rendered images with a
known correct answer, so there's no ambiguity about whether a bad result
means "solver problem" or "bad photo". Three named test fields are
built in, spanning both hemispheres (see `FIELD_PRESETS` in
`synthetic_sky.py`):

```
python scripts/generate_test_image.py --field orion        # celestial equator
python scripts/generate_test_image.py --field ursa-major    # northern (the Big Dipper)
python scripts/generate_test_image.py --field crux          # southern (the Southern Cross)

python scripts/solve_image.py test_images/synthetic_orion.png
python scripts/solve_image.py test_images/synthetic_ursa-major.png
python scripts/solve_image.py test_images/synthetic_crux.png
```

Each `generate_test_image.py` run prints its ground-truth `RA=... Dec=...
FOV=53.5`; each `solve_image.py` run's `SOLVED: RA=... Dec=...` should
land within a fraction of a degree of the corresponding one. All three
solving correctly is what actually demonstrates the database from step
10 works regardless of which hemisphere you're observing from - not just
the equator-straddling default field.

If any say "No solve", double check `solver.database_path` in
`config.yaml` actually points at step 10's database (not still `null`),
and that `cedar-detect-server` is running (see step 12 below for
starting it manually).

## 12. Sanity-check the pipeline with a real capture (before touching SkySafari)

In one terminal:
```
~/cedar-detect/target/release/cedar-detect-server
```

In another, pointed at open sky:
```
cd ~/plate-solver-sky-safari-encoder
source .venv/bin/activate
python scripts/solve_once.py
```

You want to see `SOLVED: RA=... Dec=... ...`. If it says "No stars
detected", adjust `camera.exposure_ms`/`camera.gain` in `config.yaml` and
check focus/lens cap. If stars are detected but it doesn't solve and step
11's synthetic image did solve, the issue is specific to the real
capture (focus, exposure, or a genuinely cloudy/obstructed view) rather
than the solver setup itself.

## 13. Run as services

```
mkdir -p ~/.config/systemd/user/
cp ~/plate-solver-sky-safari-encoder/systemd/*.service ~/.config/systemd/user/
sudo loginctl enable-linger $USER   # lets user services run without an active login session
systemctl --user daemon-reload
systemctl --user enable --now cedar-detect.service binoc-solve.service
journalctl --user -u binoc-solve -f   # watch it solve in real time
```

On startup, and after every location-button press, the power LED blinks
the 1-indexed position of the active location in `config.yaml`'s
`locations:` list (location 1 = one blink, location 2 = two blinks,
twice, pausing between repeats). The selection is saved to
`state/active_location.txt` and survives a power cycle - it only
changes when you press the button.

On startup, and after every simulator-button press, the activity LED
blinks 1 (real pipeline) or 2 (simulator) to confirm the new state.
Unlike the location selection, this always starts real on boot - a
forgotten press can't silently leave the field session on canned
positions after a power cycle. While simulating, solved-fix log lines
are tagged `[SIMULATED]`.

## 14. Wi-Fi access point (field use, no router needed)

Mirrors `esp32_push_to`'s standalone AP so an existing SkySafari scope
profile keeps its IP/port unchanged - just swap which device you connect
to. Bookworm's default network stack is NetworkManager:

```
sudo nmcli connection add type wifi ifname wlan0 con-name BinocularAP \
  autoconnect yes ssid Binocular_Nav
sudo nmcli connection modify BinocularAP 802-11-wireless.mode ap 802-11-wireless.band bg
sudo nmcli connection modify BinocularAP ipv4.method shared ipv4.addresses 192.168.4.1/24
sudo nmcli connection modify BinocularAP wifi-sec.key-mgmt wpa-psk wifi-sec.psk "stargazing123"
sudo nmcli connection up BinocularAP
```

**Before disconnecting from your home Wi-Fi to go observe, sync the
clock**: `timedatectl` should show `System clock synchronized: yes`. Once
the Pi is running its own AP in the field it has no path to an NTP
server, so whatever time it has when you leave is what it solves with
for the rest of the session (a few seconds of drift over one night is
fine; get it right before you leave, not after).

## 15. Configure SkySafari

| Setting | Value |
| :-- | :-- |
| Scope Type | `Sky Commander` (or `Basic Encoder System`) |
| Mount Type | `Alt-Az. Push-To` |
| IP Address | `192.168.4.1` |
| Port Number | `4030` |
| Azimuth Steps Per Rev | `36000` (`-36000` if reversed) |
| Altitude Steps Per Rev | `36000` (`-36000` if reversed) |
| Get Alignment From Scope | Disabled |
| Set Time & Location | Disabled |

Connect your phone to `Binocular_Nav`, tap Connect in SkySafari - the
crosshair will move correctly (it tracks true Alt/Az from the plate
solve every cycle) but will likely **not** be near the true sky
position yet: SkySafari's Sky Commander/Basic Encoder System protocol
treats raw encoder ticks as relative to an arbitrary zero-point until
you sync, so without one it's faithfully relaying our correct relative
motion anchored to the wrong absolute spot (confirmed empirically -
this is not just theoretical mechanical-offset correction).

Fix it with a **1-star Sync**: pick a bright, identifiable object (or
just use whatever the crosshair happens to be circling if you're
testing with the simulator button), select it in SkySafari, and choose
Align/Sync Scope Here. This teaches SkySafari the tick-to-sky offset for
the rest of the session - after that one sync, the crosshair should
track the true sky position continuously, since every report we send is
already an absolute fix, not a relative one (no need to re-sync as you
move around, only once per SkySafari session/reconnect). A 1-star Sync
also still doubles as the correction for any fixed mechanical offset
between the camera and the binoculars' true boresight, same as it would
on a normal DSC.

## Troubleshooting

- **Crosshair moves correctly (e.g. circles smoothly with the simulator
  on) but lands nowhere near the right part of the sky, even with
  location/clock both confirmed correct**: you haven't synced yet this
  session - see the 1-star Sync step above. This looks alarming (can be
  tens of degrees off in both RA and Dec) but is expected before the
  first sync.
- **Crosshair reversed on one axis**: set `flip_azimuth`/`flip_altitude:
  true` in `config.yaml`'s `encoder:` section and restart
  `binoc-solve.service`.
- **SkySafari says "no response"**: check `journalctl --user -u
  binoc-solve -f` for whether solves are succeeding at all - a device
  with no fix yet still answers `Q` (with a placeholder), so a truly
  unresponsive connection points at the network/service, not the solver.
- **Solves are rare/slow**: confirm `solver.database_path` isn't still
  `null` (step 10 - required at this camera's ~53.5deg FOV, not just an
  optimization); also check `scripts/solve_once.py`'s star count - too
  few stars usually means exposure/focus, not solver tuning.
- **Positions are off by a consistent amount at a given site**: check
  that the active location's LED blink count actually matches the site
  you're at (easy to forget a press after moving locations), and that
  its lat/lon in `config.yaml` is correct.
- **Button press doesn't do anything**: check `journalctl --user -u
  binoc-solve -f` for "Location selector ready" / "Simulator selector
  ready" at startup - if a line is missing, the service failed to claim
  that button's GPIO pin (check wiring/pin number match `config.yaml`,
  and that nothing else on the system is using GPIO17/GPIO27) or its LED
  (see below).
- **Service fails to start with a permission error on `/sys/class/leds/...`**:
  the udev rule from step 4 either wasn't applied or hasn't taken effect
  yet - confirm `/etc/udev/rules.d/99-status-led.rules` exists and
  reboot. The error message names the exact file it couldn't write.
- **No LED under `/sys/class/leds/` matches "PWR"/"ACT"**: run `ls
  /sys/class/leds/` and set `location_selector.led_name`/
  `simulator_selector.led_name` in `config.yaml` to whatever's actually
  there (the startup error also lists the available names).
- **Positions look plausible but suspiciously fixed to a handful of
  bright stars**: the simulator button was likely pressed by accident -
  check for `[SIMULATED]` in `journalctl --user -u binoc-solve -f` and
  press it again to go back to the real pipeline.
