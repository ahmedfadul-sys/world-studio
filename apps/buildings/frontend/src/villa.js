// Villa / palace generator: total built area (m²) → multi-level rectilinear plan (rooms, walls, doors, windows, stairs, roof).
// Geometry is computed on an integer centimetre grid (exact shared walls), then converted to project units.
import { fromM, makeElement, uid } from './model.js'
import { fitStairSteps } from './plan.js'

const CM = 100
const snap = (v, q = 10) => Math.round(v / q) * q          // cm, 10 cm module

// program weights (relative width inside a row) and minimum widths (cm)
const WEIGHT = { majlis: 1.4, living: 1.3, dining: 1.0, office: 0.8, kitchen: 1.0, storage: 0.6, bathroom: 0.5, bedroom: 1.0, master: 1.5, garage: 1.6, hall: 1.2 }
const MIN_W = { bathroom: 240, storage: 240, kitchen: 320, bedroom: 360, master: 440, majlis: 450, living: 400, dining: 380, office: 320, garage: 300, hall: 400 }
const FRONT_SIDES = { ground: ['majlis', 'living', 'dining', 'office', 'majlis', 'living', 'dining', 'office'], upper: ['master', 'bedroom', 'bedroom', 'office', 'bedroom', 'master', 'bedroom', 'bedroom'] }
const BACK = { ground: ['kitchen', 'storage', 'bathroom', 'bedroom', 'living', 'bedroom', 'bathroom', 'storage', 'dining', 'bathroom'], upper: ['bedroom', 'bathroom', 'living', 'bathroom', 'bedroom', 'master', 'bathroom', 'bedroom', 'living', 'bathroom'] }

/** Split `total` (cm) by weights with minimum widths; returns integer cm widths summing to `total`. */
export function splitWidths(total, items) {
  const w = items.map((it) => it.weight)
  const min = items.map((it) => it.min)
  const fixed = new Array(items.length).fill(false)
  let out = new Array(items.length).fill(0)
  for (let iter = 0; iter < items.length + 1; iter++) {
    const free = items.map((_, i) => i).filter((i) => !fixed[i])
    const used = items.reduce((s, _, i) => s + (fixed[i] ? out[i] : 0), 0)
    const sw = free.reduce((s, i) => s + w[i], 0) || 1
    let again = false
    for (const i of free) { out[i] = ((total - used) * w[i]) / sw; if (out[i] < min[i]) { out[i] = min[i]; fixed[i] = true; again = true } }
    if (!again) break
  }
  // cumulative rounding to the 10 cm module so edges are exact and the last item absorbs the remainder
  const res = []
  let acc = 0, prev = 0
  for (let i = 0; i < out.length; i++) { acc += out[i]; const e = i === out.length - 1 ? total : snap(acc); res.push(e - prev); prev = e }
  return res
}

/** Footprint W×D (m) for `area` m² over `floors` levels. */
export function footprint(area, floors, aspect = 1.5) {
  const F = area / floors
  const D = Math.max(6, Math.round(Math.sqrt(F / aspect) * 2) / 2)
  const W = Math.round((F / D) * 100) / 100
  return { W, D, F, total: Math.round(W * D * floors * 100) / 100 }
}

export const autoFloors = (area, style) => (area <= 450 ? 1 : area <= 2600 && style !== 'palace' ? 2 : area <= 1400 ? 2 : 3)

function rowPlan(W, kind, level, hasEntrance) {
  const sides = level === 0 ? FRONT_SIDES.ground : FRONT_SIDES.upper
  const nFront = Math.max(3, Math.min(9, Math.round(W / 7)))
  const nSide = Math.floor((nFront - 1) / 2)
  const left = sides.slice(0, nSide).reverse(), right = sides.slice(nSide, nSide * 2)
  const types = [...left, 'entrance', ...right]
  return types.map((t) => ({ type: t, weight: t === 'entrance' ? 0 : WEIGHT[t] || 1, min: t === 'entrance' ? 0 : MIN_W[t] || 300 }))
}

/**
 * Generate the plan. opts: {area (m², total built area), floors (0 = auto), style 'villa'|'palace', aspect, levelHeight (m), label(type)→name}.
 * Returns {W, D, floors, total, levels:[{index, rooms, walls:[{a,b,ext}], doors, windows, floors, stairBlock}], ...} in METRES / cm grid:
 * use `buildVilla(plan, levelIds, unit)` to turn it into project elements.
 */
export function planVilla(opts) {
  const { area, style = 'villa', aspect = 1.5, levelHeight = 3.2 } = opts
  const floors = Math.max(1, Math.min(4, Math.round(opts.floors || autoFloors(area, style))))
  const fp = footprint(area, floors, aspect)
  const Wc = Math.round(fp.W * CM), Dc = Math.round(fp.D * CM)
  const corr = style === 'palace' || area > 1500 ? 360 : area > 400 ? 300 : 240
  const frontD = snap((Dc - corr) / 2)
  const backD = Dc - corr - frontD
  const levels = []
  for (let li = 0; li < floors; li++) {
    const rooms = []
    const add = (type, x0, y0, x1, y1, extra = {}) => rooms.push({ type, x0, y0, x1, y1, ...extra })
    // front row (south, street side) with the entrance/stair hall in the middle
    const row = rowPlan(Wc / CM, 'front', li, true)
    const stairW = Math.max(700, snap(Wc * 0.16))
    const others = row.filter((r) => r.type !== 'entrance')
    const wid = splitWidths(Wc - stairW, others)
    let x = 0, k = 0
    for (const r of row) {
      const w = r.type === 'entrance' ? stairW : wid[k++]
      add(r.type === 'entrance' ? (li === 0 ? 'entrance' : 'hall') : r.type, x, 0, x + w, frontD, r.type === 'entrance' ? { stair: true } : {})
      x += w
    }
    add('corridor', 0, frontD, Wc, frontD + corr)
    // back row
    const nBack = Math.max(3, Math.min(10, Math.round(Wc / CM / 5.5)))
    const bt = (li === 0 ? BACK.ground : BACK.upper)
    const back = Array.from({ length: nBack }, (_, i) => bt[i % bt.length])
    const bw = splitWidths(Wc, back.map((t) => ({ weight: WEIGHT[t] || 1, min: MIN_W[t] || 300 })))
    x = 0
    back.forEach((t, i) => { add(t, x, frontD + corr, x + bw[i], Dc); x += bw[i] })
    levels.push({ index: li, rooms })
  }
  return { W: Wc / CM, D: Dc / CM, Wc, Dc, floors, corr, frontD, levelHeight, area, total: fp.total, perLevel: fp.W * fp.D, rooms: levels }
}

// ---------------------------------------------------------------- walls from room rectangles
const key = (o, c) => `${o}${c}`
function unionIntervals(list) {
  const s = [...list].sort((a, b) => a[0] - b[0])
  const out = []
  for (const [a, b] of s) { if (out.length && a <= out[out.length - 1][1]) out[out.length - 1][1] = Math.max(out[out.length - 1][1], b); else out.push([a, b]) }
  return out
}
function subtract(ints, cut) {
  let cur = ints
  for (const [ca, cb] of cut) {
    const nx = []
    for (const [a, b] of cur) {
      if (cb <= a || ca >= b) { nx.push([a, b]); continue }
      if (ca > a) nx.push([a, ca])
      if (cb < b) nx.push([cb, b])
    }
    cur = nx
  }
  return cur
}

/** Unique wall pieces (split at every room corner) for a level; `gaps` = [{o:'H'|'V', c, a, b}] stretches left open. */
export function wallPieces(rooms, W, D, gaps = []) {
  const lines = new Map()    // 'H<y>' → intervals along x ; 'V<x>' → intervals along y
  const pts = new Set()
  const addI = (o, c, a, b) => { const k = key(o, c); if (!lines.has(k)) lines.set(k, []); lines.get(k).push([a, b]) }
  for (const r of rooms) {
    addI('H', r.y0, r.x0, r.x1); addI('H', r.y1, r.x0, r.x1); addI('V', r.x0, r.y0, r.y1); addI('V', r.x1, r.y0, r.y1)
    for (const p of [[r.x0, r.y0], [r.x1, r.y0], [r.x1, r.y1], [r.x0, r.y1]]) pts.add(`${p[0]},${p[1]}`)
  }
  const verts = [...pts].map((s) => s.split(',').map(Number))
  const out = []
  for (const [k, list] of lines) {
    const o = k[0], c = Number(k.slice(1))
    let ints = unionIntervals(list)
    ints = subtract(ints, gaps.filter((g) => g.o === o && g.c === c).map((g) => [g.a, g.b]))
    const cuts = verts.filter((v) => (o === 'H' ? v[1] === c : v[0] === c)).map((v) => (o === 'H' ? v[0] : v[1]))
    for (const [a, b] of ints) {
      const ps = [a, ...cuts.filter((t) => t > a && t < b).sort((p, q) => p - q), b]
      for (let i = 0; i + 1 < ps.length; i++) {
        const ext = o === 'H' ? (c === 0 || c === D) : (c === 0 || c === W)
        out.push(o === 'H' ? { a: [ps[i], c], b: [ps[i + 1], c], ext, o, c } : { a: [c, ps[i]], b: [c, ps[i + 1]], ext, o, c })
      }
    }
  }
  return out
}

const overlap = (a0, a1, b0, b1) => [Math.max(a0, b0), Math.min(a1, b1)]
const hasType = (t, s) => t === s

/**
 * Convert a plan into project elements. levelIds[i] is the id of level i. Returns {elements, stats}.
 * opts.label(type) → display name; opts.ext/int wall thickness in metres.
 */
export function buildVilla(plan, levelIds, unit, opts = {}) {
  const label = opts.label || ((t) => t)
  const U = (cm) => fromM(cm / CM, unit)
  const P = (p) => [U(p[0]), U(p[1])]
  const elements = []
  const stats = { rooms: 0, walls: 0, doors: 0, windows: 0, stairs: 0, area: 0 }
  const ext = opts.ext ?? 0.3, inn = opts.int ?? 0.15
  const { Wc, Dc, corr, frontD } = plan
  plan.rooms.forEach((lv, li) => {
    const levelId = levelIds[li]
    const top = li === plan.floors - 1
    const counters = {}
    for (const r of lv.rooms) { counters[r.type] = (counters[r.type] || 0) + 1 }
    const seen = {}
    // stairwell block inside the entrance hall (U stair, start at the corridor edge heading south)
    const hall = lv.rooms.find((r) => r.stair)
    const hallW = hall.x1 - hall.x0
    const stairW = 120, gap = 10
    const blockW = stairW * 2 + gap
    const sx0 = hall.x0 + snap((hallW - blockW) / 2)
    const steps = fitStairSteps(plan.levelHeight, 0.17)
    const n1 = Math.max(1, Math.floor(steps.steps / 2))
    const L1 = Math.round(n1 * 28) // cm
    const blockY0 = frontD - (L1 + stairW + 20)
    const stairBlock = [[sx0, blockY0], [sx0 + blockW, blockY0], [sx0 + blockW, frontD], [sx0, frontD]]
    const gaps = [{ o: 'H', c: frontD, a: hall.x0, b: hall.x1 }]
    for (const r of lv.rooms) {
      seen[r.type] = (seen[r.type] || 0) + 1
      const name = counters[r.type] > 1 ? `${label(r.type)} ${seen[r.type]}` : label(r.type)
      r.name = name
      const poly = [[r.x0, r.y0], [r.x1, r.y0], [r.x1, r.y1], [r.x0, r.y1]].map(P)
      elements.push(makeElement('room', levelId, unit, { polygon: poly, name, room_type: r.type }))
      stats.rooms++
      if (r.stair && li > 0) {   // upper levels: the floor of the stair hall is cut around the stairwell (3 rectangles, no holes)
        const bx0 = stairBlock[0][0], bx1 = stairBlock[1][0], by0 = stairBlock[0][1]
        for (const q of [[r.x0, r.y0, bx0, r.y1], [bx1, r.y0, r.x1, r.y1], [bx0, r.y0, bx1, by0]]) {
          if (q[2] - q[0] < 20 || q[3] - q[1] < 20) continue
          const pp = [[q[0], q[1]], [q[2], q[1]], [q[2], q[3]], [q[0], q[3]]].map(P)
          elements.push(makeElement('floor', levelId, unit, { polygon: pp, material: 'mat_concrete', name: null }))
        }
      } else elements.push(makeElement('floor', levelId, unit, { polygon: poly.map((p) => [...p]), material: 'mat_concrete', name: null }))
      stats.area += ((r.x1 - r.x0) * (r.y1 - r.y0)) / CM / CM
    }
    // walls (merged, split at junctions)
    const pieces = wallPieces(lv.rooms, Wc, Dc, gaps)
    const wallEls = pieces.map((w) => {
      const el = makeElement('wall', levelId, unit, { a: P(w.a), b: P(w.b), thickness: fromM(w.ext ? ext : inn, unit), material: w.ext ? 'mat_plaster' : 'mat_plaster' })
      el._piece = w
      return el
    })
    const pieceAt = (o, c, a, b) => wallEls.find((e) => e._piece.o === o && e._piece.c === c && e._piece.a[o === 'H' ? 0 : 1] <= a && e._piece.b[o === 'H' ? 0 : 1] >= b)
    const lenCm = (e) => Math.abs(e._piece.b[0] - e._piece.a[0]) + Math.abs(e._piece.b[1] - e._piece.a[1])
    const startCm = (e) => (e._piece.o === 'H' ? e._piece.a[0] : e._piece.a[1])
    const doorAt = (e, centre, width, height, mat = 'mat_wood') => {
      if (!e || lenCm(e) < width * CM + 40) return false
      const el = makeElement('door', levelId, unit, { wall_id: e.id, offset: U(centre - startCm(e)), width: fromM(width, unit), height: fromM(height, unit), material: mat })
      elements.push(el); stats.doors++
      return true
    }
    // doors: every room opens onto the corridor; the entrance hall is open to it
    const corr = lv.rooms.find((r) => r.type === 'corridor')
    for (const r of lv.rooms) {
      if (r === corr || r.stair) continue
      const front = r.y1 === corr.y0
      const [a, b] = overlap(r.x0, r.x1, corr.x0, corr.x1)
      const c = front ? corr.y0 : corr.y1
      const piece = pieceAt('H', c, a, b)
      const w = r.type === 'bathroom' || r.type === 'storage' ? 0.8 : r.type === 'master' || r.type === 'majlis' ? 1.1 : 0.9
      doorAt(piece, Math.round((a + b) / 2), w, 2.1)
    }
    // main door in the south wall of the entrance hall (ground level only)
    if (li === 0) {
      const piece = pieceAt('H', 0, hall.x0, hall.x1)
      doorAt(piece, Math.round((hall.x0 + hall.x1) / 2), 1.6, 2.4)
    }
    // windows on exterior wall pieces
    for (const e of wallEls) {
      const w = e._piece
      if (!w.ext) continue
      const L = lenCm(e) / CM
      const mid = [(w.a[0] + w.b[0]) / 2, (w.a[1] + w.b[1]) / 2]
      const inward = w.o === 'H' ? [0, w.c === 0 ? 5 : -5] : [w.c === 0 ? 5 : -5, 0]
      const room = lv.rooms.find((r) => mid[0] + inward[0] >= r.x0 && mid[0] + inward[0] <= r.x1 && mid[1] + inward[1] >= r.y0 && mid[1] + inward[1] <= r.y1)
      if (!room || room.type === 'garage' || room.stair || L < 2.0) continue
      const small = room.type === 'bathroom' || room.type === 'storage'
      const n = small ? 1 : Math.max(1, Math.floor(L / 3.4))
      const ww = small ? 0.7 : Math.min(1.8, Math.max(1.0, L / n - 1.2))
      for (let k = 0; k < n; k++) {
        const el = makeElement('window', levelId, unit, { wall_id: e.id, offset: U(((k + 0.5) * lenCm(e)) / n), width: fromM(ww, unit), height: fromM(small ? 0.6 : 1.4, unit), sill: fromM(small ? 1.7 : 0.9, unit), material: 'mat_glass' })
        elements.push(el); stats.windows++
      }
    }
    for (const e of wallEls) { delete e._piece; elements.push(e); stats.walls++ }
    // stair up to the next level
    if (!top) {
      const flights = []
      const hgt = fromM(plan.levelHeight, unit)
      const start = [U(sx0 + stairW / 2), U(frontD)]
      const run = fromM(0.28, unit), w = fromM(stairW / CM, unit)
      const f1 = makeElement('stair', levelId, unit, { start, angle_deg: 270, width: w, steps: n1, rise: fromM(plan.levelHeight / steps.steps, unit), run, material: 'mat_concrete' })
      const n2 = Math.max(1, steps.steps - n1)
      const zl = n1 * (plan.levelHeight / steps.steps)
      const f2 = makeElement('stair', levelId, unit, { start: [U(sx0 + stairW + gap + stairW / 2), U(frontD - L1)], angle_deg: 90, width: w, steps: n2, rise: fromM(plan.levelHeight / steps.steps, unit), run, z_offset: fromM(zl, unit), material: 'mat_concrete' })
      const landing = [[sx0, frontD - L1 - stairW], [sx0 + blockW, frontD - L1 - stairW], [sx0 + blockW, frontD - L1], [sx0, frontD - L1]].map(P)
      const slab = makeElement('floor', levelId, unit, { polygon: landing, z_offset: fromM(zl, unit), material: 'mat_concrete', thickness: fromM(0.15, unit) })
      flights.push(f1, f2, slab)
      elements.push(...flights); stats.stairs++
    }
    if (top) {
      elements.push(makeElement('roof', levelId, unit, { kind: 'flat', polygon: [[0, 0], [Wc, 0], [Wc, Dc], [0, Dc]].map(P), overhang: fromM(0.3, unit), thickness: fromM(0.2, unit) }))
    }
  })
  stats.area = Math.round(stats.area * 100) / 100
  return { elements, stats }
}

/** Levels needed by the plan, as new level objects (project units) after the existing ones. */
export function levelsFor(plan, existing, unit) {
  const out = existing.slice(0, plan.floors).map((l) => ({ ...l }))
  while (out.length < plan.floors) {
    const prev = out[out.length - 1]
    out.push({ id: uid('lvl'), name: `Level ${out.length}`, elevation: prev ? prev.elevation + prev.height : 0, height: prev ? prev.height : fromM(plan.levelHeight, unit) })
  }
  out.forEach((l, i) => { if (i < existing.length) { l.height = fromM(plan.levelHeight, unit); l.elevation = i ? out[i - 1].elevation + out[i - 1].height : 0 } })
  return out
}
