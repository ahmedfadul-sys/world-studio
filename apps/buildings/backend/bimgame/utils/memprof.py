"""Process-level and Python-level memory/time measurement.

``measure()`` reports RSS before / peak / after, tracemalloc peak, wall time.
Peak RSS is sampled by a light background thread (default 20 ms) because
``ru_maxrss`` is process-lifetime and not per-operation.
"""
from __future__ import annotations

import gc
import threading
import time
import tracemalloc
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field

import psutil

MB = 2**20


def rss_mb(pid: int | None = None) -> float:
    return psutil.Process(pid).memory_info().rss / MB


def tree_rss_mb(pid: int | None = None) -> float:
    """RSS of a process plus all its children (e.g. the Blender subprocess)."""
    p = psutil.Process(pid)
    total = p.memory_info().rss
    for c in p.children(recursive=True):
        try:
            total += c.memory_info().rss
        except psutil.Error:
            pass
    return total / MB


@dataclass
class Measurement:
    label: str
    rss_before_mb: float = 0.0
    rss_peak_mb: float = 0.0
    rss_after_mb: float = 0.0
    py_peak_mb: float = 0.0
    seconds: float = 0.0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items()}


@contextmanager
def measure(label: str, include_children: bool = True, interval: float = 0.02, py_trace: bool = True):
    m = Measurement(label)
    sampler = tree_rss_mb if include_children else rss_mb
    gc.collect()
    m.rss_before_mb = sampler()
    m.rss_peak_mb = m.rss_before_mb
    stop = threading.Event()

    def _poll() -> None:
        while not stop.is_set():
            try:
                m.rss_peak_mb = max(m.rss_peak_mb, sampler())
            except psutil.Error:
                pass
            time.sleep(interval)

    t = threading.Thread(target=_poll, daemon=True)
    started_trace = py_trace and not tracemalloc.is_tracing()
    if started_trace:
        tracemalloc.start()
    t.start()
    t0 = time.perf_counter()
    try:
        yield m
    finally:
        m.seconds = time.perf_counter() - t0
        stop.set()
        t.join(timeout=1)
        if py_trace and tracemalloc.is_tracing():
            m.py_peak_mb = tracemalloc.get_traced_memory()[1] / MB
            if started_trace:
                tracemalloc.stop()
        m.rss_peak_mb = max(m.rss_peak_mb, sampler())
        gc.collect()
        m.rss_after_mb = sampler()
