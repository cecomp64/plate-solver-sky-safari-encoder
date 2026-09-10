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
  build-essential libopenblas-dev git protobuf-compiler curl
```

## 4. Clone the repos

```
cd ~
git clone <this repo's URL> plate-solver-sky-safari-encoder
git clone https://github.com/smroid/cedar-solve.git
git clone https://github.com/smroid/cedar-detect.git
```

## 5. Python virtual environment

`--system-site-packages` is required so the venv can see the apt-installed
`picamera2`/`numpy`/`scipy`/`astropy` (picamera2 wraps libcamera and has
no portable pip wheel - it must come from apt).

```
cd ~/plate-solver-sky-safari-encoder
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
```

## 6. Build cedar-solve (installs the `tetra3` package)

```
cd ~/cedar-solve
pip install -e ".[dev,cedar-detect]"
```

This also installs `grpcio`/`grpcio-tools` and gives you `tetra3`'s
already-generated gRPC stubs (`tetra3.cedar_detect_pb2` /
`cedar_detect_pb2_grpc`) for talking to cedar-detect-server - no manual
`protoc` step needed on the Python side.

## 7. Build cedar-detect (Rust)

```
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- --profile minimal
source ~/.cargo/env

cd ~/cedar-detect
cargo build --release
```

(No `-j1` needed - the Pi 5 has enough RAM/cores to build normally.)

## 8. Install this project

```
cd ~/plate-solver-sky-safari-encoder
source .venv/bin/activate
pip install -e .
cp config/config.example.yaml config/config.yaml
```

Edit `config/config.yaml`:
- `site.latitude_deg` / `site.longitude_deg` / `site.elevation_m` - your
  observing location. **This is the one thing GPS would normally give
  you automatically; for v1, set it by hand and update it if you observe
  somewhere else.**
- Leave `solver.database_path: null` for now (uses cedar-solve's bundled
  database) - see step 11 for building a faster, camera-matched one later.

## 9. Sanity-check the pipeline (before touching SkySafari)

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
check focus/lens cap. If stars are detected but it doesn't solve, try a
longer `solver.solve_timeout_ms` or a wider `solver.fov_estimate_deg`.

## 10. Run as services

```
mkdir -p ~/.config/systemd/user/
cp ~/plate-solver-sky-safari-encoder/systemd/*.service ~/.config/systemd/user/
sudo loginctl enable-linger $USER   # lets user services run without an active login session
systemctl --user daemon-reload
systemctl --user enable --now cedar-detect.service binoc-solve.service
journalctl --user -u binoc-solve -f   # watch it solve in real time
```

## 11. (Later) Build a camera-matched database

The bundled `default_database` covers a wide FOV range generically and
solves slower than a database built for your camera's actual field of
view. Once you know your real horizontal FOV (from the lens focal length
and sensor width, or by checking `solve_once.py`'s reported `FOV=` value
against the default database):

```
python scripts/build_database.py --max-fov <your_fov_deg> --save-as data/my_camera
```

Then in `config.yaml`, set `solver.database_path: data/my_camera`.

## 12. Wi-Fi access point (field use, no router needed)

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

## 13. Configure SkySafari

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
crosshair should already be near the true sky position (no 2-star align
needed, since the device reports true Alt/Az from the plate solve). A
1-star Sync corrects for any fixed mechanical offset between the camera
and the binoculars' true boresight, same as you'd do with a normal DSC.

## Troubleshooting

- **Crosshair reversed on one axis**: set `flip_azimuth`/`flip_altitude:
  true` in `config.yaml`'s `encoder:` section and restart
  `binoc-solve.service`.
- **SkySafari says "no response"**: check `journalctl --user -u
  binoc-solve -f` for whether solves are succeeding at all - a device
  with no fix yet still answers `Q` (with a placeholder), so a truly
  unresponsive connection points at the network/service, not the solver.
- **Solves are rare/slow**: build a camera-matched database (step 11);
  also check `scripts/solve_once.py`'s star count - too few stars usually
  means exposure/focus, not solver tuning.
