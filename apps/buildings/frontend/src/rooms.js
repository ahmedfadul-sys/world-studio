// Room editing: merge two adjacent rooms (shared walls removed) and split a room with a new interior wall (+ door).
import { fromM, makeElement, uid } from './model.js'
import { splitWallAt } from './plan.js'

const r6 = (v) => Math.round(v * 1e6) / 1e6
const EPS = 1e-4
const signedArea = (p) => p.reduce((s, a, i) => { const b = p[(i + 1) % p.length]; return s + (a[0] * b[1] - b[0] * a[1]) }, 0) / 2
const ccw = (p) => (signedArea(p) < 0 ? [...p].reverse() : p)
const bboxOf = (p) => [Math.min(...p.map((q) => q[0])), Math.min(...p.map((q) => q[1])), Math.max(...p.map((q) => q[0])), Math.max(...p.map((q) => q[1]))]
/** A floor that is the slab of this room (same outline, same level, no holes). */
const floorOf = (els, room) => els.find((f) => f.type === 'floor' && f.level_id === room.level_id && !(f.holes && f.holes.length) && Math.abs(signedArea(f.polygon)) > 0 && Math.abs(Math.abs(signedArea(f.polygon)) - Math.abs(signedArea(room.polygon))) < 0.02 * Math.abs(signedArea(room.polygon)) && bboxOf(f.polygon).every((v, i) => Math.abs(v - bboxOf(room.polygon)[i]) < 0.02 * (1 + Math.abs(v))))
const same = (a, b, e = 1e-3) => Math.abs(a[0] - b[0]) < e && Math.abs(a[1] - b[1]) < e

/** Overlap of two collinear segments, as {t0,t1} along a→b, or null. Only when they run in opposite directions (shared edge of two CCW polygons). */
function sharedInterval(a, b, c, d, tol) {
  const L = Math.hypot(b[0] - a[0], b[1] - a[1]); if (L < EPS) return null
  const ux = (b[0] - a[0]) / L, uy = (b[1] - a[1]) / L
  const dist = (p) => Math.abs((p[0] - a[0]) * uy - (p[1] - a[1]) * ux)
  if (dist(c) > tol || dist(d) > tol) return null
  const tc = (c[0] - a[0]) * ux + (c[1] - a[1]) * uy, td = (d[0] - a[0]) * ux + (d[1] - a[1]) * uy
  if (tc > td - 1e-9 === false && false) return null
  if (td >= tc) return null          // must run opposite to a→b
  const t0 = Math.max(0, td), t1 = Math.min(L, tc)
  return t1 - t0 > 0.05 ? { t0, t1, ux, uy } : null
}

export function sharedEdges(A, B, tol) {
  const out = []
  const pa = ccw(A), pb = ccw(B)
  for (let i = 0; i < pa.length; i++) for (let j = 0; j < pb.length; j++) {
    const a = pa[i], b = pa[(i + 1) % pa.length], c = pb[j], d = pb[(j + 1) % pb.length]
    const s = sharedInterval(a, b, c, d, tol); if (s) out.push({ a, ...s })
  }
  return out
}

/** Union of two polygons that share edges: subdivide at every vertex, cancel opposite pairs, chain what is left. */
export function unionPolygons(A, B) {
  const polys = [ccw(A), ccw(B)]
  const all = polys.flat()
  const edges = []
  for (const p of polys) for (let i = 0; i < p.length; i++) {
    const a = p[i], b = p[(i + 1) % p.length], L = Math.hypot(b[0] - a[0], b[1] - a[1])
    const on = all.filter((q) => !same(q, a) && !same(q, b) && Math.abs((q[0] - a[0]) * (b[1] - a[1]) - (q[1] - a[1]) * (b[0] - a[0])) / (L || 1) < 1e-3 && ((q[0] - a[0]) * (b[0] - a[0]) + (q[1] - a[1]) * (b[1] - a[1])) / (L * L || 1) > 0 && ((q[0] - a[0]) * (b[0] - a[0]) + (q[1] - a[1]) * (b[1] - a[1])) / (L * L || 1) < 1)
      .sort((m, n) => ((m[0] - a[0]) * (b[0] - a[0]) + (m[1] - a[1]) * (b[1] - a[1])) - ((n[0] - a[0]) * (b[0] - a[0]) + (n[1] - a[1]) * (b[1] - a[1])))
    const seq = [a, ...on, b]
    for (let k = 0; k < seq.length - 1; k++) edges.push([seq[k], seq[k + 1]])
  }
  const keep = edges.filter(([a, b], i) => !edges.some(([c, d], j) => j !== i && same(a, d) && same(b, c)))
  if (!keep.length) return null
  const chain = [keep[0][0], keep[0][1]]; const used = new Set([0])
  while (!same(chain[chain.length - 1], chain[0]) && used.size < keep.length) {
    const last = chain[chain.length - 1]
    const ni = keep.findIndex(([a], i) => !used.has(i) && same(a, last)); if (ni < 0) return null
    used.add(ni); chain.push(keep[ni][1])
  }
  if (used.size !== keep.length) return null     // disjoint pieces or branching
  chain.pop()
  // drop collinear vertices
  const res = chain.filter((p, i) => { const a = chain[(i + chain.length - 1) % chain.length], b = chain[(i + 1) % chain.length]; return Math.abs((p[0] - a[0]) * (b[1] - p[1]) - (p[1] - a[1]) * (b[0] - p[0])) > 1e-6 })
  return res.map((p) => [r6(p[0]), r6(p[1])])
}

/** Merge two rooms: shared walls (and everything in them) are removed, the polygons are united. Returns null if they do not touch. */
export function mergeRooms(elements, idA, idB, unit) {
  const A = elements.find((e) => e.id === idA && e.type === 'room'), B = elements.find((e) => e.id === idB && e.type === 'room')
  if (!A || !B || A.level_id !== B.level_id) return null
  const tol = fromM(0.4, unit)
  const sh = sharedEdges(A.polygon, B.polygon, tol)
  if (!sh.length) return null
  const poly = unionPolygons(A.polygon, B.polygon); if (!poly) return null
  const gone = new Set()
  for (const e of elements) {
    if (e.type !== 'wall' || e.level_id !== A.level_id) continue
    const mx = (e.a[0] + e.b[0]) / 2, my = (e.a[1] + e.b[1]) / 2
    for (const s of sh) {
      const t = (mx - s.a[0]) * s.ux + (my - s.a[1]) * s.uy, d = Math.abs((mx - s.a[0]) * s.uy - (my - s.a[1]) * s.ux)
      const along = Math.abs((e.b[0] - e.a[0]) * s.ux + (e.b[1] - e.a[1]) * s.uy)
      if (d <= tol && t >= s.t0 - 1e-3 && t <= s.t1 + 1e-3 && along > 0.9 * Math.hypot(e.b[0] - e.a[0], e.b[1] - e.a[1])) gone.add(e.id)
    }
  }
  const fA = floorOf(elements, A), fB = floorOf(elements, B)
  const out = elements.filter((e) => e.id !== idB && !gone.has(e.id) && !(e.wall_id && gone.has(e.wall_id)) && !(fA && fB && e.id === fB.id)).map((e) => (e.id === idA ? { ...e, polygon: poly, name: A.name } : fA && fB && e.id === fA.id ? { ...e, polygon: poly } : e))
  return { elements: out, removedWalls: gone.size }
}

const clipSide = (poly, axis, pos, keepLow) => {
  const i = axis === 'x' ? 0 : 1, inside = (p) => (keepLow ? p[i] <= pos + 1e-9 : p[i] >= pos - 1e-9), out = []
  for (let k = 0; k < poly.length; k++) {
    const a = poly[k], b = poly[(k + 1) % poly.length], ia = inside(a), ib = inside(b)
    if (ia) out.push(a)
    if (ia !== ib) { const t = (pos - a[i]) / (b[i] - a[i]); out.push(i === 0 ? [pos, r6(a[1] + t * (b[1] - a[1]))] : [r6(a[0] + t * (b[0] - a[0])), pos]) }
  }
  return out
}

/** Split a room along x = pos (axis 'x') or y = pos (axis 'y'): two rooms, a new interior wall with a door, boundary walls split at the cut. */
export function splitRoom(elements, roomId, axis, pos, unit, { thickness = fromM(0.15, unit), door = true, doorWidth = fromM(0.9, unit) } = {}) {
  const R = elements.find((e) => e.id === roomId && e.type === 'room'); if (!R) return null
  const i = axis === 'x' ? 0 : 1, j = 1 - i
  const lo = clipSide(R.polygon, axis, pos, true), hi = clipSide(R.polygon, axis, pos, false)
  const area = (p) => Math.abs(signedArea(p))
  if (lo.length < 3 || hi.length < 3 || area(lo) < 1e-6 || area(hi) < 1e-6) return null
  // extent of the cut line inside the room = intersections of the outline with the line
  const xs = []
  for (let k = 0; k < R.polygon.length; k++) {
    const a = R.polygon[k], b = R.polygon[(k + 1) % R.polygon.length]
    if ((a[i] - pos) * (b[i] - pos) <= 0 && Math.abs(b[i] - a[i]) > 1e-9) xs.push(a[j] + ((pos - a[i]) / (b[i] - a[i])) * (b[j] - a[j]))
  }
  if (xs.length < 2) return null
  const s0 = r6(Math.min(...xs)), s1 = r6(Math.max(...xs))
  const P = (s) => (i === 0 ? [r6(pos), r6(s)] : [r6(s), r6(pos)])
  // split every wall of this level that crosses the line within [s0,s1]
  let els = elements
  for (const w of elements.filter((e) => e.type === 'wall' && e.level_id === R.level_id)) {
    const da = w.a[i] - pos, db = w.b[i] - pos
    if (da * db >= 0 || Math.abs(da) < 1e-6 || Math.abs(db) < 1e-6) continue
    const t = da / (da - db), s = w.a[j] + t * (w.b[j] - w.a[j])
    if (s < s0 - fromM(0.3, unit) || s > s1 + fromM(0.3, unit)) continue
    els = splitWallAt(els, w.id, [t * Math.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1])])
  }
  const L = Math.abs(s1 - s0)
  const wall = makeElement('wall', R.level_id, unit, { a: P(s0), b: P(s1), thickness, name: null })
  const add = [wall]
  if (door && L > doorWidth + fromM(0.8, unit)) add.push(makeElement('door', R.level_id, unit, { wall_id: wall.id, offset: L / 2, width: doorWidth, material: 'mat_wood' }))
  const a = { ...R, polygon: lo }, b = { ...R, id: uid('r'), polygon: hi, name: R.name ? R.name + ' 2' : null }
  const out = []
  const fl = floorOf(els, R)
  for (const e of els) {
    if (e.id === roomId) out.push(a, b)
    else if (fl && e.id === fl.id) out.push({ ...e, polygon: clipSide(e.polygon, axis, pos, true) }, { ...e, id: uid('f'), polygon: clipSide(e.polygon, axis, pos, false) })
    else out.push(e)
  }
  return { elements: [...out, ...add], roomIds: [a.id, b.id] }
}
