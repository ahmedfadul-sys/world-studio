"""النسخة السريعة (KD) لأقرب مسافة يجب أن تطابق المرجعية: نفس المسافة، ونفس موضع s وجهة الجانب إلا عند التعادل الهندسي الحقيقي."""
import math
import numpy as np
import pytest
from app import terrain as T


def rand_path(seed, size=10000.0, n=7, step=1.5):
    r = np.random.default_rng(seed)
    P = [(r.uniform(0, size), r.uniform(0, size))]
    for _ in range(n - 1):
        P.append((float(np.clip(P[-1][0] + r.uniform(-2500, 2500), 0, size)), float(np.clip(P[-1][1] + r.uniform(-2500, 2500), 0, size))))
    return T.smooth_path(P, step)


@pytest.mark.parametrize("seed,reach,px", [(1, 40.0, 129), (2, 150.0, 257), (3, 600.0, 129), (4, 25.0, 257)])
def test_grid_matches_reference(seed, reach, px):
    path = rand_path(seed)
    cx, cy = path[0][len(path[0]) // 2], path[1][len(path[1]) // 2]
    xs = np.linspace(cx - 1000, cx + 1000, px); ys = np.linspace(cy + 1000, cy - 1000, px)
    a = T.nearest_grid_ref(path, xs, ys, reach)
    b = T.nearest_grid(path, xs, ys, reach)
    m = a[0] < reach
    assert m.any()
    assert np.array_equal(m, b[0] < reach) or (np.abs((a[0] < reach).astype(int) - (b[0] < reach).astype(int)).sum() <= 2)
    both = m & (b[0] < reach)
    assert np.abs(a[0][both] - b[0][both]).max() < 1e-3
    ds = np.abs(a[1] - b[1])
    assert ds[both].max() < 0.5                      # فرق s أقل من مقطع واحد (تعادل هندسي بين مقطعين متجاورين)
    assert (a[2][both] == b[2][both]).mean() > 0.999


def test_points_match_reference():
    path = rand_path(5)
    r = np.random.default_rng(0)
    X, Y = r.uniform(0, 10000, 3000), r.uniform(0, 10000, 3000)
    a, b = T.nearest_points_ref(path, X, Y), T.nearest_points(path, X, Y)
    assert np.abs(a[0] - b[0]).max() < 1e-3
    assert np.abs(a[1] - b[1]).max() < 0.5


def test_long_edges_ring():
    ring = np.array([(0, 0), (9000, 0), (9000, 9000), (0, 9000), (0, 0)], float)
    seg = np.hypot(*np.diff(ring, axis=0).T); s = np.r_[0, np.cumsum(seg)]
    # حلقة بأضلاع طويلة جداً مع عدد كبير من الرؤوس (تكثيف يدوي) يجب ألا يعطي نتائج خاطئة
    xs = np.linspace(-500, 9500, 200); ys = np.linspace(9500, -500, 200)
    a = T.nearest_grid_ref((ring[:, 0], ring[:, 1], s), xs, ys, 600.0)
    b = T.nearest_grid((ring[:, 0], ring[:, 1], s), xs, ys, 600.0)
    m = a[0] < 600
    assert np.abs(a[0][m] - b[0][m]).max() < 1e-3


def test_path_outside_grid_is_inf():
    path = rand_path(6)
    xs = np.linspace(-5000, -4000, 50); ys = np.linspace(-4000, -5000, 50)
    assert np.isinf(T.nearest_grid(path, xs, ys, 50.0)[0]).all()


def test_cached_tree_second_call_works():
    path = rand_path(8)
    r = np.random.default_rng(1)
    X, Y = r.uniform(0, 10000, 2000), r.uniform(0, 10000, 2000)
    a = T.nearest_points(path, X, Y)
    b = T.nearest_points(path, X, Y)       # الاستدعاء الثاني يمرّ على فهرس KD المخزَّن
    assert np.array_equal(a[0], b[0])
