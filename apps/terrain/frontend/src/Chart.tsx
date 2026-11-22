interface Series { y: number[]; color: string; label: string }
export default function Chart({ title, x, series, sea, xLabel = "المسافة (م)" }: { title: string; x: number[]; series: Series[]; sea?: number; xLabel?: string }) {
  const W = 560, H = 190, m = { l: 48, r: 10, t: 22, b: 28 };
  const all = series.flatMap((s) => s.y).concat(sea !== undefined ? [sea] : []);
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi - lo < 1) { hi += 0.5; lo -= 0.5; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const x0 = x[0], x1 = x[x.length - 1] || 1;
  const sx = (v: number) => m.l + ((v - x0) / (x1 - x0 || 1)) * (W - m.l - m.r);
  const sy = (v: number) => H - m.b - ((v - lo) / (hi - lo)) * (H - m.t - m.b);
  const path = (ys: number[]) => ys.map((v, i) => `${i ? "L" : "M"}${sx(x[i]).toFixed(1)},${sy(v).toFixed(1)}`).join("");
  return (
    <figure className="chart" dir="ltr">
      <figcaption dir="rtl">{title} · الفرق الرأسي مُكبَّر {((H - m.t - m.b) / (hi - lo) / ((W - m.l - m.r) / (x1 - x0 || 1))).toFixed(1)}×</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
        {[0, 0.5, 1].map((t) => { const v = lo + t * (hi - lo); return <g key={t}><line x1={m.l} x2={W - m.r} y1={sy(v)} y2={sy(v)} stroke="var(--line)" /><text x={m.l - 5} y={sy(v) + 4} textAnchor="end" fontSize="10" fill="var(--mute)">{v.toFixed(0)}</text></g>; })}
        {sea !== undefined && sea > lo && sea < hi && <line x1={m.l} x2={W - m.r} y1={sy(sea)} y2={sy(sea)} stroke="#4aa3ff" strokeDasharray="4 3" />}
        {series.map((s) => <path key={s.label} d={path(s.y)} fill="none" stroke={s.color} strokeWidth="1.8" />)}
        <text x={W / 2} y={H - 6} textAnchor="middle" fontSize="10" fill="var(--mute)">{xLabel}: {x0.toFixed(0)} → {x1.toFixed(0)}</text>
        {series.map((s, i) => <text key={s.label} x={m.l + 6 + i * 110} y={13} fontSize="11" fill={s.color}>● {s.label}</text>)}
      </svg>
    </figure>
  );
}
