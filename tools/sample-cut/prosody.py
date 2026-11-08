"""Objective 'tone' metrics (numpy only): how much pitch and loudness move, i.e. lively vs flat reading.

usage: python prosody.py <label=path[@start-end]> ...
pitch_st_std   : std of F0 in semitones over voiced frames (flat robotic ~1.5, lively ad read ~3+)
pitch_range_st : 5-95 percentile F0 span in semitones
energy_db_std  : std of frame loudness on voiced frames (stress / emphasis)
"""
import json
import subprocess
import sys

import numpy as np

SR = 16000


def load(path, ss=None, to=None):
    cmd = ["ffmpeg", "-v", "error"]
    if ss is not None:
        cmd += ["-ss", str(ss), "-to", str(to)]
    cmd += ["-i", path, "-ac", "1", "-ar", str(SR), "-af", "highpass=f=70,lowpass=f=4000", "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, dtype=np.float32)


def f0_track(x, frame=800, hop=160, fmin=75, fmax=500):
    lo, hi = SR // fmax, SR // fmin
    f0, en = [], []
    for i in range(0, len(x) - frame, hop):
        w = x[i:i + frame] * np.hanning(frame)
        e = float(np.sqrt(np.mean(w ** 2)) + 1e-9)
        en.append(20 * np.log10(e))
        spec = np.fft.rfft(w, 2 * frame)
        ac = np.fft.irfft(np.abs(spec) ** 2)[:frame]
        if ac[0] <= 0:
            f0.append(0); continue
        ac = ac / ac[0]
        lag = lo + int(np.argmax(ac[lo:hi]))
        f0.append(SR / lag if ac[lag] > 0.45 else 0)
    f0, en = np.array(f0), np.array(en)
    voiced = (f0 > 0) & (en > en.max() - 35)
    return f0, en, voiced


def metrics(x):
    f0, en, v = f0_track(x)
    st = 12 * np.log2(f0[v] / np.median(f0[v]))
    st = st[np.abs(st) < 12]  # drop octave errors
    return {"voiced_s": round(v.sum() * 160 / SR, 1), "median_f0": round(float(np.median(f0[v])), 1),
            "pitch_st_std": round(float(np.std(st)), 2),
            "pitch_range_st": round(float(np.percentile(st, 95) - np.percentile(st, 5)), 2),
            "energy_db_std": round(float(np.std(en[v])), 2)}


rows = {}
for arg in sys.argv[1:]:
    label, spec = arg.split("=", 1)
    ss = to = None
    if "@" in spec:
        spec, rng = spec.rsplit("@", 1)
        ss, to = (float(t) for t in rng.split("-"))
    rows[label] = metrics(load(spec, ss, to))
    print(label, rows[label])
print(json.dumps(rows, ensure_ascii=False))
