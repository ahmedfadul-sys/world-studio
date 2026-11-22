// ASCII DXF reader → wall segments. Supports LINE, LWPOLYLINE (incl. bulged arcs), POLYLINE/VERTEX, CIRCLE and ARC.
// Blocks (INSERT), text, hatches, dimensions, 3D solids and binary DXF / DWG are not read.
import { arcPoints, makeElement, UNITS } from './model.js'

const r6 = (v) => Math.round(v * 1e6) / 1e6
const INSUNITS = { 1: 'in', 2: 'ft', 4: 'mm', 5: 'cm', 6: 'm' }
const SKIPPED = new Set(['INSERT', 'SPLINE', 'ELLIPSE', 'HATCH', 'SOLID', '3DFACE', 'TEXT', 'MTEXT', 'DIMENSION', 'POINT', 'ATTRIB'])

export class DxfError extends Error {}

/** Pair up (group code, value) lines. */
function pairs(text) {
  const lines = text.split(/\r\n|\r|\n/)
  const out = []
  for (let i = 0; i + 1 < lines.length; i += 2) out.push([parseInt(lines[i].trim(), 10), lines[i + 1].trim()])
  return out
}

/** Bulged polyline segment p1→p2 as an arc primitive (raw drawing units). */
function bulgeArc(p1, p2, bulge, layer) {
  const theta = 4 * Math.atan(bulge)                 // signed included angle (+ = counter-clockwise)
  const ch = Math.hypot(p2[0] - p1[0], p2[1] - p1[1])
  if (ch < 1e-12 || Math.abs(theta) < 1e-9) return null
  const r = ch / (2 * Math.sin(Math.abs(theta) / 2))
  const mid = [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2]
  const h = Math.sqrt(Math.max(0, r * r - (ch / 2) ** 2))
  const nx = -(p2[1] - p1[1]) / ch, ny = (p2[0] - p1[0]) / ch   // left normal
  const side = theta > 0 ? 1 : -1
  const c = [mid[0] + nx * h * side * (Math.abs(theta) > Math.PI ? -1 : 1), mid[1] + ny * h * side * (Math.abs(theta) > Math.PI ? -1 : 1)]
  const a0 = Math.atan2(p1[1] - c[1], p1[0] - c[0])
  return { t: 'arc', c, r, a0, sweep: theta, layer }
}

export function parseDxf(text) {
  if (/^AutoCAD Binary DXF/.test(text)) throw new DxfError('binary')
  const g = pairs(text)
  if (g.length < 10) throw new DxfError('empty')
  const res = { entities: [], layers: {}, units: null, skipped: {} }
  let i = 0
  // header: $INSUNITS
  for (; i < g.length; i++) {
    if (g[i][0] === 9 && g[i][1] === '$INSUNITS') { const v = g[i + 1] && g[i + 1][0] === 70 ? parseInt(g[i + 1][1], 10) : 0; res.units = INSUNITS[v] || null }
    if (g[i][0] === 2 && g[i][1] === 'ENTITIES') break
  }
  if (i >= g.length) throw new DxfError('no_entities')
  i++
  const num = (v) => parseFloat(v)
  const note = (layer) => { res.layers[layer] = (res.layers[layer] || 0) + 1 }
  let poly = null   // open POLYLINE (old style) being collected
  const flushPoly = () => {
    if (poly && poly.pts.length >= 2) pushPoly(poly.pts, poly.bul, poly.closed, poly.layer)
    poly = null
  }
  const pushPoly = (pts, bul, closed, layer) => {
    const n = pts.length
    const last = closed ? n : n - 1
    for (let k = 0; k < last; k++) {
      const p1 = pts[k], p2 = pts[(k + 1) % n], b = bul[k] || 0
      if (Math.hypot(p2[0] - p1[0], p2[1] - p1[1]) < 1e-12) continue
      const arc = b ? bulgeArc(p1, p2, b, layer) : null
      res.entities.push(arc || { t: 'line', a: p1, b: p2, layer })
      note(layer)
    }
  }
  while (i < g.length) {
    const [code, val] = g[i]
    if (code === 0 && val === 'ENDSEC') break
    if (code !== 0) { i++; continue }
    const type = val
    let j = i + 1
    const rec = []
    while (j < g.length && g[j][0] !== 0) { rec.push(g[j]); j++ }
    const layer = (rec.find((r) => r[0] === 8) || [8, '0'])[1]
    const f = (c) => { const r = rec.find((x) => x[0] === c); return r ? num(r[1]) : undefined }
    if (type !== 'VERTEX' && type !== 'SEQEND') flushPoly()
    if (type === 'LINE') {
      const a = [f(10), f(20)], b = [f(11), f(21)]
      if ([...a, ...b].every(Number.isFinite) && (a[0] !== b[0] || a[1] !== b[1])) { res.entities.push({ t: 'line', a, b, layer }); note(layer) }
    } else if (type === 'LWPOLYLINE') {
      const pts = [], bul = []
      for (const [c, v] of rec) {
        if (c === 10) { pts.push([num(v), 0]); bul.push(0) } else if (c === 20 && pts.length) pts[pts.length - 1][1] = num(v)
        else if (c === 42 && pts.length) bul[pts.length - 1] = num(v)
      }
      pushPoly(pts, bul, ((f(70) || 0) & 1) === 1, layer)
    } else if (type === 'POLYLINE') {
      poly = { pts: [], bul: [], closed: ((f(70) || 0) & 1) === 1, layer }
    } else if (type === 'VERTEX' && poly) {
      const x = f(10), y = f(20)
      if (Number.isFinite(x) && Number.isFinite(y)) { poly.pts.push([x, y]); poly.bul.push(f(42) || 0) }
    } else if (type === 'CIRCLE') {
      const c = [f(10), f(20)], r = f(40)
      if (c.every(Number.isFinite) && r > 0) { res.entities.push({ t: 'arc', c, r, a0: 0, sweep: 2 * Math.PI, layer }); note(layer) }
    } else if (type === 'ARC') {
      const c = [f(10), f(20)], r = f(40)
      let a0 = ((f(50) ?? 0) * Math.PI) / 180, a1 = ((f(51) ?? 0) * Math.PI) / 180
      while (a1 <= a0) a1 += 2 * Math.PI
      if (c.every(Number.isFinite) && r > 0) { res.entities.push({ t: 'arc', c, r, a0, sweep: a1 - a0, layer }); note(layer) }
    } else if (SKIPPED.has(type)) res.skipped[type] = (res.skipped[type] || 0) + 1
    i = j
  }
  flushPoly()
  if (!res.entities.length) throw new DxfError('no_geometry')
  return res
}

/**
 * Convert parsed entities to wall elements.
 * opts: {layers:Set|null, fromUnit:'m'|'cm'|'mm'|'ft'|'in', levelId, unit(project), thickness(project units),
 *        minLen(project units), snap(project units), origin:boolean (move the drawing's lower-left corner to 0,0), maxChord(m)}
 */
export function dxfToWalls(parsed, opts) {
  const { layers = null, fromUnit = 'm', levelId, unit, thickness, minLen = 0, snap = 0, origin = true, maxChord = 1.5, max = 4000 } = opts
  const k = UNITS[fromUnit].toM / UNITS[unit].toM       // drawing unit → project unit
  const segs = []
  const chordRaw = maxChord / UNITS[fromUnit].toM
  for (const e of parsed.entities) {
    if (layers && !layers.has(e.layer)) continue
    if (e.t === 'line') segs.push([e.a, e.b])
    else {
      const n = Math.max(4, Math.min(96, Math.ceil((e.r * Math.abs(e.sweep)) / chordRaw)))
      const pts = arcPoints(e.c, e.r, e.a0, e.sweep, n)
      for (let q = 0; q + 1 < pts.length; q++) segs.push([pts[q], pts[q + 1]])
      if (Math.abs(Math.abs(e.sweep) - 2 * Math.PI) < 1e-9 && pts.length) { /* full circle: arcPoints already closes the ring */ }
    }
  }
  if (!segs.length) return { walls: [], count: 0, dropped: 0 }
  let ox = 0, oy = 0
  if (origin) {
    ox = Math.min(...segs.flatMap((s) => [s[0][0], s[1][0]]))
    oy = Math.min(...segs.flatMap((s) => [s[0][1], s[1][1]]))
  }
  const sc = (p) => [r6((p[0] - ox) * k), r6((p[1] - oy) * k)]
  // snap endpoints together (clusters within `snap`) so wall chains close exactly
  const grid = new Map()
  const tol = snap > 0 ? snap : 0
  const merge = (p) => {
    if (!tol) return p
    const cx = Math.round(p[0] / tol), cy = Math.round(p[1] / tol)
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
      const c = grid.get(`${cx + dx},${cy + dy}`)
      if (c && Math.hypot(c[0] - p[0], c[1] - p[1]) <= tol) return c
    }
    grid.set(`${cx},${cy}`, p)
    return p
  }
  const seen = new Set()
  const walls = []
  let dropped = 0
  for (const [a0, b0] of segs) {
    const a = merge(sc(a0)), b = merge(sc(b0))
    const L = Math.hypot(b[0] - a[0], b[1] - a[1])
    if (L < Math.max(minLen, 1e-6)) { dropped++; continue }
    const key = [a, b].map((p) => p.join(',')).sort().join('|')
    if (seen.has(key)) { dropped++; continue }
    seen.add(key)
    walls.push(makeElement('wall', levelId, unit, { a: [...a], b: [...b], thickness, material: 'mat_plaster' }))
    if (walls.length > max) return { walls: [], count: segs.length, dropped, tooMany: true }
  }
  return { walls, count: segs.length, dropped }
}
