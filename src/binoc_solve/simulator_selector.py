"""Wires a physical button + a status LED to a ModeStore: pressing the
button cycles the solve loop's data source through REAL -> SIMULATOR ->
SYNTHETIC -> REAL ... (see pipeline_mode.py for what each mode means).
The LED blinks the new mode's 1-indexed position in that cycle (1 =
real, 2 = simulator, 3 = synthetic), both after a press and once at
startup to confirm which pipeline is active.

Uses the Pi's ACT LED (distinct from location_selector's PWR LED) so
both indicators are visible at once without wiring a discrete LED - see
power_led.py.

gpiozero (for the button) is Pi-only - imported lazily, same reasoning
as location_selector.py.
"""
from __future__ import annotations

import logging
import threading

from binoc_solve.config import SimulatorSelectorConfig
from binoc_solve.locations import blink_count_for_index
from binoc_solve.pipeline_mode import ModeStore
from binoc_solve.power_led import PowerLed, blink_pattern

logger = logging.getLogger(__name__)


class SimulatorSelector:
    def __init__(self, config: SimulatorSelectorConfig, mode_store: ModeStore) -> None:
        from gpiozero import Button  # noqa: PLC0415 - see module docstring

        self._config = config
        self._mode_store = mode_store
        # Same reasoning as LocationSelector: serializes blink sequences
        # so a rapid second press can't garble one already in progress.
        self._blink_lock = threading.Lock()

        self._led = PowerLed(config.led_name)
        self._button = Button(config.button_gpio, bounce_time=config.bounce_time_s)
        self._button.when_pressed = self._on_button_pressed

        logger.info(
            "Simulator selector ready: button=GPIO%d, %s LED as indicator, starting %s",
            config.button_gpio, config.led_name, mode_store.current().value,
        )
        self._blink(blink_count_for_index(mode_store.current_index()))

    def _on_button_pressed(self) -> None:
        with self._blink_lock:
            mode = self._mode_store.advance()
            self._blink(blink_count_for_index(self._mode_store.current_index()))
        logger.info("Button pressed -> now using %s pipeline", mode.value)

    def _blink(self, count: int) -> None:
        blink_pattern(
            self._led, count,
            on_s=self._config.blink_on_s,
            off_s=self._config.blink_off_s,
            repeat_pause_s=self._config.blink_repeat_pause_s,
            repeats=self._config.blink_repeats,
        )

    def close(self) -> None:
        self._button.close()
        self._led.close()
