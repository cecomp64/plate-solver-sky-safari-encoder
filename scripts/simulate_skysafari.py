#!/usr/bin/env python3
"""Runs the real solve loop and SkySafari encoder server, but with the
camera/cedar-detect/cedar-solve pipeline replaced by a small set of
canned RA/Dec "solve results" you switch between by hand - so you can
test the SkySafari integration (does the crosshair land in the right
place, does the encoder protocol behave, does switching between
configured locations change the reported Alt/Az correctly) without a
camera, without cedar-detect/cedar-solve installed, and without even
being on a Raspberry Pi.

This runs fine on a laptop - point SkySafari at this machine's IP and
port 4030 (same Wi-Fi network) instead of the Pi's.

Reuses main._solve_loop unchanged, so the simulated run exercises the
exact same astro conversion and encoder-server code a real deployment
does; only the camera/detect/solver objects fed into it are fakes (see
binoc_solve/fakes.py).
"""
from __future__ import annotations

import argparse
import logging
import threading

from binoc_solve.config import Config
from binoc_solve.encoder_server import EncoderTCPServer
from binoc_solve.fakes import FakeCamera, FakeDetectClient, FakeSolver
from binoc_solve.locations import LocationStore
from binoc_solve.main import _solve_loop
from binoc_solve.simulator_toggle import SimulatorToggle
from binoc_solve.state import LatestFix


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = Config.load(args.config)

    location_store = LocationStore(config.locations, config.location_selector.state_file)
    solver = FakeSolver()
    camera = FakeCamera()
    detect = FakeDetectClient()
    latest_fix = LatestFix()

    encoder_server = EncoderTCPServer(config.encoder, latest_fix, config.loop.stale_fix_warn_s)
    threading.Thread(target=encoder_server.serve_forever, daemon=True).start()
    print(f"SkySafari encoder server listening on {config.encoder.bind_host}:{config.encoder.bind_port}")
    print(f"Using location: {location_store.current().name}")

    stop_event = threading.Event()
    # This script has no real hardware to fall back to, so the same fake
    # objects are passed for both the "real" and "fake" pipeline slots -
    # the never-toggled SimulatorToggle just makes _solve_loop's dispatch
    # a no-op here.
    threading.Thread(
        target=_solve_loop,
        args=(
            config,
            camera, detect, solver,
            camera, detect, solver,
            location_store, SimulatorToggle(),
            latest_fix, stop_event,
        ),
        daemon=True,
    ).start()

    names = solver.list_names()
    print("\nSimulated solve solutions:")
    for i, name in enumerate(names):
        print(f"  [{i}] {name}")
    print(f"\nCurrently: [0] {names[0]}")
    print("Press Enter to advance to the next one, type a number to jump to it, or 'q' to quit.\n")

    try:
        while True:
            raw = input("> ").strip()
            if raw.lower() in ("q", "quit", "exit"):
                break
            if raw == "":
                name = solver.next()
            else:
                try:
                    name = solver.select(int(raw))
                except (ValueError, IndexError) as e:
                    print(f"  {e}")
                    continue
            print(f"  -> now simulating: {name}  (watch the log lines above for the resulting Alt/Az)")
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        stop_event.set()
        encoder_server.shutdown()
        encoder_server.server_close()


if __name__ == "__main__":
    main()
