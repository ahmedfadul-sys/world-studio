// Plan-editing helpers (pure, no React): room presets, linked corner editing, copy / arrays, stairs, typed dimensions.
import { dist, fromM, handlesOf, makeElement, uid, wallLength } from './model.js'

const r6 = (v) => Math.round(v * 1e6) / 1e6
const same = (a, b, tol = 1e-4) => Math.abs(a[0] - b[0]) < tol && Math.abs(a[1] - b[1]) < tol

// ---------------------------------------------------------------- room presets (sizes in metres)
export const ROOM_TYPES = [
  { id: 'living', w: 5, d: 4 }, { id: 'hall', w: 8, d: 6 }, { id: 'majlis', w: 6, d: 4 },
  { id: 'bedroom', w: 4, d: 3.5 }, { id: 'master', w: 5, d: 4 }, { id: 'kitchen', w: 3.5, d: 3 },
  { id: 'dining', w: 4.5, d: 3.5 }, { id: 'bathroom', w: 2.5, d: 2 }, { id: 'corridor', w: 6, d: 1.5 },
  { id: 'entrance', w: 3, d: 2.5 }, { id: 'office', w: 3.5, d: 3 }, { id: 'storage', w: 2.5, d: 2 },
  { id: 'garage', w: 6, d: 3.5 }, { id: 'custom', w: 4, d: 4 },
]

export function rectCorners(x, y, w, d) { return [[x, y], [r6(x + w), y], [r6(x + w), r6(y + d)], [x, r6(y + d)]] }

const hasWall = (elements, levelId, a, b) => elements.find((e) => e.type === 'wall' && e.level_id === levelId && ((same(e.a, a) && same(e.b, b)) || (same(e.a, b) && same(e.b, a))))

/**
 * Elements of a rectangular room whose lower-left corner is (x, y). Walls that already exist (shared with a
 * neighbouring room) are not duplicated. spec: {type,name,w,d,x,y,walls,floor,ceiling,door}, sizes in project units.
 */
export function roomElements(spec, levelId, unit, existing = []) {
  const { x, y, w, d } = spec
  const pts = rectCorners(x, y, w, d)
  const out = []
  const newWalls = []
  if (spec.walls !== false) {
    for (let i = 0; i < 4; i++) {
      const a = pts[i], b = pts[(i + 1) % 4]
      if (hasWall(existing, levelId, a, b)) continue
      const wl = makeElement('wall', levelId, unit, { a, b, material: 'mat_plaster' })
      out.push(wl); newWalls.push(wl)
    }
  }
  if (spec.floor !== false) out.push(makeElement('floor', levelId, unit, { polygon: pts.map((p) => [...p]), material: 'mat_concrete', name: null }))
  if (spec.ceiling) out.push(makeElement('floor', levelId, unit, { kind: 'ceiling', polygon: pts.map((p) => [...p]), material: 'mat_concrete' }))
  if (spec.door && newWalls.length) {
    const host = newWalls[0]
    const L = wallLength(host)
    const dd = makeElement('door', levelId, unit, { wall_id: host.id, offset: r6(L / 2), material: 'mat_wood' })
    if (dd.width < L) out.push(dd)
  }
  out.push(makeElement('room', levelId, unit, { polygon: pts, name: spec.name || null, room_type: spec.type || 'generic' }))
  return out
}

/** Axis-aligned rectangle info for a polygon, or null when it is not a rectangle. */
export function rectInfo(poly, tol = 1e-4) {
  if (!poly || poly.length !== 4) return null
  const xs = poly.map((p) => p[0]), ys = poly.map((p) => p[1])
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys)
  const ok = poly.every((p) => (Math.abs(p[0] - x0) < tol || Math.abs(p[0] - x1) < tol) && (Math.abs(p[1] - y0) < tol || Math.abs(p[1] - y1) < tol))
  const corners = new Set(poly.map((p) => `${Math.abs(p[0] - x0) < tol ? 0 : 1}${Math.abs(p[1] - y0) < tol ? 0 : 1}`))
  return ok && corners.size === 4 ? { x0, y0, x1, y1, w: x1 - x0, d: y1 - y0 } : null
}

// ---------------------------------------------------------------- linked editing
/**
 * Move points: every wall end, beam end and polygon vertex of the level that sits on an `old` point goes to its
 * `new` point. Openings on walls whose length changes keep their relative position. Returns {id: element} for the
 * elements that changed (usable as live drag overrides).
 */
export function remapPoints(elements, levelId, pairs) {
  const find = (p) => { for (const [o, n] of pairs) if (same(p, o)) return n; return null }
  const out = {}
  const mapPoly = (poly) => { let ch = false; const np = poly.map((p) => { const n = find(p); if (n) { ch = true; return [...n] } return p }); return ch ? np : null }
  for (const e of elements) {
    if (e.level_id !== levelId) continue
    if (e.type === 'wall' || e.type === 'beam') {
      const na = find(e.a), nb = find(e.b)
      if (na || nb) out[e.id] = { ...e, a: na ? [...na] : e.a, b: nb ? [...nb] : e.b }
    } else if (e.polygon) {
      const np = mapPoly(e.polygon)
      if (np) out[e.id] = { ...e, polygon: np }
    }
  }
  for (const e of elements) {
    if (!e.wall_id || !out[e.wall_id]) continue
    const w0 = elements.find((x) => x.id === e.wall_id), w1 = out[e.wall_id]
    const L0 = wallLength(w0), L1 = wallLength(w1)
    if (L0 < 1e-9 || Math.abs(L1 - L0) < 1e-9) continue
    const off = Math.max(e.width / 2, Math.min(L1 - e.width / 2, (e.offset / L0) * L1))
    if (L1 >= e.width) out[e.id] = { ...e, offset: r6(off) }
  }
  return out
}

export const applyOverrides = (elements, o) => elements.map((e) => o[e.id] || e)

/** Drag vertex `index` of a wall / beam / polygon to `np`, dragging everything attached to that corner with it. */
export function linkedMove(elements, id, index, np) {
  const t = elements.find((e) => e.id === id)
  if (!t) return {}
  const old = handlesOf(t)[index]
  if (!old) return {}
  return remapPoints(elements, t.level_id, [[old, np]])
}

/** Midpoints (one per edge) of a polygon, used as "move this side" handles. */
export const edgeMidpoints = (poly) => poly.map((p, i) => { const q = poly[(i + 1) % poly.length]; return [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2] })

/** Move side `i` of a polygon parallel to itself so that it passes through `raw`; returns remap pairs. */
export function edgeMovePairs(poly, i, raw, step = 0) {
  const a = poly[i], b = poly[(i + 1) % poly.length]
  const L = dist(a, b) || 1
  const n = [-(b[1] - a[1]) / L, (b[0] - a[0]) / L]
  let t = (raw[0] - a[0]) * n[0] + (raw[1] - a[1]) * n[1]
  if (step > 0) t = Math.round(t / step) * step
  const sh = (p) => [r6(p[0] + n[0] * t), r6(p[1] + n[1] * t)]
  return [[a, sh(a)], [b, sh(b)]]
}

/** Give a rectangular room a new width / depth (lower-left corner stays), dragging its walls and floor along. */
export function resizeRect(elements, roomId, w, d) {
  const room = elements.find((e) => e.id === roomId)
  const ri = room && rectInfo(room.polygon)
  if (!ri || !(w > 0) || !(d > 0)) return {}
  const pairs = room.polygon.map((p) => [p, [r6(Math.abs(p[0] - ri.x0) < 1e-4 ? ri.x0 : ri.x0 + w), r6(Math.abs(p[1] - ri.y0) < 1e-4 ? ri.y0 : ri.y0 + d)]])
  return remapPoints(elements, room.level_id, pairs)
}

/** Missing parts of a room that was only drawn as an outline: walls / floor / ceiling on its edges. */
export function buildRoomParts(elements, roomId, unit, { walls = true, floor = true, ceiling = false } = {}) {
  const room = elements.find((e) => e.id === roomId)
  if (!room?.polygon) return []
  const out = []
  const poly = room.polygon
  if (walls) {
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i], b = poly[(i + 1) % poly.length]
      if (!hasWall(elements, room.level_id, a, b)) out.push(makeElement('wall', room.level_id, unit, { a: [...a], b: [...b], material: 'mat_plaster' }))
    }
  }
  const hasFloor = (kind) => elements.some((e) => e.type === 'floor' && e.level_id === room.level_id && e.kind === kind && e.polygon.length === poly.length && e.polygon.every((p, i) => same(p, poly[i])))
  if (floor && !hasFloor('floor')) out.push(makeElement('floor', room.level_id, unit, { polygon: poly.map((p) => [...p]), material: 'mat_concrete' }))
  if (ceiling && !hasFloor('ceiling')) out.push(makeElement('floor', room.level_id, unit, { kind: 'ceiling', polygon: poly.map((p) => [...p]), material: 'mat_concrete' }))
  return out
}

// ---------------------------------------------------------------- copy / paste / arrays
const rot = (p, c, a) => { const co = Math.cos(a), si = Math.sin(a); const x = p[0] - c[0], y = p[1] - c[1]; return [c[0] + x * co - y * si, c[1] + x * si + y * co] }

/** Clone `ids` (plus the doors/windows hosted by cloned walls) with new ids, optionally moved / rotated / sent to another level. */
export function cloneElements(elements, ids, { dx = 0, dy = 0, rotDeg = 0, center = [0, 0], levelId = null } = {}) {
  const sel = new Set(ids)
  const picked = elements.filter((e) => sel.has(e.id) || (e.wall_id && sel.has(e.wall_id)))
  const map = new Map(picked.map((e) => [e.id, uid(e.type[0])]))
  const a = (rotDeg * Math.PI) / 180
  const tp = (p) => { const q = rotDeg ? rot(p, center, a) : p; return [r6(q[0] + dx), r6(q[1] + dy)] }
  const out = []
  for (const e of picked) {
    const c = { ...e, id: map.get(e.id), overrides: [...(e.overrides || [])], props: { ...(e.props || {}) } }
    if (levelId) c.level_id = levelId
    if (e.wall_id) { if (!map.has(e.wall_id)) continue; c.wall_id = map.get(e.wall_id) }
    if (e.a) { c.a = tp(e.a); c.b = tp(e.b) }
    if (e.pos) c.pos = tp(e.pos)
    if (e.start) c.start = tp(e.start)
    if (e.polygon) c.polygon = e.polygon.map(tp)
    if (e.path) c.path = e.path.map(tp)
    if (e.holes) c.holes = e.holes.map((h) => h.map(tp))
    if (e.type === 'stair') c.angle_deg = r6(e.angle_deg + rotDeg)
    if (e.type === 'lamp') c.arm_deg = r6((e.arm_deg || 0) + rotDeg)
    if (e.type === 'decor') c.rotation_deg = r6((e.rotation_deg || 0) + rotDeg)
    out.push(c)
  }
  return out
}

/** `count` extra copies, each shifted by (dx, dy) more than the previous. */
export function arrayLinear(elements, ids, { count, dx, dy, levelId = null }) {
  const out = []
  for (let k = 1; k <= count; k++) out.push(...cloneElements(elements, ids, { dx: dx * k, dy: dy * k, levelId }))
  return out
}

/** `count` copies in total (the original counts) spread over `totalDeg` around `center`. */
export function arrayPolar(elements, ids, { count, center, totalDeg = 360, rotateCopies = true }) {
  const step = totalDeg >= 360 ? totalDeg / count : totalDeg / Math.max(1, count - 1)
  const out = []
  for (let k = 1; k < count; k++) {
    const deg = step * k
    if (rotateCopies) { out.push(...cloneElements(elements, ids, { rotDeg: deg, center })); continue }
    // keep the copies' orientation: they only travel around the centre
    const c0 = centroid(elements, ids)
    const c1 = rot(c0, center, (deg * Math.PI) / 180)
    out.push(...cloneElements(elements, ids, { dx: c1[0] - c0[0], dy: c1[1] - c0[1] }))
  }
  return out
}

export function centroid(elements, ids) {
  const sel = new Set(ids)
  const pts = []
  for (const e of elements) {
    if (!sel.has(e.id)) continue
    if (e.a) pts.push(e.a, e.b)
    else if (e.pos) pts.push(e.pos)
    else if (e.start) pts.push(e.start)
    else if (e.path) pts.push(...e.path)
    else if (e.polygon) pts.push(...e.polygon)
  }
  if (!pts.length) return [0, 0]
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1])
  return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2]
}

// ---------------------------------------------------------------- stairs
/** Number of steps and riser height that exactly reach `height` with a riser close to `rise`. */
export function fitStairSteps(height, rise) {
  const steps = Math.max(1, Math.min(200, Math.round(height / rise)))
  return { steps, rise: r6(height / steps) }
}

/**
 * L- or U-shaped stair made of two straight flights and a landing (a floor slab). `start` is the foot of the first
 * flight, `angleDeg` its direction. Everything is in project units.
 */
export function stairFlights(kind, { start, angleDeg, width, height, rise, run, gap = 0.1 }, levelId, unit) {
  const { steps, rise: rr } = fitStairSteps(height, rise)
  const n1 = Math.max(1, Math.floor(steps / 2)), n2 = Math.max(1, steps - n1)
  const a = (angleDeg * Math.PI) / 180
  const u = [Math.cos(a), Math.sin(a)], v = [-Math.sin(a), Math.cos(a)]
  const at = (s, l) => [r6(start[0] + u[0] * s + v[0] * l), r6(start[1] + u[1] * s + v[1] * l)]
  const L1 = n1 * run, hw = width / 2
  const latMax = kind === 'U' ? hw + width + gap : hw
  const landing = [at(L1, -hw), at(L1 + width, -hw), at(L1 + width, latMax), at(L1, latMax)]
  const zl = r6(n1 * rr)
  const f1 = makeElement('stair', levelId, unit, { start: [...start], angle_deg: angleDeg, width, steps: n1, rise: rr, run, material: 'mat_concrete' })
  const f2 = kind === 'U'
    ? makeElement('stair', levelId, unit, { start: at(L1, width + gap), angle_deg: r6(angleDeg + 180), width, steps: n2, rise: rr, run, z_offset: zl, material: 'mat_concrete' })
    : makeElement('stair', levelId, unit, { start: at(L1 + width / 2, hw), angle_deg: r6(angleDeg + 90), width, steps: n2, rise: rr, run, z_offset: zl, material: 'mat_concrete' })
  const slab = makeElement('floor', levelId, unit, { polygon: landing, z_offset: zl, material: 'mat_concrete', thickness: fromM(0.15, unit) })
  return [f1, f2, slab]
}

// ---------------------------------------------------------------- typed dimensions
const AR_DIGITS = '٠١٢٣٤٥٦٧٨٩'
const norm = (s) => String(s).replace(/[٠-٩]/g, (c) => AR_DIGITS.indexOf(c)).replace(/[٫،]/g, '.').trim()

/**
 * "4.5" → {kind:'len', len:4.5, ang:null};  "4.5<30", "4.5,30" or "4.5 30" → length 4.5 at 30°;  "4x3" → {kind:'wh'}.
 * Returns null while the text is not (yet) a valid number.
 */
export function parseDimInput(text) {
  const s = norm(text).toLowerCase()
  if (!s) return null
  let m = s.match(/^(\d*\.?\d+)\s*[x*×]\s*(\d*\.?\d+)$/)
  if (m) return { kind: 'wh', w: parseFloat(m[1]), h: parseFloat(m[2]) }
  m = s.match(/^(\d*\.?\d+)(?:\s*[<,;\s]\s*(-?\d*\.?\d+))?$/)
  if (m) return { kind: 'len', len: parseFloat(m[1]), ang: m[2] === undefined ? null : parseFloat(m[2]) }
  return null
}

/** Point `len` away from `from`, at `ang` degrees (CCW from +x) or, without an angle, towards `toward`. */
export function pointByDim(from, len, ang, toward = null) {
  let a
  if (ang !== null && ang !== undefined) a = (ang * Math.PI) / 180
  else if (toward && dist(from, toward) > 1e-9) a = Math.atan2(toward[1] - from[1], toward[0] - from[0])
  else a = 0
  return [r6(from[0] + len * Math.cos(a)), r6(from[1] + len * Math.sin(a))]
}

/** Lower-left corner of a w×d room when the cursor point `p` is its `anchor` corner (sw|se|nw|ne). */
export function anchorOrigin(anchor, p, w, d) {
  const x = anchor === 'se' || anchor === 'ne' ? p[0] - w : p[0]
  const y = anchor === 'nw' || anchor === 'ne' ? p[1] - d : p[1]
  return [r6(x), r6(y)]
}

/** First free "<label> n" name for a new room of `label` on the level. */
export function nextRoomName(elements, levelId, label) {
  const used = new Set(elements.filter((e) => e.type === 'room' && e.level_id === levelId).map((e) => e.name))
  for (let n = 1; n < 1000; n++) { const nm = `${label} ${n}`; if (!used.has(nm)) return nm }
  return label
}

// ---------------------------------------------------------------- underlays (scanned plans)
/** Height in world units of an underlay (follows the pixel aspect ratio). */
export const underlayHeight = (u) => (u.width * u.px_h) / u.px_w

/** World coordinates of the image's four corners: top-left, top-right, bottom-right, bottom-left. */
export function underlayCorners(u) {
  const a = (u.rotation_deg * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a), H = underlayHeight(u)
  const at = (w, h) => [r6(u.x + w * c + h * s), r6(u.y + w * s - h * c)]
  return [at(0, 0), at(u.width, 0), at(u.width, H), at(0, H)]
}

/**
 * Calibrate: the user clicked p1 and p2 on the image and says they are `real` apart.
 * The image is scaled about p1; with align 'h' / 'v' it is also rotated about p1 so the picked line becomes
 * horizontal / vertical (straightens a crooked scan).
 */
export function calibrateUnderlay(u, p1, p2, real, align = null) {
  const m = dist(p1, p2)
  if (!(m > 1e-9) || !(real > 0)) return u
  const f = real / m
  let ox = p1[0] + (u.x - p1[0]) * f, oy = p1[1] + (u.y - p1[1]) * f
  let rot = u.rotation_deg
  if (align) {
    const ang = Math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    const delta = align === 'h' ? -ang : Math.PI / 2 - ang
    const co = Math.cos(delta), si = Math.sin(delta)
    const dx = ox - p1[0], dy = oy - p1[1]
    ox = p1[0] + dx * co - dy * si; oy = p1[1] + dx * si + dy * co
    rot += (delta * 180) / Math.PI
  }
  return { ...u, x: r6(ox), y: r6(oy), width: r6(u.width * f), rotation_deg: r6(rot) }
}

/** Where a new underlay of aspect px_w:px_h and world width `width` goes so its centre sits on `centre`. */
export function centredUnderlay(centre, width, px_w, px_h) {
  const h = (width * px_h) / px_w
  return { x: r6(centre[0] - width / 2), y: r6(centre[1] + h / 2) }
}

// ---------------------------------------------------------------- length balancing
/** Walls of a level that have an end at `pt`. */
export const attachedWalls = (elements, levelId, pt) => elements.filter((e) => e.type === 'wall' && e.level_id === levelId && (same(e.a, pt) || same(e.b, pt)))

/**
 * Magnet for the "200 | 200" case: when exactly two walls meet at the dragged point, pull it onto the perpendicular
 * bisector of their far ends (both walls equally long) once it is within `tol`. Returns {p, balanced, lengths:[l1,l2]}.
 */
export function balanceSnap(elements, levelId, oldPt, p, tol) {
  const ws = attachedWalls(elements, levelId, oldPt)
  if (ws.length !== 2) return { p, balanced: false, lengths: null }
  const far = ws.map((w) => (same(w.a, oldPt) ? w.b : w.a))
  const [f1, f2] = far
  const mx = (f1[0] + f2[0]) / 2, my = (f1[1] + f2[1]) / 2
  const dx = f2[0] - f1[0], dy = f2[1] - f1[1], len = Math.hypot(dx, dy)
  if (len < 1e-9) return { p, balanced: false, lengths: null }
  const dist = ((p[0] - mx) * dx + (p[1] - my) * dy) / len          // signed distance from the bisector
  const lens = (q) => far.map((f) => Math.hypot(q[0] - f[0], q[1] - f[1]))
  if (Math.abs(dist) <= tol) {
    const q = [r6(p[0] - (dx / len) * dist), r6(p[1] - (dy / len) * dist)]
    return { p: q, balanced: true, lengths: lens(q) }
  }
  return { p, balanced: false, lengths: lens(p) }
}

/** Split a wall at the given distances from its start (project units, ascending). Openings go to the piece holding their centre. */
export function splitWallAt(elements, wallId, offsets) {
  const w = elements.find((e) => e.id === wallId && e.type === 'wall')
  if (!w) return elements
  const L = wallLength(w), ux = (w.b[0] - w.a[0]) / L, uy = (w.b[1] - w.a[1]) / L
  const cuts = [...new Set(offsets.map((o) => Math.round(o * 1e6) / 1e6).filter((o) => o > 1e-6 && o < L - 1e-6))].sort((p, q) => p - q)
  if (!cuts.length) return elements
  const bounds = [0, ...cuts, L]
  const at = (s) => [r6(w.a[0] + ux * s), r6(w.a[1] + uy * s)]
  const pieces = bounds.slice(0, -1).map((s0, i) => (i === 0 ? { ...w, a: [...w.a], b: at(bounds[1]) } : { ...w, id: uid('w'), a: at(s0), b: i === bounds.length - 2 ? [...w.b] : at(bounds[i + 1]) }))
  const out = []
  for (const e of elements) {
    if (e.id === wallId) { out.push(...pieces); continue }
    if (e.wall_id === wallId) {
      let i = bounds.findIndex((_, k) => k < bounds.length - 1 && e.offset >= bounds[k] && e.offset < bounds[k + 1])
      if (i < 0) i = pieces.length - 1
      const seg = bounds[i + 1] - bounds[i]
      const local = Math.max(e.width / 2, Math.min(seg - e.width / 2, e.offset - bounds[i]))
      out.push({ ...e, wall_id: pieces[i].id, offset: r6(Math.max(0, local)) })
    } else out.push(e)
  }
  return out
}

/** Split a wall into `n` equal walls (linked at the new points). */
export function divideWall(elements, wallId, n) {
  const w = elements.find((e) => e.id === wallId && e.type === 'wall')
  n = Math.round(n)
  if (!w || n < 2 || n > 50) return elements
  const L = wallLength(w)
  return splitWallAt(elements, wallId, Array.from({ length: n - 1 }, (_, i) => (L * (i + 1)) / n))
}

/** Order selected walls into one open chain (shared end points). Returns {walls: ordered, points: [p0..pn]} or null. */
export function wallChain(elements, ids) {
  const ws = ids.map((id) => elements.find((e) => e.id === id)).filter((e) => e && e.type === 'wall')
  if (ws.length < 1 || ws.length !== ids.length) return null
  const lvl = ws[0].level_id
  if (ws.some((w) => w.level_id !== lvl)) return null
  const ends = (w) => [w.a, w.b]
  const count = (p) => ws.filter((w) => ends(w).some((q) => same(q, p))).length
  const startW = ws.find((w) => ends(w).some((q) => count(q) === 1))
  if (!startW) return null                       // closed loop (or branching): nothing to balance
  const pts = [ends(startW).find((q) => count(q) === 1)], ordered = [startW]
  let cur = ends(startW).find((q) => !same(q, pts[0]))
  pts.push(cur)
  const left = new Set(ws.filter((w) => w !== startW))
  while (left.size) {
    const nx = [...left].find((w) => ends(w).some((q) => same(q, cur)))
    if (!nx) return null
    left.delete(nx)
    ordered.push(nx)
    cur = same(nx.a, cur) ? nx.b : nx.a
    pts.push(cur)
  }
  if (pts.slice(1, -1).some((p) => count(p) !== 2)) return null
  return { walls: ordered, points: pts, total: ordered.reduce((s, w) => s + wallLength(w), 0) }
}

/** Equalise the lengths of a chain: inner points are re-placed at equal arc-length steps along the chain. Returns overrides {id: element}. */
export function balanceChain(elements, ids) {
  const ch = wallChain(elements, ids)
  if (!ch || ch.walls.length < 2) return {}
  const n = ch.walls.length, pts = ch.points
  const cum = [0]
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
  const total = cum[cum.length - 1]
  const at = (s) => {
    let i = 1
    while (i < cum.length - 1 && cum[i] < s) i++
    const t = (s - cum[i - 1]) / ((cum[i] - cum[i - 1]) || 1)
    return [r6(pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * t), r6(pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * t)]
  }
  const pairs = []
  for (let k = 1; k < n; k++) { const np = at((total * k) / n); if (!same(np, pts[k])) pairs.push([pts[k], np]) }
  return pairs.length ? remapPoints(elements, ch.walls[0].level_id, pairs) : {}
}

/** Set the length of a wall by moving its END (b) along the wall direction, dragging everything attached to that end. */
export function setWallLength(elements, wallId, length) {
  const w = elements.find((e) => e.id === wallId && e.type === 'wall')
  if (!w || !(length > 0)) return {}
  const L = wallLength(w)
  if (L < 1e-9) return {}
  const nb = [r6(w.a[0] + ((w.b[0] - w.a[0]) / L) * length), r6(w.a[1] + ((w.b[1] - w.a[1]) / L) * length)]
  return remapPoints(elements, w.level_id, [[w.b, nb]])
}
