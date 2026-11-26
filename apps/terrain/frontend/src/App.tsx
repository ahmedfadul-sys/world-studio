import { Fragment, Suspense, lazy, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import MapCanvas, { type Mode, type Overlay, type Sel } from "./MapCanvas";
import { analyze, parseTelemetry, syntheticSessions, type Session, type TStats } from "./telemetry";
import Chart from "./Chart";
import { download, exportCapabilities, exportZip, fetchPreview, fetchProfile, jobDownload, jobStatus, lotsApi, routeApi, simulateApi, startTiles, startWorldExport, suggestSites, texEnsure, viewshedApi, worldJobStatus, type Capabilities } from "./api";
const World3D = lazy(() => import("./World3D"));
const PerfBench = lazy(() => import("./PerfBench"));      // three.js يُحمَّل عند فتح المعاينة فقط
import TexBrowser from "./TexBrowser";
import { sampleZ } from "./render";
import {
  BIOME_PRESETS, LINE_META, POINT_META, POI_META, SITE_META, ZONE_META, conflict, defaultProject, newBiome, newLine, newPoi, newPoint, newSite, newZone, polyArea, siteExt, sliceAndDice,
  defaultAtmosphere, defaultDerived, defaultDetail, defaultKit, newKitPiece, KIT_ROLES, type KitRole, defaultRoads, defaultWater, defaultSpecies, type DetailKind, type ScatterKind, defaultSurface, type Biome, type Candidate, type CellSpec, type Fall, type Lot, type Poi, type PoiKind, type RouteResult, type SimResult, type Material, type LineFeature, type LineKind, type PointFeature, type PointKind, type Preview, type Project, type Site, type SiteKind, type XY, type Zone, type ZoneLayer,
} from "./types";

function Num({ value, onChange, step = 1, min, max }: { value: number; onChange: (v: number) => void; step?: number; min?: number; max?: number }) {
  const [t, setT] = useState(String(value));
  useEffect(() => { if (parseFloat(t) !== value) setT(String(value)); }, [value]); // eslint-disable-line
  return (
    <input type="number" dir="ltr" value={t} step={step} min={min} max={max}
      onChange={(e) => { setT(e.target.value); const x = parseFloat(e.target.value); if (Number.isFinite(x)) onChange(x); }} />
  );
}
const Field = ({ label, children }: { label: string; children: ReactNode }) => <label className="field"><span>{label}</span>{children}</label>;
function OptNum({ label, value, onChange, def }: { label: string; value: number | null; onChange: (v: number | null) => void; def: number }) {
  return (
    <Field label={label}>
      <span className="pair">
        <input type="checkbox" checked={value !== null} onChange={(e) => onChange(e.target.checked ? def : null)} aria-label={label} />
        {value !== null ? <Num value={value} onChange={onChange} /> : <span className="hint">بلا حد</span>}
      </span>
    </Field>
  );
}
function MatSel({ label, value, onChange, mats }: { label: string; value: string | null; onChange: (v: string | null) => void; mats: Material[] }) {
  const col = mats.find((m) => m.id === value)?.color;
  return (
    <Field label={label}>
      <span className="pair">
        <select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
          <option value="">— بلا —</option>{mats.map((m) => <option key={m.id} value={m.id}>{m.name || m.id}</option>)}</select>
        <span className="swatch" style={{ background: col ?? "transparent" }} />
      </span>
    </Field>
  );
}
const DIRS: [string, number][] = [["شمال", 0], ["شرق", 90], ["جنوب", 180], ["غرب", 270]];
const MODES: [Mode, string][] = [["select", "تحديد"], ["point", "نقطية"], ["line", "خطية"], ["cell", "خلية"], ["profile", "مقطع"], ["biome", "منطقة"], ["site", "منشأة"], ["zone", "نباتات"], ["poi", "اهتمام"], ["route", "مسار ذكي"]];
const MODE_ICON: Record<Mode, string> = { select: "M5 3l14 7-6 2-2 6z", point: "M12 3a6 6 0 016 6c0 5-6 12-6 12S6 14 6 9a6 6 0 016-6z", line: "M4 19c4-1 3-8 8-8s4-6 8-7", cell: "M4 4h16v16H4zM4 12h16M12 4v16", profile: "M3 17l6-8 4 5 3-3 5 6", biome: "M5 18l2-12 8-2 4 8-6 6z", site: "M4 20V9l8-5 8 5v11M9 20v-6h6v6", zone: "M12 21v-8M12 13c-4 0-6-3-6-7 4 0 6 2 6 7zM12 13c4 0 6-3 6-7-4 0-6 2-6 7z", poi: "M12 3l3 6 6 1-4.5 4.5L18 21l-6-3-6 3 1.5-6.5L3 10l6-1z", route: "M4 18c3-8 5 0 8-6s5-6 8-8" };
type Tab = "world" | "design" | "play" | "look" | "export";
const TABS: [Tab, string][] = [["world", "العالم"], ["design", "التصميم"], ["play", "اللعب"], ["look", "المظهر"], ["export", "التصدير"]];
const fmtDur = (s: number) => `${Math.floor(s / 3600)}س ${Math.floor((s % 3600) / 60)}د`;

export default function App() {
  const [project, setProject] = useState<Project>(defaultProject);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mode, setMode] = useState<Mode>("point");
  const [pointKind, setPointKind] = useState<PointKind>("mountain");
  const [lineKind, setLineKind] = useState<LineKind>("river");
  const [biomePreset, setBiomePreset] = useState(0);
  const [siteKind, setSiteKind] = useState<SiteKind>("village");
  const [zoneLayer, setZoneLayer] = useState<ZoneLayer>("grass");
  const [viewMat, setViewMat] = useState(false);
  const [poiKind, setPoiKind] = useState<PoiKind>("player_start");
  const [routeKind, setRouteKind] = useState<"road" | "river">("road");
  const [routeGrade, setRouteGrade] = useState(8);
  const [routeInfo, setRouteInfo] = useState<RouteResult | null>(null);
  const [cands, setCands] = useState<Candidate[] | null>(null);
  const [lots, setLots] = useState<Lot[] | null>(null);
  const [showLots, setShowLots] = useState(false);
  const [sim, setSim] = useState<SimResult | null>(null);
  const [viewC, setViewC] = useState<HTMLCanvasElement | null>(null);
  const [viewInfo, setViewInfo] = useState<string | null>(null);
  const [ses, setSes] = useState<Session[]>([]);
  const [tstats, setTstats] = useState<TStats | null>(null);
  const [showHeat, setShowHeat] = useState(true);
  const [showTPaths, setShowTPaths] = useState(true);
  const telRef = useRef<HTMLInputElement>(null);
  const [matSel, setMatSel] = useState<string | null>(null);
  const [spSel, setSpSel] = useState<string | null>(null);
  const [kpSel, setKpSel] = useState<string | null>(null);
  const [sel, setSel] = useState<Sel>(null);
  const [cellSel, setCellSel] = useState<{ col: number; row: number } | null>(null);
  const [cellDraft, setCellDraft] = useState<CellSpec | null>(null);
  const [draft, setDraft] = useState<XY[]>([]);
  const [profileLine, setProfileLine] = useState<[XY, XY] | null>(null);
  const [profile, setProfile] = useState<{ dist: number[]; z: number[] } | null>(null);
  const [showGrid, setShowGrid] = useState(true);
  const [interval, setIntervalM] = useState(25);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [hover, setHover] = useState<XY | null>(null);
  const [autoN, setAutoN] = useState(3);
  const [autoAreas, setAutoAreas] = useState<number[]>([]);
  const [job, setJob] = useState<{ id: string; done: number; total: number; state: string; error: string | null } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [show3d, setShow3d] = useState(false);
  const [showBench, setShowBench] = useState(false);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [wjob, setWjob] = useState<{ id: string; fmt: "glb" | "blend"; state: string; done: number; stage: string | null; error: string | null } | null>(null);

  const set = (fn: (p: Project) => void) => setProject((p) => { const c = structuredClone(p); fn(c); return c; });
  const uid = (prefix: string, used: string[]) => { let i = 1; while (used.includes(`${prefix}-${i}`)) i++; return `${prefix}-${i}`; };
  const embedded = typeof window !== "undefined" && window.parent !== window;     // داخل World Studio
  const openInBim = (id: string) => {
    const site = project.sites.find((s) => s.id === id); if (!site) return;
    setSel({ t: "site", id }); window.parent.postMessage({ type: "studio.openSite", site }, "*");
  };
  const exportWorld = (mode: "tiles" | "single") => { setErr(null); window.parent.postMessage({ type: "studio.exportWorld", project, mode }, "*"); };
  useEffect(() => {
    const h = (e: MessageEvent) => {
      const d = e.data; if (!d || e.source !== window.parent) return;
      if (d.type === "studio.siteLinked" && typeof d.siteId === "string") set((p) => { const s = p.sites.find((x) => x.id === d.siteId); if (s) s.bim_project = d.project_id; });
    };
    window.addEventListener("message", h); return () => window.removeEventListener("message", h);
  });
  const flash = (m: string) => { setNotice(m); setTimeout(() => setNotice(null), 5000); };
  const [tab, setTab] = useState<Tab>("world");
  const [sideOpen, setSideOpen] = useState(true);
  const [theme, setTheme] = useState<"dark" | "light">(() => { try { return localStorage.getItem("tf-theme") === "light" ? "light" : "dark"; } catch { return "dark"; } });
  useLayoutEffect(() => { document.documentElement.dataset.theme = theme; try { localStorage.setItem("tf-theme", theme); } catch { /* التخزين غير متاح */ } }, [theme]);
  useEffect(() => { if (sel || cellSel) { setTab("design"); setSideOpen(true); } }, [sel, cellSel]);   // اختيار عنصر في الخريطة يفتح محرره

  const terrainKey = JSON.stringify({ ...project, atmosphere: null, surface: null, scatter: null, detail: null, water: null, roads: null, kit: null });          // تعديل الجو لا يغيّر الارتفاعات فلا يعيد حساب المعاينة
  useEffect(() => {
    const ac = new AbortController();
    const h = setTimeout(() => fetchPreview(project, ac.signal, 513, viewMat).then((pv) => { setPreview(pv); setErr(null); })
      .catch((e) => { if (e.name !== "AbortError") setErr(String(e.message || e)); }), 300);
    return () => { clearTimeout(h); ac.abort(); };
  }, [terrainKey, viewMat]); // eslint-disable-line

  useEffect(() => {
    if (!profileLine) { setProfile(null); return; }
    const ac = new AbortController();
    const h = setTimeout(() => fetchProfile(project, profileLine[0], profileLine[1], ac.signal).then(setProfile).catch(() => {}), 300);
    return () => { clearTimeout(h); ac.abort(); };
  }, [project, profileLine]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setDraft([]); setCellSel(null); setCellDraft(null); setMode("select"); }
      if (e.key === "Enter") finishDraft();
    };
    window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key);
  }); // eslint-disable-line

  useEffect(() => { // متابعة مهمة المربعات
    if (!job || job.state !== "running") return;
    const h = setInterval(async () => {
      const s = await jobStatus(job.id);
      setJob((j) => (j ? { ...j, ...s } : j));
      if (s.state === "done") { download(await jobDownload(job.id), "terrain_tiles.zip"); }
    }, 800);
    return () => clearInterval(h);
  }, [job?.id, job?.state]); // eslint-disable-line

  useEffect(() => { exportCapabilities().then(setCaps).catch(() => undefined); }, []);
  useEffect(() => { // متابعة مهمة تصدير GLB/.blend
    if (!wjob || wjob.state !== "running") return;
    const h = setInterval(async () => {
      const s = await worldJobStatus(wjob.id);
      setWjob((j) => (j ? { ...j, ...s } : j));
      if (s.state === "done") { download(await jobDownload(wjob.id), `world.${wjob.fmt}`); }
    }, 700);
    return () => clearInterval(h);
  }, [wjob?.id, wjob?.state]); // eslint-disable-line
  const doWorld = async (fmt: "glb" | "blend") => {
    setErr(null);
    try { const r = await startWorldExport(project, fmt); setWjob({ id: r.job_id, fmt, state: "running", done: 0, stage: "بدء", error: null }); } catch (e) { setErr(String((e as Error).message)); }
  };

  const w = project.world;
  const ground = (x: number, y: number) => (preview ? sampleZ(preview, x, y, w.size_x_m, w.size_y_m) : project.base.elevation_m);
  const selPoint = sel?.t === "point" ? project.points.find((f) => f.id === sel.id) ?? null : null;
  const selLine = sel?.t === "line" ? project.lines.find((f) => f.id === sel.id) ?? null : null;
  const selPoi = sel?.t === "poi" ? project.pois.find((f) => f.id === sel.id) ?? null : null;
  const setPoi = (patch: Partial<Poi>) => selPoi && set((p) => Object.assign(p.pois.find((f) => f.id === selPoi.id)!, patch));
  const selSite = sel?.t === "site" ? project.sites.find((f) => f.id === sel.id) ?? null : null;
  const selZone = sel?.t === "zone" ? project.zones.find((f) => f.id === sel.id) ?? null : null;
  const selBiome = sel?.t === "biome" ? project.biomes.find((f) => f.id === sel.id) ?? null : null;
  const setP = (patch: Partial<PointFeature>) => {
    if (!selPoint) return;
    const why = conflict(project.points, { ...selPoint, ...patch });
    if (why) { flash(`لا يمكن: ${why}`); return; }
    set((p) => Object.assign(p.points.find((f) => f.id === selPoint.id)!, patch));
  };
  const setL = (patch: Partial<LineFeature>) => selLine && set((p) => Object.assign(p.lines.find((f) => f.id === selLine.id)!, patch));
  const setS = (patch: Partial<Site>) => selSite && set((p) => Object.assign(p.sites.find((f) => f.id === selSite.id)!, patch));
  const setZ = (patch: Partial<Zone>) => selZone && set((p) => Object.assign(p.zones.find((f) => f.id === selZone.id)!, patch));
  const setB = (patch: Partial<Biome>) => selBiome && set((p) => Object.assign(p.biomes.find((f) => f.id === selBiome.id)!, patch));

  const generateRoute = async () => {
    const need = routeKind === "river" ? 1 : 2;
    if (draft.length < need) { flash(routeKind === "river" ? "انقر موضع المنبع (ومصباً اختيارياً)." : "انقر نقطتين على الأقل (البداية والنهاية وما بينهما)."); return; }
    setBusy(true); setErr(null);
    try {
      const rr = await routeApi(project, routeKind, draft, 257, routeGrade / 100);
      const id = uid(LINE_META[routeKind].label, project.lines.map((l) => l.id));
      set((p) => p.lines.push(newLine(routeKind, rr.points.map(([x, y]) => [Math.round(x), Math.round(y)] as XY), id, p)));
      setSel({ t: "line", id }); setDraft([]); setMode("select"); setRouteInfo(rr);
    } catch (e) { setErr(String((e as Error).message)); }
    setBusy(false);
  };
  const finishDraft = () => {
    if (mode === "route") { void generateRoute(); return; }
    const pts = draft.filter((q, i) => i === 0 || Math.hypot(q[0] - draft[i - 1][0], q[1] - draft[i - 1][1]) > 1).map(([x, y]) => [Math.round(x), Math.round(y)] as XY);
    if (mode === "line" && pts.length >= 2) {
      const id = uid(LINE_META[lineKind].label, project.lines.map((l) => l.id));
      set((p) => p.lines.push(newLine(lineKind, pts, id, p))); setSel({ t: "line", id }); setDraft([]); setMode("select");
    } else if (mode === "biome" && pts.length >= 3) {
      const id = uid("منطقة", project.biomes.map((b) => b.id)), pr = BIOME_PRESETS[biomePreset];
      set((p) => p.biomes.push(newBiome(id, `${pr.label} ${p.biomes.length + 1}`, pts, pr, Math.round(Math.min(w.size_x_m, w.size_y_m) * 0.03))));
      setSel({ t: "biome", id }); setDraft([]); setMode("select");
    } else if (mode === "zone" && pts.length >= 3) {
      const id = uid("نباتات", project.zones.map((z) => z.id));
      set((p) => p.zones.push(newZone(zoneLayer, pts, id))); setSel({ t: "zone", id }); setDraft([]); setMode("select");
    }
  };

  const clickWorld = (x: number, y: number) => {
    if (mode === "point") {
      const id = uid(POINT_META[pointKind].label, project.points.map((f) => f.id));
      const f = newPoint(pointKind, x, y, id, project, ground(x, y)), why = conflict(project.points, f);
      if (why) { flash(`لا يمكن الوضع هنا (قطر ${f.diameter_m} م): ${why}`); return; }
      set((p) => p.points.push(f)); setSel({ t: "point", id }); setMode("select");
    } else if (mode === "site") {
      const id = uid("موقع", project.sites.map((s) => s.id)), s = newSite(siteKind, x, y, id, project);
      const hit = project.sites.find((q) => Math.hypot(q.x_m - s.x_m, q.y_m - s.y_m) < siteExt(q) + siteExt(s));
      if (hit) { flash(`لا يمكن: الموقع يتداخل مع ${hit.name}. اختر مكاناً آخر.`); return; }
      set((p) => p.sites.push(s)); setSel({ t: "site", id }); setMode("select");
    } else if (mode === "poi") {
      const id = uid("اهتمام", project.pois.map((q) => q.id)), q = newPoi(poiKind, x, y, id, project);
      set((p) => p.pois.push(q)); setSel({ t: "poi", id }); setMode("select");
    } else if (mode === "line" || mode === "biome" || mode === "zone" || mode === "route") setDraft((d) => [...d, [x, y]]);
    else if (mode === "cell") {
      const col = Math.floor(x / w.cell_size_m), row = Math.floor((w.size_y_m - y) / w.cell_size_m);
      const ex = project.cells.find((c) => c.col === col && c.row === row);
      setCellSel({ col, row });
      setCellDraft(ex ?? { col, row, elevation_m: Math.round(ground((col + 0.5) * w.cell_size_m, w.size_y_m - (row + 0.5) * w.cell_size_m)), rise_m: 0, run_m: 50, aspect_deg: 0 });
    } else if (mode === "profile") {
      if (draft.length === 0) { setDraft([[x, y]]); setProfileLine(null); } else { setProfileLine([draft[0], [x, y]]); setDraft([]); }
    }
  };

  const movePoi = (id: string, x: number, y: number) => set((p) => { const q = p.pois.find((z) => z.id === id)!; q.x_m = Math.round(Math.min(w.size_x_m, Math.max(0, x))); q.y_m = Math.round(Math.min(w.size_y_m, Math.max(0, y))); });
  const findSites = async () => {
    setBusy(true); setErr(null);
    try { setCands(await suggestSites(project, siteKind, newSite(siteKind, 0, 0, "x", project).diameter_m, 5)); } catch (e) { setErr(String((e as Error).message)); }
    setBusy(false);
  };
  const placeCandidate = (c: Candidate) => {
    const id = uid("موقع", project.sites.map((s) => s.id));
    set((p) => p.sites.push(newSite(siteKind, c.x_m, c.y_m, id, p))); setSel({ t: "site", id }); setMode("select"); setCands(null);
  };
  const runSim = async (): Promise<SimResult | null> => {
    setBusy(true); setErr(null);
    try { const rr = await simulateApi(project); setSim(rr); setBusy(false); return rr; } catch (e) { setErr(String((e as Error).message)); setBusy(false); return null; }
  };
  const runView = async () => {
    if (!selPoi) { flash("اختر عنصر اهتمام على الخريطة أولاً."); return; }
    setBusy(true); setErr(null);
    try {
      const v = await viewshedApi(project, selPoi.x_m, selPoi.y_m, project.player.eye_height_m + selPoi.landmark_height_m, project.player.view_distance_m);
      const cv = document.createElement("canvas"); cv.width = v.nx; cv.height = v.ny;
      const img = new ImageData(v.nx, v.ny); for (let i = 0; i < v.mask.length; i++) if (v.mask[i]) { img.data[i * 4] = 255; img.data[i * 4 + 1] = 214; img.data[i * 4 + 2] = 10; img.data[i * 4 + 3] = 255; }
      cv.getContext("2d")!.putImageData(img, 0, 0); setViewC(cv);
      setViewInfo(`المنطقة المرئية ${v.visible_area_km2.toFixed(2)} كم² (${(v.visible_fraction_of_disc * 100).toFixed(0)}% من دائرة مدى الرؤية)`);
    } catch (e) { setErr(String((e as Error).message)); }
    setBusy(false);
  };
  const expectedPath: XY[] | null = sim ? sim.legs.filter((l) => l.reachable && l.points).flatMap((l) => l.points as XY[]) : null;
  const loadTelemetry = (list: Session[]) => { setSes(list); setTstats(analyze(list, project, expectedPath)); };
  const loadSample = async () => { const s = sim ?? (await runSim()); if (!s) return; const path = s.legs.filter((l) => l.reachable && l.points).flatMap((l) => l.points as XY[]); if (path.length < 2) { flash("لا مسار متوقع صالح لتوليد العينة."); return; } loadTelemetry(syntheticSessions(path, 30)); };
  const readTel = async (f: File) => { try { loadTelemetry(parseTelemetry(await f.text())); } catch (e) { setErr("تعذّر قراءة ملف التتبّع: " + String((e as Error).message)); } };
  const movePoint = (id: string, x: number, y: number) => {
    const f = project.points.find((q) => q.id === id); if (!f) return;
    const nx = Math.round(Math.min(w.size_x_m, Math.max(0, x))), ny = Math.round(Math.min(w.size_y_m, Math.max(0, y)));
    if (conflict(project.points, { ...f, x_m: nx, y_m: ny })) return;
    set((p) => { const q = p.points.find((z) => z.id === id)!; q.x_m = nx; q.y_m = ny; });
  };
  const moveVertex = (id: string, i: number, x: number, y: number) => set((p) => { p.lines.find((l) => l.id === id)!.points[i] = [Math.round(x), Math.round(y)]; });
  const moveSite = (id: string, x: number, y: number) => {
    const s = project.sites.find((q) => q.id === id); if (!s) return;
    const nx = Math.round(Math.min(w.size_x_m, Math.max(0, x))), ny = Math.round(Math.min(w.size_y_m, Math.max(0, y)));
    if (project.sites.some((q) => q.id !== id && Math.hypot(q.x_m - nx, q.y_m - ny) < siteExt(q) + siteExt(s))) return;
    set((p) => { const q = p.sites.find((z) => z.id === id)!; q.x_m = nx; q.y_m = ny; });
  };
  const moveZoneVertex = (id: string, i: number, x: number, y: number) => set((p) => { p.zones.find((z) => z.id === id)!.polygon[i] = [Math.round(x), Math.round(y)]; });
  const moveBiomeVertex = (id: string, i: number, x: number, y: number) => set((p) => { p.biomes.find((b) => b.id === id)!.polygon[i] = [Math.round(x), Math.round(y)]; });

  const applyCell = () => { if (cellDraft) set((p) => { p.cells = p.cells.filter((c) => !(c.col === cellDraft.col && c.row === cellDraft.row)).concat(cellDraft); }); };
  const clearCell = () => { if (cellSel) set((p) => { p.cells = p.cells.filter((c) => !(c.col === cellSel.col && c.row === cellSel.row)); }); };

  const worldKm2 = (w.size_x_m * w.size_y_m) / 1e6;
  const openAuto = (n: number) => { setAutoN(n); setAutoAreas(Array.from({ length: n }, () => +(worldKm2 / n).toFixed(3))); };
  const applyAuto = () => {
    const areas = autoAreas.length === autoN ? autoAreas : Array.from({ length: autoN }, () => worldKm2 / autoN);
    const sum = areas.reduce((a, b) => a + b, 0);
    if (sum <= 0) return;
    const rects = sliceAndDice(areas.map((a) => (a / sum) * worldKm2), 0, 0, w.size_x_m, w.size_y_m);
    const blend = Math.round(Math.min(w.size_x_m, w.size_y_m) * 0.03);
    set((p) => { p.biomes = rects.map((poly, i) => newBiome(`منطقة-${i + 1}`, `${BIOME_PRESETS[i % BIOME_PRESETS.length].label} ${i + 1}`, poly.map(([x, y]) => [Math.round(x), Math.round(y)] as XY), BIOME_PRESETS[i % BIOME_PRESETS.length], blend)); });
    if (Math.abs(sum - worldKm2) > 0.01 * worldKm2) flash(`مجموع المساحات ${sum.toFixed(2)} كم² لا يساوي مساحة العالم ${worldKm2.toFixed(2)} كم²: جرى تطبيعها بالنسبة نفسها.`);
    setSel(null);
  };

  const doExport = async () => { setBusy(true); setErr(null); try { download(await exportZip(project), "terrain_export.zip"); } catch (e) { setErr(String((e as Error).message)); } setBusy(false); };
  const doTiles = async () => {
    setErr(null);
    try { const r = await startTiles(project); setJob({ id: r.job_id, done: 0, total: r.tiles * 2, state: "running", error: null }); } catch (e) { setErr(String((e as Error).message)); }
  };
  const save = () => download(new Blob([JSON.stringify(project, null, 2)], { type: "application/json" }), `${project.name}.terrain.json`);
  const load = async (f: File) => {
    try {
      const p = JSON.parse(await f.text()) as Project;
      if (p.version !== 7 || !Array.isArray(p.pois) || !Array.isArray(p.materials) || !p.world || !Array.isArray(p.points) || !Array.isArray(p.lines) || !Array.isArray(p.biomes) || !Array.isArray(p.sites) || !Array.isArray(p.zones)) throw new Error("ملف مشروع غير صالح أو من إصدار قديم (يلزم المخطط v7).");
      p.erosion = { ...defaultProject().erosion, ...(p.erosion ?? {}) };
      p.kit = { ...defaultKit(), ...(p.kit ?? {}) };
      p.roads = { ...defaultRoads(), ...(p.roads ?? {}) };
      p.water = { ...defaultWater(), ...(p.water ?? {}) };
      p.detail = { ...defaultDetail(), ...(p.detail ?? {}) };
      p.scatter = { enabled: true, species: [], ...((p.scatter ?? {}) as Partial<Project["scatter"]>) };
      p.derived = { ...defaultDerived(), ...(p.derived ?? {}) };
      p.surface = { ...defaultSurface(), ...(p.surface ?? {}) };
      p.materials = (p.materials ?? []).map((m) => ({ roughness: null, height: null, pack: null, roughness_value: 0.9, detail_amp_m: null, detail_kind: null, ...(m as Partial<Material>) } as Material));   // ملفات قديمة بلا PBR
      p.atmosphere = { ...defaultAtmosphere(), ...(p.atmosphere ?? {}) };          // الملفات القديمة بلا جو
      p.export = { ...defaultProject().export, ...(p.export ?? {}) };              // ملفات قديمة بلا إعدادات GLB
      setProject(p); setSel(null);
      const refs = p.materials.map((m) => m.pack).filter((x): x is string => !!x && x.startsWith("cc0:"));
      if (refs.length) texEnsure(refs).then((rs) => { const bad = rs.filter((r) => !r.ok); if (bad.length) setNotice(`تعذّر تنزيل ${bad.length} خامة CC0 (ستظهر بألوانها): ${bad[0].error ?? ""}`); }).catch(() => undefined);
    } catch (e) { setErr(String((e as Error).message)); }
  };

  const cells = `${Math.ceil(w.size_x_m / w.cell_size_m)}×${Math.ceil(w.size_y_m / w.cell_size_m)}`;
  const longest = Math.max(w.size_x_m, w.size_y_m), mpp = longest / (project.export.resolution - 1);
  const tilesX = Math.ceil(w.size_x_m / w.chunk_size_m), tilesY = Math.ceil(w.size_y_m / w.chunk_size_m), tmpp = w.chunk_size_m / (project.export.tile_px - 1);
  const liSel = selLine ? preview?.linear.find((l) => l.id === selLine.id) : null;
  const pm = selPoint ? POINT_META[selPoint.kind] : null;
  const hasErrors = !!preview?.errors.length;
  const mats = project.materials;
  const setMat = (id: string, patch: Partial<Material>) => set((p) => Object.assign(p.materials.find((m) => m.id === id)!, patch));
  const addMat = () => { const id = uid("مادة", mats.map((m) => m.id)); set((p) => p.materials.push({ id, name: id, color: "#808080", albedo: null, normal: null, roughness: null, height: null, pack: null, roughness_value: 0.9, tile_m: 10, detail_amp_m: null, detail_kind: null })); setMatSel(id); };
  const delMat = (id: string) => set((p) => {
    p.materials = p.materials.filter((m) => m.id !== id);
    const fix = (v: string | null) => (v === id ? null : v);
    p.points.forEach((f) => { f.mat_low = fix(f.mat_low); f.mat_mid = fix(f.mat_mid); f.mat_high = fix(f.mat_high); });
    p.lines.forEach((f) => { f.mat_main = fix(f.mat_main); f.mat_edge = fix(f.mat_edge); });
    p.sites.forEach((f) => { f.mat_ground = fix(f.mat_ground); }); p.zones.forEach((f) => { f.mat_main = fix(f.mat_main); }); p.biomes.forEach((f) => { f.mat_base = fix(f.mat_base); });
    p.paint.slope_material = fix(p.paint.slope_material); p.paint.snow_material = fix(p.paint.snow_material); p.paint.beach_material = fix(p.paint.beach_material);
    p.derived.convex_material = fix(p.derived.convex_material); p.derived.hollow_material = fix(p.derived.hollow_material); p.derived.wet_material = fix(p.derived.wet_material);
    if (p.paint.default_material === id) p.paint.default_material = p.materials[0]?.id ?? "grass";
  });
  const selMat = mats.find((m) => m.id === matSel) ?? null;
  const kitPieces = project.kit.pieces, selKp = kitPieces.find((k) => k.id === kpSel) ?? null;
  const addKp = (role: KitRole) => { const id = uid("قطعة", kitPieces.map((k) => k.id)); set((p) => { p.kit.pieces.push(newKitPiece(id, role)); }); setKpSel(id); };
  const setKp = (patch: Partial<NonNullable<typeof selKp>>) => set((p) => { const k = p.kit.pieces.find((x) => x.id === kpSel); if (k) Object.assign(k, patch); });
  const csv = (v: string) => v.split(/[ ,،]+/).filter(Boolean);
  const species = project.scatter.species, selSp = species.find((s) => s.id === spSel) ?? null;
  const addSp = (kind: ScatterKind) => { const id = uid("نوع", species.map((s) => s.id)); set((p) => { p.scatter.species.push(defaultSpecies(id, kind)); }); setSpSel(id); };
  const setSp = (patch: Partial<NonNullable<typeof selSp>>) => set((p) => { const s = p.scatter.species.find((x) => x.id === spSel); if (s) Object.assign(s, patch); });
  const optNum = (v: string): number | null => (v.trim() === "" || isNaN(Number(v)) ? null : Number(v));
  const kindsOf = (g: "pos" | "neg" | "special") => (Object.keys(POINT_META) as PointKind[]).filter((k) => POINT_META[k].group === g);

  return (
    <div className={`app${sideOpen ? "" : " side-closed"}`}>
      <header className="top">
        <button className="icon ghost" title={sideOpen ? "إخفاء اللوحة" : "إظهار اللوحة"} aria-label="اللوحة الجانبية" aria-pressed={sideOpen} onClick={() => setSideOpen((o) => !o)}>☰</button>
        <div className="logo"><i />TerrainForge</div>
        <input className="title" aria-label="اسم المشروع" value={project.name} onChange={(e) => set((p) => { p.name = e.target.value; })} />
        <nav className="tabs" role="tablist">{TABS.map(([t, l]) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{l}</button>)}</nav>
        <button className="icon ghost" title={theme === "dark" ? "الثيم الفاتح" : "الثيم الغامق"} aria-label="تبديل الثيم" onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}>{theme === "dark" ? "☀" : "☾"}</button>
        <button className="top3d" onClick={() => setShow3d(true)} disabled={hasErrors} title="معاينة العالم ثلاثياً (نفس ملف GLB المُصدَّر)">معاينة 3D</button>
      </header>
      <div className="mainrow">
      <aside className={`panel tab-${tab}`}>
        <div className="panel-body" onClick={(e) => {
          const h = (e.target as HTMLElement).closest("h2"); if (!h) return;
          const closed = h.classList.toggle("closed");
          for (let n = h.nextElementSibling; n && n.tagName !== "H2"; n = n.nextElementSibling) (n as HTMLElement).hidden = closed;
        }}>

        <section data-tab="world">
          <h2>العالم</h2>
          <Field label="العرض شرق–غرب (م)"><Num value={w.size_x_m} min={100} step={500} onChange={(v) => set((p) => { p.world.size_x_m = v; })} /></Field>
          <Field label="الطول شمال–جنوب (م)"><Num value={w.size_y_m} min={100} step={500} onChange={(v) => set((p) => { p.world.size_y_m = v; })} /></Field>
          <Field label="حجم الخلية (م)"><Num value={w.cell_size_m} min={1} step={10} onChange={(v) => set((p) => { p.world.cell_size_m = v; })} /></Field>
          <Field label="المنطقة المحمّلة / المربع (م)"><Num value={w.chunk_size_m} min={1} step={256} onChange={(v) => set((p) => { p.world.chunk_size_m = v; })} /></Field>
          <Field label="مستوى البحر (م)"><Num value={w.sea_level_m} onChange={(v) => set((p) => { p.world.sea_level_m = v; })} /></Field>
          <Field label="Seed"><Num value={w.seed} onChange={(v) => set((p) => { p.world.seed = Math.round(v); })} /></Field>
          <p className="hint">{cells} خلية · {worldKm2.toFixed(2)} كم² · الخط البرتقالي = حدود المنطقة المحمّلة ({tilesX}×{tilesY})</p>
        </section>

        <section data-tab="world">
          <h2>الأرض الافتراضية (خارج أي منطقة)</h2>
          <Field label="منسوب العالم (م)"><Num value={project.base.elevation_m} onChange={(v) => set((p) => { p.base.elevation_m = v; })} /></Field>
          <Field label="الضوضاء">
            <select value={project.base.noise_mode} onChange={(e) => set((p) => { p.base.noise_mode = e.target.value as Project["base"]["noise_mode"]; })}>
              <option value="off">مغلقة: كل العالم بمنسوب واحد</option><option value="range">نطاق ارتفاع (منسجمة مع المعالم)</option><option value="amplitude">سعة حول المنسوب</option></select></Field>
          {project.base.noise_mode === "amplitude" && <Field label="سعة الضوضاء (م)"><Num value={project.base.noise_amplitude_m} min={0} onChange={(v) => set((p) => { p.base.noise_amplitude_m = v; })} /></Field>}
          {project.base.noise_mode === "range" && <>
            <Field label="من ارتفاع (م)"><Num value={project.base.noise_min_m} onChange={(v) => set((p) => { p.base.noise_min_m = v; })} /></Field>
            <Field label="إلى ارتفاع (م)"><Num value={project.base.noise_max_m} onChange={(v) => set((p) => { p.base.noise_max_m = v; })} /></Field>
            <Field label="تتبّع المعالم (0–1)"><Num value={project.base.noise_bias} step={0.1} min={0} max={1} onChange={(v) => set((p) => { p.base.noise_bias = Math.min(1, Math.max(0, v)); })} /></Field>
            <p className="hint">تولّد الأداة الارتفاعات بين الحدّين: أعلى قرب الجبال والسلاسل، وأخفض قرب الوديان والمنخفضات، وحرّة في السهول. ضعها بعد رسم المعالم.</p></>}
          {project.base.noise_mode !== "off" && <Field label="حجم التفصيلة (م)"><Num value={project.base.noise_scale_m} min={10} step={100} onChange={(v) => set((p) => { p.base.noise_scale_m = v; })} /></Field>}
          <Field label="تنعيم حدود الخلايا (0.05–0.5)"><Num value={project.base.cell_blend} step={0.05} min={0.05} max={0.5} onChange={(v) => set((p) => { p.base.cell_blend = Math.min(0.5, Math.max(0.05, v)); })} /></Field>
          <Field label="تفصيل داخل الخلايا (0–1)"><Num value={project.base.cell_detail} step={0.1} min={0} max={1} onChange={(v) => set((p) => { p.base.cell_detail = Math.min(1, Math.max(0, v)); })} /></Field>
        </section>

        <section className="late" data-tab="design">
          <h2>المناطق (Biomes)</h2>
          <p className="hint">{project.biomes.length} منطقة. ارسم منطقة بأداة «منطقة»، أو قسّم العالم تلقائياً بمساحات محددة:</p>
          <Field label="عدد المناطق"><Num value={autoN} min={2} max={12} onChange={(v) => openAuto(Math.min(12, Math.max(2, Math.round(v))))} /></Field>
          {autoAreas.length === autoN && autoAreas.map((a, i) => (
            <Field key={i} label={`مساحة ${i + 1} (كم²)`}><Num value={a} step={0.5} min={0.01} onChange={(v) => setAutoAreas((arr) => arr.map((q, j) => (j === i ? v : q)))} /></Field>))}
          {autoAreas.length === autoN && <p className="hint">المجموع {autoAreas.reduce((a, b) => a + b, 0).toFixed(2)} من {worldKm2.toFixed(2)} كم²</p>}
          <button onClick={() => (autoAreas.length === autoN ? applyAuto() : openAuto(autoN))}>{autoAreas.length === autoN ? "تقسيم العالم (يستبدل المناطق)" : "إعداد المساحات"}</button>
          <ul className="list">{project.biomes.map((b) => <li key={b.id}><button className={selBiome?.id === b.id ? "on" : ""} onClick={() => setSel({ t: "biome", id: b.id })}>{b.name} · {(polyArea(b.polygon) / 1e6).toFixed(2)} كم²</button></li>)}</ul>
        </section>

        <section data-tab="design">
          <h2>الأدوات</h2>
          {mode === "point" && (<>
            {(["pos", "neg", "special"] as const).map((g) => (
              <div key={g}><p className="hint">{g === "pos" ? "بارزة" : g === "neg" ? "منخفضة" : "سطحية"}</p>
                <div className="kinds">{kindsOf(g).map((k) => <button key={k} className={pointKind === k ? "on" : ""} onClick={() => setPointKind(k)}>{POINT_META[k].label}</button>)}</div></div>))}
            <p className="hint">انقر موضع المركز. القيم الافتراضية تُشتق من ارتفاع الأرض عند النقر. التداخل الكامل المنطقي فقط مسموح (بحيرة فوق هضبة…).</p>
            {POINT_META[pointKind].note && <p className="hint">{POINT_META[pointKind].note}</p>}</>)}
          {mode === "line" && (<>
            <div className="kinds">{(Object.keys(LINE_META) as LineKind[]).map((k) => <button key={k} className={lineKind === k ? "on" : ""} onClick={() => setLineKind(k)}>{LINE_META[k].label}</button>)}</div>
            <p className="hint">انقر لإضافة نقاط المسار (النهر: من المنبع للمصب · الجرف: اليسار من اتجاه الرسم مرتفع). نقر مزدوج أو Enter للإنهاء، Esc للإلغاء. ({draft.length} نقطة)</p>
            {draft.length >= 2 && <button className="primary" onClick={finishDraft}>إنهاء المسار</button>}</>)}
          {mode === "biome" && (<>
            <div className="kinds">{BIOME_PRESETS.map((b, i) => <button key={b.label} className={biomePreset === i ? "on" : ""} onClick={() => setBiomePreset(i)}>{b.label}</button>)}</div>
            <p className="hint">انقر رؤوس المنطقة (3 على الأقل) ثم نقراً مزدوجاً أو Enter. ({draft.length} نقطة)</p>
            {draft.length >= 3 && <button className="primary" onClick={finishDraft}>إنهاء المنطقة</button>}</>)}
          {mode === "poi" && (<>
            <div className="kinds">{(Object.keys(POI_META) as PoiKind[]).map((k) => <button key={k} className={poiKind === k ? "on" : ""} onClick={() => setPoiKind(k)}>{POI_META[k].icon} {POI_META[k].label}</button>)}</div>
            <p className="hint">انقر موضع العنصر. {POI_META[poiKind].note}</p></>)}
          {mode === "route" && (<>
            <div className="kinds"><button className={routeKind === "road" ? "on" : ""} onClick={() => { setRouteKind("road"); setDraft([]); }}>طريق</button><button className={routeKind === "river" ? "on" : ""} onClick={() => { setRouteKind("river"); setDraft([]); }}>نهر</button></div>
            {routeKind === "road" && <Field label="أقصى ميل مطلوب (%)"><Num value={routeGrade} min={1} max={60} onChange={(v) => setRouteGrade(Math.min(60, Math.max(1, v)))} /></Field>}
            <p className="hint">{routeKind === "road" ? "انقر البداية والنهاية (ونقاط عبور إن أردت) ثم «توليد». يتجنب الماء والجبال ويقلّل الميل والقطع/الردم." : "انقر المنبع فقط (يذهب للبحر أو الأخفض) أو المنبع ثم المصب. يهبط دائماً ولا يخترق قلب جبل."} ({draft.length} نقطة)</p>
            <button className="primary" disabled={busy} onClick={generateRoute}>{busy ? "جارٍ الحساب…" : "توليد المسار"}</button>
            {routeInfo && <p className="hint">آخر مسار: {(routeInfo.length_m / 1000).toFixed(2)} كم · أقصى ميل {(routeInfo.max_grade * 100).toFixed(1)}% · صعود {routeInfo.climb_m.toFixed(0)} م {routeInfo.notes.join(" · ")}</p>}</>)}
          {mode === "site" && (<>
            <div className="kinds">{(Object.keys(SITE_META) as SiteKind[]).map((k) => <button key={k} className={siteKind === k ? "on" : ""} onClick={() => setSiteKind(k)}>{SITE_META[k].icon} {SITE_META[k].label}</button>)}</div>
            <p className="hint">انقر موضع المركز: تُسوّى الأرض داخل البصمة إلى منسوب واحد وتُنعَّم حولها لوضع المباني.</p>
            <button disabled={busy} onClick={findSites}>اقترح 5 مواقع بأقل تسوية</button>
            {cands && <ul className="list">{cands.map((c, i) => <li key={i}><button onClick={() => placeCandidate(c)}>{i + 1}. قطع {Math.round(c.cut_m3 / 1000)}k + ردم {Math.round(c.fill_m3 / 1000)}k م³ · تفاوت {c.rms_m} م</button></li>)}{cands.length === 0 && <li className="hint">لا موقع مناسب (الماء أو الجبال أو المواقع الأخرى تشغل الأرض).</li>}</ul>}</>)}
          {mode === "zone" && (<>
            <div className="kinds">{(Object.keys(ZONE_META) as ZoneLayer[]).map((k) => <button key={k} className={zoneLayer === k ? "on" : ""} onClick={() => setZoneLayer(k)}>{ZONE_META[k].label}</button>)}</div>
            <p className="hint">انقر رؤوس المنطقة (3 على الأقل) ثم نقراً مزدوجاً أو Enter. ({draft.length} نقطة) — الأنواع «تضاريس» تغيّر الارتفاع، والبقية تنتج أقنعة كثافة.</p>
            {draft.length >= 3 && <button className="primary" onClick={finishDraft}>إنهاء المنطقة</button>}</>)}
          {mode === "cell" && <p className="hint">انقر خلية لإدخال ارتفاعها وميلها.</p>}
          {mode === "profile" && <p className="hint">انقر نقطتين (A ثم B) لرسم مقطع عرضي.</p>}
        </section>

        {mode === "cell" && cellSel && cellDraft && (
          <section className="editor" data-tab="design">
            <h2>الخلية ({cellSel.col}, {cellSel.row})</h2>
            <Field label="الارتفاع عند المركز (م)"><Num value={cellDraft.elevation_m} onChange={(v) => setCellDraft({ ...cellDraft, elevation_m: v })} /></Field>
            <Field label="مقدار التغير الرأسي (م)"><Num value={cellDraft.rise_m} step={0.5} onChange={(v) => setCellDraft({ ...cellDraft, rise_m: v })} /></Field>
            <Field label="لكل مسافة أفقية (م)"><Num value={cellDraft.run_m} min={1} step={10} onChange={(v) => setCellDraft({ ...cellDraft, run_m: Math.max(1, v) })} /></Field>
            <Field label="اتجاه الصعود (°)"><Num value={cellDraft.aspect_deg} min={0} max={360} step={15} onChange={(v) => setCellDraft({ ...cellDraft, aspect_deg: v })} /></Field>
            <div className="row">{DIRS.map(([l, a]) => <button key={l} className={cellDraft.aspect_deg === a ? "on" : ""} onClick={() => setCellDraft({ ...cellDraft, aspect_deg: a })}>{l}</button>)}</div>
            <p className="hint">الميل = {((cellDraft.rise_m / cellDraft.run_m) * 100).toFixed(2)}%. تُولَّد نقاط مستوية بهذا الميل داخل الخلية بدقة التصدير (حتى 1×1 م)، ثم تُنعَّم على حدودها مع الخلايا المجاورة.</p>
            <div className="row"><button className="primary" onClick={applyCell}>تطبيق</button><button onClick={clearCell}>مسح التعديل</button></div>
          </section>
        )}

        {selPoi && (
          <section className="editor" data-tab="design">
            <h2>{POI_META[selPoi.kind].icon} {POI_META[selPoi.kind].label} · {selPoi.id}</h2>
            <input className="title" value={selPoi.name} onChange={(e) => setPoi({ name: e.target.value })} />
            <Field label="النوع"><select value={selPoi.kind} onChange={(e) => setPoi({ kind: e.target.value as PoiKind })}>{(Object.keys(POI_META) as PoiKind[]).map((k) => <option key={k} value={k}>{POI_META[k].label}</option>)}</select></Field>
            <Field label="نصف قطر المنطقة (م، 0 = نقطة)"><Num value={selPoi.radius_m} min={0} step={10} onChange={(v) => setPoi({ radius_m: Math.max(0, v) })} /></Field>
            <Field label="ترتيب المرور (0 = خارج المسار)"><Num value={selPoi.order} min={0} onChange={(v) => setPoi({ order: Math.max(0, Math.round(v)) })} /></Field>
            <Field label="الصعوبة (1–10)"><Num value={selPoi.difficulty} min={1} max={10} onChange={(v) => setPoi({ difficulty: Math.min(10, Math.max(1, Math.round(v))) })} /></Field>
            <Field label="مستوى اللاعب (من / إلى)"><span className="pair"><Num value={selPoi.level_min} min={1} onChange={(v) => setPoi({ level_min: Math.max(1, Math.round(v)) })} /><Num value={selPoi.level_max} min={1} onChange={(v) => setPoi({ level_max: Math.max(1, Math.round(v)) })} /></span></Field>
            <Field label="المكوث المتوقع (دقيقة)"><Num value={selPoi.dwell_min} min={0} step={0.5} onChange={(v) => setPoi({ dwell_min: Math.max(0, v) })} /></Field>
            <Field label="ارتفاع المعلم المرئي (م)"><Num value={selPoi.landmark_height_m} min={0} onChange={(v) => setPoi({ landmark_height_m: Math.max(0, v) })} /></Field>
            {selPoi.radius_m > 0 && <><label className="check"><input type="checkbox" checked={selPoi.flatten} onChange={(e) => setPoi({ flatten: e.target.checked })} /> تسوية الأرض داخل المنطقة (حلبة مستوية)</label>
              {selPoi.flatten && <Field label="عرض الانتقال (م)"><Num value={selPoi.blend_m} min={1} step={5} onChange={(v) => setPoi({ blend_m: Math.max(1, v) })} /></Field>}</>}
            <input className="title" placeholder="ملاحظات" value={selPoi.notes} onChange={(e) => setPoi({ notes: e.target.value })} />
            <div className="row"><button disabled={busy} onClick={runView}>تحليل الرؤية من هنا</button><button className="danger" onClick={() => { set((p) => { p.pois = p.pois.filter((f) => f.id !== selPoi.id); }); setSel(null); }}>حذف</button></div>
            {viewInfo && <p className="hint">{viewInfo} <button onClick={() => { setViewC(null); setViewInfo(null); }}>إخفاء</button></p>}
          </section>
        )}

        {selSite && (
          <section className="editor" data-tab="design">
            <h2>{SITE_META[selSite.kind].icon} {SITE_META[selSite.kind].label} · {selSite.id}</h2>
            <input className="title" value={selSite.name} onChange={(e) => setS({ name: e.target.value })} />
            <Field label="النوع"><select value={selSite.kind} onChange={(e) => setS({ kind: e.target.value as SiteKind })}>{(Object.keys(SITE_META) as SiteKind[]).map((k) => <option key={k} value={k}>{SITE_META[k].label}</option>)}</select></Field>
            <Field label="الشكل"><select value={selSite.shape} onChange={(e) => setS({ shape: e.target.value as Site["shape"] })}><option value="circle">دائري</option><option value="rect">مستطيل</option></select></Field>
            {selSite.shape === "circle" ? <Field label="القطر (م)"><Num value={selSite.diameter_m} min={1} step={10} onChange={(v) => setS({ diameter_m: Math.max(1, v) })} /></Field> : <>
              <Field label="العرض (م)"><Num value={selSite.width_m} min={1} step={10} onChange={(v) => setS({ width_m: Math.max(1, v) })} /></Field>
              <Field label="الطول (م)"><Num value={selSite.length_m} min={1} step={10} onChange={(v) => setS({ length_m: Math.max(1, v) })} /></Field>
              <Field label="الدوران (°)"><Num value={selSite.rotation_deg} step={15} onChange={(v) => setS({ rotation_deg: v })} /></Field></>}
            <Field label="منسوب التسوية"><select value={selSite.level_mode} onChange={(e) => setS({ level_mode: e.target.value as Site["level_mode"] })}>
              <option value="mean">متوسط الأرض (قطع وردم متوازنان)</option><option value="min">أخفض نقطة (قطع فقط)</option><option value="max">أعلى نقطة (ردم فقط)</option><option value="fixed">منسوب ثابت</option></select></Field>
            {selSite.level_mode === "fixed" && <Field label="المنسوب (م)"><Num value={selSite.level_m} onChange={(v) => setS({ level_m: v })} /></Field>}
            <Field label="إزاحة المنسوب (م)"><Num value={selSite.level_offset_m} onChange={(v) => setS({ level_offset_m: v })} /></Field>
            <Field label="عرض الانتقال (م)"><Num value={selSite.blend_m} min={1} step={10} onChange={(v) => setS({ blend_m: Math.max(1, v) })} /></Field>
            <MatSel label="مادة الأرض" value={selSite.mat_ground} mats={mats} onChange={(v) => setS({ mat_ground: v })} />
            <Field label="كثافة المباني المقترحة (0–1)"><Num value={selSite.density} step={0.1} min={0} max={1} onChange={(v) => setS({ density: Math.min(1, Math.max(0, v)) })} /></Field>
            <label className="check"><input type="checkbox" checked={showLots} onChange={(e) => { setShowLots(e.target.checked); if (e.target.checked) lotsApi(project, selSite.id).then(setLots).catch((er) => setErr(String(er.message))); else setLots(null); }} /> عرض أماكن المباني المقترحة ({lots?.length ?? 0})</label>
            <Field label="قوة التسوية (0–1)"><Num value={selSite.strength} step={0.1} min={0} max={1} onChange={(v) => setS({ strength: Math.min(1, Math.max(0, v)) })} /></Field>
            <Field label="X / Y (م)"><span className="pair"><Num value={selSite.x_m} onChange={(v) => setS({ x_m: v })} /><Num value={selSite.y_m} onChange={(v) => setS({ y_m: v })} /></span></Field>
            {embedded ? <button className="primary" onClick={() => openInBim(selSite.id)}>🏗 {selSite.bim_project ? "فتح المباني في BIM Builder" : "ارسم المباني في BIM Builder"}</button>
              : <p className="hint">افتح التطبيق عبر World Studio لرسم مباني هذه المنشأة في BIM Builder.</p>}
            {selSite.bim_project && <p className="hint">مرتبطة بمشروع BIM: <code>{selSite.bim_project}</code></p>}
            <button className="danger" onClick={() => { set((p) => { p.sites = p.sites.filter((f) => f.id !== selSite.id); }); setSel(null); }}>حذف</button>
          </section>
        )}

        {selZone && (
          <section className="editor" data-tab="design">
            <h2>{ZONE_META[selZone.layer].label} · {selZone.id}</h2>
            <input className="title" value={selZone.name} onChange={(e) => setZ({ name: e.target.value })} />
            <Field label="النوع"><select value={selZone.layer} onChange={(e) => setZ({ layer: e.target.value as ZoneLayer })}>{(Object.keys(ZONE_META) as ZoneLayer[]).map((k) => <option key={k} value={k}>{ZONE_META[k].label}</option>)}</select></Field>
            <p className="hint">المساحة {(polyArea(selZone.polygon) / 1e6).toFixed(3)} كم² · اسحب المربعات الصفراء لتشكيلها.</p>
            <MatSel label="المادة" value={selZone.mat_main} mats={mats} onChange={(v) => setZ({ mat_main: v })} />
            <Field label="الكثافة (0–1)"><Num value={selZone.density} step={0.1} min={0} max={1} onChange={(v) => setZ({ density: Math.min(1, Math.max(0, v)) })} /></Field>
            <Field label="تدرّج الحافة (م)"><Num value={selZone.falloff_m} min={0} step={10} onChange={(v) => setZ({ falloff_m: Math.max(0, v) })} /></Field>
            {ZONE_META[selZone.layer].relief ? <>
              <Field label="سعة التضاريس (م)"><Num value={selZone.amplitude_m} step={0.5} min={0} onChange={(v) => setZ({ amplitude_m: Math.max(0, v) })} /></Field>
              <Field label="طول الموجة (م)"><Num value={selZone.wavelength_m} min={1} step={5} onChange={(v) => setZ({ wavelength_m: Math.max(1, v) })} /></Field></> : <>
              <Field label="أقصى ميل (°)"><Num value={selZone.max_slope_deg} min={0} max={90} step={5} onChange={(v) => setZ({ max_slope_deg: Math.min(90, Math.max(0, v)) })} /></Field>
              <Field label="التكتّل (0–1)"><Num value={selZone.patchiness} step={0.1} min={0} max={1} onChange={(v) => setZ({ patchiness: Math.min(1, Math.max(0, v)) })} /></Field>
              <OptNum label="أدنى ارتفاع (م)" value={selZone.min_elev_m} def={project.world.sea_level_m} onChange={(v) => setZ({ min_elev_m: v })} />
              <OptNum label="أقصى ارتفاع (م)" value={selZone.max_elev_m} def={project.world.sea_level_m + 500} onChange={(v) => setZ({ max_elev_m: v })} /></>}
            <button className="danger" onClick={() => { set((p) => { p.zones = p.zones.filter((f) => f.id !== selZone.id); }); setSel(null); }}>حذف</button>
          </section>
        )}

        {selBiome && (
          <section className="editor" data-tab="design">
            <h2>منطقة · {selBiome.id}</h2>
            <input className="title" value={selBiome.name} onChange={(e) => setB({ name: e.target.value })} />
            <div className="kinds">{BIOME_PRESETS.map((pr) => <button key={pr.label} onClick={() => setB({ base_elevation_m: pr.base, noise_amplitude_m: pr.amp, noise_scale_m: pr.scale, min_elev_m: pr.min ?? null, max_elev_m: pr.max ?? null })}>{pr.label}</button>)}</div>
            <p className="hint">المساحة {(polyArea(selBiome.polygon) / 1e6).toFixed(3)} كم² · اسحب المربعات الصفراء لتشكيل الحدود.</p>
            <MatSel label="مادة المنطقة" value={selBiome.mat_base} mats={mats} onChange={(v) => setB({ mat_base: v })} />
            <Field label="ارتفاع الأرض (م)"><Num value={selBiome.base_elevation_m} onChange={(v) => setB({ base_elevation_m: v })} /></Field>
            <Field label="سعة الضوضاء (م)"><Num value={selBiome.noise_amplitude_m} min={0} onChange={(v) => setB({ noise_amplitude_m: Math.max(0, v) })} /></Field>
            <Field label="حجم التفصيلة (م)"><Num value={selBiome.noise_scale_m} min={10} step={100} onChange={(v) => setB({ noise_scale_m: Math.max(10, v) })} /></Field>
            <Field label="عرض الانتقال (م)"><Num value={selBiome.blend_m} min={1} step={50} onChange={(v) => setB({ blend_m: Math.max(1, v) })} /></Field>
            <OptNum label="حد أقصى للارتفاع (م)" value={selBiome.max_elev_m} def={selBiome.base_elevation_m + 100} onChange={(v) => setB({ max_elev_m: v })} />
            <OptNum label="حد أدنى للارتفاع (م)" value={selBiome.min_elev_m} def={selBiome.base_elevation_m - 100} onChange={(v) => setB({ min_elev_m: v })} />
            <label className="check"><input type="checkbox" checked={selBiome.clamp} onChange={(e) => setB({ clamp: e.target.checked })} /> قصّ تلقائي عند الحدود (بدل الخطأ)</label>
            <button className="danger" onClick={() => { set((p) => { p.biomes = p.biomes.filter((b) => b.id !== selBiome.id); }); setSel(null); }}>حذف المنطقة</button>
          </section>
        )}

        {selPoint && pm && (
          <section className="editor" data-tab="design">
            <h2>{pm.label} · {selPoint.id}</h2>
            <Field label="القطر (م)"><Num value={selPoint.diameter_m} min={1} step={100} onChange={(v) => setP({ diameter_m: Math.max(1, v) })} /></Field>
            <p className="hint">المساحة = {((Math.PI * (selPoint.diameter_m / 2) ** 2) / 1e6).toFixed(3)} كم² (تُرسم بنفس القطر والمقياس)</p>
            {!pm.noHL && <>
              <Field label={pm.hi}><Num value={selPoint.high_m} onChange={(v) => setP({ high_m: v })} /></Field>
              <Field label={pm.lo}><Num value={selPoint.low_m} onChange={(v) => setP({ low_m: v })} /></Field></>}
            {pm.shape && <Field label="الشكل"><select value={selPoint.shape} onChange={(e) => setP({ shape: e.target.value as PointFeature["shape"] })}>
              <option value="cone">مخروطي</option><option value="dome">قبّة</option><option value="rugged">وعر</option></select></Field>}
            {pm.inner && <Field label={pm.inner[0]}><Num value={selPoint.inner_ratio} step={0.05} min={0} max={0.9} onChange={(v) => setP({ inner_ratio: Math.min(0.9, Math.max(0, v)) })} /></Field>}
            {pm.depth && <Field label="عمق الفوهة (نسبة)"><Num value={selPoint.depth_ratio} step={0.05} min={0} max={0.9} onChange={(v) => setP({ depth_ratio: Math.min(0.9, Math.max(0, v)) })} /></Field>}
            {pm.amp && <Field label={pm.amp}><Num value={selPoint.amplitude_m} min={0} onChange={(v) => setP({ amplitude_m: Math.max(0, v) })} /></Field>}
            {pm.wave && <Field label={pm.wave}><Num value={selPoint.wavelength_m} min={1} onChange={(v) => setP({ wavelength_m: Math.max(1, v) })} /></Field>}
            {pm.dir && <Field label={pm.dir}><Num value={selPoint.direction_deg} min={0} max={360} step={15} onChange={(v) => setP({ direction_deg: v })} /></Field>}
            {pm.steps && <Field label={pm.steps}><Num value={selPoint.steps} min={1} max={40} onChange={(v) => setP({ steps: Math.min(40, Math.max(1, Math.round(v))) })} /></Field>}
            <Field label="الوعورة (0–1)"><Num value={selPoint.roughness} step={0.1} min={0} max={1} onChange={(v) => setP({ roughness: Math.min(1, Math.max(0, v)) })} /></Field>
            <MatSel label={pm.neg ? "مادة القاع" : "مادة السفح"} value={selPoint.mat_low} mats={mats} onChange={(v) => setP({ mat_low: v })} />
            {selPoint.kind !== "dune" && <><MatSel label={pm.neg ? "مادة الجدار" : "مادة المنتصف"} value={selPoint.mat_mid} mats={mats} onChange={(v) => setP({ mat_mid: v })} />
            <MatSel label={pm.neg ? "مادة الحافة" : "مادة القمة"} value={selPoint.mat_high} mats={mats} onChange={(v) => setP({ mat_high: v })} /></>}
            <Field label="X / Y (م)"><span className="pair"><Num value={selPoint.x_m} onChange={(v) => setP({ x_m: v })} /><Num value={selPoint.y_m} onChange={(v) => setP({ y_m: v })} /></span></Field>
            <Field label="Seed"><Num value={selPoint.seed} onChange={(v) => setP({ seed: Math.round(v) })} /></Field>
            {pm.note && <p className="hint">{pm.note}</p>}
            <button className="danger" onClick={() => { set((p) => { p.points = p.points.filter((f) => f.id !== selPoint.id); }); setSel(null); }}>حذف</button>
          </section>
        )}

        {selLine && (
          <section className="editor" data-tab="design">
            <h2>{LINE_META[selLine.kind].label} · {selLine.id}</h2>
            <Field label={LINE_META[selLine.kind].widthLabel}><Num value={selLine.width_m} min={1} onChange={(v) => setL({ width_m: Math.max(1, v) })} /></Field>
            {(selLine.kind === "river" || selLine.kind === "valley" || selLine.kind === "ridge") &&
              <Field label="العرض عند النهاية (م)"><Num value={selLine.width_end_m ?? selLine.width_m} min={1} onChange={(v) => setL({ width_end_m: Math.max(1, v) })} /></Field>}
            {LINE_META[selLine.kind].depth && <Field label={LINE_META[selLine.kind].depth!}><Num value={selLine.depth_m} min={0} onChange={(v) => setL({ depth_m: Math.max(0, v) })} /></Field>}
            {selLine.kind === "cliff" && <><Field label="عرض الحافة المرتفعة (م)"><Num value={selLine.shoulder_m} min={1} onChange={(v) => setL({ shoulder_m: Math.max(1, v) })} /></Field>
              <p className="hint">الجهة اليسرى من اتجاه الرسم هي المرتفعة. «عكس الاتجاه» يبدّل الجهتين.</p></>}
            {selLine.kind === "river" && <>
              <Field label="أقل ميل للقاع (م/م)"><Num value={selLine.min_slope} step={0.0001} min={0} onChange={(v) => setL({ min_slope: Math.max(0, v) })} /></Field>
              <Field label="معالجة الأرض"><select value={selLine.grade_mode} onChange={(e) => setL({ grade_mode: e.target.value as "regrade" | "carve" })}>
                <option value="regrade">تعديل مناسيب الأرض (وادٍ طبيعي)</option><option value="carve">حفر خندق</option></select></Field>
              {selLine.grade_mode === "regrade"
                ? <Field label="عرض التدرج الجانبي (م)"><Num value={selLine.grade_width_m} min={0} step={10} onChange={(v) => setL({ grade_width_m: Math.max(0, v) })} /></Field>
                : <label className="check"><input type="checkbox" checked={selLine.enforce_descent} onChange={(e) => setL({ enforce_descent: e.target.checked })} /> فرض انحدار القاع (الماء لا يصعد)</label>}
              <p className="hint">الشلالات ({selLine.falls.length}):</p>
              {selLine.falls.map((fl: Fall, i: number) => (
                <div className="editor" key={i}>
                  <Field label="الموضع (% من المنبع)"><Num value={Math.round(fl.at * 100)} min={0} max={100} onChange={(v) => setL({ falls: selLine.falls.map((q, j) => (j === i ? { ...q, at: Math.min(1, Math.max(0, v / 100)) } : q)) })} /></Field>
                  <Field label="الارتفاع (م)"><Num value={fl.height_m} min={1} onChange={(v) => setL({ falls: selLine.falls.map((q, j) => (j === i ? { ...q, height_m: Math.max(1, v) } : q)) })} /></Field>
                  <Field label="الطول (م)"><Num value={fl.length_m} min={1} onChange={(v) => setL({ falls: selLine.falls.map((q, j) => (j === i ? { ...q, length_m: Math.max(1, v) } : q)) })} /></Field>
                  <button className="danger" onClick={() => setL({ falls: selLine.falls.filter((_, j) => j !== i) })}>حذف الشلال</button>
                </div>))}
              <button onClick={() => setL({ falls: [...selLine.falls, { at: 0.5, height_m: 10, length_m: 10 }] })}>إضافة شلال</button></>}
            {selLine.kind === "road" && <>
              <Field label="أقصى ميل (%)"><Num value={+(selLine.max_grade * 100).toFixed(2)} step={1} min={0.5} max={100} onChange={(v) => setL({ max_grade: Math.max(0.005, v / 100) })} /></Field>
              <Field label="عرض الجسر/الميل الجانبي (م)"><Num value={selLine.shoulder_m} min={0} onChange={(v) => setL({ shoulder_m: Math.max(0, v) })} /></Field></>}
            {(selLine.kind === "valley" || selLine.kind === "ridge") && <Field label="المقطع"><select value={selLine.profile} onChange={(e) => setL({ profile: e.target.value as "v" | "u" })}><option value="u">U (ناعم)</option><option value="v">V</option></select></Field>}
            {selLine.kind === "valley" && <OptNum label="منسوب القاع المطلق (م)" value={selLine.floor_m} def={project.base.elevation_m - 100} onChange={(v) => setL({ floor_m: v })} />}
            {selLine.kind === "ridge" && <OptNum label="منسوب القمة المطلق (م)" value={selLine.top_m} def={project.base.elevation_m + 100} onChange={(v) => setL({ top_m: v })} />}
            {(selLine.kind === "valley" || selLine.kind === "ridge") && <p className="hint">عند تفعيل المنسوب المطلق يتجاهل «العمق/الارتفاع»: وادٍ بقاع 50 في عالم منسوبه 200 يُنزل الأرض 150 م.</p>}
            {selLine.kind === "ridge" && <Field label="الوعورة (0–1)"><Num value={selLine.roughness} step={0.1} min={0} max={1} onChange={(v) => setL({ roughness: Math.min(1, Math.max(0, v)) })} /></Field>}
            <MatSel label={selLine.kind === "river" ? "مادة المجرى" : selLine.kind === "road" ? "مادة سطح الطريق" : "المادة الرئيسية"} value={selLine.mat_main} mats={mats} onChange={(v) => setL({ mat_main: v })} />
            {(selLine.kind === "river" || selLine.kind === "road") && <MatSel label={selLine.kind === "river" ? "مادة الضفاف" : "مادة الكتف"} value={selLine.mat_edge} mats={mats} onChange={(v) => setL({ mat_edge: v })} />}
            <p className="hint">{selLine.points.length} نقطة · اسحب المربعات الصفراء لتعديل المسار.</p>
            <div className="row">
              <button onClick={() => setL({ points: [...selLine.points].reverse() as XY[] })}>عكس الاتجاه</button>
              <button className="danger" onClick={() => { set((p) => { p.lines = p.lines.filter((f) => f.id !== selLine.id); }); setSel(null); }}>حذف</button>
            </div>
          </section>
        )}

        <section data-tab="play">
          <h2>اللاعب المتوقع</h2>
          <Field label="السرعة (م/ث)"><Num value={project.player.speed_mps} min={0.5} step={0.5} onChange={(v) => set((p) => { p.player.speed_mps = Math.max(0.5, v); })} /></Field>
          <Field label="ارتفاع العين (م)"><Num value={project.player.eye_height_m} min={0} step={0.1} onChange={(v) => set((p) => { p.player.eye_height_m = Math.max(0, v); })} /></Field>
          <Field label="أقصى ميل يتسلقه (°)"><Num value={project.player.max_slope_deg} min={5} max={80} onChange={(v) => set((p) => { p.player.max_slope_deg = Math.min(80, Math.max(5, v)); })} /></Field>
          <Field label="مدى الرؤية (م)"><Num value={project.player.view_distance_m} min={50} step={100} onChange={(v) => set((p) => { p.player.view_distance_m = Math.max(50, v); })} /></Field>
          <label className="check"><input type="checkbox" checked={project.player.can_swim} onChange={(e) => set((p) => { p.player.can_swim = e.target.checked; })} /> يستطيع السباحة</label>
          <button className="primary" disabled={busy} onClick={() => void runSim()}>{busy ? "جارٍ الحساب…" : "محاكاة رحلة اللاعب"}</button>
          <p className="hint">يبدأ من «نقطة الانطلاق» ويمرّ بعناصر الاهتمام حسب «ترتيب المرور»، بسرعة تتأثر بالميل (Tobler) وبتجنب الماء والمنحدرات التي لا يتسلقها.</p>
          {sim && (<>
            <ul className="stats">
              <li>المسافة: <b>{(sim.totals.distance_m / 1000).toFixed(2)} كم</b></li>
              <li>المشي: <b>{fmtDur(sim.totals.walk_s)}</b> · المكوث: <b>{fmtDur(sim.totals.dwell_s)}</b></li>
              <li>المدة الكلية المتوقعة: <b>{fmtDur(sim.totals.total_s)}</b></li>
              <li>صعود {sim.totals.climb_m.toFixed(0)} م · هبوط {sim.totals.descent_m.toFixed(0)} م · أقصى ميل {sim.totals.max_slope_deg.toFixed(0)}°</li>
              {sim.view.bands_m && <li>مدى النظر على المسار (ن25/50/75/90): <b>{sim.view.bands_m.map((v) => Math.round(v)).join(" / ")} م</b></li>}
            </ul>
            {sim.legs.map((l, i) => <p key={i} className="hint">{i + 1}. {l.from} ← {l.to}: {l.reachable ? `${((l.distance_m ?? 0) / 1000).toFixed(2)} كم · ${fmtDur(l.walk_s ?? 0)}` : "غير قابل للوصول"}</p>)}
            {sim.view.pois_seen.map((s) => <p key={s.id} className="hint">{POI_META[s.kind].icon} {s.name}: {s.ever_seen ? `يُرى لأول مرة عند ${((s.first_seen_at_m ?? 0) / 1000).toFixed(2)} كم من المسار (من ${Math.round(s.first_seen_distance_m ?? 0)} م)` : "لا يُرى من المسار"}</p>)}
            {sim.suggested_lod_distances_m && <p className="hint">مسافات LOD المقترحة من الرؤية: {sim.suggested_lod_distances_m.join(" / ")} م (تُكتب في build.json).</p>}
          </>)}
        </section>

        <section data-tab="play">
          <h2>تتبّع اللاعبين</h2>
          <p className="hint">استورد جلسات لعب حقيقية: JSON (sessions[].samples[{`{t,x,y,yaw?,pitch?}`}], events[]) أو CSV بالأعمدة session,t,x,y[,yaw,pitch][,event].</p>
          <div className="row"><button onClick={() => telRef.current?.click()}>استيراد ملف</button><button onClick={() => void loadSample()}>عينة تجريبية</button>
            <input ref={telRef} type="file" accept=".json,.csv" hidden onChange={(e) => e.target.files?.[0] && void readTel(e.target.files[0])} /></div>
          {tstats && (<>
            <label className="check"><input type="checkbox" checked={showHeat} onChange={(e) => setShowHeat(e.target.checked)} /> خريطة الحرارة</label>
            <label className="check"><input type="checkbox" checked={showTPaths} onChange={(e) => setShowTPaths(e.target.checked)} /> مسارات اللاعبين ونقاط الانسحاب (حمراء)</label>
            <ul className="stats">
              <li>{tstats.sessions} جلسة · متوسط المدة <b>{fmtDur(tstats.meanDuration_s)}</b> (وسيط {fmtDur(tstats.medianDuration_s)})</li>
              <li>متوسط المسافة {(tstats.meanDistance_m / 1000).toFixed(2)} كم · السرعة {tstats.meanSpeed_mps.toFixed(1)} م/ث</li>
              {tstats.adherence_pct !== null && <li>الالتزام بالمسار المتوقع (≤100 م): <b>{tstats.adherence_pct.toFixed(0)}%</b>{sim ? ` · المتوقع ${fmtDur(sim.totals.total_s)}` : ""}</li>}
              {tstats.pitchUp_pct !== null && <li>النظر لأعلى {tstats.pitchUp_pct.toFixed(0)}% · لأسفل {tstats.pitchDown_pct?.toFixed(0)}%</li>}
              <li>الوفيات: {tstats.deaths}</li>
            </ul>
            {tstats.pois.map((q) => <p key={q.id} className="hint">{q.name}: زاره {q.visitPct.toFixed(0)}% · مكوث {Math.round(q.meanDwell_s)}ث{q.meanArrival_s !== null ? ` · وصول بعد ${fmtDur(q.meanArrival_s)}` : ""}{q.lookedAt_s ? ` · نظر إليه ${Math.round(q.lookedAt_s)}ث` : ""}</p>)}
            <p className="hint">«النظر إليه» يقيس اتجاه الكاميرا نحو العنصر (±12°) دون التحقق من الحجب بالتضاريس.</p></>)}
        </section>

        <section data-tab="look">
          <h2>المواد والألوان</h2>
          <ul className="list">{mats.map((m) => (
            <li key={m.id} className="matrow">
              <input type="color" value={m.color} onChange={(e) => setMat(m.id, { color: e.target.value })} aria-label={`لون ${m.name}`} />
              <button className={matSel === m.id ? "on" : ""} onClick={() => setMatSel(m.id)}>{m.name || m.id}</button>
              <button className="danger" onClick={() => delMat(m.id)} aria-label="حذف المادة">✕</button>
            </li>))}</ul>
          <button onClick={addMat}>إضافة مادة</button>
          {selMat && (
            <div className="editor">
              <input className="title" value={selMat.name} onChange={(e) => setMat(selMat.id, { name: e.target.value })} />
              <TexBrowser current={selMat.pack} onPick={(r) => setMat(selMat.id, { pack: r.ref, albedo: null, normal: null, roughness: null, height: null })} />
              <label className="field"><span>مجلد الحزمة</span><input dir="ltr" placeholder="textures/rock_01" value={selMat.pack ?? ""} onChange={(e) => setMat(selMat.id, { pack: e.target.value || null })} /></label>
              <p className="hint">ضع مجلد الحزمة (من ambientCG أو Poly Haven) بجوار build.json: تُكتشف الخرائط تلقائياً من أسماء الملفات (Color/diff، Roughness/rough، Displacement/disp، NormalGL/nor_gl). المسارات أدناه اختيارية وتتغلب على الحزمة.</p>
              <label className="field"><span>Albedo</span><input dir="ltr" placeholder="تلقائي من الحزمة" value={selMat.albedo ?? ""} onChange={(e) => setMat(selMat.id, { albedo: e.target.value || null })} /></label>
              <label className="field"><span>Roughness</span><input dir="ltr" placeholder="تلقائي من الحزمة" value={selMat.roughness ?? ""} onChange={(e) => setMat(selMat.id, { roughness: e.target.value || null })} /></label>
              <label className="field"><span>Height / Displacement</span><input dir="ltr" placeholder="تلقائي من الحزمة" value={selMat.height ?? ""} onChange={(e) => setMat(selMat.id, { height: e.target.value || null })} /></label>
              <label className="field"><span>Normal</span><input dir="ltr" placeholder="تلقائي من الحزمة" value={selMat.normal ?? ""} onChange={(e) => setMat(selMat.id, { normal: e.target.value || null })} /></label>
              <Field label="نوع التفاصيل الدقيقة"><select value={selMat.detail_kind ?? ""} onChange={(e) => setMat(selMat.id, { detail_kind: (e.target.value || null) as DetailKind | null })}>
                <option value="">افتراضي حسب المادة</option><option value="soil">تربة (تموّج ناعم)</option><option value="rock">صخر (حواف وكتل)</option><option value="sand">رمل (تموجات)</option><option value="gravel">حصى</option></select></Field>
              <label className="field"><span>سعة التفاصيل (م)</span><input dir="ltr" placeholder="افتراضي" value={selMat.detail_amp_m ?? ""} onChange={(e) => { const t = e.target.value.trim(); setMat(selMat.id, { detail_amp_m: t === "" || isNaN(Number(t)) ? null : Math.min(20, Math.max(0, Number(t))) }); }} /></label>
              <Field label="خشونة ثابتة (0–1)"><Num value={selMat.roughness_value} step={0.05} min={0} max={1} onChange={(v) => setMat(selMat.id, { roughness_value: Math.min(1, Math.max(0, v)) })} /></Field>
              <Field label="تكرار الخامة كل (م)"><Num value={selMat.tile_m} min={0.1} step={1} onChange={(v) => setMat(selMat.id, { tile_m: Math.max(0.1, v) })} /></Field>
              <p className="hint">كل الخرائط اختيارية: بدون Albedo يُستعمل اللون، وبدون Roughness تُستعمل الخشونة الثابتة. المسارات نسبية لمجلد build.json.</p>
            </div>)}
          <h2>قواعد تلقائية</h2>
          <MatSel label="المادة الافتراضية" value={project.paint.default_material} mats={mats} onChange={(v) => set((p) => { p.paint.default_material = v ?? p.materials[0]?.id ?? "grass"; })} />
          <MatSel label="الميل الشديد" value={project.paint.slope_material} mats={mats} onChange={(v) => set((p) => { p.paint.slope_material = v; })} />
          {project.paint.slope_material && <>
            <Field label="يبدأ عند ميل (°)"><Num value={project.paint.slope_start_deg} min={0} max={89} onChange={(v) => set((p) => { p.paint.slope_start_deg = Math.min(89, Math.max(0, v)); })} /></Field>
            <Field label="كامل عند ميل (°)"><Num value={project.paint.slope_full_deg} min={1} max={90} onChange={(v) => set((p) => { p.paint.slope_full_deg = Math.min(90, Math.max(1, v)); })} /></Field></>}
          <MatSel label="الثلج فوق ارتفاع" value={project.paint.snow_material} mats={mats} onChange={(v) => set((p) => { p.paint.snow_material = v; })} />
          {project.paint.snow_material && <>
            <Field label="خط الثلج (م)"><Num value={project.paint.snow_elev_m} onChange={(v) => set((p) => { p.paint.snow_elev_m = v; })} /></Field>
            <Field label="تدرّج الثلج (م)"><Num value={project.paint.snow_blend_m} min={1} onChange={(v) => set((p) => { p.paint.snow_blend_m = Math.max(1, v); })} /></Field></>}
          <MatSel label="الشاطئ" value={project.paint.beach_material} mats={mats} onChange={(v) => set((p) => { p.paint.beach_material = v; })} />
          {project.paint.beach_material && <Field label="ارتفاع الشاطئ (م)"><Num value={project.paint.beach_height_m} min={0.1} step={0.5} onChange={(v) => set((p) => { p.paint.beach_height_m = Math.max(0.1, v); })} /></Field>}
          <p className="hint">مواد المعالم (أدناه) تتغلب على هذه القواعد. استخدم «عرض: مواد» فوق الخريطة لرؤية النتيجة.</p>
        </section>

        <section data-tab="world">
          <h2>التعرية</h2>
          <label className="check"><input type="checkbox" checked={project.erosion.enabled} onChange={(e) => set((p) => { p.erosion.enabled = e.target.checked; })} /> تفعيل التعرية</label>
          {project.erosion.enabled && <>
            <Field label="دقة الحساب"><select value={project.erosion.resolution} onChange={(e) => set((p) => { p.erosion.resolution = Number(e.target.value) as Project["erosion"]["resolution"]; })}>
              <option value={257}>257 (سريع للتصميم)</option><option value={513}>513</option><option value={1025}>1025 (للتصدير)</option></select></Field>
            <Field label="عدد التكرارات"><Num value={project.erosion.iterations} min={1} max={200} onChange={(v) => set((p) => { p.erosion.iterations = Math.min(200, Math.max(1, Math.round(v))); })} /></Field>
            <Field label="أقصى حت تقريبي (م)"><Num value={project.erosion.max_depth_m} min={0} onChange={(v) => set((p) => { p.erosion.max_depth_m = Math.max(0, v); })} /></Field>
            <Field label="الترسيب (0–0.9)"><Num value={project.erosion.deposition} step={0.1} min={0} max={0.9} onChange={(v) => set((p) => { p.erosion.deposition = Math.min(0.9, Math.max(0, v)); })} /></Field>
            <label className="check"><input type="checkbox" checked={project.erosion.thermal} onChange={(e) => set((p) => { p.erosion.thermal = e.target.checked; })} /> تعرية حرارية (انهيار الركام)</label>
            <Field label="زاوية الاستقرار (°)"><Num value={project.erosion.talus_deg} min={5} max={80} onChange={(v) => set((p) => { p.erosion.talus_deg = Math.min(80, Math.max(5, v)); })} /></Field>
            <Field label="التنعيم (0–1)"><Num value={project.erosion.smooth} step={0.1} min={0} max={1} onChange={(v) => set((p) => { p.erosion.smooth = Math.min(1, Math.max(0, v)); })} /></Field>
            <Field label="الخوارزمية"><select value={project.erosion.mode} onChange={(e) => set((p) => { p.erosion.mode = e.target.value as Project["erosion"]["mode"]; })}>
              <option value="sediment">نقل رواسب (يحفظ الكتلة)</option><option value="stylized">أسلوبية (القديمة)</option></select></Field>
            {project.erosion.mode === "sediment" && <>
              <Field label="قابلية التعرية (0–1)"><Num value={project.erosion.erodibility} step={0.1} min={0} max={1} onChange={(v) => set((p) => { p.erosion.erodibility = Math.min(1, Math.max(0, v)); })} /></Field>
              <Field label="سرعة الترسيب (0–1)"><Num value={project.erosion.deposition_rate} step={0.1} min={0} max={1} onChange={(v) => set((p) => { p.erosion.deposition_rate = Math.min(1, Math.max(0, v)); })} /></Field>
              <label className="check"><input type="checkbox" checked={project.erosion.fans} onChange={(e) => set((p) => { p.erosion.fans = e.target.checked; })} /> مراوح ركامية (ينتشر الترسيب جانبياً)</label>
              {project.erosion.fans && <Field label="انتشار المروحة (م)"><Num value={project.erosion.fan_spread_m} step={10} min={20} max={3000} onChange={(v) => set((p) => { p.erosion.fan_spread_m = Math.min(3000, Math.max(20, v)); })} /></Field>}
              <label className="check"><input type="checkbox" checked={project.erosion.gullies} onChange={(e) => set((p) => { p.erosion.gullies = e.target.checked; })} /> أخاديد على المنحدرات</label>
              {project.erosion.gullies && <>
                <Field label="عمق الأخدود (م)"><Num value={project.erosion.gully_depth_m} step={0.5} min={0} max={30} onChange={(v) => set((p) => { p.erosion.gully_depth_m = Math.min(30, Math.max(0, v)); })} /></Field>
                <Field label="التباعد (م)"><Num value={project.erosion.gully_spacing_m} step={5} min={5} max={500} onChange={(v) => set((p) => { p.erosion.gully_spacing_m = Math.min(500, Math.max(5, v)); })} /></Field>
                <Field label="الطول (خلايا)"><Num value={project.erosion.gully_length_cells} step={2} min={4} max={60} onChange={(v) => set((p) => { p.erosion.gully_length_cells = Math.round(Math.min(60, Math.max(4, v))); })} /></Field>
                <Field label="أدنى ميل (°)"><Num value={project.erosion.gully_min_slope_deg} step={1} min={0} max={80} onChange={(v) => set((p) => { p.erosion.gully_min_slope_deg = Math.min(80, Math.max(0, v)); })} /></Field>
                <Field label="أقصى ميل (°)"><Num value={project.erosion.gully_max_slope_deg} step={1} min={10} max={89} onChange={(v) => set((p) => { p.erosion.gully_max_slope_deg = Math.min(89, Math.max(10, v)); })} /></Field></>}
              <Field label="البذرة"><Num value={project.erosion.seed} step={1} min={0} max={999999} onChange={(v) => set((p) => { p.erosion.seed = Math.round(Math.min(999999, Math.max(0, v))); })} /></Field>
              <p className="hint">كل مجرى يحمل رواسب من أعلاه: يحفر حيث تزيد السعة (ميل ومساحة تصريف) ويرسّب حيث تقل فتتكوّن المراوح عند انكسار الميل، والكتلة محفوظة (مجموع الحفر = مجموع الترسيب، اختُبر). الأخاديد خطوط حفر باتجاه الانحدار على المنحدرات المتوسطة والشديدة (لا تُحفر الجروف ولا المسطحات). «الترسيب» أعلاه للخوارزمية القديمة فقط. أسلوبية وليست معايَرة بمعدلات حقيقية، وأبطأ من القديمة (مرورتان على الشبكة لكل تكرار).</p></>}
            <p className="hint">تعرية أسلوبية غير معايَرة بمعدلات حقيقية. تُطبَّق على الأرض الطبيعية فقط، فالمواقع والطرق والأنهار تبقى كما صُمّمت. التغيير في الأنهار/الطرق/المواقع لا يعيد حسابها.</p></>}
        </section>

        <section data-tab="look">
          <h2>الطرق (كتف وغبار وآثار إطارات)</h2>
          <label className="check"><input type="checkbox" checked={project.roads.enabled} onChange={(e) => set((p) => { p.roads.enabled = e.target.checked; })} /> أقنعة الطرق وظل الطريق الواقعي</label>
          {project.roads.enabled && <>
            <Field label="عرض الحافة المغبرّة (م)"><Num value={project.roads.dust_width_m} step={0.5} min={0} max={50} onChange={(v) => set((p) => { p.roads.dust_width_m = Math.min(50, Math.max(0, v)); })} /></Field>
            <label className="field"><span>لون الغبار</span><input type="color" value={project.roads.dust_color} onChange={(e) => set((p) => { p.roads.dust_color = e.target.value; })} /></label>
            <Field label="المسافة بين العجلتين (م)"><Num value={project.roads.track_gauge_m} step={0.1} min={0.5} max={4} onChange={(v) => set((p) => { p.roads.track_gauge_m = Math.min(4, Math.max(0.5, v)); })} /></Field>
            <Field label="عرض أثر الإطار (م)"><Num value={project.roads.track_width_m} step={0.05} min={0.1} max={2} onChange={(v) => set((p) => { p.roads.track_width_m = Math.min(2, Math.max(0.1, v)); })} /></Field>
            <Field label="قوة الأثر (0–1)"><Num value={project.roads.track_wear} step={0.1} min={0} max={1} onChange={(v) => set((p) => { p.roads.track_wear = Math.min(1, Math.max(0, v)); })} /></Field>
            <Field label="عمق الأثر (م)"><Num value={project.roads.track_depth_m} step={0.01} min={0} max={0.5} onChange={(v) => set((p) => { p.roads.track_depth_m = Math.min(0.5, Math.max(0, v)); })} /></Field>
            <Field label="تفاوت لون السطح (0–1)"><Num value={project.roads.surface_variation} step={0.05} min={0} max={1} onChange={(v) => set((p) => { p.roads.surface_variation = Math.min(1, Math.max(0, v)); })} /></Field>
            <p className="hint">الطرق نفسها (التدرج والكتف والجسر) تُضبط من خصائص الخط: عرض الطريق، «الكتف»، وأقصى ميل. هنا مظهرها: تُصدَّر أقنعة سطح وكتف وحافة مغبرّة غير منتظمة (masks/road_*.png)، وفي Blender يُرسم الطريق بشريط أعرض قليلاً بإحداثيات بالأمتار فيظهر أثر الإطارين مقطّعاً وداكناً ولامعاً وغائراً قليلاً، وبقع تآكل، وغبار يتلاشى على الأطراف. آثار الإطارات أدق من دقة الأقنعة فهي إجرائية في Blender فقط؛ للمحركات تُصدَّر معاييرها (build.json ← road_maps.tire_tracks).</p></>}
        </section>

        <section data-tab="look">
          <h2>الماء</h2>
          <label className="check"><input type="checkbox" checked={project.water.enabled} onChange={(e) => set((p) => { p.water.enabled = e.target.checked; })} /> خرائط الماء وظلال الماء الواقعية</label>
          {project.water.enabled && <>
            <h3>الخرائط المُصدَّرة</h3>
            <Field label="عرض الشاطئ الرطب (م)"><Num value={project.water.shore_width_m} step={1} min={0.5} max={200} onChange={(v) => set((p) => { p.water.shore_width_m = Math.min(200, Math.max(0.5, v)); })} /></Field>
            <Field label="عرض رغوة الحافة (م)"><Num value={project.water.foam_width_m} step={0.5} min={0.2} max={100} onChange={(v) => set((p) => { p.water.foam_width_m = Math.min(100, Math.max(0.2, v)); })} /></Field>
            <Field label="ميل رغوة المنحدرات (°)"><Num value={project.water.rapids_slope_deg} step={1} min={0.5} max={60} onChange={(v) => set((p) => { p.water.rapids_slope_deg = Math.min(60, Math.max(0.5, v)); })} /></Field>
            <Field label="كمية الرغوة (0–1)"><Num value={project.water.foam_amount} step={0.1} min={0} max={1} onChange={(v) => set((p) => { p.water.foam_amount = Math.min(1, Math.max(0, v)); })} /></Field>
            <h3>ظل الماء في Blender</h3>
            <label className="field"><span>لون الضحل</span><input type="color" value={project.water.shallow_color} onChange={(e) => set((p) => { p.water.shallow_color = e.target.value; })} /></label>
            <label className="field"><span>لون العميق</span><input type="color" value={project.water.deep_color} onChange={(e) => set((p) => { p.water.deep_color = e.target.value; })} /></label>
            <Field label="عمق اللون العميق (م)"><Num value={project.water.absorption_depth_m} step={1} min={0.2} max={200} onChange={(v) => set((p) => { p.water.absorption_depth_m = Math.min(200, Math.max(0.2, v)); })} /></Field>
            <Field label="خشونة السطح"><Num value={project.water.roughness} step={0.01} min={0} max={1} onChange={(v) => set((p) => { p.water.roughness = Math.min(1, Math.max(0, v)); })} /></Field>
            <Field label="معامل الانكسار IOR"><Num value={project.water.ior} step={0.01} min={1} max={2} onChange={(v) => set((p) => { p.water.ior = Math.min(2, Math.max(1, v)); })} /></Field>
            <Field label="ارتفاع التموّج (م)"><Num value={project.water.wave_height_m} step={0.05} min={0} max={5} onChange={(v) => set((p) => { p.water.wave_height_m = Math.min(5, Math.max(0, v)); })} /></Field>
            <Field label="حجم التموّج (م)"><Num value={project.water.wave_scale_m} step={1} min={0.5} max={500} onChange={(v) => set((p) => { p.water.wave_scale_m = Math.min(500, Math.max(0.5, v)); })} /></Field>
            <Field label="سرعة التموّج"><Num value={project.water.wave_speed} step={0.1} min={0} max={10} onChange={(v) => set((p) => { p.water.wave_speed = Math.min(10, Math.max(0, v)); })} /></Field>
            <p className="hint">من الارتفاعات والأنهار والبحيرات تُحسب: عمق (16 بت)، شاطئ، رغوة (الحافة + منحدرات النهر)، واتجاه/سرعة تدفق، وتظهر في masks/water_*.png. في Blender يتدرج اللون مع العمق، وتظهر الرغوة عند الحواف والمنحدرات، ويتحرك التموّج مع التدفق (يتطلب تشغيل الأنيميشن). دقتها بدقة الأقنعة (mask_px): الأنهار الأضيق من بكسل تُرسم بعرض بكسل على الأقل.</p></>}
        </section>

        <section data-tab="look">
          <h2>تفاصيل ارتفاع دقيقة (المربعات)</h2>
          <label className="check"><input type="checkbox" checked={project.detail.enabled} onChange={(e) => set((p) => { p.detail.enabled = e.target.checked; })} /> إضافة تفاصيل صخرية وتربة عند تصدير المربعات</label>
          {project.detail.enabled && <>
            <Field label="أطول طول موجة (م)"><Num value={project.detail.wavelength_max_m} step={2} min={2} max={500} onChange={(v) => set((p) => { p.detail.wavelength_max_m = Math.min(500, Math.max(2, v)); })} /></Field>
            <Field label="تضخيم على المنحدرات"><Num value={project.detail.slope_gain} step={0.25} min={0} max={5} onChange={(v) => set((p) => { p.detail.slope_gain = Math.min(5, Math.max(0, v)); })} /></Field>
            <Field label="البذرة"><Num value={project.detail.seed} step={1} min={0} max={999999} onChange={(v) => set((p) => { p.detail.seed = Math.round(Math.max(0, v)); })} /></Field>
            <p className="hint">تُضاف إلى ارتفاعات المربعات فقط (لا إلى الخريطة ولا إلى صورة الارتفاع الواحدة)، بسعة ونوع لكل مادة (محرر المادة) وتتضخم الصخور على المنحدرات. الطرق والمواقع تبقى مستوية، وحواف المربعات تتطابق تماماً. تُهمَل إن كانت دقة المربع أخشن من نصف طول الموجة (≈ دقة 1 م/بكسل أو أدق مناسبة). تتطلب المواد وزناً في المنطقة لتظهر تفاصيلها.</p></>}
        </section>

        <section className="late" data-tab="design">
          <h2>القرى والمباني (Kit)</h2>
          <label className="check"><input type="checkbox" checked={project.kit.enabled} onChange={(e) => set((p) => { p.kit.enabled = e.target.checked; })} /> تصدير مواضع القطع (kit/placements.csv)</label>
          <p className="hint">عرّف قطعاً (بيت، مبنى رئيسي، سور، بوابة، برج، زينة) فتُوضع تلقائياً في قطع المباني المقترحة لكل موقع وعلى محيط المواقع المسوّرة. الواجهة = المحور +X المحلي.</p>
          <ul className="list">{kitPieces.map((k) => <li key={k.id}><button className={kpSel === k.id ? "on" : ""} onClick={() => setKpSel(k.id)}>{k.name || k.id} · {KIT_ROLES.find((r) => r[0] === k.role)?.[1]}</button></li>)}</ul>
          <div className="row" style={{ flexWrap: "wrap" }}>{KIT_ROLES.map(([r, l]) => <button key={r} onClick={() => addKp(r)}>+ {l}</button>)}</div>
          {selKp && <div className="editor">
            <label className="field"><span>الاسم</span><input value={selKp.name} onChange={(e) => setKp({ name: e.target.value })} /></label>
            <Field label="الدور"><select value={selKp.role} onChange={(e) => setKp({ role: e.target.value as KitRole })}>{KIT_ROLES.map(([r, l]) => <option key={r} value={r}>{l}</option>)}</select></Field>
            <label className="field"><span>Collection في Blender</span><input dir="ltr" placeholder={`TF_Kit_${selKp.id}`} value={selKp.collection ?? ""} onChange={(e) => setKp({ collection: e.target.value || null })} /></label>
            <Field label="العرض على X (م)"><Num value={selKp.width_m} step={0.5} min={0.1} max={500} onChange={(v) => setKp({ width_m: Math.min(500, Math.max(0.1, v)) })} /></Field>
            <Field label="الطول على Y (م)"><Num value={selKp.length_m} step={0.5} min={0.1} max={500} onChange={(v) => setKp({ length_m: Math.min(500, Math.max(0.1, v)) })} /></Field>
            <Field label="الارتفاع (م)"><Num value={selKp.height_m} step={0.5} min={0.1} max={500} onChange={(v) => setKp({ height_m: Math.min(500, Math.max(0.1, v)) })} /></Field>
            <Field label="الوزن (احتمال الاختيار)"><Num value={selKp.weight} step={0.5} min={0} max={100} onChange={(v) => setKp({ weight: Math.min(100, Math.max(0, v)) })} /></Field>
            <label className="field"><span>أنواع المواقع</span><input dir="ltr" placeholder="الكل (village, castle...)" value={selKp.site_kinds.join(", ")} onChange={(e) => setKp({ site_kinds: csv(e.target.value) })} /></label>
            <p className="hint">ضع نموذجك في Collection بهذا الاسم داخل ملف Blender قبل التشغيل (واجهته نحو +X)؛ إن لم يوجد يُستعمل شكل مبسّط بأبعاد القطعة. للأسوار: الطول = طول المقطع على المحيط. أنواع المواقع المقبولة: village, town, city, castle, ruins, farm, industrial, power_plant, mine, camp, tower, temple.</p>
            <button className="danger" onClick={() => { set((p) => { p.kit.pieces = p.kit.pieces.filter((k) => k.id !== selKp.id); }); setKpSel(null); }}>حذف القطعة</button>
          </div>}
          <h3>الوضع</h3>
          <label className="check"><input type="checkbox" checked={project.kit.face_road} onChange={(e) => set((p) => { p.kit.face_road = e.target.checked; })} /> البيوت تتجه نحو أقرب طريق</label>
          <Field label="أقصى بعد للطريق (م)"><Num value={project.kit.road_snap_m} step={5} min={0} max={500} onChange={(v) => set((p) => { p.kit.road_snap_m = Math.min(500, Math.max(0, v)); })} /></Field>
          <label className="check"><input type="checkbox" checked={project.kit.walls} onChange={(e) => set((p) => { p.kit.walls = e.target.checked; })} /> أسوار وأبراج على محيط المواقع</label>
          <label className="field"><span>المواقع المسوّرة</span><input dir="ltr" value={project.kit.wall_kinds.join(", ")} onChange={(e) => set((p) => { p.kit.wall_kinds = csv(e.target.value); })} /></label>
          <Field label="عرض البوابة (م)"><Num value={project.kit.gate_width_m} step={1} min={1} max={100} onChange={(v) => set((p) => { p.kit.gate_width_m = Math.min(100, Math.max(1, v)); })} /></Field>
          <Field label="زينة لكل بيت"><Num value={project.kit.props_per_lot} step={0.1} min={0} max={5} onChange={(v) => set((p) => { p.kit.props_per_lot = Math.min(5, Math.max(0, v)); })} /></Field>
          <Field label="البذرة"><Num value={project.kit.seed} step={1} min={0} max={999999} onChange={(v) => set((p) => { p.kit.seed = Math.round(Math.max(0, v)); })} /></Field>
        </section>

        <section className="late" data-tab="design">
          <h2>نثر النباتات والصخور</h2>
          <label className="check"><input type="checkbox" checked={project.scatter.enabled} onChange={(e) => set((p) => { p.scatter.enabled = e.target.checked; })} /> تصدير مواضع النثر (scatter/*.csv)</label>
          <p className="hint">كل نوع يأخذ كثافته من مناطق النباتات بنفس الطبقة (ارسم منطقة «غابة» مثلاً)، ويُوزَّع بمسافة دنيا بين النسخ، حتمياً (نفس البذرة = نفس المواضع).</p>
          <ul className="list">{species.map((s) => <li key={s.id}><button className={spSel === s.id ? "on" : ""} onClick={() => setSpSel(s.id)}>{s.name || s.id}</button></li>)}</ul>
          <div className="row">
            <button onClick={() => addSp("tree")}>+ شجر</button><button onClick={() => addSp("bush")}>+ شجيرة</button><button onClick={() => addSp("rock")}>+ صخر</button><button onClick={() => addSp("grass")}>+ عشب</button>
          </div>
          {selSp && <div className="editor">
            <label className="field"><span>الاسم</span><input value={selSp.name} onChange={(e) => setSp({ name: e.target.value })} /></label>
            <Field label="طبقة الكثافة"><select value={selSp.layer} onChange={(e) => setSp({ layer: e.target.value as typeof selSp.layer })}>
              {(["forest", "shrubs", "grass", "flowers", "reeds", "rocks", "farmland"] as const).map((l) => <option key={l} value={l}>{l}</option>)}</select></Field>
            <Field label="أدنى مسافة بين نسختين (م)"><Num value={selSp.min_dist_m} step={0.5} min={0.3} max={500} onChange={(v) => setSp({ min_dist_m: Math.min(500, Math.max(0.3, v)) })} /></Field>
            <Field label="الحجم من"><Num value={selSp.scale_min} step={0.05} min={0.05} max={20} onChange={(v) => setSp({ scale_min: Math.max(0.05, v), scale_max: Math.max(selSp.scale_max, v) })} /></Field>
            <Field label="الحجم إلى"><Num value={selSp.scale_max} step={0.05} min={0.05} max={20} onChange={(v) => setSp({ scale_max: Math.max(selSp.scale_min, v) })} /></Field>
            <Field label="أقصى ميل (°)"><Num value={selSp.max_slope_deg} step={1} min={0} max={90} onChange={(v) => setSp({ max_slope_deg: Math.min(90, Math.max(0, v)) })} /></Field>
            <label className="field"><span>أدنى ارتفاع (م)</span><input dir="ltr" placeholder="بلا" value={selSp.min_elev_m ?? ""} onChange={(e) => setSp({ min_elev_m: optNum(e.target.value) })} /></label>
            <label className="field"><span>أقصى ارتفاع (م)</span><input dir="ltr" placeholder="بلا" value={selSp.max_elev_m ?? ""} onChange={(e) => setSp({ max_elev_m: optNum(e.target.value) })} /></label>
            <Field label="الميلان مع السطح (0–1)"><Num value={selSp.align_to_normal} step={0.1} min={0} max={1} onChange={(v) => setSp({ align_to_normal: Math.min(1, Math.max(0, v)) })} /></Field>
            <Field label="أقصى عدد"><Num value={selSp.max_count} step={1000} min={10} max={500000} onChange={(v) => setSp({ max_count: Math.round(Math.min(500000, Math.max(10, v))) })} /></Field>
            <Field label="البذرة"><Num value={selSp.seed} step={1} min={0} max={999999} onChange={(v) => setSp({ seed: Math.round(Math.max(0, v)) })} /></Field>
            <label className="field"><span>Collection في Blender</span><input dir="ltr" placeholder={`TF_Assets_${selSp.id}`} value={selSp.asset ?? ""} onChange={(e) => setSp({ asset: e.target.value || null })} /></label>
            <p className="hint">ضع أصولك (أشجار/صخور من Quixel أو Poly Haven) في Collection بهذا الاسم داخل ملف Blender قبل التشغيل؛ إن لم توجد يُستعمل شكل مبسّط مؤقت. إن زاد العدد عن الحد تُكبَّر المسافة تلقائياً كي لا يختل التوزيع.</p>
            <button className="danger" onClick={() => { set((p) => { p.scatter.species = p.scatter.species.filter((s) => s.id !== selSp.id); }); setSpSel(null); }}>حذف النوع</button>
          </div>}
        </section>

        <section data-tab="look">
          <h2>طبقات مشتقة من الارتفاعات</h2>
          <label className="check"><input type="checkbox" checked={project.derived.enabled} onChange={(e) => set((p) => { p.derived.enabled = e.target.checked; })} /> تفعيلها (تُصدَّر كأقنعة وتُستعمل في التلوين)</label>
          {project.derived.enabled && <>
            <Field label="مقياس الانحناء (م)"><Num value={project.derived.curvature_scale_m} step={1} min={1} max={500} onChange={(v) => set((p) => { p.derived.curvature_scale_m = Math.min(500, Math.max(1, v)); })} /></Field>
            <Field label="نصف قطر التجويف (م)"><Num value={project.derived.cavity_radius_m} step={1} min={2} max={500} onChange={(v) => set((p) => { p.derived.cavity_radius_m = Math.min(500, Math.max(2, v)); })} /></Field>
            <Field label="أصغر مساحة لمجرى (م²)"><Num value={project.derived.stream_area_m2} step={1000} min={100} max={100000000} onChange={(v) => set((p) => { p.derived.stream_area_m2 = Math.min(1e8, Math.max(100, v)); })} /></Field>
            <Field label="حدود فئات الميل (°)"><input dir="ltr" value={project.derived.slope_classes_deg.join(", ")} onChange={(e) => { const v = e.target.value.split(/[ ,،]+/).map(Number).filter((x) => x > 0 && x < 90).slice(0, 7); set((p) => { p.derived.slope_classes_deg = v.sort((a, b) => a - b); }); }} /></Field>
            <h3>قواعد التلوين</h3>
            <MatSel label="على الحواف المحدبة (صخر)" value={project.derived.convex_material} mats={mats} onChange={(v) => set((p) => { p.derived.convex_material = v; })} />
            {project.derived.convex_material && <>
              <Field label="الكمية (0–1)"><Num value={project.derived.convex_amount} step={0.1} min={0} max={1} onChange={(v) => set((p) => { p.derived.convex_amount = Math.min(1, Math.max(0, v)); })} /></Field>
              <Field label="أقل ميل (°)"><Num value={project.derived.convex_min_slope_deg} step={1} min={0} max={89} onChange={(v) => set((p) => { p.derived.convex_min_slope_deg = Math.min(89, Math.max(0, v)); })} /></Field></>}
            <MatSel label="في المنخفضات المقعرة (طين)" value={project.derived.hollow_material} mats={mats} onChange={(v) => set((p) => { p.derived.hollow_material = v; })} />
            {project.derived.hollow_material && <Field label="الكمية (0–1)"><Num value={project.derived.hollow_amount} step={0.1} min={0} max={1} onChange={(v) => set((p) => { p.derived.hollow_amount = Math.min(1, Math.max(0, v)); })} /></Field>}
            <MatSel label="قرب المجاري والتجمّع (رطب)" value={project.derived.wet_material} mats={mats} onChange={(v) => set((p) => { p.derived.wet_material = v; })} />
            {project.derived.wet_material && <>
              <Field label="الكمية (0–1)"><Num value={project.derived.wet_amount} step={0.1} min={0} max={1} onChange={(v) => set((p) => { p.derived.wet_amount = Math.min(1, Math.max(0, v)); })} /></Field>
              <Field label="عتبة الرطوبة (0–1)"><Num value={project.derived.wet_threshold} step={0.05} min={0} max={1} onChange={(v) => set((p) => { p.derived.wet_threshold = Math.min(1, Math.max(0, v)); })} /></Field></>}
            <p className="hint">تُحسب من الارتفاعات وحدها: الانحناء (محدب/مقعر)، التجويف، تراكم التدفق، الرطوبة (TWI)، فئات الميل. تظهر أقنعتها في مجلد masks (derived_*.png)، وتتحكم قواعد التلوين أعلاه بتوزيع الصخر والطين والرطب، ويغمّق Blender التجاويف والأرض الرطبة من قسم «سطح الأرض». المواد المختارة تؤثر في توزيع المواد (لذا تُعاد المعاينة عند تغييرها).</p></>}
        </section>

        <section data-tab="look">
          <h2>سطح الأرض (PBR)</h2>
          <label className="check"><input type="checkbox" checked={project.surface.triplanar} onChange={(e) => set((p) => { p.surface.triplanar = e.target.checked; })} /> إسقاط ثلاثي المحاور (Triplanar): لا تمدّد على المنحدرات</label>
          {project.surface.triplanar && <Field label="نعومة الحواف بين الإسقاطات"><Num value={project.surface.triplanar_blend} step={0.05} min={0} max={1} onChange={(v) => set((p) => { p.surface.triplanar_blend = Math.min(1, Math.max(0, v)); })} /></Field>}
          <label className="check"><input type="checkbox" checked={project.surface.break_tiling} onChange={(e) => set((p) => { p.surface.break_tiling = e.target.checked; })} /> كسر التكرار (عيّنتان بدوران وحجم مختلفين)</label>
          {project.surface.break_tiling && <>
            <Field label="قوة الكسر (0–1)"><Num value={project.surface.break_strength} step={0.1} min={0} max={1} onChange={(v) => set((p) => { p.surface.break_strength = Math.min(1, Math.max(0, v)); })} /></Field>
            <Field label="حجم البقع (م)"><Num value={project.surface.break_scale_m} step={10} min={1} max={5000} onChange={(v) => set((p) => { p.surface.break_scale_m = Math.min(5000, Math.max(1, v)); })} /></Field></>}
          <label className="check"><input type="checkbox" checked={project.surface.height_blend} onChange={(e) => set((p) => { p.surface.height_blend = e.target.checked; })} /> مزج بالارتفاع (الأعلى في خريطة Height يغلب عند التداخل)</label>
          {project.surface.height_blend && <Field label="حدّة المزج (0–1)"><Num value={project.surface.height_contrast} step={0.05} min={0} max={1} onChange={(v) => set((p) => { p.surface.height_contrast = Math.min(1, Math.max(0, v)); })} /></Field>}
          <Field label="عمق التفصيل البارز (م)"><Num value={project.surface.relief_m} step={0.05} min={0} max={5} onChange={(v) => set((p) => { p.surface.relief_m = Math.min(5, Math.max(0, v)); })} /></Field>
          <Field label="تغميق التجاويف (0–1)"><Num value={project.surface.cavity_strength} step={0.1} min={0} max={1} onChange={(v) => set((p) => { p.surface.cavity_strength = Math.min(1, Math.max(0, v)); })} /></Field>
          <Field label="تغميق الأرض الرطبة (0–1)"><Num value={project.surface.wet_darken} step={0.1} min={0} max={1} onChange={(v) => set((p) => { p.surface.wet_darken = Math.min(1, Math.max(0, v)); })} /></Field>
          <Field label="لمعان الأرض الرطبة (0–1)"><Num value={project.surface.wet_gloss} step={0.1} min={0} max={1} onChange={(v) => set((p) => { p.surface.wet_gloss = Math.min(1, Math.max(0, v)); })} /></Field>
          <Field label="قوة Normal"><Num value={project.surface.normal_strength} step={0.1} min={0} max={5} onChange={(v) => set((p) => { p.surface.normal_strength = Math.min(5, Math.max(0, v)); })} /></Field>
          <Field label="اصطلاح Normal"><select value={project.surface.normal_convention} onChange={(e) => set((p) => { p.surface.normal_convention = e.target.value as Project["surface"]["normal_convention"]; })}>
            <option value="GL">OpenGL (Poly Haven / NormalGL)</option><option value="DX">DirectX (NormalDX)</option></select></Field>
          <p className="hint">تُطبَّق في Blender عند الاستيراد ولا تغيّر الارتفاعات. خرائط Normal تبقى من الأعلى للأسفل (تحتاج مماسات UV)؛ التفصيل البارز على المنحدرات يأتي من خريطة Height عبر Bump، فاستعمل حزماً فيها Displacement.</p>
        </section>

        <section data-tab="look">
          <h2>الجو والإضاءة والكاميرا</h2>
          <label className="check"><input type="checkbox" checked={project.atmosphere.enabled} onChange={(e) => set((p) => { p.atmosphere.enabled = e.target.checked; })} /> تطبيقها تلقائياً في Blender</label>
          {project.atmosphere.enabled && <>
            <Field label="المحرك"><select value={project.atmosphere.engine} onChange={(e) => set((p) => { p.atmosphere.engine = e.target.value as Project["atmosphere"]["engine"]; })}>
              <option value="EEVEE">EEVEE (معاينة سريعة)</option><option value="CYCLES">Cycles (جودة نهائية)</option></select></Field>
            <Field label="معالجة الألوان"><select value={project.atmosphere.view_transform} onChange={(e) => set((p) => { p.atmosphere.view_transform = e.target.value as Project["atmosphere"]["view_transform"]; })}>
              <option value="AgX">AgX</option><option value="Filmic">Filmic</option><option value="Standard">Standard</option></select></Field>
            <Field label="التعريض (EV)"><Num value={project.atmosphere.exposure} step={0.25} min={-10} max={10} onChange={(v) => set((p) => { p.atmosphere.exposure = Math.min(10, Math.max(-10, v)); })} /></Field>
            <h3>الشمس والسماء</h3>
            <Field label="ارتفاع الشمس (°)"><Num value={project.atmosphere.sun_elevation} min={0} max={90} onChange={(v) => set((p) => { p.atmosphere.sun_elevation = Math.min(90, Math.max(0, v)); })} /></Field>
            <Field label="اتجاه الشمس (° 0=شمال)"><Num value={project.atmosphere.sun_azimuth} min={0} max={360} onChange={(v) => set((p) => { p.atmosphere.sun_azimuth = ((v % 360) + 360) % 360; })} /></Field>
            <Field label="قوة المصباح (EEVEE)"><Num value={project.atmosphere.sun_energy} step={0.5} min={0} max={100} onChange={(v) => set((p) => { p.atmosphere.sun_energy = Math.min(100, Math.max(0, v)); })} /></Field>
            <Field label="كثافة الهواء"><Num value={project.atmosphere.air_density} step={0.1} min={0} max={10} onChange={(v) => set((p) => { p.atmosphere.air_density = Math.min(10, Math.max(0, v)); })} /></Field>
            <Field label="كثافة الغبار"><Num value={project.atmosphere.dust_density} step={0.1} min={0} max={10} onChange={(v) => set((p) => { p.atmosphere.dust_density = Math.min(10, Math.max(0, v)); })} /></Field>
            <h3>الضباب</h3>
            <label className="check"><input type="checkbox" checked={project.atmosphere.fog} onChange={(e) => set((p) => { p.atmosphere.fog = e.target.checked; })} /> ضباب حجمي</label>
            {project.atmosphere.fog && <>
              <Field label="الكثافة (لكل م)">
                <span className="pair">
                  <input type="checkbox" checked={project.atmosphere.fog_density === null} aria-label="تلقائي" onChange={(e) => set((p) => { p.atmosphere.fog_density = e.target.checked ? null : 3 / Math.max(p.world.size_x_m, p.world.size_y_m); })} /> تلقائي
                  {project.atmosphere.fog_density !== null && <Num value={project.atmosphere.fog_density} step={0.0001} min={0.000001} max={1} onChange={(v) => set((p) => { p.atmosphere.fog_density = Math.min(1, Math.max(0.000001, v)); })} />}
                </span></Field>
              <Field label="توهج نحو الشمس (−0.9…0.9)"><Num value={project.atmosphere.fog_anisotropy} step={0.05} min={-0.95} max={0.95} onChange={(v) => set((p) => { p.atmosphere.fog_anisotropy = Math.min(0.95, Math.max(-0.95, v)); })} /></Field></>}
            <h3>الكاميرا</h3>
            <label className="check"><input type="checkbox" checked={project.atmosphere.camera} onChange={(e) => set((p) => { p.atmosphere.camera = e.target.checked; })} /> إنشاء كاميرا تنظر إلى العالم</label>
            {project.atmosphere.camera && <>
              <Field label="موضعها (° من المركز)"><Num value={project.atmosphere.camera_azimuth} min={0} max={360} onChange={(v) => set((p) => { p.atmosphere.camera_azimuth = ((v % 360) + 360) % 360; })} /></Field>
              <Field label="البعد (× أكبر ضلع)"><Num value={project.atmosphere.camera_distance_factor} step={0.1} min={0.05} max={5} onChange={(v) => set((p) => { p.atmosphere.camera_distance_factor = Math.min(5, Math.max(0.05, v)); })} /></Field>
              <OptNum label="الارتفاع فوق القمة (م)" value={project.atmosphere.camera_height_above_peak_m} def={Math.round(0.08 * Math.max(w.size_x_m, w.size_y_m))} onChange={(v) => set((p) => { p.atmosphere.camera_height_above_peak_m = v === null ? null : Math.max(0, v); })} />
              <Field label="البعد البؤري (مم)"><Num value={project.atmosphere.focal_length_mm} min={8} max={300} onChange={(v) => set((p) => { p.atmosphere.focal_length_mm = Math.min(300, Math.max(8, v)); })} /></Field>
              <label className="check"><input type="checkbox" checked={project.atmosphere.dof} onChange={(e) => set((p) => { p.atmosphere.dof = e.target.checked; })} /> عمق الميدان</label>
              {project.atmosphere.dof && <Field label="فتحة العدسة (f)"><Num value={project.atmosphere.f_stop} step={0.5} min={0.5} max={32} onChange={(v) => set((p) => { p.atmosphere.f_stop = Math.min(32, Math.max(0.5, v)); })} /></Field>}</>}
            <p className="hint">لا تغيّر الارتفاعات ولا تظهر في الخريطة: تُحفظ في المشروع وتُصدَّر في build.json، ويطبّقها import_build.py عند الاستيراد في Blender. عمق الميدان لا يظهر عملياً إلا بكاميرا قريبة من التضاريس.</p></>}
        </section>

        <section data-tab="export">
          <h2>تصدير العالم</h2>
          <p className="hint">ملف واحد جاهز للاستعمال: <b>GLB</b> (يفتح في Blender وGodot وUnity) أو <b>.blend</b> (المشهد الكامل بمواده وفصوله وجوّه). الصور والأكواد القديمة محفوظة أسفل للتحسين.</p>
          <button className="primary" disabled={hasErrors} onClick={() => setShow3d(true)}>{hasErrors ? "أصلح الأخطاء أولاً" : "معاينة العالم ثلاثياً"}</button>
          <Field label="دقة شبكة GLB">
            <select value={project.export.glb_resolution} onChange={(e) => set((p) => { p.export.glb_resolution = Number(e.target.value) as Project["export"]["glb_resolution"]; })}>
              {[257, 513, 1025, 2049].map((r) => <option key={r} value={r}>{r} رأس (≈ {(Math.max(w.size_x_m, w.size_y_m) / (r - 1)).toFixed(1)} م)</option>)}</select></Field>
          <Field label="دقة الخامة المخبوزة">
            <select value={project.export.glb_texture_px} onChange={(e) => set((p) => { p.export.glb_texture_px = Number(e.target.value) as Project["export"]["glb_texture_px"]; })}>
              {[1024, 2048, 4096].map((r) => <option key={r} value={r}>{r} بكسل (≈ {(Math.max(w.size_x_m, w.size_y_m) / r).toFixed(1)} م/بكسل)</option>)}</select></Field>
          <div className="expfmt">
            <button className="primary" disabled={hasErrors || wjob?.state === "running"} onClick={() => doWorld("glb")}>تصدير GLB</button>
            <button className="primary" disabled={hasErrors || wjob?.state === "running" || caps?.blend.available === false} onClick={() => doWorld("blend")}
              title={caps?.blend.available === false ? caps.blend.reason : "Blender يبني المشهد الكامل ويحفظه"}>تصدير .blend</button></div>
          {caps?.blend.available === false && <p className="hint">تصدير .blend غير متاح: {caps.blend.reason} <button onClick={() => exportCapabilities(true).then(setCaps)}>أعد الفحص</button></p>}
          {wjob?.state === "running" && <><p className="hint">{wjob.fmt === "glb" ? "GLB" : ".blend"}: {wjob.stage ?? ""} {wjob.done}%</p><progress value={wjob.done} max={100} style={{ width: "100%" }} /></>}
          {wjob?.state === "error" && <div className="msg error" style={{ whiteSpace: "pre-wrap" }}>{wjob.error}</div>}
          {wjob?.state === "done" && <p className="hint">اكتمل التصدير وتم التنزيل.</p>}
          <p className="hint">الخامة في GLB «مخبوزة» من مزج خامات المواد (وكل ما يمرّ على Poly Haven/ambientCG يُنسب في extras)؛ للخامات الحقيقية بإسقاط ثلاثي المحاور استعمل .blend.</p>
          <details className="legacy"><summary>التصدير المتقدّم: الصور والأكواد (محفوظ للتحسين)</summary>
          <h2>التصدير</h2>
          <Field label="نطاق الارتفاع">
            <select value={project.export.mode} onChange={(e) => set((p) => { p.export.mode = e.target.value as "auto" | "fixed"; })}>
              <option value="auto">تلقائي</option><option value="fixed">ثابت</option></select></Field>
          {project.export.mode === "fixed" && <>
            <Field label="الأدنى (م)"><Num value={project.export.zmin_m} onChange={(v) => set((p) => { p.export.zmin_m = v; })} /></Field>
            <Field label="الأقصى (م)"><Num value={project.export.zmax_m} onChange={(v) => set((p) => { p.export.zmax_m = v; })} /></Field></>}
          <Field label="دقة أقنعة النباتات">
            <select value={project.export.mask_px} onChange={(e) => set((p) => { p.export.mask_px = Number(e.target.value) as Project["export"]["mask_px"]; })}>
              {[513, 1025, 2049].map((r) => <option key={r} value={r}>{r} بكسل</option>)}</select></Field>
          <p className="hint">كل تصدير يتضمن <b>build.json</b> وسكربت <b>import_build.py</b> لـ Blender وأقنعة الكثافة.</p>
          <h2>صورة واحدة</h2>
          <Field label="الدقة (الضلع الأطول)">
            <select value={project.export.resolution} onChange={(e) => set((p) => { p.export.resolution = Number(e.target.value) as Project["export"]["resolution"]; })}>
              {[513, 1025, 2049, 4097].map((r) => <option key={r} value={r}>{r} بكسل</option>)}</select></Field>
          <p className="hint">{mpp.toFixed(2)} م/بكسل{w.size_x_m !== w.size_y_m ? " · صورة غير مربعة (Unity/Unreal تحتاج مربعاً)" : ""}</p>
          <button className="primary" disabled={busy || hasErrors} onClick={doExport}>{busy ? "جارٍ التصدير…" : hasErrors ? "أصلح الأخطاء أولاً" : "تصدير PNG 16-bit"}</button>
          <h2>مربعات (Tiles) بحجم المنطقة المحمّلة</h2>
          <Field label="بكسلات المربع">
            <select value={project.export.tile_px} onChange={(e) => set((p) => { p.export.tile_px = Number(e.target.value) as Project["export"]["tile_px"]; })}>
              {[513, 1025, 2049].map((r) => <option key={r} value={r}>{r} بكسل</option>)}</select></Field>
          <p className="hint">{tilesX * tilesY} مربع · {w.chunk_size_m} م لكل مربع · <b>{tmpp.toFixed(3)} م/بكسل</b>{Math.abs(tmpp - 1) < 0.01 ? " ✔ دقة 1×1 م" : " (للوصول إلى 1 م/بكسل: المربع 1024م مع 1025 بكسل، أو 512م مع 513)"}</p>
          <button className="primary" disabled={hasErrors || job?.state === "running"} onClick={doTiles}>{job?.state === "running" ? `جارٍ التوليد ${Math.round((job.done / Math.max(job.total, 1)) * 100)}%` : "تصدير المربعات"}</button>
          {job?.state === "running" && <progress value={job.done} max={job.total} style={{ width: "100%" }} />}
          {job?.state === "error" && <div className="msg error">{job.error}</div>}
          {job?.state === "done" && <p className="hint">اكتمل التصدير وتم التنزيل.</p>}
          {embedded && <>
            <h2>العالم مع المنشآت (World Studio)</h2>
            <p className="hint">يُصدَّر مجلد واحد: <b>terrain/</b> (المربعات + build.json) و<b>sites/</b> (ملف GLB لكل منشأة رسمتها في BIM Builder) و<b>sites.json</b> و<b>sites_placement.tscn</b> لـ Godot. المنشآت المرتبطة: {project.sites.filter((s) => s.bim_project).length} من {project.sites.length}.</p>
            <button className="primary" disabled={hasErrors} onClick={() => exportWorld("tiles")}>{hasErrors ? "أصلح الأخطاء أولاً" : "تصدير العالم + المنشآت (مربعات)"}</button>
            <button disabled={hasErrors} onClick={() => exportWorld("single")}>نفس التصدير بصورة واحدة</button></>}
          </details>
          <h2>قياس الأداء</h2>
          <p className="hint">يقيس سرعة جهازك ويقدّر زمن تصدير العالم كاملاً.</p>
          <button onClick={() => setShowBench(true)}>فتح صفحة قياس الأداء</button>
          <div className="row"><button onClick={save}>حفظ المشروع</button><button onClick={() => fileRef.current?.click()}>فتح مشروع</button>
            <input ref={fileRef} type="file" accept=".json" hidden onChange={(e) => e.target.files?.[0] && load(e.target.files[0])} /></div>
        </section>
        </div>
      </aside>

      <div className="rail" role="toolbar" aria-label="أدوات الرسم">
        {MODES.map(([m, l], i) => <Fragment key={m}>{(i === 1 || i === 6) && <hr />}<button className={`t${mode === m ? " on" : ""}`} title={l} aria-label={l} aria-pressed={mode === m} onClick={() => { setMode(m); setDraft([]); setTab("design"); }}><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d={MODE_ICON[m]} /></svg><span className="tip">{l}</span></button></Fragment>)}
      </div>
      <main className="stage">
        <div className="bar">
          <label>العرض <select value={viewMat ? "mat" : "h"} onChange={(e) => setViewMat(e.target.value === "mat")}><option value="h">ارتفاعات</option><option value="mat">مواد</option></select></label>
          <label><input type="checkbox" checked={showGrid} onChange={(e) => setShowGrid(e.target.checked)} /> الشبكة</label>
          <label>فاصل الكنتور (م) <span className="mini"><Num value={interval} min={0} onChange={setIntervalM} /></span></label>
          {preview && <span className="hint">النطاق {preview.zmin.toFixed(1)} → {preview.zmax.toFixed(1)} م</span>}
        </div>
        <MapCanvas project={project} preview={preview} mode={mode} sel={sel} cellSel={cellSel} draft={draft} profileLine={profileLine} showGrid={showGrid} interval={interval} viewMat={viewMat}
          onClickWorld={clickWorld} onDoubleClick={finishDraft} onSelect={setSel} onOpenSite={embedded ? openInBim : undefined} onMovePoint={movePoint} onMoveVertex={moveVertex} onMoveBiomeVertex={moveBiomeVertex} onMoveZoneVertex={moveZoneVertex} onMoveSite={moveSite} onMovePoi={movePoi}
          overlay={{ expected: sim ? sim.legs.filter((l) => l.reachable && l.points).map((l) => l.points as XY[]) : undefined, lots: showLots ? lots ?? undefined : undefined, cands: cands ?? undefined, view: viewC,
            heat: tstats && showHeat ? tstats.heat : null, tpaths: showTPaths && ses.length ? ses.slice(0, 120).map((s) => s.samples.filter((_, i) => i % 3 === 0).map((q) => [q.x, q.y] as XY)) : undefined, dropoffs: showTPaths && tstats ? tstats.dropoffs : undefined }}
          onHover={(x, y) => setHover([x, y])} />
        <div className="bottom">
        {notice && <div className="msg warn">{notice}</div>}
        {err && <div className="msg error">{err}</div>}
        {preview?.errors.map((m, i) => <div key={`e${i}`} className="msg error">{m}</div>)}
        {preview?.warnings.map((m, i) => <div key={`w${i}`} className="msg warn">{m}</div>)}
        <div className="charts">
          {profile && <Chart title="مقطع عرضي A–B" x={profile.dist} series={[{ y: profile.z, color: "#2f8fe8", label: "سطح الأرض" }]} sea={w.sea_level_m} />}
          {liSel && <Chart title={`مقطع طولي: ${liSel.id}`} x={liSel.s} sea={w.sea_level_m}
            series={[{ y: liSel.ground, color: "#8aa0b2", label: "الأرض قبل التعديل" }, ...(liSel.design ? [{ y: liSel.design, color: LINE_META[liSel.kind].color, label: liSel.kind === "river" ? "قاع النهر" : "منسوب الطريق" }] : [])]} />}
        </div>
        </div>
      </main>
      </div>
      <footer className="status"><span>الأداة: <b>{MODES.find(([m]) => m === mode)?.[1]}</b></span>{hover && <span dir="ltr">X {hover[0].toFixed(0)} · Y {hover[1].toFixed(0)}{preview ? ` · Z ${ground(hover[0], hover[1]).toFixed(1)}` : ""}</span>}</footer>
      {showBench && <Suspense fallback={null}><PerfBench project={project} onClose={() => setShowBench(false)} /></Suspense>}
      {show3d && <Suspense fallback={<div className="modal3d"><div className="m3d-note">جارٍ تحميل المعاينة…</div></div>}><World3D project={project} onClose={() => setShow3d(false)} /></Suspense>}
    </div>
  );
}
