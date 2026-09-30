"""The offline path: write_wav and --bounce. None of this needs an audio device or PortAudio."""

import sys
import types
import wave

import numpy as np
import pytest
from helpers import SR, rms

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


def test_the_board_flag_chooses_what_is_rendered(tmp_path):
    def render(board):
        np.random.seed(1)
        path = tmp_path / f"board{board}.wav"
        techno.main(["--bounce", str(path), "--bars", "1", "--board", str(board)])
        return read_wav(path)[1].astype(np.float64)

    simple, peak, empty = render(1), render(2), render(5)
    assert not empty.any()  # board 5 has nothing on it, and arming it must not sound a UI blip
    assert rms(peak) > rms(simple)  # the peak board adds hats and the acid line


def test_the_board_flag_only_takes_one_to_eight():
    assert techno.parse_args(["--board", "8"]).board == 8
    for wrong in ("0", "9"):
        with pytest.raises(SystemExit):
            techno.parse_args(["--board", wrong])


def test_a_missing_audio_library_says_how_to_render_offline(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    with pytest.raises(SystemExit) as exit_info:
        techno.main(["--stopped"])
    assert "libportaudio2" in exit_info.value.code
    assert "--bounce" in exit_info.value.code


def test_an_output_that_will_not_open_says_how_to_list_the_devices(monkeypatch, tmp_path):
    class RefusingStream:
        def __init__(self, **kwargs):
            raise ValueError("No output device matching 'nope'")

    fake = types.SimpleNamespace(
        query_devices=lambda device=None, kind=None: {"name": "fake"} if kind else [],
        OutputStream=RefusingStream,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    monkeypatch.setattr(techno, "LOG_PATH", str(tmp_path / "techno.log"))
    with pytest.raises(SystemExit) as exit_info:
        techno.main(["--stopped", "--device", "nope"])
    assert "No output device matching 'nope'" in exit_info.value.code
    assert "--list-devices" in exit_info.value.code
