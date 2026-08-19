"""Voices and effects. Everything is synthesized sample-by-sample, no assets."""

import numpy as np
from scipy.signal import lfilter

TWO_PI = 2.0 * np.pi
SUBBLOCK = 64  # samples between filter coefficient updates


def _biquad(kind, fc, q, sr):
    fc = float(np.clip(fc, 20.0, sr * 0.45))
    q = max(q, 0.3)
    w0 = TWO_PI * fc / sr
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2 * q)
    if kind == "lp":
        b = np.array([(1 - cw) / 2, 1 - cw, (1 - cw) / 2])
    elif kind == "hp":
        b = np.array([(1 + cw) / 2, -(1 + cw), (1 + cw) / 2])
    else:  # bp
        b = np.array([alpha, 0.0, -alpha])
    a = np.array([1 + alpha, -2 * cw, 1 - alpha])
    return b / a[0], a / a[0]


def _filter_swept(x, cutoff, q, sr, zi):
    """Lowpass with a cutoff that moves; coefficients refresh every SUBBLOCK samples."""
    out = np.empty_like(x)
    for i in range(0, len(x), SUBBLOCK):
        j = min(i + SUBBLOCK, len(x))
        b, a = _biquad("lp", cutoff[i], q, sr)
        out[i:j], zi = lfilter(b, a, x[i:j], zi=zi)
    return out, zi


class Voice:
    def __init__(self, sr):
        self.sr = sr
        self.t = sr * 100
        self.vel = 1.0

    def dead(self, tail=2.0):
        return self.t > self.sr * tail

    def trigger(self, vel=1.0, note=0, accent=False, slide=False):
        self.t = 0
        self.vel = vel


class Kick(Voice):
    def __init__(self, sr):
        super().__init__(sr)
        self.phase = 0.0

    def trigger(self, vel=1.0, note=0, accent=False, slide=False):
        super().trigger(vel)
        self.phase = 0.0

    def render(self, n):
        if self.dead(1.0):
            self.t += n
            return np.zeros(n, np.float32)
        t = (np.arange(n) + self.t) / self.sr
        freq = 48.0 + 95.0 * np.exp(-t / 0.032)
        ph = self.phase + TWO_PI * np.cumsum(freq) / self.sr
        self.phase = float(ph[-1] % TWO_PI)
        body = np.tanh(2.3 * np.sin(ph)) * np.exp(-t / 0.17) * (1 - np.exp(-t / 0.0008))
        click = np.exp(-t / 0.003) * np.random.uniform(-1, 1, n) * 0.35
        self.t += n
        return ((body + click) * self.vel * 0.95).astype(np.float32)


class Hat(Voice):
    def __init__(self, sr, open_hat=False):
        super().__init__(sr)
        self.decay = 0.30 if open_hat else 0.042
        self.gain = 0.28 if open_hat else 0.33
        self.b, self.a = _biquad("hp", 7200.0, 0.9, sr)
        self.zi = np.zeros(2)

    def render(self, n):
        if self.dead(1.0):
            self.t += n
            return np.zeros(n, np.float32)
        t = (np.arange(n) + self.t) / self.sr
        env = np.exp(-t / self.decay)
        y, self.zi = lfilter(self.b, self.a, np.random.uniform(-1, 1, n), zi=self.zi)
        self.t += n
        return (y * env * self.vel * self.gain).astype(np.float32)


class Clap(Voice):
    def __init__(self, sr):
        super().__init__(sr)
        self.b, self.a = _biquad("bp", 1500.0, 1.1, sr)
        self.zi = np.zeros(2)

    def render(self, n):
        if self.dead(1.0):
            self.t += n
            return np.zeros(n, np.float32)
        t = (np.arange(n) + self.t) / self.sr
        bursts = np.exp(-(t % 0.011) / 0.0028)
        env = np.where(t < 0.033, bursts, np.exp(-(t - 0.033) / 0.115) * 0.85)
        y, self.zi = lfilter(self.b, self.a, np.random.uniform(-1, 1, n), zi=self.zi)
        self.t += n
        return (y * env * self.vel * 0.5).astype(np.float32)


class Bass(Voice):
    """Sub + saw through a swept resonant lowpass."""

    base_hz = 55.0

    def __init__(self, sr):
        super().__init__(sr)
        self.phase = 0.0
        self.freq = self.base_hz
        self.target = self.base_hz
        self.accent = False
        self.zi = np.zeros(2)

    def trigger(self, vel=1.0, note=0, accent=False, slide=False):
        self.target = self.base_hz * 2 ** (note / 12.0)
        if not slide or self.dead(0.5):
            self.freq = self.target
        super().trigger(vel)
        self.accent = accent

    def render(self, n):
        if self.dead(1.0):
            self.t += n
            return np.zeros(n, np.float32)
        glide = np.exp(-np.arange(1, n + 1) / (0.035 * self.sr))
        freq = self.target + (self.freq - self.target) * glide
        self.freq = float(freq[-1])
        ph = self.phase + np.cumsum(freq) / self.sr
        self.phase = float(ph[-1] % 1.0)
        t = (np.arange(n) + self.t) / self.sr
        saw = 2.0 * (ph % 1.0) - 1.0
        sub = np.sin(TWO_PI * ph * 0.5)
        amp = np.exp(-t / 0.24) * (1 - np.exp(-t / 0.002))
        cutoff = 130.0 + (2200.0 if self.accent else 1100.0) * np.exp(-t / 0.10)
        x = 0.65 * saw + 0.75 * sub
        y, self.zi = _filter_swept(x, cutoff, 1.6, self.sr, self.zi)
        self.t += n
        return (np.tanh(1.5 * y * amp) * self.vel * 0.55).astype(np.float32)


class Acid(Voice):
    """303-style lead: saw, high-resonance sweep, slide, drive."""

    base_hz = 110.0

    def __init__(self, sr):
        super().__init__(sr)
        self.phase = 0.0
        self.freq = self.base_hz
        self.target = self.base_hz
        self.accent = False
        self.zi = np.zeros(2)
        self.cutoff_scale = 1.0
        self.resonance = 7.0

    def trigger(self, vel=1.0, note=0, accent=False, slide=False):
        self.target = self.base_hz * 2 ** (note / 12.0)
        if not slide or self.dead(0.5):
            self.freq = self.target
        super().trigger(vel)
        self.accent = accent

    def render(self, n):
        if self.dead(1.5):
            self.t += n
            return np.zeros(n, np.float32)
        glide = np.exp(-np.arange(1, n + 1) / (0.045 * self.sr))
        freq = self.target + (self.freq - self.target) * glide
        self.freq = float(freq[-1])
        ph = self.phase + np.cumsum(freq) / self.sr
        self.phase = float(ph[-1] % 1.0)
        t = (np.arange(n) + self.t) / self.sr
        saw = 2.0 * (ph % 1.0) - 1.0
        square = np.where((ph % 1.0) < 0.5, 1.0, -1.0)
        amp = np.exp(-t / 0.30) * (1 - np.exp(-t / 0.003))
        decay = 0.16 if self.accent else 0.26
        peak = 3400.0 if self.accent else 1900.0
        cutoff = (250.0 + peak * np.exp(-t / decay)) * self.cutoff_scale
        res = self.resonance + (3.0 if self.accent else 0.0)
        x = 0.8 * saw + 0.2 * square
        y, self.zi = _filter_swept(x, cutoff, res, self.sr, self.zi)
        self.t += n
        return (np.tanh(2.6 * y * amp) * self.vel * 0.32).astype(np.float32)


class Blip(Voice):
    """UI feedback tone: a short sine that can glide from one pitch to another."""

    def __init__(self, sr):
        super().__init__(sr)
        self.phase = 0.0
        self.f0 = 1800.0
        self.f1 = 1800.0
        self.dur = 0.012
        self.gain = 0.0

    def ping(self, f0, f1, dur, gain):
        self.f0, self.f1, self.dur, self.gain = f0, f1, dur, gain
        self.t = 0
        self.phase = 0.0

    def render(self, n):
        if self.t > self.dur * self.sr * 4:
            self.t += n
            return np.zeros(n, np.float32)
        t = (np.arange(n) + self.t) / self.sr
        frac = np.clip(t / self.dur, 0.0, 1.0)
        freq = self.f0 + (self.f1 - self.f0) * frac
        ph = self.phase + TWO_PI * np.cumsum(freq) / self.sr
        self.phase = float(ph[-1] % TWO_PI)
        env = np.exp(-t / (self.dur * 0.55)) * (1 - np.exp(-t / 0.0006))
        self.t += n
        return (np.sin(ph) * env * self.gain).astype(np.float32)


class PingPongDelay:
    def __init__(self, sr, max_seconds=2.0):
        self.buf = np.zeros((int(sr * max_seconds), 2), np.float32)
        self.idx = 0

    def process(self, send, delay_samples, feedback):
        n = len(send)
        size = len(self.buf)
        delay_samples = int(np.clip(delay_samples, n + 1, size - 1))
        read = (self.idx - delay_samples + np.arange(n)) % size
        wet = self.buf[read].copy()
        write = (self.idx + np.arange(n)) % size
        self.buf[write] = send + wet[:, ::-1] * feedback
        self.idx = (self.idx + n) % size
        return wet
