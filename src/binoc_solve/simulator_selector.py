"""Wires a physical button + a status LED to a SimulatorToggle:
pressing the button flips the solve loop's data source between the
real camera/cedar-detect/cedar-solve pipeline and the canned solutions
in fakes.py, so the SkySafari integration can be demoed/tested in the
field without pointing at open sky. The LED blinks the new state (1 =
real, 2 = simulated), both after a press and once at startup to confirm
which pipeline is active.

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
from binoc_solve.power_led import PowerLed, blink_pattern
from binoc_solve.simulator_toggle import SimulatorToggle

logger = logging.getLogger(__name__)

_REAL_BLINK_COUNT = 1
_SIMULATED_BLINK_COUNT = 2


class SimulatorSelector:
    def __init__(self, config: SimulatorSelectorConfig, toggle: SimulatorToggle) -> None:
        from gpiozero import Button  # noqa: PLC0415 - see module docstring

        self._config = config
        self._toggle = toggle
        # Same reasoning as LocationSelector: serializes blink sequences
        # so a rapid second press can't garble one already in progress.
        self._blink_lock = threading.Lock()

        self._led = PowerLed(config.led_name)
        self._button = Button(config.button_gpio, bounce_time=config.bounce_time_s)
        self._button.when_pressed = self._on_button_pressed

        logger.info(
            "Simulator selector ready: button=GPIO%d, %s LED as indicator, starting %s",
            config.button_gpio, config.led_name,
            "simulated" if toggle.enabled else "real",
        )
        self._blink(_SIMULATED_BLINK_COUNT if toggle.enabled else _REAL_BLINK_COUNT)

    def _on_button_pressed(self) -> None:
        with self._blink_lock:
            enabled = self._toggle.toggle()
            self._blink(_SIMULATED_BLINK_COUNT if enabled else _REAL_BLINK_COUNT)
        logger.info("Button pressed -> now using %s pipeline", "simulator" if enabled else "real")

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
