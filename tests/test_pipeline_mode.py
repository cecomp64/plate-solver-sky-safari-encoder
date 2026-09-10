from binoc_solve.pipeline_mode import Mode, ModeStore


def test_starts_at_real():
    store = ModeStore()
    assert store.current() == Mode.REAL
    assert store.current_index() == 0


def test_advance_cycles_through_all_modes_and_wraps():
    store = ModeStore()
    assert store.advance() == Mode.SIMULATOR
    assert store.current_index() == 1
    assert store.advance() == Mode.SYNTHETIC
    assert store.current_index() == 2
    assert store.advance() == Mode.REAL  # wraps around
    assert store.current_index() == 0


def test_fresh_instance_never_starts_past_real():
    # Deliberately not persisted (unlike LocationStore) - see
    # pipeline_mode.py's docstring for why.
    store1 = ModeStore()
    store1.advance()
    assert store1.current() == Mode.SIMULATOR

    store2 = ModeStore()
    assert store2.current() == Mode.REAL
