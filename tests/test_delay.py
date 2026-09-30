"""The ping-pong delay line: where echoes land, which side they come out of, and how they die."""

import numpy as np
import pytest
from helpers import SR

import dsp

BLOCK = 100
DELAY = 1000


def run(feedback, total, delay=DELAY, max_seconds=1.0):
    """Send one impulse into the left channel, then silence. Returns the wet signal, shape (total, 2)."""
    line = dsp.PingPongDelay(SR, max_seconds=max_seconds)
    out = []
    for block in range(total // BLOCK):
        send = np.zeros((BLOCK, 2), np.float32)
        if block == 0:
            send[0, 0] = 1.0
        out.append(line.process(send, delay, feedback))
    return np.concatenate(out)


def test_an_impulse_comes_back_exactly_delay_samples_later_on_the_same_side():
    wet = run(0.5, 1500)
    assert np.flatnonzero(wet.any(axis=1)).tolist() == [DELAY]
    assert wet[DELAY].tolist() == [1.0, 0.0]


def test_echoes_ping_pong_between_the_channels_and_shrink_by_the_feedback():
    wet = run(0.5, 5000)
    assert wet[1 * DELAY].tolist() == [1.0, 0.0]
    assert wet[2 * DELAY].tolist() == [0.0, 0.5]
    assert wet[3 * DELAY].tolist() == [0.25, 0.0]
    assert wet[4 * DELAY].tolist() == [0.0, 0.125]
    assert np.flatnonzero(wet.any(axis=1)).tolist() == [DELAY, 2 * DELAY, 3 * DELAY, 4 * DELAY]


def test_no_feedback_means_a_single_echo():
    wet = run(0.0, 5000)
    assert np.flatnonzero(wet.any(axis=1)).tolist() == [DELAY]


def test_echoes_keep_their_level_across_the_wrap_of_the_ring_buffer():
    wet = run(0.5, 16000, max_seconds=0.25)  # the buffer holds 12000 samples, so echoes 12 to 15 wrap
    for echo in range(1, 16):
        left, right = wet[echo * DELAY]
        level = 0.5 ** (echo - 1)
        assert (left, right) == ((level, 0.0) if echo % 2 else (0.0, level))


def test_a_delay_shorter_than_one_block_is_stretched_to_block_plus_one():
    line = dsp.PingPongDelay(SR)
    impulse = np.zeros((BLOCK, 2), np.float32)
    impulse[0, 0] = 1.0
    silence = np.zeros((BLOCK, 2), np.float32)
    wet = np.concatenate([line.process(impulse, 10, 0.0)] + [line.process(silence, 10, 0.0) for _ in range(3)])
    assert np.flatnonzero(wet.any(axis=1)).tolist() == [BLOCK + 1]


@pytest.mark.parametrize("feedback", [0.33, 0.9])
def test_energy_decays_while_feedback_is_below_one(feedback):
    wet = run(feedback, 20000)
    echoes = [np.square(wet[k * DELAY]).sum() for k in range(1, 20)]
    assert all(later < earlier for earlier, later in zip(echoes, echoes[1:], strict=False))
