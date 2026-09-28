"""Controls the Pi's built-in power LED as the location-select status
light, instead of wiring a discrete LED.

The power LED isn't wired to a normal GPIO pin the way a hand-wired LED
would be - it's driven by firmware via the Linux sysfs LED class
(/sys/class/leds/<name>/{trigger,brightness}), so this doesn't use
gpiozero.LED at all. Exposes the same on()/off()/close() surface as
gpiozero.LED so it's a drop-in swap in location_selector.py.

Needs write access to that LED's sysfs files - see SETUP.md for the
one-time udev rule (running the whole service as root just for this
isn't worth it). While this owns the LED, it no longer shows the normal
"power is good" state; close() restores its original trigger so a clean
shutdown gives that back.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_LEDS_ROOT = Path("/sys/class/leds")


def _find_led(name_substring: str, leds_root: Path) -> Path:
    if not leds_root.is_dir():
        raise RuntimeError(f"{leds_root} not found - is this running on a Raspberry Pi?")

    candidates = sorted(p for p in leds_root.iterdir() if name_substring.lower() in p.name.lower())
    if not candidates:
        available = ", ".join(p.name for p in sorted(leds_root.iterdir())) or "(none)"
        raise RuntimeError(
            f"No LED matching {name_substring!r} under {leds_root}. "
            f"Available: {available}. Set location_selector.led_name in "
            f"config.yaml to one of these."
        )
    if len(candidates) > 1:
        logger.warning(
            "Multiple LEDs match %r (%s), using %s",
            name_substring, [p.name for p in candidates], candidates[0].name,
        )
    return candidates[0]


def _current_trigger(trigger_text: str) -> str:
    # /sys/class/leds/*/trigger lists all options with the active one in
    # brackets, e.g. "none [default-on] timer mmc0 ...".
    for word in trigger_text.split():
        if word.startswith("[") and word.endswith("]"):
            return word[1:-1]
    return "none"


class PowerLed:
    def __init__(self, name_substring: str = "PWR", leds_root: Path | str = _DEFAULT_LEDS_ROOT) -> None:
        leds_root = Path(leds_root)
        self._path = _find_led(name_substring, leds_root)
        self._trigger_path = self._path / "trigger"
        self._brightness_path = self._path / "brightness"
        self._original_trigger = _current_trigger(self._trigger_path.read_text())

        self._write(self._trigger_path, "none")
        logger.info("Controlling power LED at %s (was trigger=%s)", self._path, self._original_trigger)

    def _write(self, path: Path, value: str) -> None:
        try:
            path.write_text(value)
        except PermissionError:
            raise PermissionError(
                f"No write access to {path} - see SETUP.md's udev rule for the power LED."
            ) from None

    def on(self) -> None:
        self._write(self._brightness_path, "1")

    def off(self) -> None:
        self._write(self._brightness_path, "0")

    def close(self) -> None:
        self._write(self._trigger_path, self._original_trigger)


def blink_pattern(
    led: PowerLed,
    count: int,
    *,
    on_s: float,
    off_s: float,
    repeat_pause_s: float,
    repeats: int,
) -> None:
    """Blinks `led` `count` times, `repeats` times over, pausing
    `repeat_pause_s` between repeats - e.g. count=2, repeats=2 blinks
    "on-off on-off, pause, on-off on-off, pause". Shared by
    location_selector.py and simulator_selector.py so both indicators
    blink identically."""
    for _ in range(repeats):
        for _ in range(count):
            led.on()
            time.sleep(on_s)
            led.off()
            time.sleep(off_s)
        time.sleep(repeat_pause_s)
