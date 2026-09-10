from binoc_solve.locations import LocationStore, NamedLocation, blink_count_for_index

LOCS = [
    NamedLocation(name="A", latitude_deg=1.0, longitude_deg=1.0, elevation_m=1.0),
    NamedLocation(name="B", latitude_deg=2.0, longitude_deg=2.0, elevation_m=2.0),
    NamedLocation(name="C", latitude_deg=3.0, longitude_deg=3.0, elevation_m=3.0),
]


def test_blink_count_is_one_indexed():
    assert blink_count_for_index(0) == 1
    assert blink_count_for_index(1) == 2
    assert blink_count_for_index(2) == 3


def test_starts_at_first_location_with_no_state_file(tmp_path):
    store = LocationStore(LOCS, tmp_path / "active_location.txt")
    assert store.current() == LOCS[0]
    assert store.current_index() == 0


def test_advance_cycles_and_wraps(tmp_path):
    store = LocationStore(LOCS, tmp_path / "active_location.txt")
    assert store.advance() == LOCS[1]
    assert store.advance() == LOCS[2]
    assert store.advance() == LOCS[0]  # wraps around


def test_selection_persists_across_instances(tmp_path):
    state_file = tmp_path / "active_location.txt"
    store1 = LocationStore(LOCS, state_file)
    store1.advance()
    store1.advance()
    assert store1.current() == LOCS[2]

    # A fresh store reading the same state file picks up where it left off.
    store2 = LocationStore(LOCS, state_file)
    assert store2.current() == LOCS[2]


def test_out_of_range_saved_index_falls_back_to_first(tmp_path):
    state_file = tmp_path / "active_location.txt"
    state_file.write_text("99")
    store = LocationStore(LOCS, state_file)
    assert store.current() == LOCS[0]


def test_corrupt_state_file_falls_back_to_first(tmp_path):
    state_file = tmp_path / "active_location.txt"
    state_file.write_text("not-a-number")
    store = LocationStore(LOCS, state_file)
    assert store.current() == LOCS[0]


def test_single_location_is_allowed_and_advance_is_a_noop(tmp_path):
    store = LocationStore(LOCS[:1], tmp_path / "active_location.txt")
    assert store.advance() == LOCS[0]
    assert store.current_index() == 0


def test_empty_location_list_raises():
    import pytest

    with pytest.raises(ValueError):
        LocationStore([], "unused.txt")
