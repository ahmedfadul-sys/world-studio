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
