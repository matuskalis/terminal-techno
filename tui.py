"""Curses front end: step grid, meters, oscilloscope, spectrum."""

import curses
import os
import time

import numpy as np

from engine import STEPS, TRACKS, note_name, write_wav

BLOCKS = " ▁▂▃▄▅▆▇█"
SHIFT_DIGITS = "!@#$%^&*"  # shift+1..8 arms a board directly

HELP = [
    "space play/stop   ←→ step   ↑↓ track   1-6 track   x toggle   a accent   s slide   -/= note",
    "[ ] arm prev/next board   shift+1..8 arm board N   board lands on the next bar",
    "t crossfade on/off   9 0 fader toward A / B (fader at B commits)   z/Z swing   ,/. bpm",
    "r rand (R all)   c clear (C all)   m mute   v/V volume   f/F filter   d/D delay",
    "w record wav   o next output device   O rescan devices (bluetooth)   u ui sound   q quit",
]


C_FRAME = C_ACCENT = C_PLAY = C_WARN = C_TEXT = C_DIM = C_HOT = 0


def init_colors():
    """Called after initscr(); fills the module-level attribute constants."""
    global C_FRAME, C_ACCENT, C_PLAY, C_WARN, C_TEXT, C_DIM, C_HOT
    curses.start_color()
    curses.use_default_colors()
    palette = {
        1: curses.COLOR_CYAN,
        2: curses.COLOR_MAGENTA,
        3: curses.COLOR_GREEN,
        4: curses.COLOR_YELLOW,
        5: curses.COLOR_WHITE,
        6: curses.COLOR_BLUE,
        7: curses.COLOR_RED,
    }
    for idx, fg in palette.items():
        curses.init_pair(idx, fg, -1)
    (C_FRAME, C_ACCENT, C_PLAY, C_WARN,
     C_TEXT, C_DIM, C_HOT) = (curses.color_pair(i) for i in range(1, 8))


class Ui:
    def __init__(self, eng, audio=None):
        self.eng = eng
        self.audio = audio
        self.cell = 2
        self.track = 0
        self.step = 0
        self.spectrum = np.zeros(48)
        self.scope_gain = 1.0
        self.status = "ready"

    # --- input ----------------------------------------------------------
    def handle(self, ch):
        eng = self.eng
        if ch == ord("q"):
            return False
        if ch == ord(" "):
            eng.toggle_play()
            self.status = "playing" if eng.playing else "stopped"
        elif ch in (curses.KEY_RIGHT, ord("l")):
            self.step = (self.step + 1) % STEPS
        elif ch in (curses.KEY_LEFT, ord("h")):
            self.step = (self.step - 1) % STEPS
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.track = (self.track + 1) % len(TRACKS)
        elif ch in (curses.KEY_UP, ord("k")):
            self.track = (self.track - 1) % len(TRACKS)
        elif ch in (ord("x"), ord("\n"), curses.KEY_ENTER):
            eng.toggle_step(self.track, self.step)
        elif ch == ord("a"):
            eng.toggle_accent(self.track, self.step)
        elif ch == ord("s"):
            eng.toggle_slide(self.track, self.step)
        elif ch in (ord("="), ord("+")):
            eng.shift_note(self.track, self.step, 1)
        elif ch in (ord("-"), ord("_")):
            eng.shift_note(self.track, self.step, -1)
        elif ch == ord(","):
            eng.set_bpm(eng.bpm - 1)
        elif ch == ord("."):
            eng.set_bpm(eng.bpm + 1)
        elif ch == ord("<"):
            eng.set_bpm(eng.bpm - 5)
        elif ch == ord(">"):
            eng.set_bpm(eng.bpm + 5)
        elif ch in (ord("["), ord("]")):
            base = eng.pending if eng.pending is not None else (eng.deck_b if eng.crossfading else eng.board)
            eng.arm(base + (1 if ch == ord("]") else -1))
            self._board_status()
        elif 0 <= ch < 256 and chr(ch) in SHIFT_DIGITS:
            eng.arm(SHIFT_DIGITS.index(chr(ch)))
            self._board_status()
        elif ch == ord("t"):
            if eng.crossfading:
                eng.cancel_xfade()
                self.status = "crossfade off"
            else:
                eng.start_xfade()
                self.status = f"crossfade to {eng.boards[eng.deck_b].name}"
        elif ch == ord("9"):
            eng.nudge_xfade(-0.05)
        elif ch == ord("0"):
            eng.nudge_xfade(0.05)
        elif ord("1") <= ch <= ord("6"):
            self.track = ch - ord("1")
        elif ch == ord("m"):
            eng.mute[self.track] = not eng.mute[self.track]
        elif ch == ord("r"):
            eng.randomize_track(self.track)
            self.status = f"randomized {TRACKS[self.track].name}"
        elif ch == ord("R"):
            for i in range(len(TRACKS)):
                eng.randomize_track(i)
            self.status = "randomized all"
        elif ch == ord("c"):
            eng.clear_track(self.track)
        elif ch == ord("C"):
            for i in range(len(TRACKS)):
                eng.clear_track(i)
            self.status = "cleared"
        elif ch == ord("f"):
            eng.cutoff_scale = max(0.15, eng.cutoff_scale - 0.05)
        elif ch == ord("F"):
            eng.cutoff_scale = min(2.5, eng.cutoff_scale + 0.05)
        elif ch == ord("d"):
            eng.delay_mix = max(0.0, eng.delay_mix - 0.05)
        elif ch == ord("D"):
            eng.delay_mix = min(0.9, eng.delay_mix + 0.05)
        elif ch in (ord("z"), ord("Z")):
            eng.set_swing(eng.swing + (0.02 if ch == ord("Z") else -0.02))
            self.status = f"swing {eng.swing * 100:.0f}%"
        elif ch == ord("w"):
            self._toggle_record()
        elif ch == ord("o"):
            if self.audio is not None:
                self.audio.cycle()
                self.status = self.audio.message
        elif ch == ord("O"):
            if self.audio is not None:
                self.audio.rescan()
                self.status = self.audio.message
        elif ch == ord("u"):
            eng.ui_sound = not eng.ui_sound
            self.status = f"ui sound {'on' if eng.ui_sound else 'off'}"
        elif ch == ord("v"):
            eng.vol[self.track] = max(0.0, eng.vol[self.track] - 0.05)
        elif ch == ord("V"):
            eng.vol[self.track] = min(1.5, eng.vol[self.track] + 0.05)
        eng.click()
        return True

    def _toggle_record(self):
        eng = self.eng
        if eng.recording is None:
            eng.start_recording()
            self.status = "recording"
            return
        audio = eng.stop_recording()
        if audio is None:
            self.status = "nothing recorded"
            return
        name = time.strftime("rec-%Y%m%d-%H%M%S.wav")
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        write_wav(path, audio, eng.sr)
        self.status = f"saved {name} ({len(audio) / eng.sr:.1f}s)"

    def _board_status(self):
        eng = self.eng
        if eng.pending is None:
            self.status = f"board {eng.board + 1} {eng.boards[eng.board].name}"
        else:
            self.status = f"next: {eng.pending + 1} {eng.boards[eng.pending].name}"

    # --- drawing --------------------------------------------------------
    def draw(self, scr):
        scr.erase()
        maxy, maxx = scr.getmaxyx()
        if maxy < 24 or maxx < 60:
            self._put(scr, 0, 0, "terminal too small: need 60x24", C_WARN)
            scr.refresh()
            return
        eng = self.eng
        self.cell = 3 if maxx >= 92 else 2
        grid_x = 8
        row = 0
        self._title(scr, row, maxx)
        row += 1
        self._boards(scr, row, maxx)
        row += 1
        self._ruler(scr, row, grid_x)
        row += 1
        for i, spec in enumerate(TRACKS):
            self._track_row(scr, row + i, grid_x, i, maxx)
        row += len(TRACKS)
        self._info(scr, row, maxx)
        self._status_line(scr, row + 1, maxx)
        row += 3

        left = maxy - row - len(HELP) - 1
        scope_h = max(4, min(12, left // 2))
        spec_h = max(3, left - scope_h - 1)
        width = min(maxx - 2, 100)
        self._scope(scr, row, width, scope_h)
        row += scope_h + 1
        self._spectrum(scr, row, width, spec_h)
        row += spec_h
        for i, line in enumerate(HELP):
            if row + i < maxy:
                self._put(scr, row + i, 1, line[:maxx - 2], C_DIM)
        scr.refresh()

    def _put(self, scr, y, x, text, attr=0):
        try:
            scr.addstr(y, x, text, attr)
        except curses.error:
            pass

    def _title(self, scr, y, maxx):
        eng = self.eng
        state = "▶ PLAY" if eng.playing else "■ STOP"
        head = (f"  TERMINAL TECHNO  {eng.bpm:5.1f} BPM   BOARD {eng.board + 1} {eng.boards[eng.board].name}"
                f"   {state}   BAR {eng.bar:03d}  ")
        bar = head + "─" * max(0, maxx - len(head) - 1)
        self._put(scr, y, 0, bar[:maxx - 1], C_FRAME | curses.A_BOLD)
        self._put(scr, y, 2, "TERMINAL TECHNO", C_ACCENT | curses.A_BOLD)
        if eng.playing:
            self._put(scr, y, 2 + head[2:].index(state), state, C_PLAY | curses.A_BOLD)

    def _boards(self, scr, y, maxx):
        """Row of eight board cells: [n] live, (n) armed for the next bar, <n> on deck B."""
        eng = self.eng
        self._put(scr, y, 1, "BOARD", C_DIM)
        x = 7
        for i, board in enumerate(eng.boards):
            empty = not board.pattern.on.any()
            if i == eng.board:
                cell, attr = f"[{i + 1}]", C_PLAY | curses.A_BOLD
            elif i == eng.pending:
                cell, attr = f"({i + 1})", C_WARN | curses.A_BOLD
            elif i == eng.deck_b:
                cell, attr = f"<{i + 1}>", C_ACCENT | curses.A_BOLD
            else:
                cell, attr = f" {i + 1} ", C_DIM if empty else C_FRAME
            self._put(scr, y, x, cell, attr)
            x += 4
        x += 2
        if eng.crossfading:
            width = 12
            filled = int(round(eng.xfade * width))
            self._put(scr, y, x, "A", C_PLAY | curses.A_BOLD)
            self._put(scr, y, x + 2, "█" * filled + "░" * (width - filled), C_ACCENT)
            self._put(scr, y, x + 3 + width, f"B {eng.boards[eng.deck_b].name} {eng.xfade * 100:3.0f}%",
                      C_ACCENT | curses.A_BOLD)
        elif eng.pending is not None:
            steps_left = (STEPS - eng.step) % STEPS or STEPS
            self._put(scr, y, x, f"NEXT {eng.pending + 1} {eng.boards[eng.pending].name} in {steps_left:2d}",
                      C_WARN | curses.A_BOLD)

    def _ruler(self, scr, y, x0):
        for s in range(STEPS):
            mark = str(s // 4 + 1) if s % 4 == 0 else "·"
            attr = C_FRAME if s % 4 == 0 else C_DIM
            if s == self.eng.step and self.eng.playing:
                attr = C_PLAY | curses.A_BOLD
            self._put(scr, y, x0 + s * self.cell, mark, attr)

    def _track_row(self, scr, y, x0, i, maxx):
        eng = self.eng
        p = eng.pattern
        spec = TRACKS[i]
        label_attr = C_TEXT | curses.A_BOLD if i == self.track else C_DIM
        if eng.mute[i]:
            label_attr = C_WARN
        self._put(scr, y, 1, f"{i + 1} {spec.name}{'M' if eng.mute[i] else ' '}", label_attr)
        for s in range(STEPS):
            on = p.on[i, s]
            acc = p.acc[i, s]
            if not on:
                glyph, attr = "·", C_DIM
            elif acc:
                glyph, attr = "◆", C_ACCENT | curses.A_BOLD
            else:
                glyph, attr = "■", C_FRAME
            if eng.mute[i]:
                attr = C_DIM
            if s == eng.step and eng.playing:
                attr = attr | curses.A_BOLD if on else C_PLAY
                if on:
                    attr = C_PLAY | curses.A_BOLD
            if i == self.track and s == self.step:
                attr = attr | curses.A_REVERSE
            self._put(scr, y, x0 + s * self.cell, glyph, attr)
            if s < STEPS - 1:
                link = "~" if p.slide[i, s] and spec.pitched else " "
                self._put(scr, y, x0 + s * self.cell + 1, link * (self.cell - 1),
                          C_HOT if link == "~" else 0)
        meter_x = x0 + STEPS * self.cell + 2
        span = max(8, min(20, maxx - meter_x - 8))
        if meter_x + span + 6 < maxx:
            level = float(np.clip(eng.levels[i] * 1.6, 0, 1))
            filled = int(level * span)
            bar = "█" * filled + "·" * (span - filled)
            color = C_HOT if level > 0.85 else C_PLAY
            self._put(scr, y, meter_x, bar, color)
            self._put(scr, y, meter_x + span + 1, f"{eng.vol[i]:.2f}", C_DIM)

    def _info(self, scr, y, maxx):
        eng = self.eng
        p = eng.pattern
        spec = TRACKS[self.track]
        bits = [f"TRK {spec.name}", f"STEP {self.step + 1:02d}"]
        if spec.pitched:
            bits.append(f"NOTE {note_name(p.note[self.track, self.step], spec.octave)}")
        bits.append("ACC" if p.acc[self.track, self.step] else "   ")
        bits.append("SLIDE" if p.slide[self.track, self.step] else "     ")
        bits.append(f"VOL {eng.vol[self.track]:.2f}")
        self._put(scr, y, 1, "  ".join(bits)[:maxx - 2], C_TEXT)

    def _status_line(self, scr, y, maxx):
        eng = self.eng
        bits = [f"SWING {eng.swing * 100:2.0f}%", f"FILT {eng.cutoff_scale:.2f}", f"DLY {eng.delay_mix:.2f}",
                f"UI {'on' if eng.ui_sound else 'off'}"]
        if self.audio is not None:
            bits.append(f"OUT {self.audio.name}")
        self._put(scr, y, 1, "  ".join(bits)[:maxx - 2], C_DIM)
        tail_x = 1 + len("  ".join(bits)) + 2
        if eng.recording is not None and tail_x + 12 < maxx:
            self._put(scr, y, tail_x, f"● REC {eng.record_seconds:5.1f}s", C_HOT | curses.A_BOLD)
            tail_x += 14
        if tail_x + len(self.status) < maxx:
            self._put(scr, y, tail_x, self.status, C_WARN)

    def _scope(self, scr, y, width, height):
        buf = self.eng.scope[-1024:]
        peak = max(float(np.abs(buf).max()), 0.05)
        self.scope_gain += (0.92 / peak - self.scope_gain) * 0.15
        self.scope_gain = float(np.clip(self.scope_gain, 0.5, 8.0))
        cols = np.array_split(buf * self.scope_gain, width)
        center = (height - 1) / 2.0
        for x, col in enumerate(cols):
            top = int(round(center - np.clip(col.max(), -1, 1) * center))
            bot = int(round(center - np.clip(col.min(), -1, 1) * center))
            for yy in range(min(top, bot), max(top, bot) + 1):
                if 0 <= yy < height:
                    attr = C_PLAY if abs(yy - center) < center * 0.55 else C_FRAME
                    self._put(scr, y + yy, 1 + x, "█", attr)

    def _spectrum(self, scr, y, width, height):
        buf = self.eng.scope
        mag = np.abs(np.fft.rfft(buf * np.hanning(len(buf))))
        freqs = np.fft.rfftfreq(len(buf), 1.0 / self.eng.sr)
        centers = np.geomspace(45.0, 15000.0, width)
        bars = np.interp(centers, freqs, mag)
        bars *= np.clip((centers / 150.0) ** 0.45, 0.25, 6.0)  # tilt so hats stay visible next to the kick
        db = 20.0 * np.log10(bars / (len(buf) / 8.0) + 1e-9)
        bars = (db + 39.0) / 33.0
        if len(self.spectrum) != width:
            self.spectrum = bars
        self.spectrum = np.maximum(bars, self.spectrum * 0.80)
        for x, v in enumerate(self.spectrum):
            cells = v * height
            for r in range(height):
                yy = y + height - 1 - r
                if cells >= r + 1:
                    glyph = "█"
                elif cells > r:
                    glyph = BLOCKS[int((cells - r) * 8)]
                else:
                    break
                attr = C_ACCENT if r > height * 0.7 else (C_FRAME if r > height * 0.35 else C_DIM)
                self._put(scr, yy, 1 + x, glyph, attr)
