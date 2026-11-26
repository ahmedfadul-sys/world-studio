"""قياس أداء الأداة على جهاز المستخدم: مشروع قياسي ثابت أو مشروعه الحالي، مع تقدير زمن تصدير العالم كاملاً."""
from __future__ import annotations
import math, os, platform, random, sys, threading, time
import numpy as np
from .schemas import Project
from .terrain import Engine, engine_for, grid_axes, nearest_grid, nearest_grid_ref, smooth_path
from .tiles import tile_axes, tile_plan

BENCH: dict = {}          # مهمة واحدة نشطة في كل مرة (قيد: مهمة بناء واحدة، 8 جيجا ذاكرة)


def machine() -> dict:
    info = {"cpu_count": os.cpu_count(), "python": platform.python_version(), "os": platform.platform(), "numpy": np.__version__}
    try:
        import scipy; info["scipy"] = scipy.__version__
    except Exception:  # noqa: BLE001
        pass
    try:
        import psutil
        info["ram_gb"] = round(psutil.virtual_memory().total / 2 ** 30, 1)
    except Exception:  # noqa: BLE001
        try:
            info["ram_gb"] = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30, 1)
        except Exception:  # noqa: BLE001
            info["ram_gb"] = None
    return info


def peak_mb():
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 2 ** 20)
    except Exception:  # noqa: BLE001
        pass
    try:
        import resource
        v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(v / 2 ** 20 if sys.platform == "darwin" else v / 1024)
    except Exception:  # noqa: BLE001
        return None


def standard_project(size: float = 20000.0) -> Project:
    """عالم قياسي ثابت (البذرة ثابتة) كي تُقارن النتائج بين الأجهزة والإصدارات."""
    r = random.Random(7)
    kinds = ["mountain", "hill", "plateau", "crater", "lake", "dune", "volcano", "island"]
    pts = [dict(id=f"p{i}", kind=r.choice(kinds), x_m=r.uniform(0, size), y_m=r.uniform(0, size), diameter_m=r.uniform(800, 4000),
                high_m=r.uniform(200, 900), low_m=20, seed=i + 1) for i in range(40)]
    lines = []
    for i in range(12):
        x, y = r.uniform(0, size), r.uniform(0, size); P = [(x, y)]
        for _ in range(6):
            x = min(size, max(0, x + r.uniform(-2500, 2500))); y = min(size, max(0, y + r.uniform(-2500, 2500))); P.append((x, y))
        lines.append(dict(id=f"l{i}", kind=["river", "road", "valley", "ridge"][i % 4], points=P, seed=i + 1))
    return Project(world=dict(size_x_m=size, size_y_m=size, cell_size_m=100, chunk_size_m=2000, seed=7), points=pts, lines=lines)


def _timed(steps: list, label: str, fn, note: str = ""):
    t = time.perf_counter(); out = fn(); dt = time.perf_counter() - t
    steps.append({"label": label, "seconds": round(dt, 3), "mem_mb": peak_mb(), "note": note}); return out


def run_bench(job: dict, project: Project | None) -> None:
    steps = job["steps"]
    try:
        p = project or standard_project()
    except Exception as e:  # noqa: BLE001
        job.update(state="error", error=str(e)); return
    w = p.world; plan = [("preview", 513), ("preview", 1025), ("micro", 0), ("tile", 513), ("tile", 1025)]
    job["total"] = len(plan); done = 0
    try:
        for kind, px in plan:
            if kind == "preview":
                def go(px=px):
                    eng = engine_for(p, px); xs, ys = grid_axes(w.size_x_m, w.size_y_m, px); return eng.grid(xs, ys)
                _timed(steps, f"معاينة العالم كاملاً {px}×{px}", go, f"{max(w.size_x_m, w.size_y_m) / (px - 1):.1f} م/بكسل")
            elif kind == "micro" and p.lines:
                f = max(p.lines, key=lambda l: len(l.points))
                path = smooth_path(f.points, 1.5)
                if path is not None:
                    xs = np.linspace(path[0].mean() - 1000, path[0].mean() + 1000, 257); ys = xs[::-1].copy() + (path[1].mean() - path[0].mean())
                    a = _timed(steps, "أقرب مسافة لمسار: الخوارزمية القديمة", lambda: nearest_grid_ref(path, xs, ys, 300.0), f"{len(path[0])} نقطة")
                    b = _timed(steps, "أقرب مسافة لمسار: الخوارزمية السريعة", lambda: nearest_grid(path, xs, ys, 300.0))
            elif kind == "tile":
                nx, ny, mpp = tile_plan(p)
                big = Project.model_validate({**p.model_dump(), "export": {**p.export.model_dump(), "tile_px": px}})
                nx, ny, mpp = tile_plan(big); eng = Engine(big, step=0.75 * mpp)
                c, r = nx // 2, ny // 2; ax = tile_axes(big, c, r)
                dt = {}
                def go_t(ax=ax):
                    t0 = time.perf_counter(); eng.grid(*ax); dt["t"] = time.perf_counter() - t0
                _timed(steps, f"مربع تصدير واحد {px}×{px}", go_t, f"{big.world.chunk_size_m:.0f} م · {mpp:.2f} م/بكسل · {nx * ny} مربع في العالم")
                if px == p.export.tile_px or (px == 1025 and p.export.tile_px not in (513, 1025)):
                    job["estimate"] = {"tiles": nx * ny, "tile_px": px, "seconds_per_tile": round(dt["t"], 2),
                                       "total_minutes": round(dt["t"] * nx * ny / 60.0, 1), "note": "تقدير تقريبي (مربع وسطي × عدد المربعات، بلا HLOD أو التفاصيل)"}
            done += 1; job["done"] = done
        if "estimate" not in job:
            nx, ny, _ = tile_plan(p); last = next((s for s in reversed(steps) if s["label"].startswith("مربع")), None)
            if last: job["estimate"] = {"tiles": nx * ny, "tile_px": 1025, "seconds_per_tile": last["seconds"], "total_minutes": round(last["seconds"] * nx * ny / 60.0, 1), "note": "تقدير تقريبي"}
        job["state"] = "done"
    except Exception as e:  # noqa: BLE001
        job.update(state="error", error=str(e))


def start(project: Project | None) -> str:
    if any(j["state"] == "running" for j in BENCH.values()):
        raise RuntimeError("يوجد قياس قيد التشغيل")
    jid = os.urandom(6).hex()
    BENCH[jid] = {"state": "running", "done": 0, "total": 5, "error": None, "steps": [], "machine": machine(), "standard": project is None, "estimate": None}
    for k in list(BENCH)[:-5]:
        BENCH.pop(k, None)
    threading.Thread(target=run_bench, args=(BENCH[jid], project), daemon=True).start()
    return jid
