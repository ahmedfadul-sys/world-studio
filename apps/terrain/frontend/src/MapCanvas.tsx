import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { contours } from "d3-contour";
import { LINE_META, POINT_META, POI_META, SITE_META, ZONE_META, polyArea, type Candidate, type Lot, type Preview, type Project, type XY } from "./types";
import { renderTerrain, zAt } from "./render";

export type Mode = "select" | "point" | "line" | "cell" | "profile" | "biome" | "site" | "zone" | "poi" | "route";
export type Sel = { t: "point" | "line" | "biome" | "site" | "zone" | "poi"; id: string } | null;
export interface Overlay { expected?: XY[][]; lots?: Lot[]; cands?: Candidate[]; heat?: HTMLCanvasElement | null; tpaths?: XY[][]; view?: HTMLCanvasElement | null; dropoffs?: XY[] }
export interface Props {
  project: Project; preview: Preview | null; mode: Mode; sel: Sel; cellSel: { col: number; row: number } | null;
  draft: XY[]; profileLine: [XY, XY] | null; showGrid: boolean; interval: number; px?: number; viewMat?: boolean; overlay?: Overlay; onMovePoi?: (id: string, x: number, y: number) => void;
  onOpenSite?: (id: string) => void; onClickWorld: (x: number, y: number) => void; onDoubleClick: () => void; onSelect: (s: Sel) => void;
  onMovePoint: (id: string, x: number, y: number) => void; onMoveVertex: (id: string, i: number, x: number, y: number) => void;
  onMoveBiomeVertex: (id: string, i: number, x: number, y: number) => void;
  onMoveZoneVertex: (id: string, i: number, x: number, y: number) => void; onMoveSite: (id: string, x: number, y: number) => void;
  onHover: (x: number, y: number) => void;
}
type Drag = { t: "point"; id: string; ox: number; oy: number } | { t: "vertex"; id: string; i: number } | { t: "bvertex"; id: string; i: number } | { t: "zvertex"; id: string; i: number } | { t: "site"; id: string; ox: number; oy: number } | { t: "poi"; id: string; ox: number; oy: number } | null;

const niceLen = (m: number) => { const p = 10 ** Math.floor(Math.log10(m)); return [5, 2, 1].map((k) => k * p).find((v) => v <= m) ?? p; };
const inPoly = (x: number, y: number, P: XY[]) => { let c = false; for (let i = 0, j = P.length - 1; i < P.length; j = i++) if ((P[i][1] > y) !== (P[j][1] > y) && x < ((P[j][0] - P[i][0]) * (y - P[i][1])) / (P[j][1] - P[i][1]) + P[i][0]) c = !c; return c; };
const distSeg = (px: number, py: number, a: XY, b: XY) => {
  const vx = b[0] - a[0], vy = b[1] - a[1], L2 = vx * vx + vy * vy || 1e-9;
  const t = Math.max(0, Math.min(1, ((px - a[0]) * vx + (py - a[1]) * vy) / L2));
  return Math.hypot(px - a[0] - t * vx, py - a[1] - t * vy);
};

export default function MapCanvas(p: Props) {
  const { size_x_m: Lx, size_y_m: Ly, cell_size_m: cell } = p.project.world;
  const ref = useRef<HTMLCanvasElement>(null), wrapRef = useRef<HTMLDivElement>(null), drag = useRef<Drag>(null), lastSite = useRef<{ id: string; t: number } | null>(null);
  // ── نافذة العرض: اللوحة بحجم مساحة العمل دائماً، والتكبير/التحريك يغيّران "مركز العرض" بالمتر فقط ──
  const [size, setSize] = useState({ w: 0, h: 0});
  const [view, setView] = useState({ z: 1, cx: Lx / 2, cy: Ly / 2 });       // z = تكبير نسبي للملاءمة، (cx,cy) = نقطة العالم في مركز اللوحة
  const [hand, setHand] = useState(false), [grab, setGrab] = useState(false);
  const panRef = useRef<{ x: number; y: number; cx: number; cy: number } | null>(null), moved = useRef(false), space = useRef(false);
  const CW = size.w || 760, CH = size.h || 560;
  const kFit = (Math.min(CW / Lx, CH / Ly)) * 0.94;                          // بكسل لكل متر عند الملاءمة
  const k = kFit * view.z;                                                   // مقياس رسم موحّد على المحورين
  const W = Lx * k, H = Ly * k;                                              // أبعاد العالم بالبكسل (قد تتجاوز اللوحة عند التكبير)
  const ox = CW / 2 - view.cx * k, oy = CH / 2 - (Ly - view.cy) * k;         // إزاحة العالم داخل اللوحة
  const toPx = (x: number, y: number): XY => [x * k, (Ly - y) * k];
  const geo = useRef({ CW, CH, kFit }); geo.current = { CW, CH, kFit };
  const zoomAt = (f: number, sx?: number, sy?: number) => setView((v) => {   // تكبير حول نقطة (المؤشر أو المركز) فتبقى مكانها
    const g = geo.current, x = sx ?? g.CW / 2, y = sy ?? g.CH / 2, nz = Math.min(60, Math.max(0.25, v.z * f));
    if (nz === v.z) return v;
    const ko = g.kFit * v.z, kn = g.kFit * nz, wx = v.cx + (x - g.CW / 2) / ko, wy = v.cy - (y - g.CH / 2) / ko;
    return { z: nz, cx: wx - (x - g.CW / 2) / kn, cy: wy + (y - g.CH / 2) / kn };
  });
  const zoomRef = useRef(zoomAt); zoomRef.current = zoomAt;
  const fit = () => setView({ z: 1, cx: Lx / 2, cy: Ly / 2 });

  useEffect(() => { setView({ z: 1, cx: Lx / 2, cy: Ly / 2 }); }, [Lx, Ly]);  // عالم بحجم جديد: ملاءمة من جديد
  useEffect(() => {
    const el = wrapRef.current!, ro = new ResizeObserver(([e]) => setSize({ w: Math.floor(e.contentRect.width), h: Math.floor(e.contentRect.height) }));
    ro.observe(el);
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const b = el.getBoundingClientRect(), dy = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
      zoomRef.current(Math.exp(-dy * (e.ctrlKey ? 0.01 : 0.0015)), e.clientX - b.left, e.clientY - b.top);
    };
    el.addEventListener("wheel", wheel, { passive: false });
    const dn = (e: KeyboardEvent) => { if (e.code === "Space" && !/INPUT|SELECT|TEXTAREA|BUTTON/.test((e.target as HTMLElement).tagName)) { space.current = true; e.preventDefault(); } };
    const up = (e: KeyboardEvent) => { if (e.code === "Space") space.current = false; };
    window.addEventListener("keydown", dn); window.addEventListener("keyup", up);
    return () => { ro.disconnect(); el.removeEventListener("wheel", wheel); window.removeEventListener("keydown", dn); window.removeEventListener("keyup", up); };
  }, []);

  const base = useMemo(() => {
    if (!p.preview) return null;
    const off = document.createElement("canvas");
    off.width = p.preview.nx; off.height = p.preview.ny;
    off.getContext("2d")!.putImageData(renderTerrain(p.preview, p.project.world.sea_level_m, Lx, Ly, 3, !!p.viewMat), 0, 0);
    return off;
  }, [p.preview, p.project.world.sea_level_m, Lx, Ly, p.viewMat]);

  const lines = useMemo(() => {
    const pv = p.preview;
    if (!pv || p.interval <= 0) return null;
    const vals = new Array<number>(pv.nx * pv.ny);
    for (let i = 0; i < vals.length; i++) vals[i] = zAt(pv, i);
    const th: number[] = [];
    for (let v = Math.ceil(pv.zmin / p.interval) * p.interval; v < pv.zmax && th.length < 250; v += p.interval) th.push(v);
    return { iv: p.interval, data: contours().size([pv.nx, pv.ny]).thresholds(th)(vals) };
  }, [p.preview, p.interval]);

  const linePath = (id: string, pts: XY[]): XY[] => {
    const li = p.preview?.linear.find((l) => l.id === id);
    return li ? li.x.map((x, i) => [x, li.y[i]] as XY) : pts;
  };

  useEffect(() => {
    const cv = ref.current!, dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(CW * dpr) || cv.height !== Math.round(CH * dpr)) { cv.width = Math.round(CW * dpr); cv.height = Math.round(CH * dpr); }
    const ctx = cv.getContext("2d")!, css = getComputedStyle(cv);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.setLineDash([]); ctx.globalAlpha = 1; ctx.textAlign = "start";
    ctx.fillStyle = css.getPropertyValue("--ws-bg").trim() || "#081524"; ctx.fillRect(0, 0, CW, CH);
    ctx.save(); ctx.translate(ox, oy);                                      // كل الرسم التالي بإحداثيات العالم بالبكسل
    ctx.fillStyle = css.getPropertyValue("--map-bg").trim() || "#0c1d34"; ctx.fillRect(0, 0, W, H);
    if (base) { ctx.imageSmoothingEnabled = true; ctx.drawImage(base, 0, 0, W, H); }

    const ov = p.overlay;
    if (ov?.view) { ctx.globalAlpha = 0.4; ctx.drawImage(ov.view, 0, 0, W, H); ctx.globalAlpha = 1; }
    if (ov?.heat) { ctx.imageSmoothingEnabled = true; ctx.drawImage(ov.heat, 0, 0, W, H); }
    if (lines && p.preview) {
      const kx = W / (p.preview.nx - 1), ky = H / (p.preview.ny - 1);
      for (const g of lines.data) {
        const major = Math.round(g.value / lines.iv) % 5 === 0;
        ctx.strokeStyle = major ? "rgba(32,20,8,.75)" : "rgba(32,20,8,.35)"; ctx.lineWidth = major ? 1.2 : 0.7; ctx.beginPath();
        for (const poly of g.coordinates) for (const ring of poly) ring.forEach(([x, y], i) => (i ? ctx.lineTo((x - 0.5) * kx, (y - 0.5) * ky) : ctx.moveTo((x - 0.5) * kx, (y - 0.5) * ky)));
        ctx.stroke();
      }
    }
    p.project.biomes.forEach((b, bi) => {
      const sel = p.sel?.t === "biome" && p.sel.id === b.id, hue = (bi * 67 + 20) % 360, pts = b.polygon.map(([x, y]) => toPx(x, y));
      ctx.beginPath(); pts.forEach(([a, c], i) => (i ? ctx.lineTo(a, c) : ctx.moveTo(a, c))); ctx.closePath();
      ctx.fillStyle = `hsla(${hue},70%,55%,${sel ? 0.22 : 0.12})`; ctx.fill();
      ctx.strokeStyle = `hsla(${hue},80%,70%,${sel ? 1 : 0.75})`; ctx.lineWidth = sel ? 2.5 : 1.5; ctx.stroke();
      const cx = pts.reduce((a, q) => a + q[0], 0) / pts.length, cy = pts.reduce((a, q) => a + q[1], 0) / pts.length;
      ctx.fillStyle = "#fff"; ctx.font = "bold 12px sans-serif"; ctx.textAlign = "center";
      ctx.fillText(`${b.name} · ${(polyArea(b.polygon) / 1e6).toFixed(2)} كم²`, cx, cy); ctx.textAlign = "start";
      if (sel) for (const [a, c] of pts) { ctx.fillStyle = "#ffd27a"; ctx.fillRect(a - 4, c - 4, 8, 8); }
    });
    for (const z of p.project.zones) {
      const sel = p.sel?.t === "zone" && p.sel.id === z.id, pts = z.polygon.map(([x, y]) => toPx(x, y)), col = ZONE_META[z.layer].color;
      ctx.beginPath(); pts.forEach(([a, c], i) => (i ? ctx.lineTo(a, c) : ctx.moveTo(a, c))); ctx.closePath();
      ctx.globalAlpha = sel ? 0.4 : 0.25; ctx.fillStyle = col; ctx.fill(); ctx.globalAlpha = 1;
      ctx.strokeStyle = col; ctx.setLineDash([3, 3]); ctx.lineWidth = sel ? 2.5 : 1.2; ctx.stroke(); ctx.setLineDash([]);
      if (sel) for (const [a, c] of pts) { ctx.fillStyle = "#ffd27a"; ctx.fillRect(a - 4, c - 4, 8, 8); }
    }
    if (p.showGrid) {
      if (Math.max(Lx, Ly) / cell <= 250) {
        ctx.strokeStyle = "rgba(255,255,255,.16)"; ctx.lineWidth = 0.5; ctx.beginPath();
        for (let x = 0; x <= Lx + 1e-6; x += cell) { ctx.moveTo(x * k, 0); ctx.lineTo(x * k, H); }
        for (let y = 0; y <= Ly + 1e-6; y += cell) { ctx.moveTo(0, y * k); ctx.lineTo(W, y * k); }
        ctx.stroke();
      }
      const ch = p.project.world.chunk_size_m;
      ctx.strokeStyle = "rgba(224,164,58,.85)"; ctx.setLineDash([6, 4]); ctx.lineWidth = 1; ctx.beginPath();
      for (let x = ch; x < Lx; x += ch) { ctx.moveTo(x * k, 0); ctx.lineTo(x * k, H); }
      for (let y = ch; y < Ly; y += ch) { ctx.moveTo(0, y * k); ctx.lineTo(W, y * k); }
      ctx.stroke(); ctx.setLineDash([]);
    }
    // خلايا معدّلة
    const cs = cell * k;
    ctx.font = "11px sans-serif"; ctx.textAlign = "center";
    for (const c of p.project.cells) {
      ctx.strokeStyle = "rgba(255,210,122,.9)"; ctx.lineWidth = 1; ctx.strokeRect(c.col * cs + 0.5, c.row * cs + 0.5, cs - 1, cs - 1);
      if (cs >= 28) { ctx.fillStyle = "#fff"; ctx.fillText(`${c.elevation_m}`, c.col * cs + cs / 2, c.row * cs + cs / 2 + 4); }
    }
    if (p.cellSel) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.strokeRect(p.cellSel.col * cs + 1, p.cellSel.row * cs + 1, cs - 2, cs - 2); }
    ctx.textAlign = "start";

    // تضاريس نقطية: الدائرة = البصمة الفعلية بنفس مقياس الرسم
    for (const f of p.project.points) {
      const [cx, cy] = toPx(f.x_m, f.y_m), r = (f.diameter_m / 2) * k, sel = p.sel?.t === "point" && p.sel.id === f.id;
      ctx.strokeStyle = sel ? "#ffd27a" : POINT_META[f.kind].neg ? "rgba(140,200,255,.95)" : "rgba(255,255,255,.85)";
      ctx.lineWidth = sel ? 2 : 1; ctx.setLineDash([5, 4]); ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = sel ? "#ffd27a" : "#fff"; ctx.beginPath(); ctx.arc(cx, cy, 3.5, 0, Math.PI * 2); ctx.fill();
      ctx.font = "12px sans-serif"; ctx.fillText(`${POINT_META[f.kind].label} ${f.high_m.toFixed(0)}م`, cx + 6, cy - 6);
    }
    for (const s of p.project.sites) {
      const [cx, cy] = toPx(s.x_m, s.y_m), sel = p.sel?.t === "site" && p.sel.id === s.id;
      ctx.strokeStyle = sel ? "#ffd27a" : "#ffb347"; ctx.fillStyle = sel ? "rgba(255,210,122,.25)" : "rgba(255,179,71,.18)"; ctx.lineWidth = sel ? 2.5 : 1.5; ctx.beginPath();
      if (s.shape === "circle") ctx.arc(cx, cy, (s.diameter_m / 2) * k, 0, Math.PI * 2);
      else { const th = (s.rotation_deg * Math.PI) / 180; [[-1, -1], [1, -1], [1, 1], [-1, 1]].forEach(([u, v], i) => { const a = (u * s.width_m) / 2, b = (v * s.length_m) / 2; const [px, py] = toPx(s.x_m + a * Math.cos(th) - b * Math.sin(th), s.y_m + a * Math.sin(th) + b * Math.cos(th)); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); }); ctx.closePath(); }
      ctx.fill(); ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.font = "bold 14px sans-serif"; ctx.textAlign = "center"; ctx.fillText(SITE_META[s.kind].icon, cx, cy + 5);
      ctx.font = "11px sans-serif"; ctx.fillText(s.name, cx, cy + 18); ctx.textAlign = "start";
    }
    if (ov?.lots) for (const l of ov.lots) {
      const [cx, cy] = toPx(l.x_m, l.y_m), th = (-l.rotation_deg * Math.PI) / 180;
      ctx.save(); ctx.translate(cx, cy); ctx.rotate(th); ctx.fillStyle = l.main ? "rgba(255,214,10,.85)" : "rgba(255,255,255,.75)"; ctx.strokeStyle = "#222";
      ctx.fillRect((-l.width_m * k) / 2, (-l.length_m * k) / 2, l.width_m * k, l.length_m * k); ctx.strokeRect((-l.width_m * k) / 2, (-l.length_m * k) / 2, l.width_m * k, l.length_m * k); ctx.restore();
    }
    if (ov?.cands) ov.cands.forEach((c, i) => {
      const [cx, cy] = toPx(c.x_m, c.y_m); ctx.fillStyle = "#30d158"; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(cx, cy, 11, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      ctx.fillStyle = "#06210f"; ctx.font = "bold 12px sans-serif"; ctx.textAlign = "center"; ctx.fillText(String(i + 1), cx, cy + 4); ctx.textAlign = "start";
    });
    for (const q of p.project.pois) {
      const [cx, cy] = toPx(q.x_m, q.y_m), meta = POI_META[q.kind], sel = p.sel?.t === "poi" && p.sel.id === q.id;
      if (q.radius_m > 0) { ctx.strokeStyle = meta.color; ctx.fillStyle = meta.color + "33"; ctx.lineWidth = sel ? 3 : 1.5; ctx.beginPath(); ctx.arc(cx, cy, q.radius_m * k, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); }
      ctx.fillStyle = sel ? "#fff" : meta.color; ctx.strokeStyle = "#111"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(cx, cy, 10, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      ctx.fillStyle = "#111"; ctx.font = "bold 12px sans-serif"; ctx.textAlign = "center"; ctx.fillText(meta.icon, cx, cy + 4);
      ctx.fillStyle = "#fff"; ctx.font = "11px sans-serif"; ctx.fillText(q.order > 0 ? `${q.order}. ${q.name}` : q.name, cx, cy - 15); ctx.textAlign = "start";
    }
    // تضاريس خطية
    for (const f of p.project.lines) {
      const sel = p.sel?.t === "line" && p.sel.id === f.id, path = linePath(f.id, f.points);
      ctx.strokeStyle = LINE_META[f.kind].color; ctx.lineWidth = sel ? 3 : 2; ctx.beginPath();
      path.forEach(([x, y], i) => { const [a, b] = toPx(x, y); i ? ctx.lineTo(a, b) : ctx.moveTo(a, b); }); ctx.stroke();
      const [sx, sy] = toPx(f.points[0][0], f.points[0][1]);
      ctx.fillStyle = LINE_META[f.kind].color; ctx.fillText(f.kind === "river" ? "منبع" : f.kind === "cliff" ? "▲ يسار = مرتفع" : "", sx + 6, sy - 6);
      if (sel) for (const [x, y] of f.points) { const [a, b] = toPx(x, y); ctx.fillStyle = "#ffd27a"; ctx.fillRect(a - 4, b - 4, 8, 8); }
    }
    if (ov?.tpaths) { ctx.strokeStyle = "rgba(120,200,255,.18)"; ctx.lineWidth = 1; for (const path of ov.tpaths) { ctx.beginPath(); path.forEach(([x, y], i) => { const [a, b] = toPx(x, y); i ? ctx.lineTo(a, b) : ctx.moveTo(a, b); }); ctx.stroke(); } }
    if (ov?.dropoffs) { ctx.fillStyle = "rgba(255,69,58,.8)"; for (const [x, y] of ov.dropoffs) { const [a, b] = toPx(x, y); ctx.beginPath(); ctx.arc(a, b, 3, 0, Math.PI * 2); ctx.fill(); } }
    if (ov?.expected) { ctx.strokeStyle = "#ff9f0a"; ctx.lineWidth = 3; ctx.setLineDash([8, 4]); for (const path of ov.expected) { ctx.beginPath(); path.forEach(([x, y], i) => { const [a, b] = toPx(x, y); i ? ctx.lineTo(a, b) : ctx.moveTo(a, b); }); ctx.stroke(); } ctx.setLineDash([]); }
    if (p.draft.length) {
      ctx.strokeStyle = "#fff"; ctx.setLineDash([4, 3]); ctx.lineWidth = 1.5; ctx.beginPath();
      p.draft.forEach(([x, y], i) => { const [a, b] = toPx(x, y); i ? ctx.lineTo(a, b) : ctx.moveTo(a, b); }); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = "#fff"; for (const [x, y] of p.draft) { const [a, b] = toPx(x, y); ctx.fillRect(a - 3, b - 3, 6, 6); }
    }
    if (p.profileLine) {
      const [a, b] = p.profileLine.map(([x, y]) => toPx(x, y));
      ctx.strokeStyle = "#ff4fa3"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      ctx.fillStyle = "#ff4fa3"; ctx.font = "bold 13px sans-serif"; ctx.fillText("A", a[0] + 5, a[1] - 5); ctx.fillText("B", b[0] + 5, b[1] - 5);
    }
    ctx.strokeStyle = "rgba(120,170,230,.55)"; ctx.lineWidth = 1; ctx.setLineDash([]); ctx.strokeRect(0.5, 0.5, W - 1, H - 1);   // حدّ العالم
    ctx.restore();
    // شريط مقياس الرسم (بإحداثيات الشاشة)
    const len = niceLen(140 / k), bw = len * k, bx = 12, by = CH - 14;
    ctx.fillStyle = "rgba(10,18,26,.7)"; ctx.fillRect(bx - 6, by - 20, bw + 12 + 54, 30);
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(bx, by - 6); ctx.lineTo(bx, by); ctx.lineTo(bx + bw, by); ctx.lineTo(bx + bw, by - 6); ctx.stroke();
    ctx.fillStyle = "#fff"; ctx.font = "12px sans-serif"; ctx.fillText(len >= 1000 ? `${len / 1000} كم` : `${len} م`, bx + bw + 8, by);
  });

  const world = (e: MouseEvent) => {
    const b = ref.current!.getBoundingClientRect();
    const px = e.clientX - b.left - ox, py = e.clientY - b.top - oy;      // بكسل العالم (بعد إزاحة التحريك)
    return { x: Math.min(Lx, Math.max(0, px / k)), y: Math.min(Ly, Math.max(0, Ly - py / k)), px, py };
  };

  const endPan = () => { panRef.current = null; setGrab(false); drag.current = null; };
  const down = (e: MouseEvent) => {
    if (e.button === 1 || e.button === 2 || (e.button === 0 && (hand || space.current))) {   // تحريك: زر الوسط/الأيمن، أداة اليد، أو Space
      e.preventDefault(); panRef.current = { x: e.clientX, y: e.clientY, cx: view.cx, cy: view.cy }; moved.current = false; setGrab(true); return;
    }
    if (e.button !== 0 || p.mode !== "select") return;
    const w = world(e);
    const selLine = p.sel?.t === "line" ? p.project.lines.find((l) => l.id === p.sel!.id) : null;
    if (selLine) {
      const i = selLine.points.findIndex(([x, y]) => { const [a, b] = toPx(x, y); return Math.hypot(a - w.px, b - w.py) < 9; });
      if (i >= 0) { drag.current = { t: "vertex", id: selLine.id, i }; return; }
    }
    const selBiome = p.sel?.t === "biome" ? p.project.biomes.find((b) => b.id === p.sel!.id) : null;
    if (selBiome) {
      const i = selBiome.polygon.findIndex(([x, y]) => { const [a, b] = toPx(x, y); return Math.hypot(a - w.px, b - w.py) < 9; });
      if (i >= 0) { drag.current = { t: "bvertex", id: selBiome.id, i }; return; }
    }
    const selZone = p.sel?.t === "zone" ? p.project.zones.find((z) => z.id === p.sel!.id) : null;
    if (selZone) {
      const i = selZone.polygon.findIndex(([x, y]) => { const [a, b] = toPx(x, y); return Math.hypot(a - w.px, b - w.py) < 9; });
      if (i >= 0) { drag.current = { t: "zvertex", id: selZone.id, i }; return; }
    }
    const po = p.project.pois.find((q) => { const [a, b] = toPx(q.x_m, q.y_m); return Math.hypot(a - w.px, b - w.py) <= 12; });
    if (po) { p.onSelect({ t: "poi", id: po.id }); drag.current = { t: "poi", id: po.id, ox: po.x_m - w.x, oy: po.y_m - w.y }; return; }
    const st = p.project.sites.find((s) => { const [a, b] = toPx(s.x_m, s.y_m); return Math.hypot(a - w.px, b - w.py) <= Math.max(10, ((s.shape === "circle" ? s.diameter_m : Math.hypot(s.width_m, s.length_m)) / 2) * k); });
    if (st) {
      const now = Date.now(), last = lastSite.current; lastSite.current = { id: st.id, t: now };
      if (p.onOpenSite && last && last.id === st.id && now - last.t < 450) { p.onOpenSite(st.id); lastSite.current = null; return; }   // نقر مزدوج على المنشأة
      p.onSelect({ t: "site", id: st.id }); drag.current = { t: "site", id: st.id, ox: st.x_m - w.x, oy: st.y_m - w.y }; return;
    }
    const pt = p.project.points.find((f) => { const [a, b] = toPx(f.x_m, f.y_m); return Math.hypot(a - w.px, b - w.py) <= Math.max(9, (f.diameter_m / 2) * k); });
    if (pt) { p.onSelect({ t: "point", id: pt.id }); drag.current = { t: "point", id: pt.id, ox: pt.x_m - w.x, oy: pt.y_m - w.y }; return; }
    const ln = p.project.lines.find((l) => { const pth = linePath(l.id, l.points).map(([x, y]) => toPx(x, y)); return pth.some((a, i) => i > 0 && distSeg(w.px, w.py, pth[i - 1], a) < 8); });
    if (ln) { p.onSelect({ t: "line", id: ln.id }); return; }
    const zn = p.project.zones.find((z) => inPoly(w.x, w.y, z.polygon));
    if (zn) { p.onSelect({ t: "zone", id: zn.id }); return; }
    const bm = p.project.biomes.find((b) => inPoly(w.x, w.y, b.polygon));
    p.onSelect(bm ? { t: "biome", id: bm.id } : null);
  };
  const move = (e: MouseEvent) => {
    const w = world(e); p.onHover(w.x, w.y);
    const pr = panRef.current;
    if (pr) {
      const dx = e.clientX - pr.x, dy = e.clientY - pr.y;
      if (Math.hypot(dx, dy) > 3) moved.current = true;
      setView((v) => ({ ...v, cx: Math.min(Lx, Math.max(0, pr.cx - dx / k)), cy: Math.min(Ly, Math.max(0, pr.cy + dy / k)) }));
      return;
    }
    const d = drag.current; if (!d) return;
    if (d.t === "point") p.onMovePoint(d.id, w.x + d.ox, w.y + d.oy); else if (d.t === "vertex") p.onMoveVertex(d.id, d.i, w.x, w.y); else if (d.t === "bvertex") p.onMoveBiomeVertex(d.id, d.i, w.x, w.y); else if (d.t === "zvertex") p.onMoveZoneVertex(d.id, d.i, w.x, w.y); else if (d.t === "site") p.onMoveSite(d.id, w.x + d.ox, w.y + d.oy); else p.onMovePoi?.(d.id, w.x + d.ox, w.y + d.oy);
  };
  const click = (e: MouseEvent) => {
    if (moved.current) { moved.current = false; return; }                   // انتهاء سحب تحريك: ليس نقرة
    if (hand || space.current || p.mode === "select") return;
    const w = world(e);
    if (w.px < 0 || w.py < 0 || w.px > W || w.py > H) return;               // نقرة خارج العالم
    p.onClickWorld(w.x, w.y);
  };

  const cursor = grab ? "grabbing" : hand ? "grab" : p.mode === "select" ? "default" : "crosshair";
  return (
    <div className="workspace" ref={wrapRef}>
      <canvas ref={ref} className="map" style={{ cursor }}
        onMouseDown={down} onMouseMove={move} onMouseUp={endPan} onMouseLeave={endPan} onContextMenu={(e) => e.preventDefault()}
        onClick={click} onDoubleClick={() => !hand && !space.current && (p.mode === "line" || p.mode === "biome" || p.mode === "zone" || p.mode === "route") && p.onDoubleClick()} />
      <div className="zoombar">
        <button title="تكبير" aria-label="تكبير" onClick={() => zoomAt(1.5)}>＋</button>
        <button title="تصغير" aria-label="تصغير" onClick={() => zoomAt(1 / 1.5)}>−</button>
        <button title="ملاءمة العالم للنافذة" aria-label="ملاءمة" onClick={fit}>⤢</button>
        <button className={hand ? "on" : ""} title="أداة التحريك: اسحب الخريطة" aria-label="تحريك" aria-pressed={hand} onClick={() => setHand((h) => !h)}>✋</button>
        <div className="pct">{Math.round(view.z * 100)}%</div>
      </div>
      <div className="wshint">عجلة الفأرة: تكبير · Space أو زر الوسط/الأيمن + سحب: تحريك</div>
    </div>
  );
}
