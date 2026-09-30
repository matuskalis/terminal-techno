"""The offline path: write_wav and --bounce. None of this needs an audio device or PortAudio."""

import sys
import wave

import numpy as np
from helpers import SR

import techno
from engine import STEPS, write_wav

SAMPLES_PER_STEP_130 = 60.0 / 130.0 / 4.0 * SR


def read_wav(path):
    with wave.open(str(path)) as w:
        header = (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes())
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, 2)
    return header, samples


def test_write_wav_makes_16_bit_stereo_and_scales_to_full_scale(tmp_path):
    path = tmp_path / "a.wav"
    write_wav(str(path), np.array([[0.0, 0.0], [0.5, -0.5], [1.0, -1.0]], np.float32), 44100)
    header, samples = read_wav(path)
    assert header == (2, 2, 44100, 3)
    assert samples.tolist() == [[0, 0], [16383, -16383], [32767, -32767]]


def test_write_wav_clips_what_is_beyond_full_scale(tmp_path):
    path = tmp_path / "a.wav"
    write_wav(str(path), np.array([[3.0, -3.0]], np.float32), SR)
    assert read_wav(path)[1].tolist() == [[32767, -32767]]


def test_arguments_default_to_130_bpm_48k_and_1024_frame_blocks():
    args = techno.parse_args([])
    assert (args.bpm, args.samplerate, args.blocksize, args.bars) == (130.0, 48000, 1024, 8)
    assert args.bounce is None
    assert not args.stopped


def test_bounce_writes_the_requested_number_of_bars(tmp_path, capsys):
    path = tmp_path / "out.wav"
    assert techno.main(["--bounce", str(path), "--bars", "2"]) == 0
    header, _ = read_wav(path)
    assert header == (2, 2, SR, int(2 * STEPS * SAMPLES_PER_STEP_130))
    assert f"wrote {path}" in capsys.readouterr().out


def test_bounce_follows_bpm_and_sample_rate(tmp_path):
    slow = tmp_path / "slow.wav"
    techno.main(["--bounce", str(slow), "--bars", "1", "--bpm", "65"])
    assert read_wav(slow)[0][3] == int(STEPS * 2 * SAMPLES_PER_STEP_130)
    cd = tmp_path / "cd.wav"
    techno.main(["--bounce", str(cd), "--bars", "1", "--samplerate", "44100"])
    header, _ = read_wav(cd)
    assert header[2] == 44100
    assert header[3] == int(STEPS * 60.0 / 130.0 / 4.0 * 44100)


def test_bounce_is_audible_and_stays_inside_full_scale(tmp_path):
    path = tmp_path / "out.wav"
    techno.main(["--bounce", str(path), "--bars", "2"])
    _, samples = read_wav(path)
    peak = np.abs(samples.astype(np.float64)).max() / 32767
    assert 0.3 < peak <= 1.0
    assert samples[:, 0].any()
    assert samples[:, 1].any()


def test_a_seeded_bounce_is_byte_for_byte_reproducible(tmp_path):
    first, second, third = (tmp_path / name for name in ("1.wav", "2.wav", "3.wav"))
    np.random.seed(5)
    techno.main(["--bounce", str(first), "--bars", "1"])
    np.random.seed(5)
    techno.main(["--bounce", str(second), "--bars", "1"])
    np.random.seed(6)
    techno.main(["--bounce", str(third), "--bars", "1"])
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes() != third.read_bytes()


def test_bounce_needs_no_audio_library(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)  # any import of it now raises ImportError
    assert techno.main(["--bounce", str(tmp_path / "out.wav"), "--bars", "1"]) == 0
