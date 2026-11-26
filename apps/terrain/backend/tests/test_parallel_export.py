"""التصدير المتوازي يعطي نفس بايتات المربعات كالمتسلسل."""
import io, os, zipfile
import pytest
from app.schemas import Project
from app.tiles import export_tiles, export_workers


def small(size=4000):
    return Project(world=dict(size_x_m=size, size_y_m=size, cell_size_m=100, chunk_size_m=2000, seed=3),
                   points=[dict(id="m", kind="mountain", x_m=2500, y_m=2500, diameter_m=3000, high_m=400, low_m=10, seed=1)],
                   lines=[dict(id="r", kind="river", points=[(300, 300), (2000, 1500), (3700, 3500)], seed=2)],
                   export=dict(tile_px=513))


def tiles_of(path):
    z = zipfile.ZipFile(path)
    return {n: z.read(n) for n in z.namelist() if n.endswith(".r16")}


def test_parallel_matches_sequential(tmp_path, monkeypatch):
    p = small()
    monkeypatch.setenv("TERRAIN_WORKERS", "1")
    export_tiles(p, str(tmp_path / "a.zip"))
    monkeypatch.setenv("TERRAIN_WORKERS", "3")
    seen = []
    export_tiles(p, str(tmp_path / "b.zip"), lambda d, t: seen.append(d))
    A, B = tiles_of(tmp_path / "a.zip"), tiles_of(tmp_path / "b.zip")
    assert A.keys() == B.keys() and len(A) == 4
    assert all(A[k] == B[k] for k in A)
    assert seen and seen[-1] > 0


def test_workers_policy(monkeypatch):
    monkeypatch.delenv("TERRAIN_WORKERS", raising=False)
    assert export_workers(2, False) == 1
    assert export_workers(100, True) == 1
    monkeypatch.setenv("TERRAIN_WORKERS", "2")
    assert export_workers(100, False) == 2
