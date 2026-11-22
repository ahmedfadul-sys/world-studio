// Wall-face carving helpers: more shapes, rotation/mirror/array/centre, and smart snapping (edges, openings, other shapes, equal sizes).
import { arcPoints, faceShapePolygon, polyBBox } from './model.js'

const r6 = (v) => Math.round(v * 1e6) / 1e6
const FORMER = ['rect', 'circle', 'arch', 'triangle', 'star']
export const EXTRA_SHAPES = ['ellipse', 'roundrect', 'hexagon', 'octagon', 'diamond', 'cross', 'semicircle', 'trapezoid', 'gothic', 'slot']
export const ALL_SHAPES = [...FORMER, ...EXTRA_SHAPES]
export const GLYPH = { ellipse: '⬭', roundrect: '▢', hexagon: '⬡', octagon: '⯄', diamond: '◇', cross: '✚', semicircle: '◗', trapezoid: '⏢', gothic: '⛫', slot: '╱' }

export const centreOf = (poly) => { const b = polyBBox(poly); return [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2] }

/** Rotate a polygon by `deg` (counter-clockwise on the wall face) about `c` (default: bounding-box centre). */
export function rotatePoly(poly, deg, c = centreOf(poly)) {
  const a = (deg * Math.PI) / 180, co = Math.cos(a), si = Math.sin(a)
  return poly.map(([u, v]) => [r6(c[0] + (u - c[0]) * co - (v - c[1]) * si), r6(c[1] + (u - c[0]) * si + (v - c[1]) * co)])
}
/** Mirror about a vertical ('h' = left-right) or horizontal ('v' = up-down) axis through c. */
export function mirrorPoly(poly, axis, c = centreOf(poly)) {
  return poly.map(([u, v]) => (axis === 'h' ? [r6(2 * c[0] - u), v] : [u, r6(2 * c[1] - v)])).reverse()
}
/** Move the polygon so its bounding box is centred on the wall (axis 'h' = along the wall, 'v' = in height). */
export function centreOnWall(poly, L, H, axis) {
  const b = polyBBox(poly)
  return axis === 'h' ? poly.map(([u, v]) => [r6(u + (L - (b.x0 + b.x1)) / 2), v]) : poly.map(([u, v]) => [u, r6(v + (H - (b.y0 + b.y1)) / 2)])
}
export const arrayPoly = (poly, i, du, dv) => poly.map(([u, v]) => [r6(u + du * i), r6(v + dv * i)])

const ngon = (cx, cy, rx, ry, n, rot = 0) => Array.from({ length: n }, (_, i) => { const a = rot + (2 * Math.PI * i) / n; return [r6(cx + rx * Math.cos(a)), r6(cy + ry * Math.sin(a))] })

/**
 * Polygon of any shape for a 2-point drag. Box shapes use the box p0–p1; circle/star use centre + radius; slot uses the line p0→p1 with width `barWidth`.
 * opts.angle rotates the result about its own centre (for slot the line itself already carries the angle).
 */
export function shapePolygon(shape, p0, p1, { angle = 0, barWidth = 0.1 } = {}) {
  let pg
  if (FORMER.includes(shape)) pg = faceShapePolygon(shape, p0, p1)
  else if (shape === 'slot') {
    const dx = p1[0] - p0[0], dy = p1[1] - p0[1], L = Math.hypot(dx, dy)
    if (L < 1e-6 || barWidth <= 0) return null
    const nx = -dy / L, ny = dx / L, h = barWidth / 2
    pg = [[p0[0] + nx * h, p0[1] + ny * h], [p1[0] + nx * h, p1[1] + ny * h], [p1[0] - nx * h, p1[1] - ny * h], [p0[0] - nx * h, p0[1] - ny * h]].map(([a, b]) => [r6(a), r6(b)])
    return pg                                            // the drag direction IS the angle
  } else {
    const x0 = Math.min(p0[0], p1[0]), x1 = Math.max(p0[0], p1[0]), y0 = Math.min(p0[1], p1[1]), y1 = Math.max(p0[1], p1[1])
    const w = x1 - x0, h = y1 - y0
    if (w < 1e-6 || h < 1e-6) return null
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2
    switch (shape) {
      case 'ellipse': pg = ngon(cx, cy, w / 2, h / 2, 40); break
      case 'hexagon': pg = ngon(cx, cy, w / 2, h / 2, 6); break
      case 'octagon': pg = ngon(cx, cy, w / 2, h / 2, 8, Math.PI / 8); break
      case 'diamond': pg = [[cx, y0], [x1, cy], [cx, y1], [x0, cy]]; break
      case 'cross': { const a = w * 0.34, b = h * 0.34; pg = [[cx - a / 2, y0], [cx + a / 2, y0], [cx + a / 2, cy - b / 2], [x1, cy - b / 2], [x1, cy + b / 2], [cx + a / 2, cy + b / 2], [cx + a / 2, y1], [cx - a / 2, y1], [cx - a / 2, cy + b / 2], [x0, cy + b / 2], [x0, cy - b / 2], [cx - a / 2, cy - b / 2]]; break }
      case 'trapezoid': pg = [[x0, y0], [x1, y0], [x1 - w * 0.22, y1], [x0 + w * 0.22, y1]]; break
      case 'roundrect': {
        const r = Math.min(w, h) * 0.22; pg = []
        for (const [ccx, ccy, a0] of [[x1 - r, y0 + r, -Math.PI / 2], [x1 - r, y1 - r, 0], [x0 + r, y1 - r, Math.PI / 2], [x0 + r, y0 + r, Math.PI]]) for (let i = 0; i <= 5; i++) { const a = a0 + (i * Math.PI) / 10; pg.push([ccx + r * Math.cos(a), ccy + r * Math.sin(a)]) }
        break
      }
      case 'semicircle': { pg = [[x1, y0]]; for (let i = 1; i < 20; i++) { const a = (i * Math.PI) / 20; pg.push([cx + (w / 2) * Math.cos(a), y0 + h * Math.sin(a)]) } pg.push([x0, y0]); break }
      case 'gothic': {   // pointed arch: two arcs of radius w meeting at the apex; springing line chosen so the apex is at y1
        const rr = w, rise = Math.min(h, (rr * Math.sqrt(3)) / 2), sy = y1 - rise
        const aMax = Math.asin(Math.min(1, rise / rr))   // arc about (x0, sy) from x1 up to the apex at angle aMax
        pg = [[x0, y0], [x1, y0], [x1, sy]]
        for (let i = 1; i < 10; i++) { const a = (i * aMax) / 10; pg.push([x0 + rr * Math.cos(a), sy + rr * Math.sin(a)]) }
        pg.push([cx, y1])
        for (let i = 9; i >= 1; i--) { const a = (i * aMax) / 10; pg.push([x1 - rr * Math.cos(a), sy + rr * Math.sin(a)]) }
        pg.push([x0, sy])
        break
      }
      default: return null
    }
    pg = pg.map(([a, b]) => [r6(a), r6(b)])
  }
  if (!pg) return null
  return angle ? rotatePoly(pg, angle) : pg
}

// ------------------------------------------------------------------ snapping
/** Snap targets on the face: u (along) and v (height) values from the wall box, openings and other shapes. */
export function faceTargets(L, H, openings, feats, excludeId) {
  const us = new Set([0, L, L / 2]), vs = new Set([0, H, H / 2]), w = [], h = []
  for (const o of openings) {
    const sill = o.sill || 0
    ;[o.offset - o.width / 2, o.offset, o.offset + o.width / 2].forEach((u) => us.add(r6(u)))
    ;[sill, sill + o.height / 2, sill + o.height].forEach((v) => vs.add(r6(v)))
    w.push(o.width); h.push(o.height)
  }
  for (const f of feats) {
    if (f.id === excludeId) continue
    const b = polyBBox(f.polygon)
    ;[b.x0, (b.x0 + b.x1) / 2, b.x1].forEach((u) => us.add(r6(u)))
    ;[b.y0, (b.y0 + b.y1) / 2, b.y1].forEach((v) => vs.add(r6(v)))
    for (const [u, v] of f.polygon) { us.add(r6(u)); vs.add(r6(v)) }
    w.push(b.x1 - b.x0); h.push(b.y1 - b.y0)
  }
  return { us: [...us], vs: [...vs], w: w.filter((x) => x > 1e-6), h: h.filter((x) => x > 1e-6) }
}

const nearest = (vals, x, tol) => { let best = null, bd = tol; for (const v of vals) { const d = Math.abs(v - x); if (d <= bd) { bd = d; best = v } } return best }

/**
 * Smart point snap. Priority per axis: alignment target (edge/centre/opening/other shape) > equal size to the anchor (when given) > grid.
 * Returns {p:[u,v], guides:[{axis:'u'|'v', value, kind:'align'|'size'}]}.
 */
export function snapPoint(raw, tg, { tol, step, grid = true, targets = true, anchor = null }) {
  const out = [raw[0], raw[1]], guides = []
  const axes = [['u', 0, tg.us, tg.w], ['v', 1, tg.vs, tg.h]]
  for (const [ax, i, vals, sizes] of axes) {
    const hit = targets ? nearest(vals, raw[i], tol) : null
    if (hit !== null) { out[i] = hit; guides.push({ axis: ax, value: hit, kind: 'align' }); continue }
    if (anchor && targets) {
      const sgn = raw[i] >= anchor[i] ? 1 : -1, s = nearest(sizes, Math.abs(raw[i] - anchor[i]), tol)
      if (s !== null) { out[i] = r6(anchor[i] + sgn * s); guides.push({ axis: ax, value: out[i], kind: 'size' }); continue }
    }
    if (grid && step) out[i] = r6(Math.round(raw[i] / step) * step)
  }
  return { p: out, guides }
}

/** Snap a moving bounding box: its left/centre/right and bottom/middle/top edges against the targets. Returns {du,dv,guides}. */
export function snapMove(bb, du, dv, tg, { tol, step, grid = true, targets = true }) {
  const guides = []
  const res = [du, dv]
  const spec = [['u', 0, [bb.x0, (bb.x0 + bb.x1) / 2, bb.x1], tg.us], ['v', 1, [bb.y0, (bb.y0 + bb.y1) / 2, bb.y1], tg.vs]]
  for (const [ax, i, edges, vals] of spec) {
    let best = null
    if (targets) for (const e of edges) for (const v of vals) { const d = v - (e + res[i]); if (Math.abs(d) <= tol && (!best || Math.abs(d) < Math.abs(best.d))) best = { d, at: v } }
    if (best) { res[i] += best.d; guides.push({ axis: ax, value: best.at, kind: 'align' }) } else if (grid && step) res[i] = r6(Math.round(res[i] / step) * step)
  }
  return { du: r6(res[0]), dv: r6(res[1]), guides }
}

/** Side of wall `w` (a→b) that a surface normal `nrm` (three.js Y-up: x, y, z = −plan y) faces: 'left' or 'right'. */
export function wallSide(w, nrm) {
  const dx = w.b[0] - w.a[0], dy = w.b[1] - w.a[1]
  return nrm.x * -dy + -nrm.z * dx > 0 ? 'left' : 'right'
}
