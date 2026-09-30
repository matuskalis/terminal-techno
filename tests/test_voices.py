"""The synthesis voices: pitch, envelope, tone, determinism and independence from block size."""

import numpy as np
import pytest
from helpers import (
    SR,
    dominant_hz,
    power_above,
    render_in_blocks,
    rms,
    seconds,
    spectral_centroid,
    zero_crossings_per_second,
)

import dsp

VOICES = [
    pytest.param(dsp.Kick, id="kick"),
    pytest.param(dsp.Clap, id="clap"),
    pytest.param(dsp.Hat, id="hat"),
    pytest.param(lambda sr: dsp.Hat(sr, open_hat=True), id="open hat"),
    pytest.param(dsp.Bass, id="bass"),
    pytest.param(dsp.Acid, id="acid"),
]


def hit(voice, length, **trigger):
    voice.trigger(**{"vel": 1.0, **trigger})
    return voice.render(int(length * SR))


# --- every voice -----------------------------------------------------------


@pytest.mark.parametrize("make_voice", VOICES)
def test_a_voice_is_silent_until_it_is_triggered(make_voice):
    out = make_voice(SR).render(512)
    assert out.dtype == np.float32
    assert out.shape == (512,)
    assert not out.any()


@pytest.mark.parametrize("n", [1, 63, 64, 1000])
def test_render_returns_exactly_the_requested_number_of_samples(n):
    kick = dsp.Kick(SR)
    kick.trigger()
    assert kick.render(n).shape == (n,)


@pytest.mark.parametrize("make_voice", VOICES)
def test_same_seed_gives_the_same_audio(make_voice):
    np.random.seed(99)
    first = hit(make_voice(SR), 0.2, note=5, accent=True)
    np.random.seed(99)
    second = hit(make_voice(SR), 0.2, note=5, accent=True)
    np.testing.assert_array_equal(first, second)


@pytest.mark.parametrize("make_voice", [dsp.Kick, dsp.Clap, dsp.Hat])
def test_noise_voices_change_with_the_seed(make_voice):
    np.random.seed(1)
    first = hit(make_voice(SR), 0.2)
    np.random.seed(2)
    second = hit(make_voice(SR), 0.2)
    assert not np.array_equal(first, second)


@pytest.mark.parametrize("make_voice", [dsp.Bass, dsp.Acid])
def test_tonal_voices_do_not_depend_on_the_seed(make_voice):
    np.random.seed(1)
    first = hit(make_voice(SR), 0.2, note=5)
    np.random.seed(2)
    second = hit(make_voice(SR), 0.2, note=5)
    np.testing.assert_array_equal(first, second)


@pytest.mark.parametrize("make_voice", VOICES)
def test_rendering_in_small_blocks_matches_one_big_block(make_voice):
    # 256 is a multiple of the 64 sample filter sub-block, so even the swept filters line up exactly
    np.random.seed(7)
    voice = make_voice(SR)
    voice.trigger(1.0, note=3, accent=True)
    whole = voice.render(2048)
    np.random.seed(7)
    voice = make_voice(SR)
    voice.trigger(1.0, note=3, accent=True)
    parts = render_in_blocks(voice, 2048, 256)
    np.testing.assert_allclose(parts, whole, atol=1e-5)


def test_a_voice_goes_quiet_for_good_after_its_tail():
    kick = dsp.Kick(SR)
    assert kick.dead()
    kick.trigger()
    assert not kick.dead()
    kick.render(int(1.1 * SR))
    assert not kick.render(512).any()


# --- kick ------------------------------------------------------------------


def test_kick_settles_on_48_hz():
    y = hit(dsp.Kick(SR), 1.0)
    assert 46.0 <= dominant_hz(seconds(y, 0.15, 0.5), 20, 200) <= 50.0


def test_kick_pitch_falls_from_the_attack_into_the_body():
    y = hit(dsp.Kick(SR), 0.5)
    attack = zero_crossings_per_second(seconds(y, 0.0, 0.04))
    body = zero_crossings_per_second(seconds(y, 0.2, 0.4))
    assert attack > 2.5 * body


def test_kick_decays_to_almost_nothing_within_a_second():
    y = hit(dsp.Kick(SR), 1.0)
    start = rms(seconds(y, 0.0, 0.05))
    assert rms(seconds(y, 0.4, 0.45)) < 0.15 * start
    assert rms(seconds(y, 0.9, 1.0)) < 0.01 * start


# --- hats and clap ---------------------------------------------------------


@pytest.mark.parametrize("open_hat", [False, True])
def test_hats_are_highpassed_noise(open_hat):
    y = hit(dsp.Hat(SR, open_hat=open_hat), 0.1)
    assert power_above(y, 3000) > 0.99


def test_closed_hat_is_short_and_open_hat_rings():
    closed = hit(dsp.Hat(SR), 0.4)
    open_ = hit(dsp.Hat(SR, open_hat=True), 0.4)
    assert rms(seconds(closed, 0.1, 0.11)) < 0.15 * rms(seconds(closed, 0.0, 0.01))
    assert rms(seconds(open_, 0.1, 0.11)) > 4 * rms(seconds(closed, 0.1, 0.11))


def test_clap_is_three_noise_bursts_then_a_tail():
    y = hit(dsp.Clap(SR), 0.6)
    for start in (0.0, 0.011, 0.022):
        burst = rms(seconds(y, start, start + 0.002))
        gap = rms(seconds(y, start + 0.008, start + 0.010))
        assert burst > 5 * gap
    assert rms(seconds(y, 0.1, 0.11)) > 0  # the tail is still sounding
    assert rms(seconds(y, 0.5, 0.6)) < 0.05 * rms(seconds(y, 0.0, 0.03))


def test_clap_is_a_band_of_noise_not_a_hiss():
    tail = seconds(hit(dsp.Clap(SR), 0.3), 0.04, 0.2)
    assert power_above(tail, 6000) < 0.15  # raw white noise would put about 75 percent up there
    assert 1 - power_above(tail, 500) < 0.05


# --- bass ------------------------------------------------------------------


@pytest.mark.parametrize(("note", "sub_hz"), [(0, 27.5), (12, 55.0), (7, 41.2)])
def test_bass_sub_sits_one_octave_below_the_saw(note, sub_hz):
    y = hit(dsp.Bass(SR), 0.3, note=note)
    assert dominant_hz(seconds(y, 0.05, 0.25), 20, 1000) == pytest.approx(sub_hz, abs=1.0)


def test_bass_root_is_a1_at_55_hz():
    bass = dsp.Bass(SR)
    bass.trigger(note=0)
    assert bass.target == pytest.approx(55.0)
    bass.trigger(note=12)
    assert bass.target == pytest.approx(110.0)


def test_bass_slide_glides_from_the_previous_pitch():
    bass = dsp.Bass(SR)
    bass.trigger(note=0)
    bass.render(SR // 10)
    bass.trigger(note=12, slide=True)
    assert bass.freq == pytest.approx(55.0)  # still where the last note left it, the glide runs while rendering
    bass.render(SR // 2)
    assert bass.freq == pytest.approx(110.0, rel=1e-3)


def test_bass_without_slide_jumps_straight_to_the_new_pitch():
    bass = dsp.Bass(SR)
    bass.trigger(note=0)
    bass.render(SR // 10)
    bass.trigger(note=12)
    assert bass.freq == pytest.approx(110.0)


def test_a_slide_into_silence_does_not_glide():
    bass = dsp.Bass(SR)
    bass.trigger(note=12, slide=True)
    assert bass.freq == pytest.approx(110.0)


def test_bass_accent_opens_the_filter_further():
    plain = spectral_centroid(hit(dsp.Bass(SR), 0.2, note=12))
    accent = spectral_centroid(hit(dsp.Bass(SR), 0.2, note=12, accent=True))
    assert accent > plain


# --- acid ------------------------------------------------------------------


@pytest.mark.parametrize(("note", "hz"), [(0, 110.0), (12, 220.0), (7, 164.8)])
def test_acid_pitch_follows_the_note_from_a2(note, hz):
    y = hit(dsp.Acid(SR), 0.3, note=note, accent=True)
    assert dominant_hz(y, 60, 3000) == pytest.approx(hz, abs=2.0)


def test_acid_cutoff_scale_darkens_and_brightens_the_tone():
    def tone(scale):
        acid = dsp.Acid(SR)
        acid.cutoff_scale = scale
        return spectral_centroid(hit(acid, 0.3, note=0))

    dark, normal, bright = tone(0.3), tone(1.0), tone(2.0)
    assert dark < 0.6 * normal
    assert bright > 1.5 * normal


def test_acid_accent_opens_the_filter_further():
    plain = spectral_centroid(hit(dsp.Acid(SR), 0.3, note=0))
    accent = spectral_centroid(hit(dsp.Acid(SR), 0.3, note=0, accent=True))
    assert accent > 1.2 * plain


# --- blip ------------------------------------------------------------------


def test_blip_is_a_short_tone_that_glides_between_its_two_pitches_and_then_stops():
    blip = dsp.Blip(SR)
    blip.ping(880.0, 1760.0, 0.09, 0.13)
    first = blip.render(int(0.4 * SR))
    assert 0.05 < np.abs(first).max() <= 0.13
    assert 800.0 <= dominant_hz(seconds(first, 0.0, 0.09), 500, 3000) <= 1800.0
    assert not blip.render(SR // 10).any()
