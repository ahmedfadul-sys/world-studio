import { describe, expect, it } from 'vitest'
import {
  UNITS, bbox, convertUnits, defaults, deleteElements, fromM, histNew, histPush, histRedo, histUndo, hitTest,
  makeElement, moveElements, nearestWall, orthoPoint, patchElement, placeOpening, pointInPolygon, polygonArea,
  snapPoint, snapStep, gridStep, stairRect,
} from './model.js'

const W = (id, a, b, extra = {}) => ({ id, type: 'wall', level_id: 'L', a, b, thickness: 0.2, ...extra })
const base = () => [W('w1', [0, 0], [6, 0]), W('w2', [6, 0], [6, 4])]

describe('snapping', () => {
  it('prefers endpoints, then wall lines, then grid, then free', () => {
    const o = { step: 0.1, enabled: true, endpoints: [[6, 0]], walls: base(), tol: 0.25 }
    expect(snapPoint([5.9, 0.1], o)).toEqual({ p: [6, 0], kind: 'point' })
    expect(snapPoint([3.04, 0.2], o).kind).toBe('wall')               // T-junction onto w1's centre line
    expect(snapPoint([3.04, 0.2], o).p).toEqual([3.04, 0])
    expect(snapPoint([2.04, 2.07], o)).toEqual({ p: [2, 2.1], kind: 'grid' })
    expect(snapPoint([2.04, 2.07], { ...o, enabled: false })).toEqual({ p: [2.04, 2.07], kind: 'free' })
  })
  it('does not hardcode tolerance/precision: unit defaults and user overrides', () => {
    const mk = (u, ed = {}) => ({ units: { name: u }, editor: ed })
    expect(snapStep(mk('m'))).toBe(0.1)
    expect(snapStep(mk('cm'))).toBe(10)
    expect(snapStep(mk('m', { snap_size: 0.025 }))).toBe(0.025)
    expect(gridStep(mk('ft'))).toBe(1)
    expect(snapPoint([1.012, 1.012], { step: 0.025, enabled: true })).toEqual({ p: [1.0, 1.0], kind: 'grid' })
  })
  it('ortho constrains to the dominant axis', () => {
    expect(orthoPoint([0, 0], [5, 1])).toEqual([5, 0])
    expect(orthoPoint([0, 0], [1, -5])).toEqual([0, -5])
  })
})

describe('openings', () => {
  it('hosts a door on the nearest wall and clamps it inside the wall', () => {
    const r = placeOpening('door', [0.1, 0.05], base(), 'L', 'm', 0.3)
    expect(r.element.wall_id).toBe('w1')
    expect(r.element.offset).toBeCloseTo(0.45)               // clamped: half the 0.9 door width
    expect(r.element.width).toBeCloseTo(0.9)
  })
  it('snaps the position along the wall to the snap step when asked', () => {
    expect(placeOpening('door', [2.992, 0.02], base(), 'L', 'm', 0.3, 0.1).element.offset).toBeCloseTo(3.0)
    expect(placeOpening('door', [2.992, 0.02], base(), 'L', 'm', 0.3, 0).element.offset).toBeCloseTo(2.992)
  })
  it('reports no_wall and wall_too_short', () => {
    expect(placeOpening('window', [3, 3], base(), 'L', 'm', 0.3).error).toBe('no_wall')
    expect(placeOpening('door', [0.2, 0], [W('s', [0, 0], [0.5, 0])], 'L', 'm', 0.3).error).toBe('wall_too_short')
  })
  it('uses unit-aware defaults (cm)', () => {
    expect(defaults('door', 'cm').width).toBeCloseTo(90)
    expect(defaults('wall', 'mm').thickness).toBeCloseTo(200)
    expect(nearestWall([3, 0.05], base(), 0.1).wall.id).toBe('w1')
  })
})

describe('hit testing', () => {
  const els = [
    ...base(),
    { id: 'd1', type: 'door', level_id: 'L', wall_id: 'w1', offset: 2, width: 0.9, height: 2.1, sill: 0 },
    { id: 'f1', type: 'floor', level_id: 'L', polygon: [[0, 0], [6, 0], [6, 4], [0, 4]], holes: [], thickness: 0.2 },
    { id: 'c1', type: 'column', level_id: 'L', pos: [3, 2], shape: 'box', width: 0.4, depth: 0.4 },
    { id: 'u', type: 'wall', level_id: 'OTHER', a: [0, 0], b: [6, 0], thickness: 0.2 },
  ]
  it('opening wins over its wall, wall over floor, column over floor; other levels ignored', () => {
    expect(hitTest([2, 0], els, 'L', 0.05)).toBe('d1')
    expect(hitTest([4.5, 0], els, 'L', 0.05)).toBe('w1')
    expect(hitTest([3, 2], els, 'L', 0.05)).toBe('c1')
    expect(hitTest([1, 2], els, 'L', 0.05)).toBe('f1')
    expect(hitTest([9, 9], els, 'L', 0.05)).toBeNull()
  })
  it('stair rectangle follows its angle', () => {
    const s = { id: 's', type: 'stair', level_id: 'L', start: [0, 0], angle_deg: 90, width: 1, steps: 10, rise: 0.18, run: 0.28 }
    expect(pointInPolygon([0, 1], stairRect(s))).toBe(true)
    expect(pointInPolygon([1, 0.1], stairRect(s))).toBe(false)
  })
})

describe('editing', () => {
  it('moves walls with their openings; a lone opening slides along its wall and stays inside', () => {
    const els = [...base(), { id: 'd1', type: 'door', level_id: 'L', wall_id: 'w1', offset: 2, width: 0.9 }]
    const m1 = moveElements(els, ['w1', 'd1'], 1, 1)
    expect(m1.find((e) => e.id === 'w1').a).toEqual([1, 1])
    expect(m1.find((e) => e.id === 'd1').offset).toBe(2)       // unchanged, relative to host
    const m2 = moveElements(els, ['d1'], 1.5, 9)
    expect(m2.find((e) => e.id === 'd1').offset).toBeCloseTo(3.5) // only the along-wall component
    const m3 = moveElements(els, ['d1'], 100, 0)
    expect(m3.find((e) => e.id === 'd1').offset).toBeCloseTo(5.55)
  })
  it('deleting a wall removes its openings (no dangling host references)', () => {
    const els = [...base(), { id: 'd1', type: 'door', level_id: 'L', wall_id: 'w1', offset: 2, width: 0.9 }]
    expect(deleteElements(els, ['w1']).map((e) => e.id)).toEqual(['w2'])
  })
  it('records user-edited fields as overrides so modules never clobber them', () => {
    const e = patchElement(makeElement('wall', 'L', 'm', { a: [0, 0], b: [1, 0] }), { thickness: 0.3 })
    expect(e.overrides).toContain('thickness')
  })
  it('geometry helpers', () => {
    expect(polygonArea([[0, 0], [6, 0], [6, 4], [0, 4]])).toBe(24)
    expect(bbox(base(), 'L')).toEqual({ x0: 0, y0: 0, x1: 6, y1: 4 })
  })
})

describe('unit conversion', () => {
  it('keeps the real-world size when switching m -> cm -> m', () => {
    const p = {
      units: { name: 'm' }, editor: { grid_size: 1, snap_size: null },
      levels: [{ id: 'L', elevation: 3, height: 3 }],
      elements: [W('w1', [0, 0], [6, 0]),
        { id: 'd', type: 'door', level_id: 'L', wall_id: 'w1', offset: 2, width: 0.9, height: 2.1, sill: 0 },
        { id: 'f', type: 'floor', level_id: 'L', polygon: [[0, 0], [6, 0], [6, 4]], holes: [[[1, 1], [2, 1], [2, 2]]], thickness: 0.2, z_offset: 0 },
        { id: 'x', type: 'decor', level_id: 'L', pos: [1, 1], z: 0.5, size: [1, 2, 3] }],
    }
    const c = convertUnits(p, 'cm')
    expect(c.units.name).toBe('cm')
    expect(c.elements[0].b).toEqual([600, 0])
    expect(c.elements[0].thickness).toBe(20)
    expect(c.elements[1].offset).toBe(200)
    expect(c.elements[2].holes[0][1]).toEqual([200, 100])
    expect(c.elements[3].size).toEqual([100, 200, 300])
    expect(c.levels[0].elevation).toBe(300)
    expect(c.editor.grid_size).toBe(100)
    expect(c.editor.snap_size).toBeNull()
    expect(convertUnits(c, 'm')).toEqual(p)
    expect(fromM(0.2, 'ft')).toBeCloseTo(0.656168)
    expect(UNITS.in.toM).toBe(0.0254)
  })
})

describe('history', () => {
  it('undo / redo and branch cut', () => {
    let h = histNew('a')
    h = histPush(h, 'b'); h = histPush(h, 'c')
    h = histUndo(h); expect(h.present).toBe('b')
    h = histUndo(h); expect(h.present).toBe('a')
    expect(histUndo(h)).toBe(h)                                 // nothing to undo
    h = histRedo(h); expect(h.present).toBe('b')
    h = histPush(h, 'z'); expect(h.future).toEqual([])
    expect(histRedo(h)).toBe(h)
  })
  it('coalesces rapid edits with the same key into one undo step', () => {
    let h = histNew(0)
    h = histPush(h, 1, 'k', 1000); h = histPush(h, 2, 'k', 1200); h = histPush(h, 3, 'k', 1400)
    expect(h.past).toEqual([0])
    h = histPush(h, 4, 'k', 3000)                               // pause > 900 ms -> new step
    expect(h.past).toEqual([0, 3])
    expect(histUndo(histUndo(h)).present).toBe(0)
  })
  it('is bounded', () => {
    let h = histNew(0)
    for (let i = 1; i <= 250; i++) h = histPush(h, i)
    expect(h.past.length).toBe(100)
  })
})

import { clampOpenings, handlesOf, moveHandle, wallExtensions } from './model.js'

describe('2D helpers', () => {
  it('extends wall ends at corners and T-junctions but not along a straight run', () => {
    const rect = [W('a', [0, 0], [6, 0]), W('b', [6, 0], [6, 4])]
    const e = wallExtensions(rect)
    expect(e.a).toEqual([0, 0.1]); expect(e.b).toEqual([0.1, 0])
    const line = wallExtensions([W('a', [0, 0], [2, 0]), W('b', [2, 0], [5, 0])])
    expect(line.a).toEqual([0, 0]); expect(line.b).toEqual([0, 0])
    const t = wallExtensions([W('host', [0, 0], [6, 0]), W('stub', [3, 0], [3, 2], { thickness: 0.3 })])
    expect(t.stub[0]).toBeCloseTo(0.1)
  })
  it('dragging a corner moves the connected wall too, and openings are re-clamped', () => {
    const els = [W('a', [0, 0], [6, 0]), W('b', [6, 0], [6, 4]), { id: 'd', type: 'door', level_id: 'L', wall_id: 'a', offset: 5.5, width: 0.9 }]
    const out = moveHandle(els, 'a', 1, [3, 0])
    expect(out.a.b).toEqual([3, 0]); expect(out.b.a).toEqual([3, 0])
    const merged = els.map((e) => out[e.id] || e)
    expect(clampOpenings(merged, 'a').find((e) => e.id === 'd').offset).toBeCloseTo(2.55)
    expect(handlesOf(els[0])).toEqual([[0, 0], [6, 0]])
    expect(moveHandle([{ id: 'f', type: 'floor', level_id: 'L', polygon: [[0, 0], [1, 0], [1, 1]] }], 'f', 2, [5, 5]).f.polygon[2]).toEqual([5, 5])
  })
})

import { applyModule, moduleFromElement, moduleFits, reapplyModule } from './model.js'

describe('modules', () => {
  const stone = { id: 'm1', kind: 'wall', name: 'Stone', defaults: { thickness: 0.6, material: 'mat_concrete' } }
  it('writes metre defaults converted to project units and respects overrides', () => {
    const w = { id: 'w', type: 'wall', level_id: 'L', a: [0, 0], b: [1, 0], thickness: 20, overrides: [] }
    expect(applyModule(w, stone, 'cm')).toMatchObject({ module: 'm1', thickness: 60, material: 'mat_concrete' })
    expect(applyModule({ ...w, overrides: ['thickness'] }, stone, 'cm').thickness).toBe(20)
    expect(moduleFits('wall', stone)).toBe(true); expect(moduleFits('door', stone)).toBe(false)
  })
  it('saves a module from an element in metres and edits touch only users of that module', () => {
    const w = { id: 'w', type: 'wall', level_id: 'L', thickness: 30, material: 'mat_x', overrides: [] }
    const m = moduleFromElement(w, 'wall', 'My wall', 'cm')
    expect(m.defaults).toEqual({ thickness: 0.3, material: 'mat_x' })
    const proj = { units: { name: 'cm' }, elements: [{ ...w, module: m.id }, { ...w, id: 'other', thickness: 99 }] }
    const out = reapplyModule(proj, m.id, { ...m, defaults: { thickness: 0.5 } })
    expect(out.elements[0].thickness).toBe(50)
    expect(out.elements[1]).toBe(proj.elements[1])           // same object: not rebuilt, not touched
  })
})

describe('circles and arcs', () => {
  it('builds a closed ring of connected walls on the circle', async () => {
    const { arcWalls, wallExtensions } = await import('./model.js')
    const ws = arcWalls({ c: [5, 5], r: 4, a0: 0, sweep: 2 * Math.PI }, 'L', 'm')
    expect(ws.length).toBeGreaterThanOrEqual(12)
    ws.forEach((w, i) => { expect(w.b).toEqual(ws[(i + 1) % ws.length].a); expect(Math.hypot(w.a[0] - 5, w.a[1] - 5)).toBeCloseTo(4, 5) })
    const n = ws.length
    const e = wallExtensions(ws)[ws[0].id][0]
    expect(e).toBeCloseTo(0.1 * Math.tan(Math.PI / n), 5)   // exact mitre, not t/2
  })
  it('arcThrough follows the points and detects collinear input', async () => {
    const { arcThrough, arcWalls } = await import('./model.js')
    const g = arcThrough([4, 0], [0, 4], [-4, 0])            // upper half circle, CCW
    expect(g.r).toBeCloseTo(4); expect(g.c[0]).toBeCloseTo(0); expect(g.sweep).toBeCloseTo(Math.PI)
    const h = arcThrough([4, 0], [0, -4], [-4, 0])           // lower half: clockwise
    expect(h.sweep).toBeCloseTo(-Math.PI)
    const ws = arcWalls(g, 'L', 'm')
    expect(ws[0].a[0]).toBeCloseTo(4); expect(ws[ws.length - 1].b[0]).toBeCloseTo(-4)
    expect(arcThrough([0, 0], [1, 1], [2, 2])).toBeNull()
  })
})

describe('floor/roof shapes', () => {
  it('rect and circle polygons; circle matches the wall ring vertices', async () => {
    const { shapePolygon, arcWalls } = await import('./model.js')
    expect(shapePolygon('rect', [0, 0], [4, 3], 'floor', 'm')).toEqual([[0, 0], [4, 0], [4, 3], [0, 3]])
    expect(shapePolygon('rect', [0, 0], [4, 0], 'floor', 'm')).toBeNull()
    const f = shapePolygon('circle', [5, 5], [9, 5], 'floor', 'm')
    const w = arcWalls({ c: [5, 5], r: 4, a0: 0, sweep: 2 * Math.PI }, 'L', 'm')
    expect(f.length).toBe(w.length)
    f.forEach((p, i) => expect(p).toEqual(w[i].a))
    expect(shapePolygon('circle', [5, 5], [9, 5], 'roof', 'm').length).toBeGreaterThanOrEqual(32)
  })
})

describe('wall face shapes', () => {
  it('builds rect / circle / arch / triangle / star polygons and rejects degenerate input', async () => {
    const m = await import('./model.js')
    expect(m.faceShapePolygon('rect', [3, 2], [1, 1])).toEqual([[1, 1], [3, 1], [3, 2], [1, 2]])
    expect(m.faceShapePolygon('rect', [1, 1], [1, 3])).toBeNull()
    expect(m.faceShapePolygon('circle', [0, 0], [0, 0])).toBeNull()
    const c = m.faceShapePolygon('circle', [5, 5], [6, 5]); expect(c.length).toBe(32)
    const a = m.faceShapePolygon('arch', [0, 0], [1, 2]); expect(Math.max(...a.map((p) => p[1]))).toBeCloseTo(2, 5); expect(a.length).toBeGreaterThan(8)
    expect(m.faceShapePolygon('triangle', [0, 0], [2, 1])).toEqual([[0, 0], [2, 0], [1, 1]])
    expect(m.faceShapePolygon('star', [0, 0], [1, 0]).length).toBe(10)
  })
  it('resizes via bounding boxes and generates battlements inside the wall length', async () => {
    const m = await import('./model.js')
    const out = m.fitPolyToBBox([[0, 0], [2, 0], [2, 1], [0, 1]], { x0: 0, y0: 0, x1: 2, y1: 1 }, { x0: 1, y0: 1, x1: 5, y1: 3 })
    expect(out).toEqual([[1, 1], [5, 1], [5, 3], [1, 3]])
    const fs = m.battlementFeatures(6, 3, 'm')
    expect(fs.length).toBeGreaterThanOrEqual(3)
    fs.forEach((f) => { const b = m.polyBBox(f.polygon); expect(b.x0).toBeGreaterThanOrEqual(0); expect(b.x1).toBeLessThanOrEqual(6); expect(f.kind).toBe('cut') })
    expect(m.frameFeatures({ x0: 0, y0: 0, x1: 2, y1: 2 }, 0.1, 0.03).length).toBe(4)
  })
})

describe('apply specs to all', () => {
  it('copies only the chosen specs, keeps positions, respects the scope and records overrides', async () => {
    const { applySpecsToAll } = await import('./model.js')
    const w = (id, lvl, len, t, h) => ({ id, type: 'wall', level_id: lvl, a: [0, 0], b: [len, 0], thickness: t, height: h })
    const els = [w('a', 'L0', 3, 0.3, 4), w('b', 'L0', 7, 0.1, 2), w('c', 'L1', 5, 0.1, 2), { id: 'd', type: 'door', level_id: 'L0', offset: 1, width: 1 }]
    const r = applySpecsToAll(els, els[0], ['thickness', 'height', 'a', 'b'], 'all')
    expect(r.count).toBe(2)
    const b = r.elements.find((e) => e.id === 'b')
    expect([b.thickness, b.height, b.b[0]]).toEqual([0.3, 4, 7])      // spec copied, length untouched
    expect(b.overrides).toEqual(expect.arrayContaining(['thickness', 'height']))
    expect(r.elements.find((e) => e.id === 'd')).toBe(els[3])         // other types untouched
    expect(applySpecsToAll(els, els[0], ['thickness'], 'level').count).toBe(1)
    expect(applySpecsToAll(els, els[0], ['thickness'], 'level').elements.find((e) => e.id === 'c').thickness).toBe(0.1)
  })
})
