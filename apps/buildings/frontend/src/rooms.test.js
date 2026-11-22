import { describe, expect, it } from 'vitest'
import { mergeRooms, splitRoom, unionPolygons } from './rooms.js'
import { buildVilla, planVilla, levelsFor } from './villa.js'
import { makeElement } from './model.js'

const W = (a, b) => makeElement('wall', 'L', 'm', { a, b, thickness: 0.15 })
const R = (poly) => makeElement('room', 'L', 'm', { polygon: poly, room_type: 'generic' })
const area = (p) => Math.abs(p.reduce((s, a, i) => { const b = p[(i + 1) % p.length]; return s + a[0] * b[1] - b[0] * a[1] }, 0) / 2)

describe('rooms', () => {
  it('union of two adjacent rectangles', () => {
    const u = unionPolygons([[0, 0], [4, 0], [4, 3], [0, 3]], [[4, 0], [9, 0], [9, 3], [4, 3]])
    expect(u.length).toBe(4); expect(area(u)).toBeCloseTo(27, 6)
  })
  it('merge removes the shared wall and its door, keeps the rest', () => {
    const a = R([[0, 0], [4, 0], [4, 3], [0, 3]]), b = R([[4, 0], [9, 0], [9, 3], [4, 3]])
    const mid = W([4, 0], [4, 3]), other = W([0, 0], [4, 0])
    const door = makeElement('door', 'L', 'm', { wall_id: mid.id, offset: 1.5 })
    const r = mergeRooms([a, b, mid, other, door], a.id, b.id, 'm')
    expect(r.removedWalls).toBe(1)
    expect(r.elements.map((e) => e.type).sort()).toEqual(['room', 'wall'])
    expect(area(r.elements.find((e) => e.type === 'room').polygon)).toBeCloseTo(27, 6)
  })
  it('merge fails for rooms that do not touch', () => {
    const a = R([[0, 0], [2, 0], [2, 2], [0, 2]]), b = R([[5, 0], [7, 0], [7, 2], [5, 2]])
    expect(mergeRooms([a, b], a.id, b.id, 'm')).toBeNull()
  })
  it('split makes two rooms, a wall with a door, and splits the boundary walls', () => {
    const r = R([[0, 0], [8, 0], [8, 4], [0, 4]])
    const fl = makeElement('floor', 'L', 'm', { polygon: [[0, 0], [8, 0], [8, 4], [0, 4]] })
    const ws = [W([0, 0], [8, 0]), W([8, 0], [8, 4]), W([8, 4], [0, 4]), W([0, 4], [0, 0])]
    const s = splitRoom([r, fl, ...ws], r.id, 'x', 3, 'm')
    expect(s.elements.filter((e) => e.type === 'floor').map((q) => area(q.polygon)).sort()).toEqual([12, 20])
    const mm = mergeRooms(s.elements, s.roomIds[0], s.roomIds[1], 'm')
    expect(mm.elements.filter((e) => e.type === 'floor').length).toBe(1)
    const rooms = s.elements.filter((e) => e.type === 'room')
    expect(rooms.length).toBe(2); expect(rooms.map((q) => area(q.polygon)).sort()).toEqual([12, 20])
    expect(s.elements.filter((e) => e.type === 'wall').length).toBe(7)
    expect(s.elements.filter((e) => e.type === 'door').length).toBe(1)
    const cut = s.elements.filter((e) => e.type === 'wall').find((w) => w.a[0] === 3 && w.b[0] === 3 && w.a[1] === 0 && w.b[1] === 4)
    expect(cut).toBeTruthy()
  })
  it('split then merge round trip on a generated villa room', () => {
    const plan = planVilla({ area: 2000, style: 'villa', floors: 0, aspect: 1.5 })
    const levels = levelsFor(plan, [], 'm')
    const res = buildVilla(plan, levels.map((l) => l.id), 'm', { label: (x) => x })
    const room = res.elements.find((e) => e.type === 'room' && area(e.polygon) > 30)
    const xs = room.polygon.map((p) => p[0])
    const s = splitRoom(res.elements, room.id, 'x', (Math.min(...xs) + Math.max(...xs)) / 2, 'm')
    expect(s.elements.filter((e) => e.type === 'room').length).toBe(res.elements.filter((e) => e.type === 'room').length + 1)
    const m = mergeRooms(s.elements, s.roomIds[0], s.roomIds[1], 'm')
    expect(m.elements.filter((e) => e.type === 'room').length).toBe(res.elements.filter((e) => e.type === 'room').length)
  })
})
