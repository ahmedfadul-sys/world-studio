import type { Candidate, LinearInfo, Lot, Preview, Project, RouteResult, SimResult, SiteKind, XY } from "./types";

async function post(url: string, body: unknown, signal?: AbortSignal) {
  const r = await fetch(url, { method: "POST", signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r;
}

export async function fetchPreview(project: Project, signal: AbortSignal, resolution = 513, colors = false): Promise<Preview> {
  const j = await (await post("/api/preview", { project, resolution, colors }, signal)).json();
  const bin = atob(j.data_b64), bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  let color: Uint8Array | undefined;
  if (j.color_b64) { const cb = atob(j.color_b64); color = new Uint8Array(cb.length); for (let i = 0; i < cb.length; i++) color[i] = cb.charCodeAt(i); }
  return { color, nx: j.nx, ny: j.ny, zmin: j.zmin, zmax: j.zmax, u16: new Uint16Array(bytes.buffer), errors: j.errors, warnings: j.warnings, linear: j.linear_info as LinearInfo[] };
}

export async function fetchProfile(project: Project, p0: XY, p1: XY, signal: AbortSignal): Promise<{ dist: number[]; z: number[] }> {
  return (await post("/api/profile", { project, p0, p1, samples: 400 }, signal)).json();
}

export async function exportZip(project: Project): Promise<Blob> {
  return (await post("/api/export", project)).blob();
}

export function download(blob: Blob, name: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

export async function startTiles(project: Project): Promise<{ job_id: string; tiles: number }> {
  return (await post("/api/export-tiles", project)).json();
}
export async function jobStatus(id: string): Promise<{ state: "running" | "done" | "error"; done: number; total: number; error: string | null }> {
  const r = await fetch(`/api/job/${id}`);
  return r.json();
}
export async function jobDownload(id: string): Promise<Blob> {
  const r = await fetch(`/api/job/${id}/download`);
  if (!r.ok) throw new Error("تعذّر تنزيل الملف");
  return r.blob();
}

export async function routeApi(project: Project, kind: "road" | "river", points: XY[], resolution: 257 | 513 = 257, maxGrade = 0.08): Promise<RouteResult> {
  return (await post("/api/route", { project, kind, points, resolution, max_grade: maxGrade })).json();
}
export async function suggestSites(project: Project, kind: SiteKind, diameter_m: number, count = 5): Promise<Candidate[]> {
  return (await (await post("/api/suggest-sites", { project, kind, diameter_m, count })).json()).candidates;
}
export async function lotsApi(project: Project, site_id: string): Promise<Lot[]> {
  return (await (await post("/api/lots", { project, site_id })).json()).lots;
}
export async function simulateApi(project: Project): Promise<SimResult> {
  return (await post("/api/simulate", { project, resolution: 513 })).json();
}
export async function viewshedApi(project: Project, x_m: number, y_m: number, height_m: number, radius_m: number): Promise<{ nx: number; ny: number; mask: Uint8Array; visible_area_km2: number; visible_fraction_of_disc: number }> {
  const j = await (await post("/api/viewshed", { project, x_m, y_m, height_m, radius_m, resolution: 513 })).json();
  const bin = atob(j.mask_b64), mask = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) mask[i] = bin.charCodeAt(i);
  return { nx: j.nx, ny: j.ny, mask, visible_area_km2: j.visible_area_km2, visible_fraction_of_disc: j.visible_fraction_of_disc };
}

// ── تصدير GLB / .blend ──
export interface Capabilities { glb: { available: boolean; max_resolution: number }; blend: { available: boolean; reason: string } }
export async function exportCapabilities(refresh = false): Promise<Capabilities> {
  return (await fetch(`/api/export-capabilities${refresh ? "?refresh=true" : ""}`)).json();
}
export async function startWorldExport(project: Project, fmt: "glb" | "blend"): Promise<{ job_id: string }> {
  return (await post(`/api/export-world?fmt=${fmt}`, project)).json();
}
export async function worldJobStatus(id: string): Promise<{ state: "running" | "done" | "error"; done: number; total: number; error: string | null; stage: string | null }> {
  return (await fetch(`/api/job/${id}`)).json();
}
export async function previewGlb(project: Project, res: number, tex: number, signal?: AbortSignal): Promise<{ data: ArrayBuffer; vertices: number; triangles: number }> {
  const r = await post(`/api/preview-glb?res=${res}&tex=${tex}`, project, signal);
  const rep = JSON.parse(r.headers.get("X-TF-Report") ?? "{}");
  return { data: await r.arrayBuffer(), vertices: rep.vertices ?? 0, triangles: rep.triangles ?? 0 };
}

// ── خامات CC0 (1K) ──
export interface TexHit { provider: string; id: string; name: string; categories: string[]; thumb: string | null; page: string }
export interface TexRecord { provider: string; id: string; name: string; authors: string[]; source_url: string; license: string; resolution: string; ref: string; folder: string; files: Record<string, string>; credit: string; cached?: boolean }
export interface TexProvider { id: string; title: string; credit: string; license: string; resolution: string }
export async function texProviders(): Promise<TexProvider[]> { return (await fetch("/api/textures/providers")).json(); }
export async function texSearch(provider: string, q: string): Promise<TexHit[]> {
  const r = await fetch(`/api/textures/search?provider=${encodeURIComponent(provider)}&q=${encodeURIComponent(q)}&limit=30`);
  if (!r.ok) throw new Error(((await r.json().catch(() => ({}))).detail as string) ?? `${r.status}`);
  return (await r.json()).results;
}
export async function texFetch(provider: string, asset_id: string): Promise<TexRecord> { return (await post("/api/textures/fetch", { provider, asset_id })).json(); }
export async function texCache(): Promise<TexRecord[]> {
  return ((await (await fetch("/api/textures/cache")).json()).items as TexRecord[]).map((r) => ({ ...r, ref: `cc0:${r.provider}/${r.id}` }));
}
export async function texEnsure(refs: string[]): Promise<{ ref: string; ok: boolean; error?: string }[]> { return (await (await post("/api/textures/ensure", { refs })).json()).results; }
export const texFileUrl = (r: { provider: string; id: string; files: Record<string, string> }) => `/api/textures/file/${r.provider}/${r.id}/${r.files.diff}`;

export type BenchStep = { label: string; seconds: number; mem_mb: number | null; note: string };
export type BenchJob = { state: "running" | "done" | "error"; done: number; total: number; error: string | null; steps: BenchStep[]; standard: boolean;
  estimate: { tiles: number; tile_px: number; seconds_per_tile: number; total_minutes: number; note: string } | null;
  machine: { cpu_count: number | null; ram_gb: number | null; python: string; os: string; numpy: string; scipy?: string } };
export async function benchStart(project: Project | null): Promise<string> { return (await (await post("/api/bench", { project })).json()).job_id; }
export async function benchStatus(id: string): Promise<BenchJob> { return (await fetch(`/api/bench/${id}`)).json(); }
