import type { Project, XY } from "./types";

export interface Sample { t: number; x: number; y: number; yaw?: number; pitch?: number }
export interface TEvent { t: number; type: string; x: number; y: number }
export interface Session { id: string; samples: Sample[]; events: TEvent[] }

/** JSON: { sessions:[{id, samples:[{t,x,y,yaw?,pitch?}], events:[{t,type,x,y}]}] }  أو CSV: session,t,x,y[,yaw,pitch][,event] */
export function parseTelemetry(text: string): Session[] {
  const t = text.trim();
  if (t.startsWith("{") || t.startsWith("[")) {
    const j = JSON.parse(t), arr = Array.isArray(j) ? j : j.sessions;
    return arr.map((s: Session, i: number) => ({ id: String(s.id ?? i), samples: [...s.samples].sort((a, b) => a.t - b.t), events: s.events ?? [] }));
  }
  const rows = t.split(/\r?\n/).map((r) => r.split(",").map((c) => c.trim())), head = rows[0].map((h) => h.toLowerCase());
  const ix = (n: string) => head.indexOf(n);
  const bySes = new Map<string, Session>();
  for (const r of rows.slice(1)) {
    if (r.length < 4) continue;
    const id = r[ix("session")] ?? "0";
    const ses = bySes.get(id) ?? { id, samples: [], events: [] };
    const sm: Sample = { t: +r[ix("t")], x: +r[ix("x")], y: +r[ix("y")] };
    if (ix("yaw") >= 0 && r[ix("yaw")] !== "") sm.yaw = +r[ix("yaw")];
    if (ix("pitch") >= 0 && r[ix("pitch")] !== "") sm.pitch = +r[ix("pitch")];
    ses.samples.push(sm);
    if (ix("event") >= 0 && r[ix("event")]) ses.events.push({ t: sm.t, type: r[ix("event")], x: sm.x, y: sm.y });
    bySes.set(id, ses);
  }
  return [...bySes.values()].map((s) => ({ ...s, samples: s.samples.sort((a, b) => a.t - b.t) }));
}

export interface TStats {
  sessions: number; meanDuration_s: number; medianDuration_s: number; meanDistance_m: number; meanSpeed_mps: number;
  pois: { id: string; name: string; visits: number; visitPct: number; meanDwell_s: number; meanArrival_s: number | null; lookedAt_s: number }[];
  pitchUp_pct: number | null; pitchDown_pct: number | null; adherence_pct: number | null; deaths: number; dropoffs: XY[];
  heat: HTMLCanvasElement;
}

const dist = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);
function distToPath(p: XY, path: XY[]) { let m = Infinity; for (let i = 1; i < path.length; i++) { const [x0, y0] = path[i - 1], [x1, y1] = path[i], vx = x1 - x0, vy = y1 - y0, L2 = vx * vx + vy * vy || 1e-9, t = Math.max(0, Math.min(1, ((p[0] - x0) * vx + (p[1] - y0) * vy) / L2)); m = Math.min(m, Math.hypot(p[0] - x0 - t * vx, p[1] - y0 - t * vy)); } return m; }

export function analyze(ses: Session[], project: Project, expected: XY[] | null): TStats {
  const Lx = project.world.size_x_m, Ly = project.world.size_y_m, N = 256, kx = N / Math.max(Lx, Ly);
  const W = Math.max(2, Math.round(Lx * kx)), H = Math.max(2, Math.round(Ly * kx)), grid = new Float32Array(W * H);
  const durs: number[] = [], dists: number[] = [], dropoffs: XY[] = [];
  let up = 0, down = 0, pitchN = 0, onPath = 0, pathN = 0, deaths = 0;
  const pois = project.pois.filter((p) => p.kind !== "player_start");
  const ps = pois.map((p) => ({ p, visits: 0, dwell: 0, arrive: [] as number[], look: 0 }));
  for (const s of ses) {
    const sm = s.samples; if (sm.length < 2) continue;
    durs.push(sm[sm.length - 1].t - sm[0].t);
    let d = 0;
    for (let i = 1; i < sm.length; i++) {
      const dt = Math.max(0, sm[i].t - sm[i - 1].t), seg = dist(sm[i], sm[i - 1]); d += seg;
      const gx = Math.floor((sm[i].x / Lx) * (W - 1)), gy = Math.floor(((Ly - sm[i].y) / Ly) * (H - 1));
      if (gx >= 0 && gx < W && gy >= 0 && gy < H) grid[gy * W + gx] += Math.min(dt, 5) + 0.2;
      if (sm[i].pitch !== undefined) { pitchN++; if (sm[i].pitch! > 15) up++; if (sm[i].pitch! < -15) down++; }
      if (expected) { pathN++; if (distToPath([sm[i].x, sm[i].y], expected) <= 100) onPath++; }
      for (const e of ps) {
        const R = Math.max(e.p.radius_m, 30);
        if (dist(sm[i], { x: e.p.x_m, y: e.p.y_m }) <= R) e.dwell += dt;
        if (sm[i].yaw !== undefined) {
          const dx = e.p.x_m - sm[i].x, dy = e.p.y_m - sm[i].y, dd = Math.hypot(dx, dy);
          if (dd > R && dd < project.player.view_distance_m) { const bearing = ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360; let diff = Math.abs(bearing - ((sm[i].yaw! % 360) + 360) % 360); diff = Math.min(diff, 360 - diff); if (diff <= 12) e.look += dt; }
        }
      }
    }
    dists.push(d);
    dropoffs.push([sm[sm.length - 1].x, sm[sm.length - 1].y]);
    deaths += s.events.filter((e) => e.type.toLowerCase() === "death").length;
    for (const e of ps) {
      const hit = sm.find((q) => dist(q, { x: e.p.x_m, y: e.p.y_m }) <= Math.max(e.p.radius_m, 30));
      if (hit) { e.visits++; e.arrive.push(hit.t - sm[0].t); }
    }
  }
  const sorted = [...durs].sort((a, b) => a - b), mean = (a: number[]) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
  // خريطة حرارة بتنعيم بسيط
  const sm2 = new Float32Array(W * H);
  for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) { let v = 0; for (let j = -2; j <= 2; j++) for (let i = -2; i <= 2; i++) { const yy = Math.min(H - 1, Math.max(0, y + j)), xx = Math.min(W - 1, Math.max(0, x + i)); v += grid[yy * W + xx] / (1 + Math.abs(i) + Math.abs(j)); } sm2[y * W + x] = v; }
  let mx = 0; for (const v of sm2) mx = Math.max(mx, v);
  const heat = document.createElement("canvas"); heat.width = W; heat.height = H;
  const img = new ImageData(W, H);
  for (let i = 0; i < sm2.length; i++) { const t = mx ? Math.min(1, Math.pow(sm2[i] / mx, 0.5)) : 0; img.data[i * 4] = 255 * Math.min(1, t * 2); img.data[i * 4 + 1] = 255 * Math.max(0, Math.min(1, t * 2 - 0.6)); img.data[i * 4 + 2] = 40; img.data[i * 4 + 3] = t < 0.04 ? 0 : 60 + 170 * t; }
  heat.getContext("2d")!.putImageData(img, 0, 0);
  const n = durs.length || 1;
  return {
    sessions: ses.length, meanDuration_s: mean(durs), medianDuration_s: sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0, meanDistance_m: mean(dists),
    meanSpeed_mps: mean(durs) ? mean(dists) / mean(durs) : 0,
    pois: ps.map((e) => ({ id: e.p.id, name: e.p.name || e.p.id, visits: e.visits, visitPct: (e.visits / n) * 100, meanDwell_s: e.visits ? e.dwell / e.visits : 0, meanArrival_s: e.arrive.length ? mean(e.arrive) : null, lookedAt_s: e.look })),
    pitchUp_pct: pitchN ? (up / pitchN) * 100 : null, pitchDown_pct: pitchN ? (down / pitchN) * 100 : null, adherence_pct: expected && pathN ? (onPath / pathN) * 100 : null,
    deaths, dropoffs, heat,
  };
}

/** عينة تجريبية: جلسات حول المسار المتوقع (لتجربة الواجهة قبل ربط لعبتك). */
export function syntheticSessions(path: XY[], n = 30, seed = 7): Session[] {
  let s = seed; const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  const cum = [0]; for (let i = 1; i < path.length; i++) cum.push(cum[i - 1] + Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]));
  const total = cum[cum.length - 1] || 1, out: Session[] = [];
  for (let k = 0; k < n; k++) {
    const speed = 3.5 + rnd() * 3, lat = 15 + rnd() * 50, stop = rnd() < 0.25 ? 0.2 + rnd() * 0.7 : 1; // 25% ينسحبون مبكراً
    const samples: Sample[] = [], events: TEvent[] = [];
    let d = 0, t = 0, j = 1;
    while (d < total * stop) {
      while (j < cum.length - 1 && cum[j] < d) j++;
      const f = (d - cum[j - 1]) / Math.max(cum[j] - cum[j - 1], 1e-9), [x0, y0] = path[j - 1], [x1, y1] = path[j];
      const hx = x1 - x0, hy = y1 - y0, hl = Math.hypot(hx, hy) || 1, off = (rnd() - 0.5) * 2 * lat;
      samples.push({ t, x: x0 + hx * f + (-hy / hl) * off, y: y0 + hy * f + (hx / hl) * off, yaw: (((Math.atan2(hx, hy) * 180) / Math.PI + (rnd() - 0.5) * 60) + 360) % 360, pitch: (rnd() - 0.5) * 40 });
      const pause = rnd() < 0.05 ? 8 + rnd() * 20 : 0;
      t += 2 + pause; d += speed * (2 + 0) * (pause ? 0.1 : 1);
    }
    if (stop < 1 && rnd() < 0.6) events.push({ t, type: "death", x: samples[samples.length - 1].x, y: samples[samples.length - 1].y });
    out.push({ id: `sim-${k + 1}`, samples, events });
  }
  return out;
}
