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
  const svg = useRef<SVGSVGElement>(null);
  const VW = 320, k = VW / W, VH = Math.max(40, H * k);

  const toWorld = (e: React.PointerEvent) => {
    const r = svg.current!.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * W, y = H - ((e.clientY - r.top) / r.height) * H;     // الشمال للأعلى
    const q = (v: number) => (snap > 0 ? Math.round(v / snap) * snap : v);
    return { x: Math.min(W, Math.max(0, q(x))), y: Math.min(H, Math.max(0, q(y))) };
  };
  const down = (e: React.PointerEvent) => { svg.current!.setPointerCapture(e.pointerId); const p = toWorld(e); setDrag({ x0: p.x, y0: p.y, x1: p.x, y1: p.y }); };
  const move = (e: React.PointerEvent) => { if (!drag) return; const p = toWorld(e); setDrag({ ...drag, x1: p.x, y1: p.y }); };
  const up = () => {
    if (!drag) return;
    const x = Math.min(drag.x0, drag.x1), y = Math.min(drag.y0, drag.y1), w = Math.abs(drag.x1 - drag.x0), h = Math.abs(drag.y1 - drag.y0);
    setDrag(null);
    if (w < 1 || h < 1) return;
    const id = `level-${Date.now().toString(36)}`;
    onChange((p) => { (p.levels ??= []).push({ id, name: `Level ${p.levels.length + 1}`, x_m: x, y_m: y, w_m: w, h_m: h }); });
    setSel(id);
  };
  const upd = (id: string, patch: Partial<Level>) => onChange((p) => { const l = p.levels?.find((v) => v.id === id); if (l) Object.assign(l, patch); });
  const del = (id: string) => { onChange((p) => { p.levels = (p.levels ?? []).filter((v) => v.id !== id); }); if (sel === id) setSel(null); };
  const grid = (n: number) => {
    const cols = Math.max(1, Math.round(n)), rows = Math.max(1, Math.round(n));
    onChange((p) => { p.levels = []; let i = 1; for (let r = rows - 1; r >= 0; r--) for (let c = 0; c < cols; c++) p.levels.push({ id: `level-${i}`, name: `Level ${i++}`, x_m: (W / cols) * c, y_m: (H / rows) * r, w_m: W / cols, h_m: H / rows }); });
  };
  const bad = (l: Level) => l.x_m + l.w_m > W + 1e-6 || l.y_m + l.h_m > H + 1e-6;
  const overlap = (a: Level, b: Level) => a.x_m < b.x_m + b.w_m && b.x_m < a.x_m + a.w_m && a.y_m < b.y_m + b.h_m && b.y_m < a.y_m + a.h_m;
  const overl = levels.some((a, i) => levels.some((b, j) => j > i && overlap(a, b)));
  const num = (v: number, f: (n: number) => void, label: string) => (
    <label className="field"><span>{label}</span><input type="number" dir="ltr" value={Math.round(v * 100) / 100} min={0} onChange={(e) => f(Math.max(0, Number(e.target.value) || 0))} /></label>);

  return (
    <div className="levels">
      <h2>تصميم المراحل</h2>
      <p className="hint">العالم واحد ({(W / 1000).toFixed(1)} × {(H / 1000).toFixed(1)} كم). اسحب على الخريطة لرسم مرحلة، أو قسّمه شبكةً دفعة واحدة. التصدير ملف ZIP فيه مجلد لكل مرحلة بملف Godot ‏.tscn.</p>
      <svg ref={svg} className="levelmap" viewBox={`0 0 ${VW} ${VH}`} onPointerDown={down} onPointerMove={move} onPointerUp={up} role="img" aria-label="خريطة تقسيم المراحل">
        <rect x={0} y={0} width={VW} height={VH} className="lm-world" />
        {levels.map((l, i) => (
          <g key={l.id} onPointerDown={(e) => { e.stopPropagation(); setSel(l.id); }}>
            <rect x={l.x_m * k} y={(H - l.y_m - l.h_m) * k} width={l.w_m * k} height={l.h_m * k} fill={COLORS[i % COLORS.length]} fillOpacity={sel === l.id ? 0.55 : 0.3} stroke={bad(l) ? "#ff4d4d" : COLORS[i % COLORS.length]} strokeWidth={sel === l.id ? 2.5 : 1.2} />
            <text x={(l.x_m + l.w_m / 2) * k} y={(H - l.y_m - l.h_m / 2) * k} textAnchor="middle" dominantBaseline="middle" className="lm-text">{i + 1}</text>
          </g>))}
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
          <div className="row">{num(l.x_m, (v) => upd(l.id, { x_m: v }), "غرب (م)")}{num(l.y_m, (v) => upd(l.id, { y_m: v }), "جنوب (م)")}</div>
          <div className="row">{num(l.w_m, (v) => upd(l.id, { w_m: Math.max(10, v) }), "العرض (م)")}{num(l.h_m, (v) => upd(l.id, { h_m: Math.max(10, v) }), "الطول (م)")}</div>
          {bad(l) && <div className="msg error">المرحلة تخرج عن حدود العالم.</div>}
        </div>); })()}
      {overl && <div className="msg">بعض المراحل متداخلة — مسموح، لكن الحواف المشتركة ستُكرَّر.</div>}
      <button className="primary" disabled={!levels.length || levels.some(bad) || busy !== null} onClick={onExport}>{busy ? busy : "تصدير المراحل (Godot ‏.tscn ‏ZIP)"}</button>
    </div>
  );
}
