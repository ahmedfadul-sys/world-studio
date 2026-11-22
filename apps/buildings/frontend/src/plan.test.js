import { describe, expect, it } from 'vitest'
import { dist, makeElement, wallLength } from './model.js'
import {
  anchorOrigin, calibrateUnderlay, centredUnderlay, underlayCorners, underlayHeight, applyOverrides, arrayLinear, arrayPolar, buildRoomParts, cloneElements, edgeMovePairs, fitStairSteps, linkedMove,
  parseDimInput, pointByDim, rectInfo, remapPoints, resizeRect, roomElements, stairFlights,
} from './plan.js'

const L = 'lvl_0'
const room = (x = 0, y = 0, w = 4, d = 3, existing = []) => roomElements({ type: 'living', name: 'Living 1', w, d, x, y, door: true, ceiling: false }, L, 'm', existing)

describe('room wizard', () => {
  it('creates 4 closed walls, a floor, a named room and a door', () => {
    const els = room()
    const t = (k) => els.filter((e) => e.type === k)
    expect(t('wall')).toHaveLength(4)
    expect(t('floor')).toHaveLength(1)
    expect(t('room')[0].name).toBe('Living 1')
    expect(t('room')[0].room_type).toBe('living')
    expect(t('door')).toHaveLength(1)
    const w = t('wall')
    for (let i = 0; i < 4; i++) expect(dist(w[i].b, w[(i + 1) % 4].a)).toBe(0)   // closed loop
    expect(t('door')[0].wall_id).toBe(w[0].id)
  })
  it('does not duplicate walls shared with a neighbouring room', () => {
    const a = room(0, 0, 4, 3)
    const b = room(4, 0, 4, 3, a)
    expect(b.filter((e) => e.type === 'wall')).toHaveLength(3)    // the shared wall x=4 already exists
    expect(b.find((e) => e.type === 'room').polygon[0]).toEqual([4, 0])
  })
  it('anchor corner decides where the room goes', () => {
    expect(anchorOrigin('sw', [5, 5], 4, 2)).toEqual([5, 5])
    expect(anchorOrigin('ne', [5, 5], 4, 2)).toEqual([1, 3])
    expect(anchorOrigin('se', [5, 5], 4, 2)).toEqual([1, 5])
  })
  it('detects rectangles', () => {
    expect(rectInfo([[0, 0], [4, 0], [4, 3], [0, 3]])).toMatchObject({ w: 4, d: 3 })
    expect(rectInfo([[0, 0], [4, 0], [4, 3], [1, 3]])).toBeNull()
    expect(rectInfo([[0, 0], [4, 0], [2, 3]])).toBeNull()
  })
  it('builds missing walls / floor for an outline-only room', () => {
    const r = makeElement('room', L, 'm', { polygon: [[0, 0], [5, 0], [5, 5], [0, 5]], name: 'X' })
    const parts = buildRoomParts([r], r.id, 'm')
    expect(parts.filter((p) => p.type === 'wall')).toHaveLength(4)
    expect(parts.filter((p) => p.type === 'floor')).toHaveLength(1)
    expect(buildRoomParts([r, ...parts], r.id, 'm')).toHaveLength(0)   // idempotent
  })
})

describe('linked editing', () => {
  it('dragging a corner moves both walls, the floor and the room', () => {
    const els = room()
    const room0 = els.find((e) => e.type === 'room')
    const o = linkedMove(els, room0.id, 2, [5, 4])     // corner (4,3) -> (5,4)
    const out = applyOverrides(els, o)
    expect(out.find((e) => e.type === 'room').polygon[2]).toEqual([5, 4])
    expect(out.find((e) => e.type === 'floor').polygon[2]).toEqual([5, 4])
    const walls = out.filter((e) => e.type === 'wall')
    expect(walls.filter((w) => dist(w.a, [5, 4]) < 1e-9 || dist(w.b, [5, 4]) < 1e-9)).toHaveLength(2)
    expect(walls.every((w) => !(dist(w.a, [4, 3]) < 1e-9 || dist(w.b, [4, 3]) < 1e-9))).toBe(true)
  })
  it('dragging a wall end drags the room outline and floor too', () => {
    const els = room()
    const w0 = els.find((e) => e.type === 'wall')
    const out = applyOverrides(els, linkedMove(els, w0.id, 1, [4, -1]))
    expect(out.find((e) => e.type === 'room').polygon[1]).toEqual([4, -1])
  })
  it('moving a side keeps it parallel', () => {
    const els = room()
    const rm = els.find((e) => e.type === 'room')
    const pairs = edgeMovePairs(rm.polygon, 1, [6, 1.5])    // right side x=4 -> x=6
    const out = applyOverrides(els, remapPoints(els, L, pairs))
    expect(out.find((e) => e.type === 'room').polygon).toEqual([[0, 0], [6, 0], [6, 3], [0, 3]])
  })
  it('resizing a room by width x depth stretches walls, keeps the door relative position', () => {
    const els = room()
    const rm = els.find((e) => e.type === 'room')
    const door = els.find((e) => e.type === 'door')
    const out = applyOverrides(els, resizeRect(els, rm.id, 6, 5))
    expect(rectInfo(out.find((e) => e.type === 'room').polygon)).toMatchObject({ w: 6, d: 5 })
    expect(rectInfo(out.find((e) => e.type === 'floor').polygon)).toMatchObject({ w: 6, d: 5 })
    const host = out.find((e) => e.id === door.wall_id)
    expect(wallLength(host)).toBe(6)
    expect(out.find((e) => e.id === door.id).offset).toBeCloseTo(3, 6)   // was centred, stays centred
  })
})

describe('copy and arrays', () => {
  it('clones with new ids, remaps hosts and carries openings along', () => {
    const els = room()
    const walls = els.filter((e) => e.type === 'wall').map((w) => w.id)
    const c = cloneElements(els, walls, { dx: 10, dy: 0 })
    expect(c).toHaveLength(5)    // 4 walls + their door
    expect(new Set(c.map((e) => e.id)).size).toBe(5)
    expect(c.every((e) => !els.some((o) => o.id === e.id))).toBe(true)
    const d = c.find((e) => e.type === 'door')
    expect(c.find((e) => e.id === d.wall_id).a[0]).toBeGreaterThanOrEqual(10)
  })
  it('linear array makes count copies at multiples of the step', () => {
    const col = makeElement('column', L, 'm', { pos: [1, 1] })
    const out = arrayLinear([col], [col.id], { count: 3, dx: 2, dy: 0 })
    expect(out.map((e) => e.pos)).toEqual([[3, 1], [5, 1], [7, 1]])
  })
  it('polar array of columns lies on one circle', () => {
    const col = makeElement('column', L, 'm', { pos: [5, 0] })
    const out = arrayPolar([col], [col.id], { count: 6, center: [0, 0] })
    expect(out).toHaveLength(5)
    for (const e of out) expect(Math.hypot(e.pos[0], e.pos[1])).toBeCloseTo(5, 5)
    expect(out[2].pos[0]).toBeCloseTo(-5, 5)    // 3 steps of 60 degrees
  })
  it('copies to another level and rotates stairs', () => {
    const st = makeElement('stair', L, 'm', { start: [0, 0], angle_deg: 10 })
    const [c] = cloneElements([st], [st.id], { rotDeg: 90, center: [0, 0], levelId: 'lvl_1' })
    expect(c.level_id).toBe('lvl_1')
    expect(c.angle_deg).toBe(100)
  })
})

describe('stairs', () => {
  it('fits steps to the storey height', () => {
    expect(fitStairSteps(3, 0.18)).toEqual({ steps: 17, rise: 0.176471 })
    const f = fitStairSteps(2.8, 0.17)
    expect(f.steps * f.rise).toBeCloseTo(2.8, 5)
  })
  it('L and U stairs have two flights summing to the full height plus a landing', () => {
    for (const kind of ['L', 'U']) {
      const [a, b, slab] = stairFlights(kind, { start: [0, 0], angleDeg: 0, width: 1, height: 3, rise: 0.18, run: 0.28 }, L, 'm')
      expect(a.steps + b.steps).toBe(17)
      expect(b.z_offset).toBeCloseTo(a.steps * a.rise, 5)
      expect((b.z_offset) + b.steps * b.rise).toBeCloseTo(3, 4)
      expect(slab.type).toBe('floor')
      expect(slab.z_offset).toBeCloseTo(b.z_offset, 5)
    }
  })
})

describe('typed dimensions', () => {
  it('parses lengths, angles and sizes (also Arabic digits)', () => {
    expect(parseDimInput('4.5')).toEqual({ kind: 'len', len: 4.5, ang: null })
    expect(parseDimInput('4.5<30')).toEqual({ kind: 'len', len: 4.5, ang: 30 })
    expect(parseDimInput('4,30')).toEqual({ kind: 'len', len: 4, ang: 30 })
    expect(parseDimInput('4x3')).toEqual({ kind: 'wh', w: 4, h: 3 })
    expect(parseDimInput('٤٫٥')).toEqual({ kind: 'len', len: 4.5, ang: null })
    expect(parseDimInput('4.')).toBeNull
    expect(parseDimInput('abc')).toBeNull()
    expect(parseDimInput('')).toBeNull()
  })
  it('places the point along the angle or towards the cursor', () => {
    expect(pointByDim([1, 1], 2, 90)).toEqual([1, 3])
    expect(pointByDim([0, 0], 5, null, [10, 0])).toEqual([5, 0])
    expect(pointByDim([0, 0], 5, null, [0, -3])).toEqual([0, -5])
  })
})

describe('underlays', () => {
  const u = { x: 0, y: 10, width: 12, px_w: 1200, px_h: 800, rotation_deg: 0 }
  it('corners follow the pixel aspect ratio', () => {
    expect(underlayHeight(u)).toBe(8)
    expect(underlayCorners(u)).toEqual([[0, 10], [12, 10], [12, 2], [0, 2]])
    const r = underlayCorners({ ...u, rotation_deg: 90 })
    expect(r[1][0]).toBeCloseTo(0, 5); expect(r[1][1]).toBeCloseTo(22, 5)
  })
  it('is centred on a point', () => {
    expect(centredUnderlay([6, 4], 12, 1200, 800)).toEqual({ x: 0, y: 8 })
  })
  it('calibration scales about the first point so it stays put', () => {
    const p1 = [1, 9], p2 = [7, 9]           // 6 units on screen that really are 10
    const c = calibrateUnderlay(u, p1, p2, 10)
    expect(c.width).toBeCloseTo(20, 5)
    // the point on the image that was under p1 is still under p1
    const k = c.width / u.width
    expect(c.x + (p1[0] - u.x) * k).toBeCloseTo(p1[0], 5)
    expect(c.y + (p1[1] - u.y) * k).toBeCloseTo(p1[1], 5)
  })
  it('can straighten a crooked scan', () => {
    const c = calibrateUnderlay(u, [0, 0], [5, 5], Math.hypot(5, 5), 'h')   // a 45-degree line should become horizontal
    expect(c.rotation_deg).toBeCloseTo(-45, 5)
    expect(c.width).toBeCloseTo(12, 5)
  })
})
