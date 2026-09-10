"""Wires a physical button + the Pi's built-in power LED to a
LocationStore: pressing the button cycles to the next configured
location and persists it; the LED blinks out (1-indexed) which location
is now active, both after a press and once at startup to confirm the
persisted selection.

gpiozero (for the button) is Pi-only (uses the lgpio backend for the Pi
5's RP1 GPIO chip) - imported lazily so the rest of this package stays
importable/testable on a machine without it. The power LED itself is
controlled via power_led.PowerLed, not gpiozero - see that module.
"""
from __future__ import annotations

import logging
import threading
import time

from binoc_solve.config import LocationSelectorConfig
from binoc_solve.locations import LocationStore, blink_count_for_index
from binoc_solve.power_led import PowerLed

logger = logging.getLogger(__name__)


class LocationSelector:
    def __init__(self, config: LocationSelectorConfig, store: LocationStore) -> None:
        from gpiozero import Button  # noqa: PLC0415 - see module docstring

        self._config = config
        self._store = store
        # Serializes button-press handling so a rapid second press can't
        # interleave its blink sequence with one already in progress -
        # it just waits its turn instead of producing a garbled pattern.
        self._blink_lock = threading.Lock()

        self._led = PowerLed(config.led_name)
        self._button = Button(config.button_gpio, bounce_time=config.bounce_time_s)
        self._button.when_pressed = self._on_button_pressed

        logger.info(
            "Location selector ready: button=GPIO%d, power LED as indicator, starting at %s",
            config.button_gpio, store.current().name,
        )
        self._blink(blink_count_for_index(store.current_index()))

    def _on_button_pressed(self) -> None:
        with self._blink_lock:
            location = self._store.advance()
            self._blink(blink_count_for_index(self._store.current_index()))
        logger.info("Button pressed -> now using %s", location.name)

    def _blink(self, count: int) -> None:
        for _ in range(self._config.blink_repeats):
            for _ in range(count):
                self._led.on()
                time.sleep(self._config.blink_on_s)
                self._led.off()
                time.sleep(self._config.blink_off_s)
            time.sleep(self._config.blink_repeat_pause_s)

    def close(self) -> None:
        self._button.close()
        self._led.close()
