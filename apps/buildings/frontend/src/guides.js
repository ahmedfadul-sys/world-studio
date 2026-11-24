// مخطط المدينة: خطوط إرشادية وهمية تظهر في المحرر ثنائي الأبعاد فقط (لا تدخل البناء ولا المعاينة ولا التصدير).
import { arcPoints, fromM, uid } from './model.js'

const rotPt = (o, a, x, y) => [o[0] + x * Math.cos(a) - y * Math.sin(a), o[1] + x * Math.sin(a) + y * Math.cos(a)]

export function makeGuide(kind, unit, fields = {}) {
  return { id: uid('gd'), name: null, kind, origin: [0, 0], angle_deg: 0, spacing_x: fromM(50, unit), spacing_y: fromM(50, unit), count_x: 6, count_y: 6, length: fromM(300, unit), b: null, color: '#35c4ff', visible: true, locked: false, ...fields }
}

/** Polylines (arrays of points) that draw the guide. */
export function guideLines(g) {
  const a = (g.angle_deg * Math.PI) / 180, o = g.origin
  const out = []
  if (g.kind === 'line') {
    out.push([o, g.b || rotPt(o, a, g.length, 0)])
  } else if (g.kind === 'parallel') {
    for (let i = 0; i < g.count_x; i++) out.push([rotPt(o, a, 0, i * g.spacing_x), rotPt(o, a, g.length, i * g.spacing_x)])
  } else if (g.kind === 'grid') {
    const W = g.count_x * g.spacing_x, H = g.count_y * g.spacing_y
    for (let i = 0; i <= g.count_x; i++) out.push([rotPt(o, a, i * g.spacing_x, 0), rotPt(o, a, i * g.spacing_x, H)])
    for (let j = 0; j <= g.count_y; j++) out.push([rotPt(o, a, 0, j * g.spacing_y), rotPt(o, a, W, j * g.spacing_y)])
  } else if (g.kind === 'radial') {
    const R = g.count_x * g.spacing_x
    for (let i = 1; i <= g.count_x; i++) out.push(arcPoints(o, i * g.spacing_x, 0, 2 * Math.PI, 72))
    for (let k = 0; k < g.count_y; k++) { const t = a + (2 * Math.PI * k) / g.count_y; out.push([o, [o[0] + R * Math.cos(t), o[1] + R * Math.sin(t)]]) }
  }
  return out
}

/** Intersections / end points that elements can snap to. */
export function guidePoints(g) {
  const a = (g.angle_deg * Math.PI) / 180, o = g.origin
  const pts = []
  if (g.kind === 'grid') {
    for (let i = 0; i <= g.count_x; i++) for (let j = 0; j <= g.count_y; j++) pts.push(rotPt(o, a, i * g.spacing_x, j * g.spacing_y))
  } else if (g.kind === 'parallel') {
    for (let i = 0; i < g.count_x; i++) pts.push(rotPt(o, a, 0, i * g.spacing_x), rotPt(o, a, g.length, i * g.spacing_x))
  } else if (g.kind === 'line') {
    pts.push(o, g.b || rotPt(o, a, g.length, 0))
  } else if (g.kind === 'radial') {
    pts.push(o)
    for (let k = 0; k < g.count_y; k++) { const t = a + (2 * Math.PI * k) / g.count_y; for (let i = 1; i <= g.count_x; i++) pts.push([o[0] + i * g.spacing_x * Math.cos(t), o[1] + i * g.spacing_x * Math.sin(t)]) }
  }
  return pts
}

/** Nearest guide snap to p within tol: a node first, otherwise the closest point on a guide line. Null when none. */
export function guideSnap(p, guides, tol) {
  let best = null
  const vis = guides.filter((g) => g.visible)
  for (const g of vis) for (const q of guidePoints(g)) {
    const d = Math.hypot(q[0] - p[0], q[1] - p[1])
    if (d <= tol && (!best || d < best.d)) best = { p: q, d }
  }
  if (best) return { p: best.p, kind: 'point' }
  for (const g of vis) for (const pl of guideLines(g)) for (let i = 0; i + 1 < pl.length; i++) {
    const a = pl[i], b = pl[i + 1], vx = b[0] - a[0], vy = b[1] - a[1], L2 = vx * vx + vy * vy
    if (L2 < 1e-12) continue
    const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L2))
    const q = [a[0] + t * vx, a[1] + t * vy], d = Math.hypot(q[0] - p[0], q[1] - p[1])
    if (d <= tol * 0.6 && (!best || d < best.d)) best = { p: q, d }
  }
  return best ? { p: best.p, kind: 'wall' } : null
}
