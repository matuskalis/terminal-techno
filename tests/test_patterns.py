"""Pattern data, the factory boards, step editing and randomize."""

import random

import numpy as np
import pytest
from helpers import BAS, CLP, HAT, KCK, LED, OHT

import engine
from engine import SCALE, STEPS, TRACKS, Engine


def steps_on(pattern, track):
    return np.flatnonzero(pattern.on[track]).tolist()


# --- names and layout -------------------------------------------------------


def test_six_tracks_in_order_and_only_bass_and_lead_are_pitched():
    assert [t.name for t in TRACKS] == ["KCK", "CLP", "HAT", "OHT", "BAS", "LED"]
    assert [t.name for t in TRACKS if t.pitched] == ["BAS", "LED"]
    assert all(-1.0 <= t.pan <= 1.0 for t in TRACKS)
    assert STEPS == 16


@pytest.mark.parametrize(
    ("semitones", "octave", "name"),
    [(0, 1, "A1"), (2, 1, "B1"), (3, 1, "C2"), (-2, 1, "G1"), (-12, 1, "A0"), (12, 2, "A3"), (24, 2, "A4")],
)
def test_note_names_count_from_the_a_of_the_track_octave(semitones, octave, name):
    assert engine.note_name(semitones, octave) == name


# --- factory boards ---------------------------------------------------------


def test_eight_boards_four_filled_and_four_empty():
    boards = engine.default_boards()
    assert [b.name for b in boards] == ["simple", "peak", "acid", "dub", "empty 5", "empty 6", "empty 7", "empty 8"]
    assert [bool(b.pattern.on.any()) for b in boards] == [True] * 4 + [False] * 4


def test_every_board_has_a_six_by_sixteen_grid_and_notes_in_range():
    for board in engine.default_boards():
        p = board.pattern
        assert p.on.shape == p.acc.shape == p.slide.shape == p.note.shape == (len(TRACKS), STEPS)
        assert p.note.min() >= -12
        assert p.note.max() <= 24


def test_simple_board_is_four_on_the_floor():
    p = engine.simple_pattern()
    assert steps_on(p, KCK) == [0, 4, 8, 12]
    assert steps_on(p, CLP) == [4, 12]
    assert steps_on(p, OHT) == [2, 6, 10, 14]
    assert steps_on(p, BAS) == [0, 8]
    assert steps_on(p, HAT) == []
    assert steps_on(p, LED) == []


def test_peak_board_runs_hats_on_every_step_with_accents_on_the_offbeat():
    p = engine.default_pattern()
    assert steps_on(p, HAT) == list(range(STEPS))
    assert np.flatnonzero(p.acc[HAT]).tolist() == [2, 6, 10, 14]
    assert p.slide[LED].any()


def test_slides_only_appear_on_pitched_tracks_in_the_factory_boards():
    for board in engine.default_boards():
        assert not board.pattern.slide[[KCK, CLP, HAT, OHT]].any()


def test_factory_boards_do_not_share_arrays():
    first = engine.default_boards()
    second = engine.default_boards()
    first[0].pattern.on[KCK, 0] = False
    assert second[0].pattern.on[KCK, 0]
    assert first[0].pattern.on is not first[1].pattern.on


# --- editing ----------------------------------------------------------------


def test_toggle_step_flips_only_that_step():
    eng = Engine(48000)
    before = eng.pattern.on.copy()
    eng.toggle_step(HAT, 3)
    changed = np.argwhere(eng.pattern.on != before).tolist()
    assert changed == [[HAT, 3]]
    eng.toggle_step(HAT, 3)
    np.testing.assert_array_equal(eng.pattern.on, before)


def test_accent_toggles_on_any_track():
    eng = Engine(48000)
    eng.toggle_accent(KCK, 5)
    assert eng.pattern.acc[KCK, 5]
    eng.toggle_accent(KCK, 5)
    assert not eng.pattern.acc[KCK, 5]


def test_slide_and_note_shift_ignore_unpitched_tracks():
    eng = Engine(48000)
    eng.toggle_slide(KCK, 0)
    eng.shift_note(KCK, 0, 5)
    assert not eng.pattern.slide[KCK].any()
    assert not eng.pattern.note[KCK].any()
    eng.toggle_slide(BAS, 1)
    eng.shift_note(BAS, 1, 5)
    assert eng.pattern.slide[BAS, 1]
    assert eng.pattern.note[BAS, 1] == 5


def test_shift_note_stays_between_minus_12_and_24():
    eng = Engine(48000)
    for _ in range(50):
        eng.shift_note(LED, 0, 1)
    assert eng.pattern.note[LED, 0] == 24
    for _ in range(80):
        eng.shift_note(LED, 0, -1)
    assert eng.pattern.note[LED, 0] == -12


def test_clear_track_resets_that_track_and_leaves_the_others():
    eng = Engine(48000)
    eng.board = 1  # peak
    before = eng.pattern.on[[KCK, CLP, HAT, OHT, BAS]].copy()
    eng.clear_track(LED)
    p = eng.pattern
    assert not (p.on[LED].any() or p.acc[LED].any() or p.slide[LED].any() or p.note[LED].any())
    np.testing.assert_array_equal(p.on[[KCK, CLP, HAT, OHT, BAS]], before)


def test_editing_always_targets_the_live_board():
    eng = Engine(48000)
    eng.arm(2)  # stopped, so it lands at once
    assert eng.pattern is eng.boards[2].pattern
    eng.toggle_step(KCK, 1)
    assert eng.boards[2].pattern.on[KCK, 1]
    assert not eng.boards[0].pattern.on[KCK, 1]


# --- randomize --------------------------------------------------------------


def randomized(track):
    eng = Engine(48000)
    eng.board = 4  # an empty board
    eng.randomize_track(track)
    return eng.pattern


def test_random_kick_keeps_four_on_the_floor_and_adds_at_most_one_offbeat():
    for _ in range(100):
        on = set(steps_on(randomized(KCK), KCK))
        assert {0, 4, 8, 12} <= on
        assert len(on - {0, 4, 8, 12}) <= 1
        assert on - {0, 4, 8, 12} <= {3, 7, 11, 15}


def test_random_clap_sits_on_two_and_four():
    assert steps_on(randomized(CLP), CLP) == [4, 12]


def test_random_hats_are_dense_and_accent_only_where_they_play_on_the_offbeat():
    closed = np.mean([randomized(HAT).on[HAT].mean() for _ in range(300)])
    opened = np.mean([randomized(OHT).on[OHT].mean() for _ in range(300)])
    assert closed == pytest.approx(0.9, abs=0.04)
    assert opened == pytest.approx(0.3, abs=0.04)
    for track in (HAT, OHT):
        p = randomized(track)
        accents = np.flatnonzero(p.acc[track])
        assert set(accents) <= set(np.flatnonzero(p.on[track]))
        assert all(s % 4 == 2 for s in accents)


@pytest.mark.parametrize("track", [BAS, LED])
def test_random_bass_and_lead_draw_notes_from_the_scale_only_on_played_steps(track):
    allowed = set(SCALE) | {n - 12 for n in SCALE}
    for _ in range(50):
        p = randomized(track)
        for step in range(STEPS):
            if p.on[track, step]:
                assert int(p.note[track, step]) in allowed
            else:
                assert not (p.acc[track, step] or p.slide[track, step] or p.note[track, step])


@pytest.mark.parametrize("track", [KCK, CLP, HAT, OHT])
def test_random_unpitched_tracks_get_no_notes_or_slides(track):
    p = randomized(track)
    assert not p.note[track].any()
    assert not p.slide[track].any()


def test_randomize_replaces_what_was_there():
    eng = Engine(48000)
    eng.board = 4
    eng.pattern.on[BAS, :] = True
    eng.randomize_track(BAS)
    assert not eng.pattern.on[BAS].all()


def test_randomize_is_reproducible_with_a_seed():
    random.seed(5)
    first = randomized(LED)
    random.seed(5)
    second = randomized(LED)
    for name in ("on", "acc", "slide", "note"):
        np.testing.assert_array_equal(getattr(first, name), getattr(second, name))
