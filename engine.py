"""Step sequencer + realtime mixer. The audio callback calls Engine.render()."""

import random
import wave
from dataclasses import dataclass, field

import numpy as np

import dsp

STEPS = 16
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SCALE = [0, 3, 5, 7, 10, 12, 15]  # A minor pentatonic-ish, used by randomize


@dataclass
class TrackSpec:
    name: str
    kind: str
    pitched: bool
    pan: float  # -1 left .. 1 right
    send: float  # amount into the delay
    vol: float
    octave: int = 1  # octave label for note 0


TRACKS = [
    TrackSpec("KCK", "kick", False, 0.0, 0.00, 1.00),
    TrackSpec("CLP", "clap", False, 0.15, 0.28, 0.75),
    TrackSpec("HAT", "hat", False, -0.25, 0.10, 0.65),
    TrackSpec("OHT", "ohat", False, 0.30, 0.22, 0.55),
    TrackSpec("BAS", "bass", True, 0.0, 0.05, 0.90, 1),
    TrackSpec("LED", "acid", True, -0.10, 0.55, 0.80, 2),
]


@dataclass
class Pattern:
    on: np.ndarray = field(default_factory=lambda: np.zeros((len(TRACKS), STEPS), bool))
    acc: np.ndarray = field(default_factory=lambda: np.zeros((len(TRACKS), STEPS), bool))
    slide: np.ndarray = field(default_factory=lambda: np.zeros((len(TRACKS), STEPS), bool))
    note: np.ndarray = field(default_factory=lambda: np.zeros((len(TRACKS), STEPS), np.int16))


def write_wav(path, audio, sr):
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def note_name(semitones, base_octave=1):
    """Names a semitone offset from the track root (A of base_octave)."""
    semitones = int(semitones)
    octave = base_octave + (semitones + 9) // 12
    return f"{NOTE_NAMES[(semitones + 9) % 12]}{octave}"


def default_pattern():
    p = Pattern()
    for s in (0, 4, 8, 12):
        p.on[0, s] = True
    for s in (4, 12):
        p.on[1, s] = True
    p.on[2, :] = True
    p.acc[2, (2, 6, 10, 14)] = True
    for s in (2, 6, 10, 14):
        p.on[3, s] = True
    bass = [(0, 0, True), (3, 0, False), (6, 12, False), (8, 0, True), (11, 3, False), (14, -2, False)]
    for s, n, acc in bass:
        p.on[4, s] = True
        p.note[4, s] = n
        p.acc[4, s] = acc
    lead = [(0, 0, True, False), (2, 12, False, False), (3, 12, False, True), (6, 3, False, False),
            (7, 10, False, False), (10, 0, True, False), (11, 12, False, True), (14, 7, False, False),
            (15, 10, False, False)]
    for s, n, acc, sl in lead:
        p.on[5, s] = True
        p.note[5, s] = n
        p.acc[5, s] = acc
        p.slide[5, s] = sl
    return p


def simple_pattern():
    """One plain four-on-the-floor beat: kick, clap on 2 and 4, offbeat hat, root bass."""
    p = Pattern()
    for s in (0, 4, 8, 12):
        p.on[0, s] = True
    for s in (4, 12):
        p.on[1, s] = True
    for s in (2, 6, 10, 14):
        p.on[3, s] = True
    for s in (0, 8):
        p.on[4, s] = True
        p.acc[4, s] = True
    return p


def acid_pattern():
    """Rolling 303 line over a stripped kit."""
    p = Pattern()
    for s in (0, 4, 8, 12):
        p.on[0, s] = True
    for s in (2, 6, 10, 14):
        p.on[3, s] = True
    for s in (0, 8):
        p.on[4, s] = True
        p.acc[4, s] = True
    lead = [(0, 0, True, False), (1, 0, False, True), (2, 12, False, False), (4, 10, False, False),
            (5, 10, False, True), (6, 7, False, False), (8, 0, True, False), (9, 12, False, True),
            (10, 15, False, False), (12, 10, False, False), (13, 7, False, True), (14, 3, False, False),
            (15, 0, False, False)]
    for s, n, acc, sl in lead:
        p.on[5, s] = True
        p.note[5, s] = n
        p.acc[5, s] = acc
        p.slide[5, s] = sl
    return p


def dub_pattern():
    """Sparse dub techno: half-time kick, offbeat open hats, long sliding bass."""
    p = Pattern()
    for s in (0, 8):
        p.on[0, s] = True
    p.on[1, 12] = True
    for s in (2, 6, 10, 14):
        p.on[3, s] = True
    for s, n, sl in ((0, 0, False), (7, -5, True), (8, 0, False), (15, 3, True)):
        p.on[4, s] = True
        p.note[4, s] = n
        p.slide[4, s] = sl
        p.acc[4, s] = s in (0, 8)
    for s, n in ((6, 12), (14, 15)):
        p.on[5, s] = True
        p.note[5, s] = n
        p.acc[5, s] = True
    return p


@dataclass
class Board:
    name: str
    pattern: Pattern


def default_boards():
    return [
        Board("simple", simple_pattern()),
        Board("peak", default_pattern()),
        Board("acid", acid_pattern()),
        Board("dub", dub_pattern()),
        Board("empty 5", Pattern()),
        Board("empty 6", Pattern()),
        Board("empty 7", Pattern()),
        Board("empty 8", Pattern()),
    ]


def make_voice(kind, sr):
    return {
        "kick": lambda: dsp.Kick(sr),
        "clap": lambda: dsp.Clap(sr),
        "hat": lambda: dsp.Hat(sr, open_hat=False),
        "ohat": lambda: dsp.Hat(sr, open_hat=True),
        "bass": lambda: dsp.Bass(sr),
        "acid": lambda: dsp.Acid(sr),
    }[kind]()


class Engine:
    def __init__(self, sr):
        self.sr = sr
        self.voices = [make_voice(t.kind, sr) for t in TRACKS]
        self.voices_b = [make_voice(t.kind, sr) for t in TRACKS]
        self.vol = np.array([t.vol for t in TRACKS])
        self.mute = np.zeros(len(TRACKS), bool)
        self.boards = default_boards()
        self.board = 0        # deck A, the board being played and edited
        self.pending = None   # board armed to land on the next bar
        self.deck_b = None    # board loaded on deck B while crossfading
        self.xfade = 0.0      # 0.0 = all deck A, 1.0 = all deck B
        self.bpm = 130.0
        self.playing = False
        self.step = 0
        self.step_phase = 0.0
        self.bar = 0
        self.master = 0.9
        self.delay_mix = 0.30
        self.delay_fb = 0.33
        self.delay = dsp.PingPongDelay(sr)
        self.scope = np.zeros(2048, np.float32)
        self.levels = np.zeros(len(TRACKS))
        self.cutoff_scale = 1.0
        self.swing = 0.0          # 0 = straight 16ths, 0.3 = heavy shuffle
        self.blip = dsp.Blip(sr)
        self.ui_sound = True
        self.recording = None     # list of rendered blocks while recording

    # --- transport -----------------------------------------------------
    @property
    def pattern(self):
        """The board the cursor edits: always deck A."""
        return self.boards[self.board].pattern

    @property
    def crossfading(self):
        return self.deck_b is not None

    @property
    def samples_per_step(self):
        return 60.0 / self.bpm / 4.0 * self.sr

    def step_len(self, step):
        """Swing lengthens the downbeat 16th and shortens the offbeat; the bar keeps its length."""
        ratio = 1.0 + self.swing if step % 2 == 0 else 1.0 - self.swing
        return self.samples_per_step * ratio

    def set_swing(self, value):
        self.swing = float(np.clip(value, 0.0, 0.35))

    # --- UI feedback ----------------------------------------------------
    def click(self):
        if self.ui_sound:
            self.blip.ping(2100.0, 1900.0, 0.010, 0.10)

    def confirm(self):
        if self.ui_sound:
            self.blip.ping(880.0, 1760.0, 0.09, 0.13)

    # --- recording ------------------------------------------------------
    def start_recording(self):
        self.recording = []

    def stop_recording(self):
        blocks, self.recording = self.recording, None
        return np.concatenate(blocks) if blocks else None

    @property
    def record_seconds(self):
        return sum(len(b) for b in self.recording) / self.sr if self.recording is not None else 0.0

    def toggle_play(self):
        self.playing = not self.playing
        if self.playing:
            self.step = 0
            self.step_phase = 0.0
            self.bar = 0
            self._trigger(0)

    def set_bpm(self, bpm):
        self.bpm = float(np.clip(bpm, 60.0, 200.0))

    # --- pattern editing ------------------------------------------------
    def toggle_step(self, track, step):
        p = self.pattern
        p.on[track, step] = not p.on[track, step]

    def toggle_accent(self, track, step):
        p = self.pattern
        p.acc[track, step] = not p.acc[track, step]

    def toggle_slide(self, track, step):
        if TRACKS[track].pitched:
            p = self.pattern
            p.slide[track, step] = not p.slide[track, step]

    def shift_note(self, track, step, delta):
        if TRACKS[track].pitched:
            p = self.pattern
            p.note[track, step] = int(np.clip(p.note[track, step] + delta, -12, 24))

    def clear_track(self, track):
        p = self.pattern
        for arr in (p.on, p.acc, p.slide):
            arr[track, :] = False
        p.note[track, :] = 0

    def randomize_track(self, track):
        p = self.pattern
        self.clear_track(track)
        kind = TRACKS[track].kind
        if kind == "kick":
            for s in range(0, STEPS, 4):
                p.on[track, s] = True
            if random.random() < 0.4:
                p.on[track, random.choice([3, 7, 11, 15])] = True
        elif kind == "clap":
            for s in (4, 12):
                p.on[track, s] = True
        elif kind in ("hat", "ohat"):
            density = 0.9 if kind == "hat" else 0.3
            for s in range(STEPS):
                p.on[track, s] = random.random() < density
                p.acc[track, s] = p.on[track, s] and s % 4 == 2
        else:
            density = 0.45 if kind == "bass" else 0.55
            for s in range(STEPS):
                if random.random() < density:
                    p.on[track, s] = True
                    p.note[track, s] = random.choice(SCALE) - (12 if random.random() < 0.2 else 0)
                    p.acc[track, s] = random.random() < 0.3
                    p.slide[track, s] = random.random() < 0.25

    def arm(self, index):
        """Queue a board; it lands on the next bar line (or immediately when stopped)."""
        index %= len(self.boards)
        target = self.deck_b if self.crossfading else self.board
        if index == target:
            self.pending = None
            return
        self.pending = index
        if not self.playing:
            self._land()

    def _land(self):
        if self.pending is None:
            return
        if self.crossfading:
            self.deck_b = self.pending
        else:
            self.board = self.pending
        self.pending = None
        self.confirm()

    def start_xfade(self):
        if self.crossfading:
            return
        self.deck_b = self.pending if self.pending is not None else (self.board + 1) % len(self.boards)
        self.pending = None
        self.xfade = 0.0

    def cancel_xfade(self):
        self.deck_b = None
        self.xfade = 0.0

    def nudge_xfade(self, delta):
        if not self.crossfading:
            return
        self.xfade = float(np.clip(self.xfade + delta, 0.0, 1.0))
        if self.xfade >= 1.0:
            self.commit_xfade()

    def commit_xfade(self):
        """Deck B becomes the live board; voice banks swap so its tails keep ringing."""
        if not self.crossfading:
            return
        self.board = self.deck_b
        self.voices, self.voices_b = self.voices_b, self.voices
        self.deck_b = None
        self.xfade = 0.0
        self.confirm()

    # --- audio ----------------------------------------------------------
    def _trigger(self, step):
        self._trigger_deck(self.voices, self.pattern, step)
        if self.crossfading:
            self._trigger_deck(self.voices_b, self.boards[self.deck_b].pattern, step)

    def _trigger_deck(self, voices, p, step):
        for i, spec in enumerate(TRACKS):
            if not p.on[i, step]:
                continue
            accent = bool(p.acc[i, step])
            vel = 1.0 if accent else 0.72
            voices[i].trigger(vel=vel, note=int(p.note[i, step]),
                              accent=accent, slide=bool(p.slide[i, step]))

    def _mix_deck(self, voices, n, gain, dry, send, peaks):
        for i, spec in enumerate(TRACKS):
            if spec.kind == "acid":
                voices[i].cutoff_scale = self.cutoff_scale
            sig = voices[i].render(n)
            if self.mute[i] or gain <= 0.0:
                continue
            sig = sig * (self.vol[i] * gain)
            peaks[i] = max(peaks[i], float(np.abs(sig).max()))
            left = np.sqrt(max(0.0, (1.0 - spec.pan) / 2.0))
            right = np.sqrt(max(0.0, (1.0 + spec.pan) / 2.0))
            dry[:, 0] += sig * left
            dry[:, 1] += sig * right
            if spec.send > 0:
                send[:, 0] += sig * left * spec.send
                send[:, 1] += sig * right * spec.send

    def _render_chunk(self, out, pos, n, peaks):
        dry = np.zeros((n, 2), np.float32)
        send = np.zeros((n, 2), np.float32)
        if self.crossfading:
            gain_a = float(np.cos(self.xfade * np.pi / 2))  # equal power, so the blend holds level
            gain_b = float(np.sin(self.xfade * np.pi / 2))
        else:
            gain_a, gain_b = 1.0, 0.0
        self._mix_deck(self.voices, n, gain_a, dry, send, peaks)
        if self.crossfading:
            self._mix_deck(self.voices_b, n, gain_b, dry, send, peaks)
        delay_samples = 0.75 * 60.0 / self.bpm * self.sr
        wet = self.delay.process(send, delay_samples, self.delay_fb)
        mix = np.tanh((dry + wet * self.delay_mix) * self.master)
        if self.recording is not None:
            self.recording.append(mix.copy())  # tapped before the UI blip, so takes stay clean
        blip = self.blip.render(n)
        mix[:, 0] += blip
        mix[:, 1] += blip
        out[pos:pos + n] = mix

    def render(self, frames):
        out = np.zeros((frames, 2), np.float32)
        peaks = np.zeros(len(TRACKS))
        pos = 0
        while pos < frames:
            if self.playing:
                remain = self.step_len(self.step) - self.step_phase
                n = int(min(frames - pos, max(1.0, np.ceil(remain))))
            else:
                n = frames - pos
            self._render_chunk(out, pos, n, peaks)
            pos += n
            if self.playing:
                self.step_phase += n
                cur_len = self.step_len(self.step)
                if self.step_phase >= cur_len - 1e-9:
                    self.step_phase -= cur_len
                    self.step = (self.step + 1) % STEPS
                    if self.step == 0:
                        self.bar += 1
                        self._land()
                    self._trigger(self.step)
        mono = out.mean(axis=1)
        keep = len(self.scope) - frames
        if keep > 0:
            self.scope = np.concatenate((self.scope[frames:], mono))
        else:
            self.scope = mono[-len(self.scope):]
        self.levels = np.maximum(self.levels * 0.72, peaks)
        return out
