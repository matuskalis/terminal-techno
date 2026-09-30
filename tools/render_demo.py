#!/usr/bin/env python3
"""Render a short demo set offline through the real engine, as an MP3 and a picture of the signal.

Nothing here opens an audio device. The script plays the engine the way the keys do (arm a board,
hold the filter key, crossfade, hold the delay key, stop) and renders the result block by block in
the same 1024-frame size the live callback uses. What you hear is what Engine.render() returns,
encoded to MP3 with no processing in between.

    pip install pillow
    python tools/render_demo.py --mp3 docs/demo.mp3 --png docs/signal.png

The picture has the mix as a waveform, a spectrogram of it (mono, log frequency, dB below the
loudest frame), and the triggers the sequencer fired, from the engine itself.
Needs ffmpeg with libmp3lame for the MP3. The face is JetBrains Mono, see tools/capture_tui.py.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import STEPS, TRACKS, Engine, write_wav
from termshot import ANSI, Fonts, hex_to_rgb

FONT_DIR = ROOT / "tools" / "fonts"
SAMPLE_RATE = 48000
BLOCK = 1024  # the live callback's block size
SEED = 2026
TAIL_SECONDS = 2.5  # after the last bar, the voices and the delay ring out

# The set, in bars counted from 0. Every line is a key a player would press.
ARM_PEAK_AT = 1  # ] arms board 2, it lands on the next bar line
FILTER_FROM, FILTER_TO = 2, 6  # hold F: the acid filter opens from 0.45 to 1.6
CROSSFADE_FROM, CROSSFADE_BARS = 6.25, 2  # t, then 0 held for two bars: board 3 takes over
DELAY_FROM, DELAY_TO = 10, 12  # hold D: the delay mix rises from 0.30 to 0.55
ARM_DUB_AT = 12  # ] again, board 4 lands on bar 13
STOP_AT = 14  # space
FILTER_RANGE = (0.45, 1.6)
DELAY_RANGE = (0.30, 0.55)


def bars_to_samples(eng, bars):
    return bars * STEPS * eng.samples_per_step


class Score:
    """What the sequencer fired and what the player's hands did, sampled at every block."""

    def __init__(self):
        self.triggers = []  # (sample, track, accent, deck)
        self.board = []
        self.deck_b = []
        self.xfade = []


def watch_triggers(eng, score):
    """Record every trigger at the sample it lands on, without changing what the voices do."""
    where = {"call_start": 0, "at": 0}
    render_chunk, trigger_deck = eng._render_chunk, eng._trigger_deck

    def chunk(out, pos, n, peaks):
        where["at"] = where["call_start"] + pos + n  # a trigger follows the chunk that ends on its step
        return render_chunk(out, pos, n, peaks)

    def triggered(voices, pattern, step):
        deck = "A" if voices is eng.voices else "B"
        for track in range(len(TRACKS)):
            if pattern.on[track, step]:
                score.triggers.append((where["at"], track, bool(pattern.acc[track, step]), deck))
        trigger_deck(voices, pattern, step)

    eng._render_chunk, eng._trigger_deck = chunk, triggered
    return where


def lerp(a, b, t):
    return a + (b - a) * min(1.0, max(0.0, t))


def perform():
    """Play the set and return (stereo float32 audio, score)."""
    np.random.seed(SEED)
    eng = Engine(SAMPLE_RATE)
    eng.ui_sound = False  # the blips are UI feedback, not music
    score = Score()
    where = watch_triggers(eng, score)
    eng.toggle_play()

    def bar(at):
        return bars_to_samples(eng, at)

    total = int(bar(STOP_AT) + TAIL_SECONDS * SAMPLE_RATE)
    blocks, done = [], 0
    armed_peak = armed_dub = crossfade_started = stopped = False
    fader_moves = 0
    while done < total:
        now = done  # samples since the start; a key pressed now lands in this block
        if not armed_peak and now >= bar(ARM_PEAK_AT):
            eng.arm(1)
            armed_peak = True
        if FILTER_FROM <= now / bar(1) <= FILTER_TO:
            eng.cutoff_scale = lerp(*FILTER_RANGE, (now - bar(FILTER_FROM)) / bar(FILTER_TO - FILTER_FROM))
        if not crossfade_started and now >= bar(CROSSFADE_FROM):
            eng.arm(2)
            eng.start_xfade()
            crossfade_started = True
        if crossfade_started and eng.crossfading:
            due = int(20 * (now - bar(CROSSFADE_FROM)) / bar(CROSSFADE_BARS)) + 1  # 0.05 per press, 20 presses
            while fader_moves < min(due, 20):
                eng.nudge_xfade(0.05)
                fader_moves += 1
        if DELAY_FROM <= now / bar(1) <= DELAY_TO:
            eng.delay_mix = lerp(*DELAY_RANGE, (now - bar(DELAY_FROM)) / bar(DELAY_TO - DELAY_FROM))
        if not armed_dub and now >= bar(ARM_DUB_AT):
            eng.arm(3)
            armed_dub = True
        if not stopped and now >= bar(STOP_AT):
            eng.toggle_play()
            stopped = True
        n = min(BLOCK, total - done)
        where["call_start"] = done
        blocks.append(eng.render(n))
        score.board.append(eng.board)
        score.deck_b.append(eng.deck_b)
        score.xfade.append(eng.xfade)
        done += n
    return np.concatenate(blocks), score


# --- MP3 --------------------------------------------------------------------


def encode_mp3(audio, path):
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "set.wav"
        write_wav(str(wav), audio, SAMPLE_RATE)
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-i", str(wav),
                "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact",
                "-codec:a", "libmp3lame", "-b:a", "128k", str(path),
            ],
            check=True,
        )  # fmt: skip


# --- the picture --------------------------------------------------------------

BACKGROUND = hex_to_rgb("#1d1f21")
DIM = hex_to_rgb(ANSI["blue"])
CYAN = hex_to_rgb(ANSI["cyan"])
MAGENTA = hex_to_rgb(ANSI["magenta"])
GREEN = hex_to_rgb(ANSI["green"])
TEXT = hex_to_rgb("#c5c8c6")
GRID = hex_to_rgb("#33373b")

# Level ramp: the terminal's own cyan, then its yellow for the loudest frames.
RAMP = [
    (0.00, "#1d1f21"),
    (0.20, "#233b3c"),
    (0.45, "#3f7670"),
    (0.70, "#8abeb7"),
    (0.88, "#f0c674"),
    (1.00, "#fff7e0"),
]
DB_RANGE = 70.0
F_LOW, F_HIGH = 20.0, 16000.0
FREQUENCY_TICKS = [
    (50, "50"),
    (100, "100"),
    (200, "200"),
    (500, "500"),
    (1000, "1k"),
    (2000, "2k"),
    (5000, "5k"),
    (10000, "10k"),
]
PICTURE_COLOURS = 128  # the spectrogram is 256 flat levels already, so this costs nothing visible and halves the file


def ramp_lut(size=256):
    stops = np.array([stop for stop, _ in RAMP])
    colours = np.array([hex_to_rgb(colour) for _, colour in RAMP], float)
    t = np.linspace(0, 1, size)
    return np.stack([np.interp(t, stops, colours[:, c]) for c in range(3)], axis=1).astype(np.uint8)


def spectrogram(mono, columns, rows, nfft=4096, pad=4):
    """Level in dB below the loudest frame, shape (rows, columns), row 0 at F_HIGH."""
    centres = (np.arange(columns) + 0.5) * len(mono) / columns
    starts = np.clip((centres - nfft / 2).astype(int), 0, len(mono) - nfft)
    window = np.hanning(nfft)
    freqs = np.fft.rfftfreq(nfft * pad, 1.0 / SAMPLE_RATE)
    row_hz = np.geomspace(F_HIGH, F_LOW, rows)  # one row per pixel, the top row is the highest pitch
    out = np.empty((rows, columns))
    for col, start in enumerate(starts):
        magnitude = np.abs(np.fft.rfft(mono[start : start + nfft] * window, nfft * pad))
        out[:, col] = np.interp(row_hz, freqs, magnitude)
    return 20.0 * np.log10(out / out.max() + 1e-10)


def to_rgb(db):
    level = np.clip((db + DB_RANGE) / DB_RANGE, 0.0, 1.0)
    return ramp_lut()[(level * 255).astype(int)]


class Figure:
    """Geometry and drawing helpers. Everything sits on the TUI's character grid."""

    def __init__(self, audio, score, fonts):
        self.audio, self.score, self.fonts = audio, score, fonts
        cw, ch = fonts.cell_w, fonts.cell_h
        self.width = 100 * cw
        self.left, self.right = 9 * cw, 99 * cw
        self.plot_w = self.right - self.left
        self.title_y = ch // 2
        self.board_y = self.title_y + ch
        self.wave_top, self.wave_h = self.board_y + ch + 4, 4 * ch
        self.spec_top, self.spec_h = self.wave_top + self.wave_h + ch // 2, 11 * ch
        self.lane_top = self.spec_top + self.spec_h + ch // 2
        self.axis_y = self.lane_top + len(TRACKS) * ch
        self.height = self.axis_y + 2 * ch + ch // 2
        self.img = Image.new("RGB", (self.width, self.height), BACKGROUND)
        self.draw = ImageDraw.Draw(self.img)
        self.samples_per_bar = STEPS * 60.0 / 130.0 / 4.0 * SAMPLE_RATE

    def text(self, x, y, s, colour=TEXT, bold=False):
        font = self.fonts.bold if bold else self.fonts.regular
        self.draw.text((x, y + self.fonts.baseline), s, font=font, fill=colour, anchor="ls")

    def x_of(self, sample):
        return self.left + sample * self.plot_w / len(self.audio)

    def title(self):
        cw = self.fonts.cell_w
        self.text(cw, self.title_y, "TERMINAL TECHNO", MAGENTA, bold=True)
        facts = f"demo set   130 BPM   {STOP_AT} bars and the tail   {len(self.audio) / SAMPLE_RATE:.1f} s"
        self.text(19 * cw, self.title_y, facts, CYAN)
        bar_w = 12 * cw
        x0 = self.right - bar_w - 5 * cw
        lut = ramp_lut()
        for i in range(bar_w):
            self.draw.line(
                [x0 + i, self.title_y + 6, x0 + i, self.title_y + 26], fill=tuple(lut[int(255 * i / (bar_w - 1))])
            )
        self.text(x0 - 7 * cw, self.title_y, f"-{DB_RANGE:.0f} dB", DIM)
        self.text(x0 + bar_w + cw, self.title_y, "0 dB", DIM)

    def boards(self):
        """Which board is live, and the span where deck B was fading in."""
        names = [board.name for board in Engine(SAMPLE_RATE).boards]
        live, ch = self.score.board, self.fonts.cell_h
        start = 0
        for i in range(1, len(live) + 1):
            if i == len(live) or live[i] != live[start]:
                self.text(
                    self.x_of(start * BLOCK) + 4,
                    self.board_y,
                    f"[{live[start] + 1}] {names[live[start]]}",
                    GREEN,
                    bold=True,
                )
                start = i
        fading = [i for i, deck in enumerate(self.score.deck_b) if deck is not None]
        if fading:
            x0, x1 = self.x_of(fading[0] * BLOCK), self.x_of((fading[-1] + 1) * BLOCK)
            deck = self.score.deck_b[fading[0]]
            self.draw.line([x0, self.board_y + ch - 3, x1, self.board_y + ch - 3], fill=CYAN, width=2)
            self.text(x0 + 4, self.board_y, f"<{deck + 1}> {names[deck]}", CYAN, bold=True)

    def waveform(self, mono):
        edges = np.linspace(0, len(mono), self.plot_w + 1).astype(int)
        mid = self.wave_top + self.wave_h // 2
        scale = self.wave_h / 2 / 0.75
        self.draw.line([self.left, mid, self.right, mid], fill=GRID)
        for col in range(self.plot_w):
            segment = mono[edges[col] : edges[col + 1]]
            x = self.left + col
            self.draw.line([x, mid - float(segment.max()) * scale, x, mid - float(segment.min()) * scale], fill=CYAN)
        self.text(self.fonts.cell_w, self.wave_top + self.fonts.cell_h // 2, "mix", DIM)

    def spectrogram(self, mono):
        self.img.paste(
            Image.fromarray(to_rgb(spectrogram(mono, self.plot_w, self.spec_h)), "RGB"), (self.left, self.spec_top)
        )
        for hz, label in FREQUENCY_TICKS:
            y = self.spec_top + self.spec_h * np.log(F_HIGH / hz) / np.log(F_HIGH / F_LOW)
            self.draw.line([self.left - 6, y, self.left - 1, y], fill=DIM)
            self.text(self.left - 8 - len(label) * self.fonts.cell_w, int(y) - self.fonts.cell_h // 2 + 4, label, DIM)
        self.text(self.fonts.cell_w, self.spec_top, "Hz", DIM)

    def lanes(self):
        ch = self.fonts.cell_h
        for row, spec in enumerate(TRACKS):
            self.text(self.fonts.cell_w, self.lane_top + row * ch, spec.name, DIM)
        for sample, track, accent, deck in self.score.triggers:
            colour = MAGENTA if accent else (DIM if deck == "B" else CYAN)
            x, y = int(self.x_of(sample)), self.lane_top + track * ch + ch // 2
            self.draw.rectangle([x, y - 7, x + 2, y + 7], fill=colour)

    def axis(self):
        cw, bar = self.fonts.cell_w, 0
        while bar * self.samples_per_bar < len(self.audio):
            x = int(self.x_of(bar * self.samples_per_bar))
            if bar:
                self.draw.line([x, self.wave_top, x, self.wave_top + self.wave_h], fill=GRID)
                self.draw.line([x, self.lane_top, x, self.lane_top + len(TRACKS) * self.fonts.cell_h], fill=GRID)
            self.text(x + 3, self.axis_y, str(bar + 1), DIM)
            bar += 1
        self.text(cw, self.axis_y, "bar", DIM)

    def legend(self):
        """One line under the bar numbers: what the tick colours in the lanes mean."""
        cw, y = self.fonts.cell_w, self.axis_y + self.fonts.cell_h
        x = self.right - 32 * cw
        for colour, label in ((CYAN, "step"), (MAGENTA, "accent"), (DIM, "deck B")):
            self.draw.rectangle([x, y + 8, x + 2, y + 22], fill=colour)
            self.text(x + cw, y, label, DIM)
            x += (len(label) + 3) * cw

    def save(self, path):
        mono = self.audio.mean(axis=1)
        self.title()
        self.boards()
        self.waveform(mono)
        self.spectrogram(mono)
        self.axis()
        self.lanes()
        self.legend()
        self.img.quantize(colors=PICTURE_COLOURS, dither=Image.Dither.NONE).save(path, optimize=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mp3", default=str(ROOT / "docs" / "demo.mp3"))
    ap.add_argument("--png", default=str(ROOT / "docs" / "signal.png"))
    ap.add_argument("--font")
    ap.add_argument("--bold")
    args = ap.parse_args()

    regular = Path(args.font) if args.font else FONT_DIR / "JetBrainsMono-Regular.ttf"
    bold = Path(args.bold) if args.bold else FONT_DIR / "JetBrainsMono-Bold.ttf"
    fonts = Fonts(regular, bold)

    audio, score = perform()
    Path(args.mp3).parent.mkdir(parents=True, exist_ok=True)
    encode_mp3(audio, args.mp3)
    Figure(audio, score, fonts).save(args.png)
    peak = float(np.abs(audio).max())
    rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float64)))))
    print(f"{len(audio) / SAMPLE_RATE:.1f} s  peak {peak:.3f}  rms {rms:.3f}  {len(score.triggers)} triggers")
    for path in (args.mp3, args.png):
        print(f"wrote {path} ({Path(path).stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
