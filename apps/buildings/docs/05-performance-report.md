# Performance report (measured, `tools/perf_run.py`, raw data `docs/perf.json`)

Machine: 2 CPUs, 8 GB RAM. Full export (collision + LODs, GLB), including Blender subprocess.

| size | elements | tris | 1st build | cached rebuild | RAM peak (tree) | Blender peak | RAM after | GLB |
|---|---|---|---|---|---|---|---|---|
| small | 34 | 1.5k | 2.3 s | 1.0 s | 350 MB | 268 MB | 83 MB | 0.2 MB |
| medium | 301 | 13k | 3.9 s | 2.6 s | 415 MB | 326 MB | 89 MB | 1.7 MB |
| large | 2169 | 93k | 31 s | 23 s | 853 MB | 703 MB | 150 MB | 12 MB |

Editing one window rebuilds 2 elements: geometry 0.04 s (small), 0.23 s (medium), 1.4 s (large). No Blender process survived any run; RAM returns to baseline after each job (no growth over repeats). All values within the 8 GB target.
Limits: only 2 runs per size; synthetic buildings; Linux only; Blender via the `bpy` module (the real Blender binary path is untested here).
