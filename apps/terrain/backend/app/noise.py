"""ضوضاء قيمة (Value Noise) حتمية بإحداثيات العالم الحقيقية.
لأنها تعتمد على الإحداثيات المطلقة وليس على الصورة، فأي نافذة/مربع (Tile) يعطي نفس القيم
عند نفس النقطة -> لا شقوق بين المربعات. الدوال تقبل xs بشكل (1,W) و ys بشكل (H,1)."""
import numpy as np

_U = np.uint64


def _lattice(ix: np.ndarray, iy: np.ndarray, seed: int) -> np.ndarray:
    s = _U((int(seed) * 0xC2B2AE3D) & 0xFFFFFFFFFFFFFFFF)
    with np.errstate(over="ignore"):
        h = ix.astype(np.int64).astype(np.uint64) * _U(0x9E3779B1)
        h = h ^ (iy.astype(np.int64).astype(np.uint64) * _U(0x85EBCA77))
        h = h ^ s
        h = h ^ (h >> _U(15))
        h = h * _U(0x2C1B3C6D)
        h = h ^ (h >> _U(12))
        h = h * _U(0x297A2D39)
        h = h ^ (h >> _U(15))
    return (h & _U(0xFFFFFF)).astype(np.float32) / np.float32(0xFFFFFF)


def _fade(t: np.ndarray) -> np.ndarray:
    return t * t * t * (t * (t * 6 - 15) + 10)


def value_noise(x: np.ndarray, y: np.ndarray, seed: int) -> np.ndarray:
    """قيم في [0,1]. x و y بوحدات الشبكة (بعد ضرب التردد)."""
    x0, y0 = np.floor(x), np.floor(y)
    u = _fade((x - x0).astype(np.float32))
    v = _fade((y - y0).astype(np.float32))
    ix, iy = x0.astype(np.int64), y0.astype(np.int64)
    n00 = _lattice(ix, iy, seed)
    n10 = _lattice(ix + 1, iy, seed)
    n01 = _lattice(ix, iy + 1, seed)
    n11 = _lattice(ix + 1, iy + 1, seed)
    a = n00 + (n10 - n00) * u
    b = n01 + (n11 - n01) * u
    return a + (b - a) * v


def fbm(xs: np.ndarray, ys: np.ndarray, freq: float, octaves: int, seed: int) -> np.ndarray:
    """ضوضاء كسورية تقريباً في [-1,1]. xs:(1,W) ys:(H,1) بالمتر، freq = 1/المتر."""
    total, amp, norm = 0.0, 1.0, 0.0
    for o in range(octaves):
        f = freq * (2.0 ** o)
        total = total + amp * (value_noise(xs * f, ys * f, seed + 101 * o) * 2.0 - 1.0)
        norm += amp
        amp *= 0.5
    return (total / norm).astype(np.float32)
