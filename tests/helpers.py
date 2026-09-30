"""Small helpers shared by the tests."""

import numpy as np

from engine import Pattern

SR = 48000
KCK, CLP, HAT, OHT, BAS, LED = range(6)  # track indices, in engine.TRACKS order


def seconds(x, start, end, sr=SR):
    return x[int(start * sr) : int(end * sr)]


def rms(x):
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


def dominant_hz(x, low, high, sr=SR):
    """Frequency of the strongest spectral peak between low and high Hz (Hann window, zero padded)."""
    padded = len(x) * 8
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x)), padded))
    freqs = np.fft.rfftfreq(padded, 1 / sr)
    band = (freqs >= low) & (freqs <= high)
    return float(freqs[band][np.argmax(spectrum[band])])


def spectral_centroid(x, sr=SR):
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1 / sr)
    return float((spectrum * freqs).sum() / spectrum.sum())


def power_above(x, hz, sr=SR):
    """Share of the signal's spectral power that lies above hz."""
    power = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / sr)
    return float(power[freqs > hz].sum() / power.sum())


def zero_crossings_per_second(x, sr=SR):
    rising = (x[:-1] < 0) & (x[1:] >= 0)
    return float(rising.sum() / (len(x) / sr))


def undo_master(out, gain=0.9):
    """Invert the master bus (tanh of the sum times the master gain) to get the mix before it."""
    return np.arctanh(out) / gain


def render_in_blocks(source, total, block):
    """Call source.render(n) in pieces of `block` frames (last piece shorter) and join the results."""
    pieces = []
    done = 0
    while done < total:
        n = min(block, total - done)
        pieces.append(source.render(n))
        done += n
    return np.concatenate(pieces)


class TriggerLog:
    """Stands in for a voice: silent, but remembers the sample each trigger landed on."""

    def __init__(self):
        self.samples_rendered = 0
        self.triggers = []

    def trigger(self, vel=1.0, note=0, accent=False, slide=False):
        self.triggers.append(self.samples_rendered)

    def render(self, n):
        self.samples_rendered += n
        return np.zeros(n, np.float32)


def pattern_with(track, steps, note=0, accent=False):
    """A pattern with one track switched on at the given steps."""
    p = Pattern()
    for step in steps:
        p.on[track, step] = True
        p.acc[track, step] = accent
        p.note[track, step] = note
    return p
