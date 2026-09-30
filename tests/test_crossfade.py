"""Deck B, the equal-power fader and the swap of voice banks."""

import math

import numpy as np
import pytest
from helpers import BAS, KCK, LED, SR, TriggerLog, pattern_with, undo_master

from engine import STEPS, TRACKS, Board, Engine, Pattern

BAR_AT_130 = STEPS * 60.0 / 130.0 / 4.0 * SR


# --- the fader ---------------------------------------------------------------


def test_deck_b_opens_on_the_armed_board_or_else_the_next_one():
    eng = Engine(SR)
    eng.start_xfade()
    assert (eng.crossfading, eng.deck_b, eng.xfade) == (True, 1, 0.0)

    eng = Engine(SR)
    eng.toggle_play()
    eng.arm(5)
    eng.start_xfade()
    assert (eng.deck_b, eng.pending) == (5, None)


def test_the_last_board_hands_over_to_the_first():
    eng = Engine(SR)
    eng.board = 7
    eng.start_xfade()
    assert eng.deck_b == 0


def test_starting_a_crossfade_while_one_runs_changes_nothing():
    eng = Engine(SR)
    eng.start_xfade()
    eng.nudge_xfade(0.3)
    eng.start_xfade()
    assert (eng.deck_b, eng.xfade) == (1, pytest.approx(0.3))


def test_cancel_drops_deck_b_and_puts_the_fader_back():
    eng = Engine(SR)
    eng.start_xfade()
    eng.nudge_xfade(0.4)
    eng.cancel_xfade()
    assert (eng.crossfading, eng.deck_b, eng.xfade, eng.board) == (False, None, 0.0, 0)


def test_the_fader_clamps_at_a_and_commits_after_twenty_steps_toward_b():
    eng = Engine(SR)
    eng.start_xfade()
    eng.nudge_xfade(-0.05)
    assert (eng.xfade, eng.crossfading) == (0.0, True)
    for _ in range(19):
        eng.nudge_xfade(0.05)
    assert eng.crossfading
    assert eng.xfade == pytest.approx(0.95)
    eng.nudge_xfade(0.05)
    assert (eng.crossfading, eng.board, eng.xfade) == (False, 1, 0.0)


def test_nudging_with_no_crossfade_does_nothing():
    eng = Engine(SR)
    eng.nudge_xfade(0.5)
    assert (eng.xfade, eng.crossfading) == (0.0, False)
    eng.commit_xfade()
    assert eng.board == 0


def test_commit_makes_deck_b_the_live_board_and_swaps_the_voice_banks():
    eng = Engine(SR)
    eng.start_xfade()
    live, other = eng.voices, eng.voices_b
    eng.commit_xfade()
    assert eng.board == 1
    assert eng.voices is other
    assert eng.voices_b is live


def test_the_bank_that_takes_over_keeps_ringing_instead_of_restarting():
    eng = Engine(SR)
    eng.ui_sound = False
    eng.boards[0] = Board("a", Pattern())
    eng.boards[1] = Board("b", pattern_with(BAS, [0], accent=True))
    eng.start_xfade()
    eng.toggle_play()
    eng.render(1024)
    assert eng.voices_b[BAS].t == 1024
    eng.commit_xfade()
    eng.render(1024)
    assert eng.voices[BAS].t == 2048  # the same note, 2048 samples old, not retriggered


def test_arming_during_a_crossfade_retargets_deck_b_on_the_next_bar():
    eng = Engine(SR)
    eng.toggle_play()
    eng.start_xfade()
    eng.arm(3)
    assert (eng.deck_b, eng.pending) == (1, 3)
    eng.render(math.floor(BAR_AT_130))
    assert (eng.deck_b, eng.pending) == (1, 3)
    eng.render(1)
    assert (eng.deck_b, eng.pending, eng.board) == (3, None, 0)


# --- both decks run on one clock --------------------------------------------


def test_both_decks_fire_on_the_same_clock_until_the_crossfade_is_cancelled():
    eng = Engine(SR)
    eng.ui_sound = False
    deck_a = [TriggerLog() for _ in TRACKS]
    deck_b = [TriggerLog() for _ in TRACKS]
    eng.voices, eng.voices_b = deck_a, deck_b
    eng.boards[0] = Board("a", pattern_with(KCK, [0, 4, 8, 12], accent=True))
    eng.boards[1] = Board("b", pattern_with(KCK, [2, 6], accent=True))
    eng.start_xfade()
    eng.toggle_play()
    eng.render(math.floor(BAR_AT_130))
    assert len(deck_a[KCK].triggers) == 4
    assert len(deck_b[KCK].triggers) == 2
    eng.cancel_xfade()
    eng.render(math.floor(BAR_AT_130))
    assert len(deck_a[KCK].triggers) == 8
    assert len(deck_b[KCK].triggers) == 2


# --- the blend ---------------------------------------------------------------

A = Board("bass", pattern_with(BAS, [0], note=0, accent=True))
B = Board("lead", pattern_with(LED, [0], note=7, accent=True))


def dry(position, board_a=A, board_b=B, frames=2048):
    """The pre-master mix with the fader parked at `position` and both boards fired on step 0."""
    eng = Engine(SR)
    eng.ui_sound = False
    eng.delay_mix = 0.0
    eng.boards[0], eng.boards[1] = board_a, board_b
    eng.start_xfade()
    eng.xfade = position
    eng.toggle_play()
    return undo_master(eng.render(frames), eng.master)


def live(board, frames=2048):
    """The pre-master mix of one board played on its own, with no crossfade."""
    eng = Engine(SR)
    eng.ui_sound = False
    eng.delay_mix = 0.0
    eng.boards[0] = board
    eng.toggle_play()
    return undo_master(eng.render(frames), eng.master)


def test_with_the_fader_at_a_only_deck_a_is_heard():
    np.testing.assert_allclose(dry(0.0), live(A), atol=1e-4)


def test_with_the_fader_at_b_deck_b_sounds_exactly_like_that_board_played_live():
    np.testing.assert_allclose(dry(1.0), live(B), atol=1e-4)


@pytest.mark.parametrize("position", [0.1, 0.25, 0.5, 0.75, 0.9])
def test_the_blend_is_cosine_of_deck_a_plus_sine_of_deck_b(position):
    theta = position * math.pi / 2
    expected = math.cos(theta) * dry(0.0) + math.sin(theta) * dry(1.0)
    np.testing.assert_allclose(dry(position), expected, atol=1e-4)
