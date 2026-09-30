"""The step clock, board landing, the mix bus, recording and the meters."""

import math

import numpy as np
import pytest
from helpers import BAS, CLP, HAT, KCK, LED, SR, TriggerLog, pattern_with, render_in_blocks, undo_master

from engine import STEPS, TRACKS, Board, Engine, Pattern

BAR_AT_130 = STEPS * 60.0 / 130.0 / 4.0 * SR  # 88615.38 samples


def engine_with_trigger_logs(swing=0.0, bpm=130.0):
    eng = Engine(SR)
    eng.set_bpm(bpm)
    eng.set_swing(swing)
    eng.ui_sound = False
    logs = [TriggerLog() for _ in TRACKS]
    eng.voices = logs
    full = Pattern()
    full.on[:] = True
    eng.boards[0] = Board("full", full)
    return eng, logs


def step_starts(eng, count):
    """Exact start of each step in samples, with the swing the engine has right now."""
    starts, position = [], 0.0
    for step in range(count):
        starts.append(position)
        position += eng.step_len(step % STEPS)
    return starts


# --- the clock --------------------------------------------------------------


def test_a_sixteenth_note_at_130_bpm_is_5538_samples():
    eng = Engine(SR)
    assert eng.samples_per_step == pytest.approx(5538.46, abs=0.01)
    eng.set_bpm(65)
    assert eng.samples_per_step == pytest.approx(11076.92, abs=0.01)


def test_bpm_and_swing_are_clamped():
    eng = Engine(SR)
    eng.set_bpm(10)
    assert eng.bpm == 60.0
    eng.set_bpm(999)
    assert eng.bpm == 200.0
    eng.set_swing(-1)
    assert eng.swing == 0.0
    eng.set_swing(1)
    assert eng.swing == 0.35


def test_swing_moves_the_offbeat_but_the_bar_keeps_its_length():
    eng = Engine(SR)
    eng.set_swing(0.2)
    assert eng.step_len(0) == pytest.approx(1.2 * eng.samples_per_step)
    assert eng.step_len(1) == pytest.approx(0.8 * eng.samples_per_step)
    assert sum(eng.step_len(s) for s in range(STEPS)) == pytest.approx(STEPS * eng.samples_per_step)


@pytest.mark.parametrize("swing", [0.0, 0.2])
@pytest.mark.parametrize("block", [13, 64, 333, 1024, 4096, 100_000])
def test_every_step_fires_on_its_exact_sample_whatever_the_block_size(block, swing):
    eng, logs = engine_with_trigger_logs(swing=swing)
    eng.toggle_play()
    bars = 2
    starts = step_starts(eng, bars * STEPS)
    render_in_blocks(eng, math.ceil(bars * STEPS * eng.samples_per_step) - 1, block)
    for log in logs:
        assert len(log.triggers) == bars * STEPS
        for fired, exact in zip(log.triggers, starts, strict=True):
            assert -1e-6 <= fired - exact <= 1.0 + 1e-6  # never early, at most one sample late


def test_the_bar_counter_turns_over_exactly_on_the_bar_line():
    eng = Engine(SR)
    eng.toggle_play()
    eng.render(math.floor(BAR_AT_130))  # 88615, one sample short of the bar line
    assert (eng.bar, eng.step) == (0, 15)
    eng.render(1)
    assert (eng.bar, eng.step) == (1, 0)


def test_play_starts_from_the_top_and_fires_step_zero_at_once():
    eng, logs = engine_with_trigger_logs()
    eng.step, eng.bar = 7, 3
    eng.toggle_play()
    assert eng.playing
    assert (eng.step, eng.bar) == (0, 0)
    assert all(log.triggers == [0] for log in logs)


def test_stop_halts_the_clock():
    eng, logs = engine_with_trigger_logs()
    eng.toggle_play()
    eng.render(2000)
    eng.toggle_play()
    assert not eng.playing
    eng.render(SR)
    assert all(len(log.triggers) == 1 for log in logs)


def test_accents_trigger_louder_and_carry_their_flags():
    eng = Engine(SR)
    seen = []

    class Spy:
        def trigger(self, vel=1.0, note=0, accent=False, slide=False):
            seen.append((vel, note, accent, slide))

        def render(self, n):
            return np.zeros(n, np.float32)

    p = Pattern()
    p.on[LED, 0] = p.on[LED, 1] = True
    p.acc[LED, 0] = True
    p.note[LED, 0], p.note[LED, 1] = 7, -5
    p.slide[LED, 1] = True
    eng.boards[0] = Board("t", p)
    eng.voices[LED] = Spy()
    eng.toggle_play()
    eng.render(math.ceil(eng.samples_per_step) + 1)
    assert seen == [(1.0, 7, True, False), (0.72, -5, False, True)]


# --- boards -----------------------------------------------------------------


def test_arming_a_board_while_stopped_lands_at_once():
    eng = Engine(SR)
    eng.arm(3)
    assert (eng.board, eng.pending) == (3, None)


def test_arming_while_playing_waits_for_the_next_bar_line():
    eng = Engine(SR)
    eng.toggle_play()
    eng.arm(2)
    assert (eng.board, eng.pending) == (0, 2)
    eng.render(math.floor(BAR_AT_130))
    assert (eng.board, eng.pending) == (0, 2)
    eng.render(1)
    assert (eng.board, eng.pending) == (2, None)


def test_arming_the_live_board_again_cancels_the_pending_swap():
    eng = Engine(SR)
    eng.toggle_play()
    eng.arm(2)
    eng.arm(0)
    assert eng.pending is None


def test_board_numbers_wrap_around_the_eight_boards():
    eng = Engine(SR)
    eng.arm(-1)
    assert eng.board == 7
    eng.arm(9)
    assert eng.board == 1


def test_the_landing_board_plays_its_own_pattern():
    eng, logs = engine_with_trigger_logs()
    eng.boards[1] = Board("kick on step 3", pattern_with(KCK, [3]))
    eng.toggle_play()
    eng.arm(1)
    eng.render(math.ceil(BAR_AT_130 + 3.5 * eng.samples_per_step))  # through step 3 of the second bar
    assert len(logs[KCK].triggers) == STEPS + 1  # the full board for one bar, then the new board's single kick
    assert len(logs[CLP].triggers) == STEPS  # the claps stop because the new board has none


# --- the mix bus ------------------------------------------------------------


def silent_engine():
    eng = Engine(SR)
    eng.ui_sound = False
    return eng


def test_a_stopped_engine_renders_silence():
    out = silent_engine().render(1024)
    assert out.shape == (1024, 2)
    assert out.dtype == np.float32
    assert not out.any()


def test_the_master_bus_never_clips_even_with_everything_on_and_every_fader_up():
    eng = silent_engine()
    full = Pattern()
    full.on[:] = True
    full.acc[:] = True
    eng.boards[0] = Board("everything", full)
    eng.vol[:] = 1.5
    eng.toggle_play()
    out = render_in_blocks(eng, 2 * math.ceil(BAR_AT_130), 1024)
    assert 0.5 < np.abs(out).max() <= 1.0


def test_a_muted_track_is_silent_and_an_unmuted_one_is_not():
    eng = silent_engine()
    eng.boards[0] = Board("bass", pattern_with(BAS, [0]))
    eng.mute[BAS] = True
    eng.toggle_play()
    assert not eng.render(4096).any()
    eng.mute[BAS] = False
    eng.toggle_play()
    eng.toggle_play()
    assert eng.render(4096).any()


def test_track_volume_scales_the_meter_and_the_mix():
    def render_bass(vol):
        eng = silent_engine()
        eng.boards[0] = Board("bass", pattern_with(BAS, [0]))
        eng.vol[BAS] = vol
        eng.delay_mix = 0.0
        eng.toggle_play()
        return eng, eng.render(2048)

    loud, loud_out = render_bass(1.0)
    quiet, quiet_out = render_bass(0.5)
    assert quiet.levels[BAS] == pytest.approx(0.5 * loud.levels[BAS])
    np.testing.assert_allclose(undo_master(quiet_out), 0.5 * undo_master(loud_out), atol=1e-4)


def test_pan_is_constant_power(monkeypatch):
    def dry_bass(pan):
        monkeypatch.setattr(TRACKS[BAS], "pan", pan)
        eng = silent_engine()
        eng.boards[0] = Board("bass", pattern_with(BAS, [0]))
        eng.delay_mix = 0.0
        eng.toggle_play()
        return undo_master(eng.render(2048), eng.master)

    centre = dry_bass(0.0)
    np.testing.assert_allclose(centre[:, 0], centre[:, 1], atol=1e-6)
    hard_right = dry_bass(1.0)
    assert not hard_right[:, 0].any()
    leaning = dry_bass(0.4)
    assert np.abs(leaning[:, 1]).max() > np.abs(leaning[:, 0]).max()
    power_centre = np.square(centre).sum(axis=1)
    np.testing.assert_allclose(np.square(leaning).sum(axis=1), power_centre, atol=1e-6)


def test_the_delay_follows_the_tempo_as_a_dotted_eighth():
    eng = silent_engine()
    eng.boards[0] = Board("hat", pattern_with(HAT, [0]))
    eng.delay_mix = 1.0
    eng.toggle_play()
    out = np.abs(render_in_blocks(eng, SR, 256)).max(axis=1)
    dotted_eighth = int(0.75 * 60.0 / 130.0 * SR)  # 17307 samples, 346 ms
    assert out[14000:dotted_eighth].max() < 1e-3  # the hat itself has died away by now
    assert out[dotted_eighth : dotted_eighth + 512].max() > 1e-2  # and its echo arrives on the dot
    assert np.argmax(out[14000:] > 1e-3) + 14000 == dotted_eighth


# --- UI clicks, recording, scope, meters ------------------------------------


def test_ui_click_is_audible_on_the_output_but_not_in_the_recording():
    eng = Engine(SR)
    eng.start_recording()
    eng.click()
    out = eng.render(2048)
    assert out.any()
    take = eng.stop_recording()
    assert not take.any()


def test_ui_sound_off_silences_clicks_and_confirmations():
    eng = silent_engine()
    eng.click()
    eng.confirm()
    assert not eng.render(2048).any()


def test_recording_returns_exactly_what_was_rendered():
    eng = silent_engine()
    eng.boards[0] = Board("kick", pattern_with(KCK, [0, 8]))
    eng.toggle_play()
    eng.start_recording()
    played = np.concatenate([eng.render(n) for n in (1000, 2500, 333)])
    assert eng.record_seconds == pytest.approx(3833 / SR)
    take = eng.stop_recording()
    np.testing.assert_array_equal(take, played)
    assert eng.recording is None
    assert eng.record_seconds == 0.0


def test_stopping_a_recording_that_never_rendered_gives_nothing():
    eng = silent_engine()
    eng.start_recording()
    assert eng.stop_recording() is None


@pytest.mark.parametrize("frames", [100, 2048, 5000])
def test_the_scope_keeps_its_length_and_holds_the_latest_audio(frames):
    eng = silent_engine()
    eng.boards[0] = Board("kick", pattern_with(KCK, [0]))
    eng.toggle_play()
    out = eng.render(frames)
    assert len(eng.scope) == 2048
    mono = out.mean(axis=1)
    np.testing.assert_allclose(eng.scope[-min(frames, 2048) :], mono[-2048:], atol=1e-7)


def test_meters_fall_by_28_percent_per_block_and_jump_to_a_new_peak():
    eng = silent_engine()
    eng.levels[:] = 1.0
    eng.render(512)
    np.testing.assert_allclose(eng.levels, 0.72)
    eng.render(512)
    np.testing.assert_allclose(eng.levels, 0.72**2)
