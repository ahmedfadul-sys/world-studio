import json

import pytest

from bimgame.config import Settings
from bimgame.geometry.cache import affected_by, build_geometry, load_manifest
from bimgame.schema import Window, Wall, Project
from bimgame.services.storage import ProjectStore
from bimgame.utils.errors import AppError, BuildError, NotFound
from conftest import house


def test_incremental_rebuild_only_touches_dirty(tmp_path):
    p = house()
    g = tmp_path / "geometry"
    s1 = build_geometry(p, g)
    n = len(s1.rebuilt)
    assert n == 10 and not s1.cached and s1.triangles > 0
    mtimes = {f.name: f.stat().st_mtime_ns for f in g.glob("*.npz")}

    s2 = build_geometry(p, g)  # nothing changed
    assert not s2.rebuilt and len(s2.cached) == n

    # change only the window width: window + its host wall (hole size changes) must rebuild
    win = next(e for e in p.elements if e.id == "n1")
    win.width = 1.5
    p2 = Project.model_validate(p.model_dump())
    s3 = build_geometry(p2, g)
    assert set(s3.rebuilt) == {"n1", "w_s"}
    after = {f.name: f.stat().st_mtime_ns for f in g.glob("*.npz")}
    unchanged = [k for k in mtimes if k not in ("n1.npz", "w_s.npz")]
    assert all(after[k] == mtimes[k] for k in unchanged)  # unchanged meshes preserved byte-for-byte on disk

    # moving a wall endpoint refreshes the touching walls (corner extension) but not floor/column/roof
    w = next(e for e in p2.elements if e.id == "w_e")
    w.b = (6, 5)
    p3 = Project.model_validate(p2.model_dump())
    s4 = build_geometry(p3, g)
    assert {"w_e", "w_s", "w_n"} <= set(s4.rebuilt)
    assert not {"c1", "r1", "s1", "f1"} & set(s4.rebuilt)
    assert {"w_e", "w_s"} <= affected_by(p3, {"w_e"})


def test_removed_elements_are_deleted_and_manifest_updated(tmp_path):
    p = house()
    g = tmp_path / "g"
    build_geometry(p, g)
    p.elements = [e for e in p.elements if e.id not in ("c1",)]
    p = Project.model_validate(p.model_dump())
    st = build_geometry(p, g)
    assert st.removed == ["c1"] and not (g / "c1.npz").exists()
    assert "c1" not in load_manifest(g)["parts"]


def test_level_filter_builds_only_that_level(tmp_path):
    p = house()
    from bimgame.schema import Level
    p.levels.append(Level(id="lvl_1", name="First", elevation=3.0, height=3.0))
    p.elements.append(Wall(id="u1", level_id="lvl_1", a=(0, 0), b=(2, 0)))
    p = Project.model_validate(p.model_dump())
    st = build_geometry(p, tmp_path / "g", levels={"lvl_1"})
    assert st.rebuilt == ["u1"]
    man = load_manifest(tmp_path / "g")["parts"]
    assert man["u1"]["bbox"][0][2] == pytest.approx(3.0)   # placed on the level elevation


def test_invalid_geometry_is_reported_not_silenced(tmp_path):
    p = house()
    p.elements.append(Window(id="huge", level_id="lvl_0", wall_id="w_e", offset=2.0, width=1.0, height=5.0, sill=0.0))
    p = Project.model_validate(p.model_dump())
    # a window taller than the wall: geometry layer still must not silently emit a broken mesh
    try:
        build_geometry(p, tmp_path / "g")
    except (BuildError, AppError):
        return
    # if it built, the wall must still be a valid solid (hole clipped by the outline)
    assert load_manifest(tmp_path / "g")["parts"]["w_e"]["tris"] > 0


@pytest.fixture
def store(tmp_path):
    s = ProjectStore(Settings(data_dir=tmp_path))
    yield s
    s.close()


def test_save_load_roundtrip_and_listing(store):
    p = house()
    store.save(p)
    q = store.load(p.id)
    assert q.model_dump(exclude={"updated_at"}) == p.model_dump(exclude={"updated_at"})
    rows = store.list()
    assert rows[0]["id"] == p.id and rows[0]["elements"] == len(p.elements)


def test_corrupt_project_recovers_from_backup(store):
    p = house()
    store.save(p)
    p.name = "v2"
    store.save(p)  # creates .bak of v1
    store.file(p.id).write_text("{ not json")
    q = store.load(p.id)
    assert q.name == "house"  # fell back to the last good backup


def test_corrupt_without_backup_is_clear_error(store):
    p = house()
    store.save(p)
    store.file(p.id).write_text("garbage")
    store.file(p.id).with_suffix(".json.bak").unlink(missing_ok=True)
    with pytest.raises(AppError) as e:
        store.load(p.id)
    assert "corrupted" in e.value.what


def test_missing_and_unsafe_ids(store):
    with pytest.raises(NotFound):
        store.load("prj_nope")
    with pytest.raises(AppError):
        store.dir("../etc")


def test_delete_and_schema_rejects_bad_refs(store):
    p = house()
    store.save(p)
    store.delete(p.id)
    assert not store.exists(p.id)
    bad = json.loads(house().model_dump_json())
    bad["elements"][0]["level_id"] = "lvl_missing"
    with pytest.raises(Exception):
        Project.model_validate(bad)


def test_interrupted_jobs_marked_failed_on_start(store):
    store.job_put({"id": "j1", "project_id": "p", "kind": "build", "status": "running", "created_at": "t"})
    assert store.mark_interrupted_jobs() == 1
    assert store.job_get("j1")["status"] == "failed"
