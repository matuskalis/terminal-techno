"""The biquad design and the swept lowpass that the bass and acid voices run through."""

import numpy as np
import pytest
from helpers import SR, power_above, seconds
from scipy.signal import freqz

import dsp


def gain(kind, cutoff, q, at_hz):
    b, a = dsp._biquad(kind, cutoff, q, SR)
    _, h = freqz(b, a, worN=[2 * np.pi * at_hz / SR])
    return abs(h[0])


def test_lowpass_passes_dc_and_blocks_nyquist():
    assert gain("lp", 1000, 0.7, 1.0) == pytest.approx(1.0, abs=1e-3)
    assert gain("lp", 1000, 0.7, SR / 2 - 1) < 1e-3


def test_highpass_blocks_dc_and_passes_nyquist():
    assert gain("hp", 1000, 0.7, 1.0) < 1e-3
    assert gain("hp", 1000, 0.7, SR / 2 - 1) == pytest.approx(1.0, abs=1e-3)


@pytest.mark.parametrize("kind", ["lp", "hp"])
@pytest.mark.parametrize("q", [0.7, 2.0, 7.0])
def test_resonance_peaks_at_the_cutoff_with_gain_q(kind, q):
    assert gain(kind, 1000, q, 1000) == pytest.approx(q, rel=1e-3)


def test_bandpass_has_unity_gain_at_its_centre_and_nothing_at_the_ends():
    assert gain("bp", 1500, 1.1, 1500) == pytest.approx(1.0, abs=1e-3)
    assert gain("bp", 1500, 1.1, 1.0) < 1e-2
    assert gain("bp", 1500, 1.1, SR / 2 - 1) < 1e-2


def test_cutoff_is_clamped_to_20_hz_and_below_nyquist():
    np.testing.assert_allclose(dsp._biquad("lp", 1.0, 1.0, SR), dsp._biquad("lp", 20.0, 1.0, SR))
    np.testing.assert_allclose(dsp._biquad("lp", 1e6, 1.0, SR), dsp._biquad("lp", SR * 0.45, 1.0, SR))


def test_q_has_a_floor_of_0_3():
    np.testing.assert_allclose(dsp._biquad("lp", 1000, 0.0, SR), dsp._biquad("lp", 1000, 0.3, SR))


def test_swept_filter_with_a_constant_cutoff_is_one_plain_biquad():
    from scipy.signal import lfilter

    x = np.random.default_rng(1).standard_normal(1000)  # 1000 is not a multiple of the 64 sample sub-block
    swept, _ = dsp._filter_swept(x, np.full(len(x), 800.0), 2.0, SR, np.zeros(2))
    b, a = dsp._biquad("lp", 800.0, 2.0, SR)
    plain, _ = lfilter(b, a, x, zi=np.zeros(2))
    np.testing.assert_allclose(swept, plain, atol=1e-12)


def test_swept_filter_opens_as_the_cutoff_rises():
    noise = np.random.default_rng(1).standard_normal(SR // 2)
    cutoff = np.linspace(200.0, 8000.0, len(noise))
    out, _ = dsp._filter_swept(noise, cutoff, 1.0, SR, np.zeros(2))
    early = power_above(seconds(out, 0.0, 0.1), 4000)
    late = power_above(seconds(out, 0.4, 0.5), 4000)
    assert early < 0.01
    assert late > 0.3


def test_swept_filter_hands_its_state_to_the_next_block():
    noise = np.random.default_rng(2).standard_normal(1024)
    cutoff = np.linspace(300.0, 3000.0, 1024)
    whole, _ = dsp._filter_swept(noise, cutoff, 3.0, SR, np.zeros(2))
    first, zi = dsp._filter_swept(noise[:512], cutoff[:512], 3.0, SR, np.zeros(2))
    second, _ = dsp._filter_swept(noise[512:], cutoff[512:], 3.0, SR, zi)  # 512 is a multiple of 64
    np.testing.assert_allclose(np.concatenate([first, second]), whole, atol=1e-12)
