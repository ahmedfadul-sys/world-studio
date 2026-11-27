import { useRef, useState } from "react";
import type { Level, Project } from "./types";

const COLORS = ["#4f8cff", "#ff9f43", "#2ecc71", "#e84393", "#a29bfe", "#f1c40f", "#00cec9", "#fd7272"];

/** تبويب «تصميم المراحل»: العالم واحد، وكل مرحلة مستطيل منه. اسحب على الخريطة لرسم مرحلة جديدة. */
export default function LevelsPanel({ project, onChange, onExport, busy }: { project: Project; onChange: (fn: (p: Project) => void) => void; onExport: () => void; busy: string | null }) {
  const W = project.world.size_x_m, H = project.world.size_y_m;
  const levels = project.levels ?? [];
  const [sel, setSel] = useState<string | null>(null);
  const [snap, setSnap] = useState(100);
  const [drag, setDrag] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [vdrag, setVdrag] = useState<{ id: string; i: number } | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const VW = 320, k = VW / W, VH = Math.max(40, H * k);

  const toWorld = (e: React.PointerEvent) => {
    const r = svg.current!.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * W, y = H - ((e.clientY - r.top) / r.height) * H;     // الشمال للأعلى
    const q = (v: number) => (snap > 0 ? Math.round(v / snap) * snap : v);
    return { x: Math.min(W, Math.max(0, q(x))), y: Math.min(H, Math.max(0, q(y))) };
  };
  const ptsOf = (l: Level): [number, number][] => l.points ?? [[l.x_m, l.y_m], [l.x_m + l.w_m, l.y_m], [l.x_m + l.w_m, l.y_m + l.h_m], [l.x_m, l.y_m + l.h_m]];
  /** يكتب الحدود ويحدّث الصندوق المحيط (يستعمله المصدّر). */
  const setPts = (id: string, pts: [number, number][]) => onChange((p) => {
    const l = p.levels?.find((v) => v.id === id); if (!l) return;
    const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]);
    l.points = pts; l.x_m = Math.min(...xs); l.y_m = Math.min(...ys); l.w_m = Math.max(10, Math.max(...xs) - l.x_m); l.h_m = Math.max(10, Math.max(...ys) - l.y_m);
  });
  const down = (e: React.PointerEvent) => { svg.current!.setPointerCapture(e.pointerId); const p = toWorld(e); setDrag({ x0: p.x, y0: p.y, x1: p.x, y1: p.y }); };
  const move = (e: React.PointerEvent) => {
    if (vdrag) { const l = levels.find((v) => v.id === vdrag.id); if (!l) return; const p = toWorld(e); const pts = ptsOf(l).map((q) => q.slice() as [number, number]); pts[vdrag.i] = [p.x, p.y]; setPts(l.id, pts); return; }
    if (!drag) return; const p = toWorld(e); setDrag({ ...drag, x1: p.x, y1: p.y }); };
  const up = () => {
    if (vdrag) { setVdrag(null); return; }
    if (!drag) return;
    const x = Math.min(drag.x0, drag.x1), y = Math.min(drag.y0, drag.y1), w = Math.abs(drag.x1 - drag.x0), h = Math.abs(drag.y1 - drag.y0);
    setDrag(null);
    if (w < 1 || h < 1) return;
    const id = `level-${Date.now().toString(36)}`;
    onChange((p) => { (p.levels ??= []).push({ id, name: `Level ${p.levels.length + 1}`, x_m: x, y_m: y, w_m: w, h_m: h, points: [[x, y], [x + w, y], [x + w, y + h], [x, y + h]] }); });
    setSel(id);
  };
  const upd = (id: string, patch: Partial<Level>) => onChange((p) => { const l = p.levels?.find((v) => v.id === id); if (l) Object.assign(l, patch); });
  const del = (id: string) => { onChange((p) => { p.levels = (p.levels ?? []).filter((v) => v.id !== id); }); if (sel === id) setSel(null); };
  const grid = (n: number) => {
    const cols = Math.max(1, Math.round(n)), rows = Math.max(1, Math.round(n));
    onChange((p) => { p.levels = []; let i = 1; for (let r = rows - 1; r >= 0; r--) for (let c = 0; c < cols; c++) { const x = (W / cols) * c, y = (H / rows) * r, w = W / cols, h = H / rows; p.levels.push({ id: `level-${i}`, name: `Level ${i++}`, x_m: x, y_m: y, w_m: w, h_m: h, points: [[x, y], [x + w, y], [x + w, y + h], [x, y + h]] }); } });
  };
  const bad = (l: Level) => l.x_m + l.w_m > W + 1e-6 || l.y_m + l.h_m > H + 1e-6;
  const overlap = (a: Level, b: Level) => a.x_m < b.x_m + b.w_m && b.x_m < a.x_m + a.w_m && a.y_m < b.y_m + b.h_m && b.y_m < a.y_m + a.h_m;
  const overl = levels.some((a, i) => levels.some((b, j) => j > i && overlap(a, b)));
  const _unusedNum = (v: number, f: (n: number) => void, label: string) => (
    <label className="field"><span>{label}</span><input type="number" dir="ltr" value={Math.round(v * 100) / 100} min={0} onChange={(e) => f(Math.max(0, Number(e.target.value) || 0))} /></label>);

  return (
    <div className="levels">
      <h2>تصميم المراحل</h2>
      <p className="hint">العالم واحد ({(W / 1000).toFixed(1)} × {(H / 1000).toFixed(1)} كم). اسحب على الخريطة لرسم مرحلة، ثم حرّك نقاطها (الكبيرة) لتتبع التضاريس، واسحب النقاط الصغيرة على الأضلاع لإضافة نقطة، ونقر مزدوج على نقطة يحذفها. أو قسّمه شبكةً دفعة واحدة. التصدير ملف ZIP فيه مجلد لكل مرحلة بملف Godot ‏.tscn.</p>
      <svg ref={svg} className="levelmap" viewBox={`0 0 ${VW} ${VH}`} onPointerDown={down} onPointerMove={move} onPointerUp={up} role="img" aria-label="خريطة تقسيم المراحل">
        <rect x={0} y={0} width={VW} height={VH} className="lm-world" />
        {levels.map((l, i) => { const pts = ptsOf(l); const col = COLORS[i % COLORS.length]; const P = pts.map(([x, y]) => `${x * k},${(H - y) * k}`).join(" ");
          const cx = pts.reduce((a, q) => a + q[0], 0) / pts.length, cy = pts.reduce((a, q) => a + q[1], 0) / pts.length;
          return (
          <g key={l.id} onPointerDown={(e) => { e.stopPropagation(); setSel(l.id); }}>
            <polygon points={P} fill={col} fillOpacity={sel === l.id ? 0.5 : 0.28} stroke={bad(l) ? "#ff4d4d" : col} strokeWidth={sel === l.id ? 2.5 : 1.2} strokeLinejoin="round" />
            <text x={cx * k} y={(H - cy) * k} textAnchor="middle" dominantBaseline="middle" className="lm-text">{i + 1}</text>
          </g>); })}
        {(() => { const l = levels.find((v) => v.id === sel); if (!l) return null; const pts = ptsOf(l); return (<g>
          {pts.map((q, i) => { const n = pts[(i + 1) % pts.length]; const mx = (q[0] + n[0]) / 2, my = (q[1] + n[1]) / 2; return (
            <circle key={"m" + i} cx={mx * k} cy={(H - my) * k} r={4} className="lm-mid" onPointerDown={(e) => { e.stopPropagation(); svg.current!.setPointerCapture(e.pointerId); const np = pts.map((z) => z.slice() as [number, number]); np.splice(i + 1, 0, [mx, my]); setPts(l.id, np); setVdrag({ id: l.id, i: i + 1 }); }}><title>اسحب لإضافة نقطة</title></circle>); })}
          {pts.map((q, i) => (
            <circle key={"v" + i} cx={q[0] * k} cy={(H - q[1]) * k} r={6} className="lm-vtx"
              onPointerDown={(e) => { e.stopPropagation(); svg.current!.setPointerCapture(e.pointerId); setVdrag({ id: l.id, i }); }}
              onDoubleClick={(e) => { e.stopPropagation(); if (pts.length > 3) setPts(l.id, pts.filter((_, j) => j !== i)); }}><title>اسحب لتحريك النقطة · نقر مزدوج لحذفها</title></circle>))}
        </g>); })()}
        {drag && <rect x={Math.min(drag.x0, drag.x1) * k} y={(H - Math.max(drag.y0, drag.y1)) * k} width={Math.abs(drag.x1 - drag.x0) * k} height={Math.abs(drag.y1 - drag.y0) * k} className="lm-drag" />}
      </svg>
      <div className="row">
        <label className="field"><span>التقريب (م)</span><select value={snap} onChange={(e) => setSnap(Number(e.target.value))}>{[0, 10, 50, 100, 250, 500, 1000].map((v) => <option key={v} value={v}>{v === 0 ? "حر" : v}</option>)}</select></label>
        <label className="field"><span>تقسيم شبكة</span><select value="" onChange={(e) => e.target.value && grid(Number(e.target.value))}><option value="">اختر…</option>{[1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n} × {n}</option>)}</select></label>
      </div>
      <ul className="list">{levels.map((l, i) => (
        <li key={l.id} className={"matrow" + (sel === l.id ? " on" : "")}>
          <span className="lvdot" style={{ background: COLORS[i % COLORS.length] }} />
          <button className={sel === l.id ? "on" : ""} onClick={() => setSel(l.id)}>{l.name || l.id}</button>
          <button className="danger" onClick={() => del(l.id)} aria-label="حذف المرحلة">✕</button>
        </li>))}</ul>
      {levels.find((l) => l.id === sel) && (() => { const l = levels.find((v) => v.id === sel)!; return (
        <div className="editor">
          <input className="title" value={l.name} onChange={(e) => upd(l.id, { name: e.target.value })} />
          <p className="hint">{ptsOf(l).length} نقاط · الصندوق المحيط {Math.round(l.w_m)} × {Math.round(l.h_m)} م</p>
          <button onClick={() => setPts(l.id, [[l.x_m, l.y_m], [l.x_m + l.w_m, l.y_m], [l.x_m + l.w_m, l.y_m + l.h_m], [l.x_m, l.y_m + l.h_m]])}>إعادة إلى مستطيل</button>
          {bad(l) && <div className="msg error">المرحلة تخرج عن حدود العالم.</div>}
        </div>); })()}
      {overl && <div className="msg">بعض المراحل متداخلة — مسموح، لكن الحواف المشتركة ستُكرَّر.</div>}
      <button className="primary" disabled={!levels.length || levels.some(bad) || busy !== null} onClick={onExport}>{busy ? busy : "تصدير المراحل (Godot ‏.tscn ‏ZIP)"}</button>
    </div>
  );
}
