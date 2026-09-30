"""Run the real techno.py in a pseudo-terminal with no sound card, and read its screen with pyte.

tools/null_audio stands in for sounddevice, so no audio device is opened and nothing is played.
Whatever the app writes to the terminal goes through the pyte terminal emulator; frames are taken
only when the output has been quiet for a few milliseconds, so a frame is never half a redraw.

Used by tools/capture_tui.py and tools/bench.py. Needs: pip install pyte
"""

import fcntl
import os
import pty
import select
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

import pyte

from termshot import snapshot

ROOT = Path(__file__).resolve().parent.parent
NULL_AUDIO = ROOT / "tools" / "null_audio"
QUIET_SECONDS = 0.004


def cpu_seconds(pid):
    """CPU time the process has used so far, from ps (format [H:]MM:SS.cc)."""
    out = subprocess.run(["ps", "-o", "cputime=", "-p", str(pid)], capture_output=True, text=True, check=True)
    total = 0.0
    for part in out.stdout.strip().split(":"):
        total = total * 60 + float(part)
    return total


class Session:
    def __init__(self, cols=96, rows=32, args=()):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        env = dict(
            os.environ,
            TERM="xterm-256color",
            LANG="en_US.UTF-8" if sys.platform == "darwin" else "C.UTF-8",
            PYTHONPATH=str(NULL_AUDIO),
        )
        self.proc = subprocess.Popen(
            [sys.executable, "techno.py", *args],
            cwd=ROOT,
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
        )
        os.close(slave)
        self.master = master
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        self.started = time.perf_counter()
        self.frames = []  # (seconds since start, cells)

    def lines(self):
        return self.screen.display

    def send(self, keys):
        os.write(self.master, keys)

    def pump(self, seconds, sample_every=None):
        """Read output for `seconds`. With sample_every, keep a frame that often while the screen is quiet."""
        end = time.perf_counter() + seconds
        next_sample = time.perf_counter()
        while time.perf_counter() < end:
            ready, _, _ = select.select([self.master], [], [], QUIET_SECONDS)
            if ready:
                try:
                    self.stream.feed(os.read(self.master, 65536))
                except OSError:
                    return
                continue
            now = time.perf_counter()
            if sample_every and now >= next_sample:
                self.frames.append((now - self.started, snapshot(self.screen)))
                next_sample = now + sample_every

    def wait_for(self, predicate, what, timeout=90.0, sample_every=None):
        end = time.perf_counter() + timeout
        while time.perf_counter() < end:
            self.pump(0.05, sample_every)
            if predicate(self.lines()):
                return
        raise TimeoutError(f"never saw {what}; screen was:\n" + "\n".join(self.lines()))

    def close(self):
        """Ask the app to quit. Keep reading meanwhile: a full pty buffer would block its writes."""
        if self.proc.poll() is None:
            self.send(b"q")
            deadline = time.perf_counter() + 5
            while self.proc.poll() is None and time.perf_counter() < deadline:
                self.pump(0.05)
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        os.close(self.master)
