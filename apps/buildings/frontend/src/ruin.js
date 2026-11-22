// "Ruin" tool: cuts a building along a jagged line, lowers / breaks the walls near the cut, drops slabs and roofs, and scatters debris.
// Pure function over the project's elements; everything stays editable and Undo restores the building.
import { fromM, makeElement, pointInPolygon } from './model.js'
import { splitWallAt } from './plan.js'

export function rng(seed) {
  let a = (seed >>> 0) || 1
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296 }
}
const clamp = (v, a, b) => Math.max(a, Math.min(b, v))
const lerp = (a, b, t) => a + (b - a) * t
const r6 = (v) => Math.round(v * 1e6) / 1e6
const area = (poly) => Math.abs(poly.reduce((s, p, i) => { const q = poly[(i + 1) % poly.length]; return s + (p[0] * q[1] - q[0] * p[1]) }, 0) / 2)

/** Keep the part of `poly` with dot(p - c, n) <= d (Sutherland–Hodgman against one half-plane). */
export function clipHalfPlane(poly, c, n, d) {
  const f = (p) => (p[0] - c[0]) * n[0] + (p[1] - c[1]) * n[1] - d
  const out = []
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i], q = poly[(i + 1) % poly.length], fp = f(p), fq = f(q)
    if (fp <= 0) out.push(p)
    if ((fp < 0 && fq > 0) || (fp > 0 && fq < 0)) { const t = fp / (fp - fq); out.push([r6(p[0] + (q[0] - p[0]) * t), r6(p[1] + (q[1] - p[1]) * t)]) }
  }
  return out
}

/**
 * opts: {unit, levels, seed, severity 0..1, cutAngle (deg | null = random), cutOffset -0.5..0.5 (fraction of the footprint), jag 0..1,
 *        debris 0..1, ids (Set | null: only these elements), levelIds (array | null)}
 */
export function ruinElements(elements, opts) {
  const { unit, levels, seed = 1, severity = 0.6, jag = 0.5, debris = 0.6 } = opts
  const k = fromM(1, unit)
  const R = rng(seed)
  const inScope = (e) => (!opts.ids || opts.ids.has(e.id)) && (!opts.levelIds || opts.levelIds.includes(e.level_id))
  const lvls = [...levels].sort((a, b) => a.elevation - b.elevation)
  const li = Object.fromEntries(lvls.map((l, i) => [l.id, i]))
  const lh = Object.fromEntries(lvls.map((l) => [l.id, l.height]))
  const stats = { removedWalls: 0, loweredWalls: 0, removedFloors: 0, brokenOpenings: 0, removedOthers: 0, debris: 0 }
  const scoped = elements.filter(inScope)
  const pts = []
  for (const e of scoped) { if (e.type === 'wall') pts.push(e.a, e.b); else if (e.polygon) pts.push(...e.polygon) }
  if (!pts.length) return { elements, stats }
  const x0 = Math.min(...pts.map((p) => p[0])), x1 = Math.max(...pts.map((p) => p[0]))
  const y0 = Math.min(...pts.map((p) => p[1])), y1 = Math.max(...pts.map((p) => p[1]))
  const c = [(x0 + x1) / 2, (y0 + y1) / 2]
  const ext = Math.max(x1 - x0, y1 - y0) / 2
  const th = ((opts.cutAngle ?? R() * 360) * Math.PI) / 180
  const tdir = [Math.cos(th), Math.sin(th)], n = [-Math.sin(th), Math.cos(th)]
  const off0 = (opts.cutOffset ?? 0.15) * ext * 2
  const stagger = 0.1 * ext
  // jagged cut line: random offsets every ~2 m along the line, linearly interpolated
  const step = 2 * k, K = Math.max(4, Math.ceil((ext * 2.4) / step))
  const jv = Array.from({ length: K + 1 }, () => (R() * 2 - 1) * jag * 1.6 * k)
  const jagAt = (s) => { const u = clamp((s + ext * 1.2) / step, 0, K - 1e-9); const i = Math.floor(u); return lerp(jv[i], jv[i + 1], u - i) }
  const cutD = (lv) => off0 - (li[lv] || 0) * stagger * severity
  const margin = (p, lv) => cutD(lv) + jagAt((p[0] - c[0]) * tdir[0] + (p[1] - c[1]) * tdir[1]) - ((p[0] - c[0]) * n[0] + (p[1] - c[1]) * n[1])
  const band = (4 + severity * 8) * k
  const removedMids = []
  let removedLen = 0, removedFloorArea = 0

  // 1) split the walls that touch the damage zone into short pieces
  let els = elements
  for (const w of elements.filter((e) => e.type === 'wall' && inScope(e))) {
    const L = Math.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1])
    const ms = [0, 0.25, 0.5, 0.75, 1].map((t) => margin([w.a[0] + (w.b[0] - w.a[0]) * t, w.a[1] + (w.b[1] - w.a[1]) * t], w.level_id))
    if (Math.max(...ms) < 0 || (Math.min(...ms) > band && R() > severity * 0.5)) continue
    const cuts = []
    let s = (0.7 + R() * 1.1) * k
    while (s < L - 0.5 * k) { cuts.push(s); s += (0.7 + R() * 1.1) * k }
    els = splitWallAt(els, w.id, cuts)
  }
  // 2) walls: remove / lower pieces
  const removed = new Set()
  const lowered = new Map()
  for (const w of els.filter((e) => e.type === 'wall' && inScope(e) && (!opts.ids || true))) {
    const mid = [(w.a[0] + w.b[0]) / 2, (w.a[1] + w.b[1]) / 2]
    const m = margin(mid, w.level_id)
    const L = Math.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1])
    const ground = li[w.level_id] === 0
    if (m < 0 || (R() < severity * (ground ? 0.06 : 0.14) && m < band * 2)) { removed.add(w.id); removedMids.push({ p: mid, L }); removedLen += L; stats.removedWalls++; continue }
    const H = w.height ?? lh[w.level_id] ?? 3 * k
    let f = 1
    if (m < band) f = lerp(0.15, 1, m / band) * (0.65 + 0.35 * R())
    if (R() < severity * 0.5) f *= 0.3 + 0.7 * R()
    f = ground ? Math.max(f, 0.3) : f
    if (f < 0.97) { const nh = Math.max(0.3 * k, H * f); lowered.set(w.id, nh); stats.loweredWalls++ }
  }
  // 3) openings on removed / lowered walls
  const out = []
  for (const e of els) {
    if (e.type === 'wall') {
      if (removed.has(e.id)) continue
      out.push(lowered.has(e.id) ? { ...e, height: r6(lowered.get(e.id)), overrides: [...new Set([...(e.overrides || []), 'height'])] } : e)
      continue
    }
    if (e.type === 'door' || e.type === 'window' || e.type === 'opening') {
      if (removed.has(e.wall_id)) continue
      const nh = lowered.get(e.wall_id)
      if (nh !== undefined) {
        const sill = e.sill || 0
        if (sill >= nh - 0.2 * k) continue
        if (sill + e.height > nh) { stats.brokenOpenings++; out.push({ ...e, type: 'opening', height: r6(nh - sill), material: null, hinge: undefined, swing: undefined }); continue }
      }
      if (R() < severity * 0.45 && e.type !== 'opening' && nh !== undefined) { stats.brokenOpenings++; out.push({ ...e, type: 'opening', material: null, hinge: undefined, swing: undefined }); continue }
      out.push(e); continue
    }
    if (!inScope(e)) { out.push(e); continue }
    const lv = e.level_id
    if (e.type === 'floor' && li[lv] >= 1) {
      let poly = clipHalfPlane(e.polygon, c, n, cutD(lv))
      if (poly.length < 3 || area(poly) < 0.5 * k * k) { stats.removedFloors++; removedFloorArea += area(e.polygon); continue }
      removedFloorArea += Math.max(0, area(e.polygon) - area(poly))
      let holes = e.holes || []
      if (severity > 0.35 && area(poly) > 12 * k * k && R() < severity) {   // a collapsed section inside the slab
        const bx = poly.map((p) => p[0]), by = poly.map((p) => p[1])
        for (let t = 0; t < 6; t++) {
          const w = (1.5 + R() * 2.5) * k, h = (1.5 + R() * 2.5) * k
          const x = Math.min(...bx) + R() * (Math.max(...bx) - Math.min(...bx) - w), y = Math.min(...by) + R() * (Math.max(...by) - Math.min(...by) - h)
          const rect = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
          const m = 0.4 * k
          const inner = [[x - m, y - m], [x + w + m, y - m], [x + w + m, y + h + m], [x - m, y + h + m]]
          if (inner.every((q) => pointInPolygon(q, poly)) && poly.every((q) => !(q[0] > x - m && q[0] < x + w + m && q[1] > y - m && q[1] < y + h + m))) { holes = [...holes, rect.map((q) => [r6(q[0]), r6(q[1])])]; break }
        }
      }
      out.push({ ...e, polygon: poly, holes })
      continue
    }
    if (e.type === 'roof') {
      if (severity >= 0.45 || (li[lv] ?? 0) >= 0 && R() < severity) { stats.removedOthers++; continue }
      const poly = clipHalfPlane(e.polygon, c, n, cutD(lv))
      if (poly.length < 3 || area(poly) < 0.5 * k * k) { stats.removedOthers++; continue }
      out.push({ ...e, polygon: poly }); continue
    }
    const at = e.type === 'wall' ? null : e.pos || (e.a && e.b ? [(e.a[0] + e.b[0]) / 2, (e.a[1] + e.b[1]) / 2] : e.start || (e.polygon && e.polygon[0]))
    if (at && ['column', 'beam', 'stair', 'decor', 'room'].includes(e.type) && margin(e.type === 'room' ? e.polygon.reduce((a, p) => [a[0] + p[0] / e.polygon.length, a[1] + p[1] / e.polygon.length], [0, 0]) : at, lv) < 0) { stats.removedOthers++; continue }
    out.push(e)
  }
  // 3b) every remaining opening must fit its (shorter / lower) wall piece: shrink it, or drop it when nothing sensible is left
  const wallOf = Object.fromEntries(out.filter((e) => e.type === 'wall').map((e) => [e.id, e]))
  const fitted = []
  for (const e of out) {
    if (!(e.type === 'door' || e.type === 'window' || e.type === 'opening')) { fitted.push(e); continue }
    const w = wallOf[e.wall_id]
    if (!w) continue
    const L = Math.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1]), H = w.height ?? lh[w.level_id] ?? 3 * k
    const pad = 0.05 * k
    let width = e.width, height = e.height
    const sill = e.sill || 0
    let kind = e.type
    if (width > L - 2 * pad) { width = L - 2 * pad; kind = 'opening' }
    if (sill + height > H - 1.6 * pad) { height = H - 1.6 * pad - sill; kind = 'opening' }
    if (width < 0.35 * k || height < 0.3 * k) { stats.brokenOpenings++; continue }
    const mid = Math.max(width / 2 + pad, Math.min(L - width / 2 - pad, e.offset))
    fitted.push(kind === e.type && width === e.width && height === e.height && mid === e.offset ? e : { ...e, type: kind, width: r6(width), height: r6(height), offset: r6(mid), ...(kind === 'opening' ? { material: null, hinge: undefined, swing: undefined } : {}) })
  }
  out.length = 0; out.push(...fitted)
  // 4) debris on the ground level, near what was removed and along the cut line
  const ground = lvls[0]
  const sources = removedMids.map((r) => r.p)
  for (let s = -ext * 1.1; s <= ext * 1.1; s += 2.5 * k) {
    const p = [c[0] + tdir[0] * s + n[0] * (cutD(ground.id) + jagAt(s)), c[1] + tdir[1] * s + n[1] * (cutD(ground.id) + jagAt(s))]
    if (p[0] > x0 - 3 * k && p[0] < x1 + 3 * k && p[1] > y0 - 3 * k && p[1] < y1 + 3 * k) sources.push(p)
  }
  const want = Math.min(600, Math.round(debris * ((removedLen / k) * 0.9 + (removedFloorArea / (k * k)) * 0.12 + sources.length * 0.4)))
  for (let i = 0; i < want && sources.length; i++) {
    const src = sources[Math.floor(R() * sources.length)]
    const dn = R() * 3.5 * k, dt = (R() * 2 - 1) * 2.2 * k
    const big = R() < 0.18
    const sz = [(big ? 0.7 + R() * 0.9 : 0.2 + R() * 0.55) * k, (big ? 0.5 + R() * 0.6 : 0.15 + R() * 0.4) * k, (big ? 0.25 + R() * 0.4 : 0.1 + R() * 0.3) * k]
    out.push(makeElement('decor', ground.id, unit, { pos: [r6(src[0] + n[0] * dn + tdir[0] * dt), r6(src[1] + n[1] * dn + tdir[1] * dt)], z: 0, size: sz.map(r6), shape: 'box', rotation_deg: Math.round(R() * 360), material: 'mat_concrete', name: 'Debris', props: { debris: true } }))
    stats.debris++
  }
  return { elements: out, stats, cut: { c, angle: (th * 180) / Math.PI } }
}

export const isDebris = (e) => e.type === 'decor' && e.props && e.props.debris
export const clearDebris = (elements) => elements.filter((e) => !isDebris(e))
