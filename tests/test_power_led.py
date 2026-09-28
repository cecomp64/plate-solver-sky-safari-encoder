import stat

import pytest

from binoc_solve.power_led import PowerLed, blink_pattern


def _make_fake_led(leds_root, name, trigger_options, active):
    led_dir = leds_root / name
    led_dir.mkdir(parents=True)
    words = [f"[{opt}]" if opt == active else opt for opt in trigger_options]
    (led_dir / "trigger").write_text(" ".join(words))
    (led_dir / "brightness").write_text("1")
    return led_dir


def test_finds_led_by_case_insensitive_substring(tmp_path):
    _make_fake_led(tmp_path, "PWR", ["none", "default-on", "mmc0"], "default-on")
    led = PowerLed(name_substring="pwr", leds_root=tmp_path)
    assert led._path.name == "PWR"


def test_sets_trigger_to_none_on_init(tmp_path):
    led_dir = _make_fake_led(tmp_path, "PWR", ["none", "default-on"], "default-on")
    PowerLed(name_substring="PWR", leds_root=tmp_path)
    assert (led_dir / "trigger").read_text() == "none"


def test_on_off_write_brightness(tmp_path):
    led_dir = _make_fake_led(tmp_path, "PWR", ["none", "default-on"], "none")
    led = PowerLed(name_substring="PWR", leds_root=tmp_path)

    led.on()
    assert (led_dir / "brightness").read_text() == "1"
    led.off()
    assert (led_dir / "brightness").read_text() == "0"


def test_close_restores_original_trigger(tmp_path):
    led_dir = _make_fake_led(tmp_path, "PWR", ["none", "default-on", "mmc0"], "mmc0")
    led = PowerLed(name_substring="PWR", leds_root=tmp_path)
    assert (led_dir / "trigger").read_text() == "none"

    led.close()
    assert (led_dir / "trigger").read_text() == "mmc0"


def test_no_matching_led_raises_with_available_names(tmp_path):
    _make_fake_led(tmp_path, "ACT", ["none", "mmc0"], "mmc0")
    with pytest.raises(RuntimeError, match="ACT"):
        PowerLed(name_substring="PWR", leds_root=tmp_path)


def test_missing_leds_root_raises(tmp_path):
    with pytest.raises(RuntimeError):
        PowerLed(name_substring="PWR", leds_root=tmp_path / "does_not_exist")


def test_permission_error_is_wrapped_with_guidance(tmp_path):
    led_dir = _make_fake_led(tmp_path, "PWR", ["none", "default-on"], "default-on")
    (led_dir / "trigger").chmod(stat.S_IRUSR)  # read-only, like an unconfigured sysfs file
    try:
        with pytest.raises(PermissionError, match="udev rule"):
            PowerLed(name_substring="PWR", leds_root=tmp_path)
    finally:
        (led_dir / "trigger").chmod(stat.S_IRUSR | stat.S_IWUSR)  # allow cleanup


def test_prefers_first_match_when_multiple_leds_match(tmp_path):
    _make_fake_led(tmp_path, "PWR", ["none", "default-on"], "none")
    _make_fake_led(tmp_path, "PWR2", ["none", "default-on"], "none")
    led = PowerLed(name_substring="PWR", leds_root=tmp_path)
    assert led._path.name == "PWR"  # sorted first alphabetically


def test_blink_pattern_calls_on_off_in_sequence(tmp_path):
    _make_fake_led(tmp_path, "PWR", ["none", "default-on"], "none")
    led = PowerLed(name_substring="PWR", leds_root=tmp_path)

    calls = []
    led.on = lambda: calls.append("on")
    led.off = lambda: calls.append("off")

    blink_pattern(led, count=2, on_s=0, off_s=0, repeat_pause_s=0, repeats=2)
    assert calls == ["on", "off", "on", "off", "on", "off", "on", "off"]
