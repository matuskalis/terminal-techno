"""A sounddevice stand-in with no hardware behind it.

Put this directory first on PYTHONPATH and the real techno.py runs unchanged: the
"stream" is a thread that calls the audio callback at the pace a sound card would
and throws the samples away. Nothing here touches PortAudio or a speaker.

Used by tools/capture_tui.py and tools/bench.py.
"""

import threading
import time

import numpy as np

NAME = "null output (no sound card)"
_DEVICES = [{"name": NAME, "max_output_channels": 2}]


def query_devices(device=None, kind=None):
    if device is None and kind is None:
        return list(_DEVICES)
    return _DEVICES[0]


def _terminate():
    pass


def _initialize():
    pass


class OutputStream:
    def __init__(self, samplerate, channels, dtype, blocksize, device, latency, callback):
        self.samplerate = samplerate
        self.channels = channels
        self.blocksize = blocksize
        self.callback = callback
        self.device = 0
        self.latency = blocksize / samplerate
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def close(self):
        self.stop()

    def _pump(self):
        period = self.blocksize / self.samplerate
        deadline = time.perf_counter()
        outdata = np.zeros((self.blocksize, self.channels), np.float32)
        while not self._stop.is_set():
            self.callback(outdata, self.blocksize, None, None)
            deadline += period
            wait = deadline - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
