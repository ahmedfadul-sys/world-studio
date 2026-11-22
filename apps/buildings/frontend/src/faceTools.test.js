import { describe, expect, it } from 'vitest'
import { ALL_SHAPES, centreOnWall, faceTargets, mirrorPoly, rotatePoly, shapePolygon, snapMove, snapPoint } from './faceTools.js'
import { polyBBox } from './model.js'

describe('faceTools', () => {
  it('every shape gives a valid polygon inside its drag box', () => {
    for (const s of ALL_SHAPES) {
      const pg = shapePolygon(s, s === 'circle' || s === 'star' ? [2, 2] : [1, 1], s === 'circle' || s === 'star' ? [3, 2] : [3, 3.5])
      expect(pg && pg.length >= 3, s).toBe(true)
      expect(pg.every((p) => p.every(Number.isFinite)), s).toBe(true)
    }
    for (const s of ['ellipse', 'hexagon', 'octagon', 'diamond', 'cross', 'trapezoid', 'roundrect', 'semicircle', 'gothic']) {
      const b = polyBBox(shapePolygon(s, [1, 1], [3, 3.5]))
      expect(b.x0, s).toBeGreaterThanOrEqual(1 - 1e-4); expect(b.x1, s).toBeLessThanOrEqual(3 + 1e-4)
      expect(b.y0, s).toBeGreaterThanOrEqual(1 - 1e-4); expect(b.y1, s).toBeLessThanOrEqual(3.5 + 1e-4)
    }
  })
  it('gothic arch reaches the top and is pointed', () => {
    const b = polyBBox(shapePolygon('gothic', [0, 0], [1, 2]))
    expect(b.y1).toBeCloseTo(2, 3)
  })
  it('slot is a slanted bar of the given width', () => {
    const pg = shapePolygon('slot', [0, 0], [3, 4], { barWidth: 0.5 })
    expect(Math.hypot(pg[1][0] - pg[0][0], pg[1][1] - pg[0][1])).toBeCloseTo(5, 5)
    expect(Math.hypot(pg[3][0] - pg[0][0], pg[3][1] - pg[0][1])).toBeCloseTo(0.5, 5)
  })
  it('rotation keeps the centre and size of a square', () => {
    const sq = [[0, 0], [2, 0], [2, 2], [0, 2]], r = rotatePoly(sq, 45)
    const b = polyBBox(r)
    expect((b.x0 + b.x1) / 2).toBeCloseTo(1, 5); expect(b.x1 - b.x0).toBeCloseTo(2 * Math.SQRT2, 5)
    expect(polyBBox(shapePolygon('rect', [0, 0], [2, 1], { angle: 90 })).y1 - polyBBox(shapePolygon('rect', [0, 0], [2, 1], { angle: 90 })).y0).toBeCloseTo(2, 5)
  })
  it('mirror and centre', () => {
    const tri = [[0, 0], [2, 0], [0, 3]]
    expect(polyBBox(mirrorPoly(tri, 'h', [1, 0])).x1).toBe(2)
    const c = centreOnWall([[0, 0], [1, 0], [1, 1], [0, 1]], 10, 3, 'h'); expect(polyBBox(c).x0).toBeCloseTo(4.5, 6)
  })
  it('snap: aligns to opening edges, equal sizes, then grid', () => {
    const tg = faceTargets(10, 3, [{ offset: 5, width: 1, height: 2, sill: 0.9 }], [{ id: 'a', polygon: [[1, 1], [2.5, 1], [2.5, 2], [1, 2]] }], 'none')
    let s = snapPoint([4.52, 1.1], tg, { tol: 0.06, step: 0.1 })
    expect(s.p[0]).toBe(4.5); expect(s.guides.some((g) => g.axis === 'u' && g.kind === 'align')).toBe(true)
    // equal width to feature a (1.5): anchor at 6, cursor at 7.47 -> 7.5
    s = snapPoint([7.47, 2.6], tg, { tol: 0.05, step: 0.1, anchor: [6, 2.6] }); expect(s.p[0]).toBe(7.5)
    s = snapPoint([7.43, 2.62], tg, { tol: 0.01, step: 0.1 }); expect(s.p).toEqual([7.4, 2.6])
    s = snapPoint([7.43, 2.62], tg, { tol: 0.05, step: 0.1, targets: false, grid: false }); expect(s.p).toEqual([7.43, 2.62])
  })
  it('snap while moving: edge of the box meets the edge of another shape', () => {
    const tg = faceTargets(10, 3, [], [{ id: 'a', polygon: [[1, 1], [2, 1], [2, 2], [1, 2]] }], 'none')
    const bb = { x0: 4, y0: 1.04, x1: 5, y1: 2.04 }
    const m = snapMove(bb, -1.97, 0, tg, { tol: 0.06, step: 0.1 })
    expect(m.du).toBeCloseTo(-2, 6); expect(m.dv).toBeCloseTo(-0.04, 6)    // left edge 4 → 2 (a.x1), bottom 1.04 → 1
  })
})

import { wallSide } from './faceTools.js'
describe('wallSide', () => {
  it('left/right of a→b from the normal (three.js z = −plan y)', () => {
    const w = { a: [0, 0], b: [10, 0] }
    expect(wallSide(w, { x: 0, y: 0, z: -1 })).toBe('left')    // plan +y side
    expect(wallSide(w, { x: 0, y: 0, z: 1 })).toBe('right')
  })
})
