# Phase 1 — Technical feasibility & debim verification report

All values below were observed in this environment (Linux x86_64, 8022 MB RAM total, 7.5 GB free at start).

## Environment

| Item | Result |
|---|---|
| Python | 3.13 (backend venv `.venv`), 3.11 also present (used for `bpy`) |
| Node / npm | v22 / 10.9 |
| Blender binary | **not installed**; download.blender.org blocked (HTTP 403 via proxy) |
| `bpy` module | **installed** `bpy==5.0.1` in `.venv-blender` (Py 3.11, 935 MB on disk). 5.1+ needs Python 3.13 and was not resolvable on 3.11 |
| bpy memory | import: RSS 16 → 270 MB (+254 MB), 1.4 s |
| bpy exporters | glTF and FBX operators present |
| Godot | **not installed**; GitHub releases blocked (HTTP 403). Godot import is therefore **NOT verified** |

## debim — identity (verified from the wheel, not imported first)

- PyPI `debim` **1.2.0** (also 1.1.0 … 0.2.0 exist). MIT licence, author PRIDA-TAKON, `Requires-Python >=3.11`, status Alpha.
- Self-description: "minimal, Git-native, declarative BIM engine & MCP server". It is a **declarative YAML/JSON manifest + spatial resolver + IFC compiler**, not a mesh generator.
- Hard dependencies: pydantic>=2.7, pyyaml, numpy, ezdxf, shapely, scipy. Optional extras: `ifc` (ifcopenshell), `mcp`, `docx`.
- Footprint: wheel 608 kB; `import debim` RSS 20 → 52 MB (0.6 s). Importing `debim.resolver` + resolving a 4-element manifest: RSS 16 → 105 MB, tracemalloc peak 42.7 MB, 2.4 s (includes cold imports of scipy/shapely).

## debim — verified public surface

Exported by `debim/__init__.py`: `__version__`, `parse_debim`, `load_debim_file`, `resolve_default_manifest_path`, `bundle_manifest`, `split_manifest`.

Used by this project (read from source, then executed in `tools/phase1_probe_debim.py`):

- `debim.schema.ProjectManifest` (Pydantic v2) — requires `project`, `spatial_structure.storeys`, `grids.axes_x/axes_y`, `materials`, `elements`.
- `debim.resolver.SpatialResolver(manifest).resolve() -> ResolvedManifest`.
- Resolved results (observed): `walls` (start/end points, length, thickness, height, `children` = doors/windows with `position`, `width`, `height`, `sill_height`), `slabs` (3D polygon, thickness, area, voids), `columns` (start/end/height), plus beams, stairs, roofs, etc.
- Elements are placed by **grid references** (`from_grid: [x_axis, y_axis]`), so the adapter generates axes from our free-form coordinates.

## What debim does NOT give us (verified)

- No triangle meshes for walls/openings. `ResolvedWall` is parametric. **Mesh generation with real holes is our geometry layer.**
- `compile_to_ifc` exists but IFC export is not a game format and is not used in the game path.
- Its own `ModuleDefinition` / `modular` features are IFC-oriented; our modular library is internal and mapped to debim elements by the adapter.

## Decisions

1. debim is the **spatial resolver of record**: every build passes the project through `ProjectManifest` → `SpatialResolver`, and geometry consumes the resolved walls/openings/slabs/columns. The adapter is the only module that imports debim.
2. Blender runs as a separate subprocess using `bpy` 5.0.1 (module) because the Blender binary is unavailable; the runner also supports a real `blender -b -P` command via `BIM_BLENDER_CMD`.
3. Godot import test project is provided but **was not executed here**.

## Memory risks (measured/estimated)

- Backend (FastAPI + debim + shapely/scipy): ~100–150 MB measured at idle/probe scale.
- Blender process: +254 MB at import, then scene-dependent. Mitigated by launching only per job and exiting afterwards.
- Real risk: large projects (hundreds of walls) held as Python objects → mitigated by per-element mesh files on disk and dirty rebuild. Large-project numbers are in `docs/05-performance-report.md` after Phase 7.
