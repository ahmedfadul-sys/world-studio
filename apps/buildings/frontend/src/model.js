// Pure editing logic (no React, no DOM) so it can be unit-tested.
// World coordinates are in PROJECT UNITS, Y up (like the backend).

export const UNITS = {
  m: { toM: 1, snap: 0.1, grid: 1 },
  cm: { toM: 0.01, snap: 10, grid: 100 },
  mm: { toM: 0.001, snap: 100, grid: 1000 },
  ft: { toM: 0.3048, snap: 0.25, grid: 1 },
  in: { toM: 0.0254, snap: 4, grid: 12 },
}

const r6 = (v) => Math.round(v * 1e6) / 1e6
export const fromM = (m, unit) => r6(m / UNITS[unit].toM)
export const toM = (v, unit) => v * UNITS[unit].toM

let _n = 0
export const uid = (prefix = 'e') =>
  `${prefix}_${Date.now().toString(36).slice(-4)}${(_n++).toString(36)}${Math.random().toString(36).slice(2, 5)}`

export const dist = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1])
export const sub = (a, b) => [a[0] - b[0], a[1] - b[1]]
export const wallLength = (w) => dist(w.a, w.b)

export function gridStep(project) {
  return project.editor.grid_size || UNITS[project.units.name].grid
}
export function snapStep(project) {
  return project.editor.snap_size || UNITS[project.units.name].snap
}

// ---------------------------------------------------------------- defaults
export function defaults(type, unit) {
  const u = (m) => fromM(m, unit)
  switch (type) {
    case 'wall': return { thickness: u(0.2) }
    case 'door': return { width: u(0.9), height: u(2.1), sill: 0 }
    case 'window': return { width: u(1.2), height: u(1.2), sill: u(0.9) }
    case 'opening': return { width: u(1.0), height: u(2.0), sill: 0, shape: 'rect' }
    case 'column': return { shape: 'box', width: u(0.4), depth: u(0.4) }
    case 'beam': return { width: u(0.25), depth: u(0.4) }
    case 'floor': return { kind: 'floor', thickness: u(0.2), z_offset: 0, holes: [] }
    case 'roof': return { kind: 'gable', pitch_deg: 30, overhang: u(0.3), thickness: u(0.15), ridge_axis: 'x' }
    case 'stair': return { angle_deg: 0, width: u(1.0), steps: 15, rise: u(0.18), run: u(0.28), kind: 'straight', inner_radius: u(0.3), turn_deg: 360, clockwise: false }
    case 'room': return { room_type: 'generic' }
    case 'decor': return { z: 0, size: [u(0.3), u(0.3), u(0.3)], shape: 'box', rotation_deg: 0 }
    case 'road': return { width: u(7), sidewalk: u(1.5), surface: 'asphalt', curb_height: u(0.15), thickness: u(0.1), sidewalk_material: null, z_offset: 0 }
    case 'lamp': return { height: u(5), arm: 0, arm_deg: 0, pole_radius: u(0.06), light: true, color: '#ffd9a0', intensity: 300, range: u(12), z_offset: 0 }
    default: return {}
  }
}

export function makeElement(type, levelId, unit, fields) {
  return { id: uid(type[0]), type, level_id: levelId, name: null, material: null, module: null, overrides: [], props: {}, ...defaults(type, unit), ...fields }
}

// ---------------------------------------------------------------- geometry helpers
export function projectOnSegment(p, a, b) {
  const vx = b[0] - a[0], vy = b[1] - a[1]
  const L2 = vx * vx + vy * vy
  const t = L2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L2))
  const q = [a[0] + t * vx, a[1] + t * vy]
  return { q, t, d: dist(p, q), along: t * Math.sqrt(L2) }
}

export function pointInPolygon(p, poly) {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j]
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

export function polygonArea(poly) {
  let s = 0
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length]
    s += x1 * y2 - x2 * y1
  }
  return Math.abs(s) / 2
}

export function openingRect(op, wall) {
  const len = wallLength(wall)
  const d = [(wall.b[0] - wall.a[0]) / len, (wall.b[1] - wall.a[1]) / len]
  return { c: [wall.a[0] + d[0] * op.offset, wall.a[1] + d[1] * op.offset], dir: d, len: op.width, thick: wall.thickness }
}

export function stairRect(s) {
  const a = (s.angle_deg * Math.PI) / 180
  const d = [Math.cos(a), Math.sin(a)], n = [-Math.sin(a), Math.cos(a)]
  const L = s.steps * s.run, h = s.width / 2
  const p0 = s.start
  const at = (u, v) => [p0[0] + d[0] * u + n[0] * v, p0[1] + d[1] * u + n[1] * v]
  return [at(0, -h), at(L, -h), at(L, h), at(0, h)]
}

// ---------------------------------------------------------------- snapping
/** Snap priority: existing endpoints > points on wall centre-lines (T-junction) > grid > free. */
export function snapPoint(p, { step, enabled = true, endpoints = [], walls = [], tol = 0 }) {
  let best = null
  for (const e of endpoints) {
    const d = dist(p, e)
    if (d <= tol && (!best || d < best.d)) best = { p: e, d }
  }
  if (best) return { p: [...best.p], kind: 'point' }
  let bw = null
  for (const w of walls) {
    const s = projectOnSegment(p, w.a, w.b)
    if (s.d <= tol && (!bw || s.d < bw.d)) bw = { p: s.q, d: s.d }
  }
  if (bw) return { p: bw.p.map(r6), kind: 'wall' }
  if (enabled && step > 0) return { p: [r6(Math.round(p[0] / step) * step), r6(Math.round(p[1] / step) * step)], kind: 'grid' }
  return { p, kind: 'free' }
}

export function orthoPoint(from, p) {
  return Math.abs(p[0] - from[0]) >= Math.abs(p[1] - from[1]) ? [p[0], from[1]] : [from[0], p[1]]
}

export function levelEndpoints(elements, levelId) {
  const pts = []
  for (const e of elements) {
    if (e.level_id !== levelId) continue
    if (e.type === 'wall' || e.type === 'beam') pts.push(e.a, e.b)
    else if (e.type === 'column' || e.type === 'lamp') pts.push(e.pos)
    else if (e.type === 'road') pts.push(...e.path)
    else if (e.type === 'floor' || e.type === 'roof' || e.type === 'room') pts.push(...e.polygon)
  }
  return pts
}

// ---------------------------------------------------------------- openings
export function nearestWall(p, walls, maxDist) {
  let best = null
  for (const w of walls) {
    const s = projectOnSegment(p, w.a, w.b)
    const lim = maxDist + w.thickness / 2
    if (s.d <= lim && (!best || s.d < best.d)) best = { wall: w, ...s }
  }
  return best
}

/** Build an opening element hosted on the wall nearest to p, or {error}. */
export function placeOpening(type, p, elements, levelId, unit, tol, snap = 0) {
  const walls = elements.filter((e) => e.type === 'wall' && e.level_id === levelId)
  const hit = nearestWall(p, walls, tol)
  if (!hit) return { error: 'no_wall' }
  const d = defaults(type, unit)
  const L = wallLength(hit.wall)
  if (d.width > L) return { error: 'wall_too_short' }
  const along = snap > 0 ? Math.round(hit.along / snap) * snap : hit.along
  const offset = r6(Math.max(d.width / 2, Math.min(L - d.width / 2, along)))
  return { element: makeElement(type, levelId, unit, { wall_id: hit.wall.id, offset, material: type === 'opening' ? null : 'mat_wood' }) }
}

// ---------------------------------------------------------------- hit testing
const PRIO = { door: 0, window: 0, opening: 0, lamp: 0, column: 1, decor: 1, stair: 2, beam: 3, wall: 4, road: 5, floor: 6, room: 7, roof: 5 }

export function hitTest(p, elements, levelId, tol) {
  const walls = new Map(elements.filter((e) => e.type === 'wall').map((w) => [w.id, w]))
  let best = null
  const consider = (e, score) => {
    const k = [PRIO[e.type], score]
    if (!best || k[0] < best.k[0] || (k[0] === best.k[0] && k[1] < best.k[1])) best = { id: e.id, k }
  }
  for (const e of elements) {
    if (e.level_id !== levelId) continue
    switch (e.type) {
      case 'wall': { const s = projectOnSegment(p, e.a, e.b); if (s.d <= e.thickness / 2 + tol) consider(e, s.d); break }
      case 'door': case 'window': case 'opening': {
        const w = walls.get(e.wall_id); if (!w) break
        const r = openingRect(e, w)
        const v = sub(p, r.c)
        const u = v[0] * r.dir[0] + v[1] * r.dir[1], n = -v[0] * r.dir[1] + v[1] * r.dir[0]
        if (Math.abs(u) <= r.len / 2 + tol && Math.abs(n) <= r.thick / 2 + tol) consider(e, Math.abs(n)); break
      }
      case 'column': {
        const hw = e.width / 2 + tol, hd = (e.shape === 'round' ? e.width : e.depth) / 2 + tol
        if (Math.abs(p[0] - e.pos[0]) <= hw && Math.abs(p[1] - e.pos[1]) <= hd) consider(e, dist(p, e.pos)); break
      }
      case 'beam': { const s = projectOnSegment(p, e.a, e.b); if (s.d <= e.width / 2 + tol) consider(e, s.d); break }
      case 'floor': case 'roof': case 'room':
        if (pointInPolygon(p, e.polygon)) consider(e, polygonArea(e.polygon)); break
      case 'stair':
        if (e.kind === 'spiral' ? dist(p, e.start) <= e.inner_radius + e.width + tol : pointInPolygon(p, stairRect(e))) consider(e, 0)
        break
      case 'lamp': if (dist(p, e.pos) <= Math.max(e.pole_radius * 2, 0) + tol * 1.2) consider(e, dist(p, e.pos)); break
      case 'road': {
        const reach = e.width / 2 + e.sidewalk + tol * 0.2
        let dmin = Infinity
        for (let i = 0; i + 1 < e.path.length; i++) dmin = Math.min(dmin, projectOnSegment(p, e.path[i], e.path[i + 1]).d)
        if (dmin <= reach) consider(e, dmin)
        break
      }
      case 'decor': if (dist(p, e.pos) <= Math.max(...e.size) / 2 + tol) consider(e, dist(p, e.pos)); break
      default: break
    }
  }
  return best ? best.id : null
}

// ---------------------------------------------------------------- editing
const mv = (pt, dx, dy) => [r6(pt[0] + dx), r6(pt[1] + dy)]

export function moveElements(elements, ids, dx, dy) {
  const set = new Set(ids)
  const walls = new Map(elements.filter((e) => e.type === 'wall').map((w) => [w.id, w]))
  return elements.map((e) => {
    if (!set.has(e.id)) return e
    switch (e.type) {
      case 'wall': case 'beam': return { ...e, a: mv(e.a, dx, dy), b: mv(e.b, dx, dy) }
      case 'column': case 'decor': case 'lamp': return { ...e, pos: mv(e.pos, dx, dy) }
      case 'floor': case 'roof': case 'room':
        return { ...e, polygon: e.polygon.map((p) => mv(p, dx, dy)), ...(e.holes ? { holes: e.holes.map((h) => h.map((p) => mv(p, dx, dy))) } : {}) }
      case 'stair': return { ...e, start: mv(e.start, dx, dy) }
      case 'road': return { ...e, path: e.path.map((q) => mv(q, dx, dy)) }
      case 'door': case 'window': case 'opening': {
        const w = walls.get(e.wall_id)
        if (!w || set.has(w.id)) return e // moves with its host wall
        const L = wallLength(w)
        const d = [(w.b[0] - w.a[0]) / L, (w.b[1] - w.a[1]) / L]
        const off = e.offset + dx * d[0] + dy * d[1]
        return { ...e, offset: r6(Math.max(e.width / 2, Math.min(L - e.width / 2, off))) }
      }
      default: return e
    }
  })
}

export function deleteElements(elements, ids) {
  const gone = new Set(ids)
  for (const e of elements) if (e.type === 'wall' && gone.has(e.id)) for (const o of elements) if (o.wall_id === e.id) gone.add(o.id)
  return elements.filter((e) => !gone.has(e.id))
}

/** Record that the user edited `fields` so module defaults never overwrite them. */
export function patchElement(e, patch) {
  const overrides = new Set(e.overrides || [])
  for (const k of Object.keys(patch)) overrides.add(k)
  return { ...e, ...patch, overrides: [...overrides] }
}

export function bbox(elements, levelId) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  const add = (p) => { x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]) }
  for (const e of elements) {
    if (levelId && e.level_id !== levelId) continue
    if (e.a) { add(e.a); add(e.b) }
    else if (e.pos) add(e.pos)
    else if (e.start) add(e.start)
    else if (e.path) e.path.forEach(add)
    else if (e.polygon) e.polygon.forEach(add)
  }
  return x0 === Infinity ? null : { x0, y0, x1, y1 }
}

// ---------------------------------------------------------------- units
const LEN_FIELDS = {
  wall: ['thickness', 'height'], door: ['offset', 'width', 'height', 'sill'], window: ['offset', 'width', 'height', 'sill'],
  opening: ['offset', 'width', 'height', 'sill'], column: ['width', 'depth', 'height'], beam: ['width', 'depth', 'top'],
  floor: ['thickness', 'z_offset'], roof: ['overhang', 'thickness'], stair: ['width', 'rise', 'run', 'inner_radius'], room: [], decor: ['z'],
  road: ['width', 'sidewalk', 'curb_height', 'thickness', 'z_offset'], lamp: ['height', 'arm', 'pole_radius', 'range', 'z_offset'],
}
const PT_FIELDS = ['a', 'b', 'pos', 'start']

/** Rescale every length so the building keeps its real-world size when the unit changes. */
export function convertUnits(project, newUnit) {
  const k = UNITS[project.units.name].toM / UNITS[newUnit].toM
  const s = (v) => (v == null ? v : r6(v * k))
  const sp = (p) => [s(p[0]), s(p[1])]
  const elements = project.elements.map((e) => {
    const o = { ...e }
    for (const f of LEN_FIELDS[e.type] || []) if (o[f] != null) o[f] = s(o[f])
    for (const f of PT_FIELDS) if (o[f]) o[f] = sp(o[f])
    if (o.polygon) o.polygon = o.polygon.map(sp)
    if (o.holes) o.holes = o.holes.map((h) => h.map(sp))
    if (o.path) o.path = o.path.map(sp)
    if (e.type === 'decor') o.size = e.size.map(s)
    return o
  })
  return {
    ...project,
    units: { name: newUnit },
    levels: project.levels.map((l) => ({ ...l, elevation: s(l.elevation), height: s(l.height) })),
    editor: { ...project.editor, grid_size: s(project.editor.grid_size) ?? null, snap_size: s(project.editor.snap_size) ?? null },
    elements,
    ...(project.guides ? { guides: project.guides.map((g) => ({ ...g, origin: sp(g.origin), b: g.b ? sp(g.b) : g.b, spacing_x: s(g.spacing_x), spacing_y: s(g.spacing_y), length: s(g.length) })) } : {}),
  }
}

export function fmtLen(v, unit) {
  const d = unit === 'mm' ? 0 : unit === 'cm' ? 1 : 2
  return `${(Math.round(v * 10 ** d) / 10 ** d).toString()} ${unit}`
}

// ---------------------------------------------------------------- history (undo / redo)
export const HISTORY_LIMIT = 100

export function histPush(h, present, key, now = Date.now()) {
  const coalesce = key && h.key === key && now - h.at < 900
  const past = coalesce ? h.past : [...h.past, h.present].slice(-HISTORY_LIMIT)
  return { past, present, future: [], key: key || null, at: now }
}
export function histUndo(h) {
  if (!h.past.length) return h
  return { past: h.past.slice(0, -1), present: h.past[h.past.length - 1], future: [h.present, ...h.future], key: null, at: 0 }
}
export function histRedo(h) {
  if (!h.future.length) return h
  return { past: [...h.past, h.present], present: h.future[0], future: h.future.slice(1), key: null, at: 0 }
}
export const histNew = (present) => ({ past: [], present, future: [], key: null, at: 0 })

// ---------------------------------------------------------------- 2D helpers used by the canvas
/** wall id -> [extension at a, at b]: closes outer corners / T-junctions in the plan view like the 3D build does. */
export function wallExtensions(walls, tol = 1e-3) {
  const out = {}
  for (const w of walls) {
    const dw = sub(w.b, w.a), Lw = Math.hypot(dw[0], dw[1]) || 1
    out[w.id] = [w.a, w.b].map((p, end) => {
      let e = 0
      for (const o of walls) {
        if (o === w || projectOnSegment(p, o.a, o.b).d > tol) continue
        const dv = sub(o.b, o.a), Lo = Math.hypot(dv[0], dv[1]) || 1
        if (Math.abs(dw[0] * dv[1] - dw[1] * dv[0]) / (Lw * Lo) < 1e-3) continue
        let x = o.thickness / 2
        // End-to-end corner that turns by <= 90 deg: exact mitre extension (t/2)*tan(turn/2); 90 deg gives t/2.
        const atEnd = dist(p, o.a) <= tol || dist(p, o.b) <= tol
        if (atEnd) {
          const ui = end === 0 ? [dw[0] / Lw, dw[1] / Lw] : [-dw[0] / Lw, -dw[1] / Lw]   // away from p along w
          const uo = dist(p, o.a) <= tol ? [dv[0] / Lo, dv[1] / Lo] : [-dv[0] / Lo, -dv[1] / Lo]
          const cosPhi = ui[0] * uo[0] + ui[1] * uo[1]   // interior angle phi between the walls
          if (cosPhi <= 0.0000001) x = (o.thickness / 2) * Math.tan((Math.PI - Math.acos(Math.max(-1, Math.min(1, cosPhi)))) / 2)
        }
        e = Math.max(e, x)
      }
      return r6(e)
    })
  }
  return out
}

/** Keep every opening hosted on `wallId` inside the wall after the wall was resized. */
export function clampOpenings(elements, wallId) {
  const w = elements.find((e) => e.id === wallId)
  if (!w) return elements
  const L = wallLength(w)
  return elements.map((e) => {
    if (e.wall_id !== wallId) return e
    const off = Math.max(e.width / 2, Math.min(L - e.width / 2, e.offset))
    return off === e.offset || L < e.width ? e : { ...e, offset: r6(off) }
  })
}

/** Move one handle (wall/beam end or polygon vertex); connected wall ends follow, like in CAD. */
export function moveHandle(elements, id, index, np) {
  const target = elements.find((e) => e.id === id)
  if (!target) return {}
  const out = {}
  if (target.type === 'wall' || target.type === 'beam') {
    const key = index === 0 ? 'a' : 'b'
    const old = target[key]
    out[id] = { ...target, [key]: np }
    if (target.type === 'wall') {
      for (const o of elements) {
        if (o.type !== 'wall' || o.id === id || o.level_id !== target.level_id) continue
        if (dist(o.a, old) < 1e-6) out[o.id] = { ...(out[o.id] || o), a: np }
        if (dist(o.b, old) < 1e-6) out[o.id] = { ...(out[o.id] || o), b: np }
      }
    }
  } else if (target.polygon) {
    out[id] = { ...target, polygon: target.polygon.map((p, i) => (i === index ? np : p)) }
  } else if (target.path) {
    out[id] = { ...target, path: target.path.map((p, i) => (i === index ? np : p)) }
  }
  return out
}

export function handlesOf(e) {
  if (!e) return []
  if (e.type === 'wall' || e.type === 'beam') return [e.a, e.b]
  if (e.polygon) return e.polygon
  if (e.path) return e.path
  return []
}

// ---------------------------------------------------------------- modules (defaults are stored in METRES)
export const LENGTH_KEYS = new Set(['thickness', 'height', 'width', 'depth', 'sill', 'overhang', 'rise', 'run', 'top', 'z_offset'])
export const MODULE_KINDS = {
  wall: ['wall', 'corner'], door: ['door_frame'], window: ['window_frame'], column: ['pillar', 'corner'],
  beam: ['beam'], floor: ['floor'], roof: ['roof'], stair: ['stair'],
}
const SAVE_FIELDS = {
  wall: ['thickness', 'material'], door: ['width', 'height', 'sill', 'material'], window: ['width', 'height', 'sill', 'material'],
  column: ['shape', 'width', 'depth', 'material'], beam: ['width', 'depth', 'material'], floor: ['thickness', 'material'],
  roof: ['kind', 'pitch_deg', 'overhang', 'thickness', 'material'], stair: ['rise', 'run', 'width'],
}
export const moduleFits = (elType, mod) => (MODULE_KINDS[elType] || []).includes(mod.kind)
export const defaultKindFor = (elType) => (MODULE_KINDS[elType] || [])[0] || null

/** Assign a module: its defaults are written into the element (except fields the user overrode by hand). */
export function applyModule(e, mod, unit) {
  const overrides = new Set(e.overrides || [])
  const out = { ...e, module: mod.id }
  for (const [k, v] of Object.entries(mod.defaults)) {
    if (overrides.has(k)) continue
    out[k] = LENGTH_KEYS.has(k) ? fromM(v, unit) : v
  }
  return out
}

/** Make a reusable module from an element's current values (lengths saved in metres). */
export function moduleFromElement(e, kind, name, unit) {
  const defaults = {}
  for (const k of SAVE_FIELDS[e.type] || []) if (e[k] != null) defaults[k] = LENGTH_KEYS.has(k) ? r6(toM(e[k], unit)) : e[k]
  return { id: uid('mod'), kind, name, defaults }
}

/** After a module changed, re-apply it to every element using it (unrelated elements untouched). */
export function reapplyModule(project, moduleId, mod) {
  let changed = false
  const elements = project.elements.map((e) => {
    if (e.module !== moduleId) return e
    changed = true
    return applyModule(e, mod, project.units.name)
  })
  return changed ? { ...project, elements } : project
}


// ---------------------------------------------------------------- circles and arcs (drawn as chains of straight walls)
/** Segment count for an arc: chord <= maxChord (default 1.5 m in project units), at least `min`. */
export function arcSegments(radius, sweep, unit, { maxChordM = 1.5, min = 6, max = 96 } = {}) {
  const arcLen = Math.abs(sweep) * toM(radius, unit)
  return Math.max(min, Math.min(max, Math.ceil(arcLen / maxChordM)))
}

/** Points on an arc from angle a0 sweeping `sweep` radians (CCW positive) in n segments (n+1 points). */
export function arcPoints(c, r, a0, sweep, n) {
  const pts = []
  for (let i = 0; i <= n; i++) { const a = a0 + (sweep * i) / n; pts.push([r6(c[0] + r * Math.cos(a)), r6(c[1] + r * Math.sin(a))]) }
  return pts
}

/** Circle through three points: {c, r, a0, sweep} going p1 -> p2 -> p3, or null when collinear. */
export function arcThrough(p1, p2, p3) {
  const d = 2 * (p1[0] * (p2[1] - p3[1]) + p2[0] * (p3[1] - p1[1]) + p3[0] * (p1[1] - p2[1]))
  if (Math.abs(d) < 1e-9) return null
  const s1 = p1[0] ** 2 + p1[1] ** 2, s2 = p2[0] ** 2 + p2[1] ** 2, s3 = p3[0] ** 2 + p3[1] ** 2
  const c = [(s1 * (p2[1] - p3[1]) + s2 * (p3[1] - p1[1]) + s3 * (p1[1] - p2[1])) / d, (s1 * (p3[0] - p2[0]) + s2 * (p1[0] - p3[0]) + s3 * (p2[0] - p1[0])) / d]
  const r = dist(c, p1)
  const ang = (p) => Math.atan2(p[1] - c[1], p[0] - c[0])
  const a1 = ang(p1), a2 = ang(p2), a3 = ang(p3)
  const norm = (x) => ((x % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)
  let sweep = norm(a3 - a1)                       // CCW sweep p1 -> p3
  if (norm(a2 - a1) > sweep) sweep -= 2 * Math.PI  // p2 not on the CCW arc: go clockwise
  return { c, r, a0: a1, sweep }
}

/** Walls approximating a full circle (closed) or an arc; consecutive walls share endpoints exactly. */
export function arcWalls({ c, r, a0 = 0, sweep = 2 * Math.PI }, levelId, unit, fields = {}) {
  const full = Math.abs(Math.abs(sweep) - 2 * Math.PI) < 1e-9
  const n = arcSegments(r, sweep, unit, { min: full ? 12 : 3 })
  const pts = arcPoints(c, r, a0, sweep, n)
  if (full) pts[n] = pts[0]
  const walls = []
  for (let i = 0; i < n; i++) walls.push(makeElement('wall', levelId, unit, { a: pts[i], b: pts[i + 1], material: 'mat_plaster', ...fields }))
  return walls
}

/** Polygon for the floor/roof/room tools' circle and rectangle modes (2 clicks). Circle vertices match arcWalls. */
export function shapePolygon(shape, p0, p1, tool, unit) {
  if (shape === 'rect') {
    if (Math.abs(p1[0] - p0[0]) < 1e-6 || Math.abs(p1[1] - p0[1]) < 1e-6) return null
    return [[p0[0], p0[1]], [p1[0], p0[1]], [p1[0], p1[1]], [p0[0], p1[1]]]
  }
  const r = dist(p0, p1)
  if (r < 1e-6) return null
  let n = arcSegments(r, 2 * Math.PI, unit, { min: 12 })
  if (tool === 'roof') n = Math.max(n, 32)            // smoother cone/dome than the wall ring
  return arcPoints(p0, r, 0, 2 * Math.PI, n).slice(0, n)
}

// ---------------------------------------------------------------- wall face (elevation) shapes
export const FACE_SHAPES = ['rect', 'circle', 'arch', 'triangle', 'star']

const bb = (poly) => {
  const xs = poly.map((p) => p[0]), ys = poly.map((p) => p[1])
  return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) }
}
export const polyBBox = bb

/** Polygon (wall-local u,v) for a 2-point drag/click. rect/arch/triangle use the box, circle/star centre + radius. */
export function faceShapePolygon(shape, p0, p1) {
  const x0 = Math.min(p0[0], p1[0]), x1 = Math.max(p0[0], p1[0]), y0 = Math.min(p0[1], p1[1]), y1 = Math.max(p0[1], p1[1])
  const w = x1 - x0, h = y1 - y0
  if (shape === 'circle' || shape === 'star') {
    const r = dist(p0, p1)
    if (r < 1e-6) return null
    if (shape === 'circle') return arcPoints(p0, r, 0, 2 * Math.PI, 32).slice(0, 32)
    const out = []
    for (let i = 0; i < 10; i++) {
      const a = Math.PI / 2 + (i * Math.PI) / 5, rr = i % 2 ? r * 0.4 : r
      out.push([r6(p0[0] + rr * Math.cos(a)), r6(p0[1] + rr * Math.sin(a))])
    }
    return out
  }
  if (w < 1e-6 || h < 1e-6) return null
  if (shape === 'triangle') return [[x0, y0], [x1, y0], [r6((x0 + x1) / 2), y1]]
  if (shape === 'arch') {
    const r = w / 2
    if (h <= r) return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    const top = y1 - r, pts = [[x0, y0], [x1, y0], [x1, top]]
    for (let i = 1; i < 12; i++) { const a = (i * Math.PI) / 12; pts.push([r6(x0 + r + r * Math.cos(a)), r6(top + r * Math.sin(a))]) }
    pts.push([x0, top])
    return pts
  }
  return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
}

export const translatePoly = (poly, du, dv) => poly.map(([u, v]) => [r6(u + du), r6(v + dv)])

/** Scale a polygon from bounding box `from` to bounding box `to` (resize handles). */
export function fitPolyToBBox(poly, from, to) {
  const sw = from.x1 - from.x0 || 1, sh = from.y1 - from.y0 || 1
  return poly.map(([u, v]) => [r6(to.x0 + ((u - from.x0) / sw) * (to.x1 - to.x0)), r6(to.y0 + ((v - from.y0) / sh) * (to.y1 - to.y0))])
}

export function makeFeature(kind, shape, polygon, depth, face = 'right') {
  return { id: uid('f'), kind, shape, polygon, depth, face }
}

/** Crenellations: cut notches along the top edge. All lengths in project units. */
export function battlementFeatures(len, height, unit, { notch = fromM(0.5, unit), merlon = fromM(0.5, unit), depth = fromM(0.5, unit) } = {}) {
  const pitch = notch + merlon
  const n = Math.max(1, Math.floor((len - merlon) / pitch))
  const used = n * pitch + merlon
  const start = (len - used) / 2 + merlon
  const out = []
  for (let i = 0; i < n; i++) {
    const u0 = r6(start + i * pitch)
    out.push(makeFeature('cut', 'rect', [[u0, r6(height - depth)], [r6(u0 + notch), r6(height - depth)], [r6(u0 + notch), r6(height + depth)], [u0, r6(height + depth)]], fromM(0.05, unit)))
  }
  return out
}

/** A picture-frame moulding: four thin relief bars around the box. */
export function frameFeatures(box, bar, relief) {
  const { x0, y0, x1, y1 } = box
  const R = (a, b, c, d) => makeFeature('relief', 'rect', [[r6(a), r6(b)], [r6(c), r6(b)], [r6(c), r6(d)], [r6(a), r6(d)]], relief)
  return [R(x0, y0, x1, y0 + bar), R(x0, y1 - bar, x1, y1), R(x0, y0 + bar, x0 + bar, y1 - bar), R(x1 - bar, y0 + bar, x1, y1 - bar)]
}

/** Copy the given spec fields of `source` onto every other element of the same type (positions are never touched).
 *  scope: 'all' = whole building, 'level' = only the source's level. Returns {elements, count}. */
export const POSITIONAL = new Set(['offset', 'a', 'b', 'pos', 'polygon', 'wall_id', 'id', 'level_id', 'type', 'features', 'holes', 'start', 'angle_deg', 'rotation_deg'])
export function applySpecsToAll(elements, source, keys, scope = 'all') {
  const ks = keys.filter((k) => !POSITIONAL.has(k))
  let count = 0
  const out = elements.map((e) => {
    if (e.id === source.id || e.type !== source.type) return e
    if (scope === 'level' && e.level_id !== source.level_id) return e
    count++
    const patch = {}
    for (const k of ks) patch[k] = source[k] === undefined ? null : source[k]
    return patchElement(e, patch)
  })
  return { elements: out, count }
}
