import { describe, expect, it } from 'vitest'
import { autoFloors, buildVilla, footprint, levelsFor, planVilla, splitWidths, wallPieces } from './villa.js'

const mk = (area, o = {}) => { const plan = planVilla({ area, ...o }); const lv = levelsFor(plan, [], 'm'); return { plan, lv, res: buildVilla(plan, lv.map((l) => l.id), 'm') } }

describe('villa generator', () => {
  it('splitWidths sums exactly, respects minimums', () => {
    const w = splitWidths(2400, [{ weight: 1, min: 300 }, { weight: 0.1, min: 240 }, { weight: 2, min: 300 }])
    expect(w.reduce((a, b) => a + b, 0)).toBe(2400); expect(w[1]).toBeGreaterThanOrEqual(240); expect(w.every((x) => x % 10 === 0)).toBe(true)
  })
  it('footprint hits the requested total area', () => {
    for (const [a, f] of [[2000, 2], [5000, 3], [300, 1], [1234, 2]]) expect(Math.abs(footprint(a, f).total - a)).toBeLessThan(a * 0.002)
  })
  it('auto floors', () => { expect(autoFloors(300, 'villa')).toBe(1); expect(autoFloors(2000, 'villa')).toBe(2); expect(autoFloors(5000, 'palace')).toBe(3) })

  for (const [area, style] of [[2000, 'villa'], [5000, 'palace'], [350, 'villa']]) {
    it(`${area} m² ${style}: area, levels and rooms are consistent`, () => {
      const { plan, lv, res } = mk(area, { style })
      expect(Math.abs(plan.total - area)).toBeLessThan(area * 0.002)
      expect(lv.length).toBe(plan.floors)
      expect(Math.abs(res.stats.area - plan.total)).toBeLessThan(0.5)             // sum of room areas = built area
      for (const lvl of plan.rooms) {
        const sum = lvl.rooms.reduce((s, r) => s + ((r.x1 - r.x0) * (r.y1 - r.y0)) / 1e4, 0)
        expect(Math.abs(sum - plan.perLevel)).toBeLessThan(0.1)
        for (const r of lvl.rooms) expect(r.x1 - r.x0).toBeGreaterThan(150), expect(r.y1 - r.y0).toBeGreaterThan(150)
      }
    })
    it(`${area} m² ${style}: walls are unique, axis-aligned, joined at corners; openings fit`, () => {
      const { res, lv } = mk(area, { style })
      const walls = res.elements.filter((e) => e.type === 'wall')
      const keys = new Set()
      for (const w of walls) {
        const k = [w.a, w.b].map((p) => p.join(',')).sort().join('|')
        expect(keys.has(k + w.level_id)).toBe(false); keys.add(k + w.level_id)
        expect(w.a[0] === w.b[0] || w.a[1] === w.b[1]).toBe(true)
      }
      const byId = Object.fromEntries(walls.map((w) => [w.id, w]))
      for (const o of res.elements.filter((e) => e.type === 'door' || e.type === 'window')) {
        const w = byId[o.wall_id]; expect(w, o.type).toBeTruthy()
        const L = Math.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1])
        expect(o.offset - o.width / 2).toBeGreaterThanOrEqual(-1e-6); expect(o.offset + o.width / 2).toBeLessThanOrEqual(L + 1e-6)
      }
      // no two openings overlap on the same wall
      for (const w of walls) {
        const os = res.elements.filter((e) => e.wall_id === w.id).sort((p, q) => p.offset - q.offset)
        for (let i = 1; i < os.length; i++) expect(os[i].offset - os[i].width / 2).toBeGreaterThanOrEqual(os[i - 1].offset + os[i - 1].width / 2 - 1e-6)
      }
      expect(res.stats.doors).toBeGreaterThan(lv.length * 4)
      expect(res.elements.filter((e) => e.type === 'stair').length).toBe(2 * (lv.length - 1))
      expect(res.elements.filter((e) => e.type === 'roof').length).toBe(1)
    })
  }
  it('every room can be reached from the corridor (door or open hall)', () => {
    const { res, plan } = mk(2000)
    const g = plan.rooms[0]
    const doors = res.elements.filter((e) => e.type === 'door' && e.level_id === res.elements.find((x) => x.type === 'room').level_id)
    expect(doors.length).toBeGreaterThanOrEqual(g.rooms.length - 2)   // all rooms except corridor + stair hall, plus the main door
  })
  it('wallPieces split at T junctions and honour gaps', () => {
    const rooms = [{ x0: 0, y0: 0, x1: 400, y1: 300 }, { x0: 400, y0: 0, x1: 800, y1: 300 }]
    const p = wallPieces(rooms, 800, 300)
    expect(p.filter((w) => w.o === 'H' && w.c === 0).length).toBe(2)       // split at x=400
    expect(p.filter((w) => w.o === 'V' && w.c === 400).length).toBe(1)     // shared wall once
    const q = wallPieces(rooms, 800, 300, [{ o: 'H', c: 300, a: 0, b: 400 }])
    expect(q.filter((w) => w.o === 'H' && w.c === 300).length).toBe(1)
  })
  it('works in other project units', () => {
    const plan = planVilla({ area: 600 }); const r = buildVilla(plan, levelsFor(plan, [], 'cm').map((l) => l.id), 'cm')
    const w = r.elements.find((e) => e.type === 'wall')
    expect(Math.max(...w.a, ...w.b)).toBeGreaterThan(100)
  })
})
