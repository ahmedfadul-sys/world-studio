// Plaza / square generator: a raised platform of any shape with stepped sides, an optional central dais and a ring of columns.
import { arcPoints, fromM, makeElement } from './model.js'

export const PLAZA_SHAPES = ['circle', 'ellipse', 'square', 'rect', 'hexagon', 'octagon', 'cross', 'custom']
const r6 = (v) => Math.round(v * 1e6) / 1e6

/** Unit outline (extent about ±1 in x and y) of a plaza shape. */
export function unitOutline(shape, custom) {
  const ngon = (n, rot = 0) => Array.from({ length: n }, (_, i) => { const a = rot + (2 * Math.PI * i) / n; return [Math.cos(a), Math.sin(a)] })
  switch (shape) {
    case 'circle': case 'ellipse': return arcPoints([0, 0], 1, 0, 2 * Math.PI, 64).slice(0, 64)
    case 'square': case 'rect': return [[-1, -1], [1, -1], [1, 1], [-1, 1]]
    case 'hexagon': return ngon(6)
    case 'octagon': return ngon(8, Math.PI / 8)
    case 'cross': { const a = 0.38; return [[-a, -1], [a, -1], [a, -a], [1, -a], [1, a], [a, a], [a, 1], [-a, 1], [-a, a], [-1, a], [-1, -a], [-a, -a]] }
    case 'custom': {
      if (!custom || custom.length < 3) return [[-1, -1], [1, -1], [1, 1], [-1, 1]]
      const cx = custom.reduce((s, p) => s + p[0], 0) / custom.length, cy = custom.reduce((s, p) => s + p[1], 0) / custom.length
      const hx = Math.max(...custom.map((p) => Math.abs(p[0] - cx))) || 1, hy = Math.max(...custom.map((p) => Math.abs(p[1] - cy))) || 1
      return custom.map((p) => [(p[0] - cx) / hx, (p[1] - cy) / hy])
    }
    default: return [[-1, -1], [1, -1], [1, 1], [-1, 1]]
  }
}

/**
 * opts (metres): {shape, width, depth (full extent), height (top of the plaza), tiers (steps around it, outward), tierRun, dais:{on, frac, height}, columns:{n, height, frac}, custom}
 * Returns elements for level `levelId`, centred on `centre` (project units).
 */
export function buildPlaza(opts, centre, levelId, unit) {
  const { shape = 'circle', width = 30, height = 0.6, tiers = 3, tierRun = 0.45, dais = { on: true, frac: 0.28, height: 0.5 }, columns = { n: 0, height: 5, frac: 0.88 }, custom } = opts
  const depth = shape === 'circle' || shape === 'square' || shape === 'hexagon' || shape === 'octagon' ? width : (opts.depth ?? width)
  const U = (m) => fromM(m, unit)
  const out = []
  const outline = unitOutline(shape, custom)
  const hx = width / 2, hy = depth / 2
  const poly = (grow, sx = 1, sy = 1) => outline.map((p) => {
    // grow = extra distance (m) outward on every side, applied per-axis
    const gx = (hx * sx + grow) / hx, gy = (hy * sy + grow) / hy
    return [r6(centre[0] + U(p[0] * hx * gx)), r6(centre[1] + U(p[1] * hy * gy))]
  })
  const riser = height / Math.max(1, tiers + 1)       // the plaza top is the highest step; `tiers` steps lead up to it from the ground
  const nT = Math.max(0, Math.round(tiers))
  // outer tiers first (lowest), top surface last
  for (let j = nT; j >= 0; j--) {
    const top = height - j * riser
    out.push(makeElement('floor', levelId, unit, { polygon: poly(j * tierRun), thickness: U(top), z_offset: U(top), material: 'mat_concrete', name: j === 0 ? 'Plaza' : `Plaza step ${nT - j + 1}` }))
  }
  if (dais && dais.on) {
    const f = Math.max(0.1, Math.min(0.7, dais.frac))
    const steps = 2, dr = dais.height / steps
    for (let s = steps; s >= 1; s--) {
      const top = height + dr * s
      const fs = f * (1 + (steps - s) * 0.0) * (1 + (steps - s) * 0.35)   // lower dais step is wider
      const g = (steps - s) * 0.35
      out.push(makeElement('floor', levelId, unit, { polygon: outline.map((p) => [r6(centre[0] + U(p[0] * hx * f) + U(p[0] * g * f * hx)), r6(centre[1] + U(p[1] * hy * f) + U(p[1] * g * f * hy))]), thickness: U(top), z_offset: U(top), material: 'mat_concrete', name: s === steps ? 'Dais' : 'Dais step' }))
    }
  }
  if (columns && columns.n >= 3) {
    const n = Math.min(64, Math.round(columns.n)), f = Math.max(0.5, Math.min(0.97, columns.frac))
    const ring = shape === 'circle' || shape === 'ellipse' ? Array.from({ length: n }, (_, i) => [Math.cos((2 * Math.PI * i) / n), Math.sin((2 * Math.PI * i) / n)]) : null
    const pts = ring || (() => {                       // polygonal shapes: columns spread along the outline
      const o = outline, total = o.reduce((s, p, i) => s + Math.hypot(o[(i + 1) % o.length][0] - p[0], o[(i + 1) % o.length][1] - p[1]), 0)
      const res = []
      for (let q = 0; q < n; q++) {
        let d = (total * q) / n
        for (let i = 0; i < o.length; i++) { const a = o[i], b = o[(i + 1) % o.length], L = Math.hypot(b[0] - a[0], b[1] - a[1]); if (d <= L + 1e-9) { res.push([a[0] + ((b[0] - a[0]) * d) / (L || 1), a[1] + ((b[1] - a[1]) * d) / (L || 1)]); break } d -= L }
      }
      return res
    })()
    for (const p of pts) out.push(makeElement('column', levelId, unit, { pos: [r6(centre[0] + U(p[0] * hx * f)), r6(centre[1] + U(p[1] * hy * f))], shape: 'round', width: U(0.7), depth: U(0.7), height: U(height + columns.height), material: 'mat_plaster', name: 'Plaza column' }))
  }
  return out
}
