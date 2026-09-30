#!/usr/bin/env python3
"""How much of a CPU core the engine needs to stay ahead of the sound card.

Offline, the default: render audio through Engine.render() in 1024-frame blocks, the size the live
callback asks for, and time each call with the thread's CPU clock, which does not count time the OS
spent on other processes. CPU share is CPU seconds per second of audio; its inverse is the realtime
factor. The budget for one block is 1024 / 48000 = 21.3 ms.

    python tools/bench.py             engine only, offline, no pty and no audio device
    python tools/bench.py --profile   where the engine's time goes, per voice
    python tools/bench.py --app       the whole app (engine, curses, FFTs) in a pty with tools/null_audio

--app needs pyte and reads CPU time from ps, which macOS reports to 10 ms and Linux to 1 s.
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import scipy

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import TRACKS, Engine

SAMPLE_RATE = 48000
BLOCK = 1024
BUDGET_MS = 1000.0 * BLOCK / SAMPLE_RATE
WARMUP_BLOCKS = 20

SCENARIOS = [
    ("board 1 simple", 0, False),
    ("board 2 peak", 1, False),
    ("board 2 peak, crossfading to 3", 1, True),
]


def make_engine(board, crossfade):
    np.random.seed(1)
    eng = Engine(SAMPLE_RATE)
    eng.ui_sound = False
    eng.arm(board)  # stopped, so it lands at once
    if crossfade:
        eng.start_xfade()
        eng.xfade = 0.5  # both decks audible
    eng.toggle_play()
    return eng


def block_times(eng, seconds):
    """CPU seconds per render call, after a short warm-up."""
    for _ in range(WARMUP_BLOCKS):
        eng.render(BLOCK)
    times = np.empty(int(seconds * SAMPLE_RATE / BLOCK))
    for i in range(len(times)):
        start = time.thread_time()
        eng.render(BLOCK)
        times[i] = time.thread_time() - start
    return times


def offline(seconds, repeats):
    print(f"engine only, {seconds:g} s of audio per run, best of {repeats}, blocks of {BLOCK} at {SAMPLE_RATE} Hz")
    print(f"{'scenario':34} {'realtime':>9} {'CPU share':>10} {'block median':>13} {'p99':>8} {'max':>8}")
    for label, board, crossfade in SCENARIOS:
        runs = [block_times(make_engine(board, crossfade), seconds) for _ in range(repeats)]
        best = min(runs, key=lambda t: t.sum())
        share = best.sum() / (len(best) * BLOCK / SAMPLE_RATE)
        ms = best * 1000.0
        print(
            f"{label:34} {1 / share:8.0f}x {100 * share:9.2f}% "
            f"{np.median(ms):10.2f} ms {np.percentile(ms, 99):5.2f} ms {ms.max():5.2f} ms"
        )
    print(f"budget per block: {BUDGET_MS:.1f} ms")


def profile(seconds):
    eng = make_engine(1, False)
    spent = {}

    def timed(obj, name, label):
        function = getattr(obj, name)

        def wrapper(*args):
            start = time.thread_time()
            result = function(*args)
            spent[label] = spent.get(label, 0.0) + time.thread_time() - start
            return result

        setattr(obj, name, wrapper)

    for spec, voice in zip(TRACKS, eng.voices, strict=True):
        timed(voice, "render", spec.name)
    timed(eng.delay, "process", "delay line")
    for _ in range(WARMUP_BLOCKS):
        eng.render(BLOCK)
    spent.clear()
    blocks = int(seconds * SAMPLE_RATE / BLOCK)
    start = time.thread_time()
    for _ in range(blocks):
        eng.render(BLOCK)
    total = time.thread_time() - start
    spent["mixing and the rest"] = total - sum(spent.values())
    print(f"board 2 peak, {seconds:g} s of audio: {100 * total / seconds:.2f}% of one core, split by where it goes")
    for label, cpu in sorted(spent.items(), key=lambda item: -item[1]):
        print(f"  {label:22} {100 * cpu / total:5.1f}%")


def app(seconds):
    from ptyapp import Session, cpu_seconds

    print(f"whole app in a pty, null audio device, {seconds:g} s measured per state")
    session = Session(96, 32)
    try:
        session.wait_for(lambda lines: "BAR 002" in lines[0], "bar 2")

        def measure(label):
            start_cpu, start_wall = cpu_seconds(session.proc.pid), time.perf_counter()
            session.pump(seconds)
            cpu, wall = cpu_seconds(session.proc.pid) - start_cpu, time.perf_counter() - start_wall
            print(f"  {label:34} {100 * cpu / wall:5.1f}% of one core")

        measure("board 1 simple")
        session.send(b"]")
        session.wait_for(lambda lines: "[2]" in lines[1], "board 2")
        measure("board 2 peak")
        session.send(b"]t")
        for _ in range(10):
            session.send(b"0")
            session.pump(0.05)
        measure("board 2 peak, crossfading to 3")
    finally:
        session.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--app", action="store_true")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--repeats", type=int, default=5)
    args = ap.parse_args()
    if args.app:
        sys.path.insert(0, str(ROOT / "tools"))
        app(args.seconds)
    elif args.profile:
        profile(args.seconds)
    else:
        offline(args.seconds, args.repeats)
    print(f"python {sys.version.split()[0]}, numpy {np.__version__}, scipy {scipy.__version__}")


if __name__ == "__main__":
    main()
