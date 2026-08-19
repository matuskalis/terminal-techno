#!/usr/bin/env python3
"""Terminal Techno - a live techno sequencer that runs in your terminal."""

import argparse
import curses
import threading
import os
import sys
import time
import traceback

import numpy as np

from engine import Engine, write_wav
from tui import Ui, init_colors

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "techno.log")


def parse_args(argv):
    ap = argparse.ArgumentParser(description="Live techno sequencer in the terminal")
    ap.add_argument("--bpm", type=float, default=130.0)
    ap.add_argument("--samplerate", type=int, default=48000)
    ap.add_argument("--blocksize", type=int, default=1024)
    ap.add_argument("--device", default=None, help="output device name or index")
    ap.add_argument("--stopped", action="store_true", help="start paused instead of playing")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--bounce", metavar="FILE.wav", help="render the default pattern to a wav and exit")
    ap.add_argument("--bars", type=int, default=8, help="bars to render with --bounce")
    return ap.parse_args(argv)


def bounce(args):
    eng = Engine(args.samplerate)
    eng.set_bpm(args.bpm)
    eng.toggle_play()
    total = int(args.bars * 16 * eng.samples_per_step)
    blocks = []
    done = 0
    while done < total:
        n = min(args.blocksize, total - done)
        blocks.append(eng.render(n))
        done += n
    audio = np.concatenate(blocks)
    write_wav(args.bounce, audio, args.samplerate)
    print(f"wrote {args.bounce}  {len(audio) / args.samplerate:.1f}s  peak {np.abs(audio).max():.3f}")


ARROWS = {ord("A"): curses.KEY_UP, ord("B"): curses.KEY_DOWN,
          ord("C"): curses.KEY_RIGHT, ord("D"): curses.KEY_LEFT}


def read_key(scr):
    """getch() plus a fallback parser for terminals that send raw CSI arrow sequences."""
    ch = scr.getch()
    if ch != 27:
        return ch
    nxt = scr.getch()
    if nxt in (ord("["), ord("O")):
        return ARROWS.get(scr.getch(), -1)
    return nxt


class AudioOut:
    """Owns the output stream so the device can change without restarting the app."""

    def __init__(self, eng, samplerate, blocksize, log):
        import sounddevice as sd
        self.sd = sd
        self.eng = eng
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.log = log
        self.stream = None
        self.message = ""
        self.devices = [(i, d["name"]) for i, d in enumerate(sd.query_devices())
                        if d["max_output_channels"] > 0]
        self.index = None
        self.name = "?"
        self.busy = False

    def default_name(self):
        return self.sd.query_devices(kind="output")["name"]

    def open(self, device=None):
        self.close()
        target = self.default_name() if device is None else device
        self.stream = self.sd.OutputStream(samplerate=self.samplerate, channels=2, dtype="float32",
                                           blocksize=self.blocksize, device=target,
                                           latency="low", callback=self._callback)
        self.stream.start()
        self.index = self.stream.device
        self.name = self.sd.query_devices(self.index)["name"]
        self.log.write(f"output: {self.name} latency={self.stream.latency}\n")

    def close(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def _async(self, fn, label):
        """Device work runs off the UI thread: opening a dead device can block for 10s."""
        if self.busy:
            return
        self.busy = True
        self.message = label

        def work():
            try:
                fn()
            except Exception as exc:
                self.message = f"output failed: {exc}"
                self.log.write(f"{label} failed: {exc}\n")
            finally:
                self.busy = False

        threading.Thread(target=work, daemon=True).start()

    def cycle(self):
        self._async(self._cycle, "switching output...")

    def rescan(self):
        self._async(self._rescan, "rescanning devices...")

    def _cycle(self):
        """Switch to the next output device that accepts our format."""
        if not self.devices:
            return
        start = next((n for n, (i, _) in enumerate(self.devices) if i == self.index), -1)
        for offset in range(1, len(self.devices) + 1):
            idx, name = self.devices[(start + offset) % len(self.devices)]
            try:
                self.open(idx)
                self.message = f"out: {name}"
                return
            except Exception as exc:
                self.log.write(f"device {name} rejected: {exc}\n")
        self.message = "no other usable output"

    def _rescan(self):
        """Re-init PortAudio (with no stream open) so devices connected after launch appear."""
        self.close()
        self.sd._terminate()
        self.sd._initialize()
        self.devices = [(i, d["name"]) for i, d in enumerate(self.sd.query_devices())
                        if d["max_output_channels"] > 0]
        self.open()
        self.message = f"out: {self.name}"

    def follow_default(self):
        """Reopen on the system default when it changes in Sound settings."""
        if self.busy:
            return
        try:
            wanted = self.default_name()
        except Exception:
            return
        if wanted != self.name:
            self._async(lambda: self.open(), f"following {wanted}...")

    def _callback(self, outdata, frames, time_info, status):
        # curses swallows stderr, so callback trouble goes to the log file instead
        try:
            outdata[:] = self.eng.render(frames)
            if status:
                self.log.write(f"status: {status}\n")
        except Exception:
            self.log.write(traceback.format_exc())
            raise


def run_tui(stdscr, eng, audio, log):
    curses.curs_set(0)
    init_colors()
    stdscr.nodelay(True)
    stdscr.keypad(True)
    ui = Ui(eng, audio)
    last_check = time.time()
    try:
        while True:
            ui.draw(stdscr)
            ch = read_key(stdscr)
            while ch != -1:
                if not ui.handle(ch):
                    return
                ch = read_key(stdscr)
            if time.time() - last_check > 2.0:
                audio.follow_default()
                last_check = time.time()
            time.sleep(0.03)  # time.sleep releases the GIL; curses.napms does not, which starves audio
    finally:
        audio.close()


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    if args.bounce:
        bounce(args)
        return 0

    import sounddevice as sd

    if args.list_devices:
        print(sd.query_devices())
        return 0

    eng = Engine(args.samplerate)
    eng.set_bpm(args.bpm)
    if not args.stopped:
        eng.toggle_play()

    log = open(LOG_PATH, "w", buffering=1)
    audio = AudioOut(eng, args.samplerate, args.blocksize, log)
    audio.open(args.device)
    try:
        curses.wrapper(run_tui, eng, audio, log)
    except Exception:
        log.write(traceback.format_exc())
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
