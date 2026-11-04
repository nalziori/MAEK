"""Classical rust segmenter (numpy only): HSV colour threshold + morphology.

A deliberately simple baseline for function (1); a learned YOLO-seg model replaces it.
"""

from __future__ import annotations

import numpy as np


def rgb_to_hsv(rgb: np.ndarray):
    """uint8 or 0-1 float RGB (HxWx3) -> (h in degrees, s, v), float32."""
    x = rgb.astype(np.float32)
    if rgb.dtype == np.uint8:
        x = x / 255.0
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    v = x.max(-1)
    c = v - x.min(-1)
    s = np.where(v > 1e-6, c / np.maximum(v, 1e-6), 0.0)
    cs = np.maximum(c, 1e-6)
    h = np.where(v == r, ((g - b) / cs) % 6, np.where(v == g, (b - r) / cs + 2, (r - g) / cs + 4))
    return (h * 60.0).astype(np.float32), s.astype(np.float32), v.astype(np.float32)


def _shift_or(m: np.ndarray, k: int) -> np.ndarray:
    p = np.pad(m, k)
    H, W = m.shape
    out = np.zeros_like(m)
    for dy in range(2 * k + 1):
        for dx in range(2 * k + 1):
            out |= p[dy:dy + H, dx:dx + W]
    return out


def dilate(m: np.ndarray, k: int = 1) -> np.ndarray:
    return _shift_or(m, k)


def erode(m: np.ndarray, k: int = 1) -> np.ndarray:
    return ~_shift_or(~m, k)


def _box3(x: np.ndarray) -> np.ndarray:
    p = np.pad(x, ((1, 1), (1, 1), (0, 0)), mode="edge")
    H, W = x.shape[:2]
    return sum(p[i:i + H, j:j + W] for i in range(3) for j in range(3)) / 9.0


def segment_rust(rgb: np.ndarray, hue_range=(5.0, 40.0), sat_min=0.35, val_min=0.12,
                 open_k: int = 1) -> np.ndarray:
    """Boolean rust mask: hue/saturation/value gate on a smoothed, gain-normalised image."""
    x = rgb.astype(np.float32) / (255.0 if rgb.dtype == np.uint8 else 1.0)
    x = _box3(x)
    gain = 0.45 / max(float(x.mean()), 1e-3)  # crude exposure normalisation
    x = np.clip(x * min(max(gain, 0.5), 2.5), 0, 1)
    h, s, v = rgb_to_hsv(x)
    m = (h >= hue_range[0]) & (h <= hue_range[1]) & (s >= sat_min) & (v >= val_min)
    return dilate(erode(m, open_k), open_k)
