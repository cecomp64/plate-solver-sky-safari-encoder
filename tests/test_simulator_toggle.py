from binoc_solve.simulator_toggle import SimulatorToggle


def test_starts_disabled():
    toggle = SimulatorToggle()
    assert toggle.enabled is False


def test_toggle_flips_and_returns_new_value():
    toggle = SimulatorToggle()
    assert toggle.toggle() is True
    assert toggle.enabled is True
    assert toggle.toggle() is False
    assert toggle.enabled is False


def test_fresh_instance_never_starts_enabled():
    # Deliberately not persisted (unlike LocationStore) - see
    # simulator_toggle.py's docstring for why.
    toggle1 = SimulatorToggle()
    toggle1.toggle()
    assert toggle1.enabled is True

    toggle2 = SimulatorToggle()
    assert toggle2.enabled is False
