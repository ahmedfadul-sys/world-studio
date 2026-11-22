import { describe, expect, it } from 'vitest'
import { clearDebris, clipHalfPlane, isDebris, rng, ruinElements } from './ruin.js'
import { planVilla, buildVilla, levelsFor } from './villa.js'

const house = () => { const plan = planVilla({ area: 800 }); const lv = levelsFor(plan, [], 'm'); return { lv, els: buildVilla(plan, lv.map((l) => l.id), 'm').elements } }
const count = (els, t) => els.filter((e) => e.type === t).length

describe('ruin', () => {
  it('rng is deterministic', () => { const a = rng(5), b = rng(5); expect([a(), a(), a()]).toEqual([b(), b(), b()]) })
  it('clipHalfPlane keeps one side', () => {
    const sq = [[0, 0], [4, 0], [4, 4], [0, 4]]
    const r = clipHalfPlane(sq, [0, 0], [1, 0], 2)
    expect(Math.max(...r.map((p) => p[0]))).toBe(2); expect(r.length).toBe(4)
    expect(clipHalfPlane(sq, [0, 0], [1, 0], -1)).toEqual([])
  })
  it('is deterministic per seed and differs between seeds', () => {
    const { lv, els } = house()
    const a = ruinElements(els, { unit: 'm', levels: lv, seed: 7 }), b = ruinElements(els, { unit: 'm', levels: lv, seed: 7 }), c = ruinElements(els, { unit: 'm', levels: lv, seed: 8 })
    expect(JSON.stringify(a.elements.map((e) => e.type + (e.height ?? '')))).toBe(JSON.stringify(b.elements.map((e) => e.type + (e.height ?? ''))))
    expect(a.stats.removedWalls + a.stats.loweredWalls).toBeGreaterThan(0)
    expect(JSON.stringify(c.stats)).not.toBe(JSON.stringify(a.stats))
  })
  it('cuts walls, lowers heights, drops roof/floors and adds debris near the building', () => {
    const { lv, els } = house()
    const r = ruinElements(els, { unit: 'm', levels: lv, seed: 3, severity: 0.8, debris: 1, cutAngle: 0, cutOffset: 0 })
    expect(count(r.elements, 'wall')).toBeGreaterThan(0); expect(r.stats.removedWalls).toBeGreaterThan(5)
    expect(r.elements.some((e) => e.type === 'wall' && e.height && e.height < 3)).toBe(true)
    expect(count(r.elements, 'roof')).toBe(0)
    expect(r.stats.debris).toBeGreaterThan(10); expect(r.elements.filter(isDebris).length).toBe(r.stats.debris)
    expect(clearDebris(r.elements).length).toBe(r.elements.length - r.stats.debris)
    // every opening still points at a living wall, and inside it
    const w = Object.fromEntries(r.elements.filter((e) => e.type === 'wall').map((x) => [x.id, x]))
    for (const o of r.elements.filter((e) => ['door', 'window', 'opening'].includes(e.type))) {
      expect(w[o.wall_id], o.type).toBeTruthy()
      expect(o.sill || 0).toBeLessThan((w[o.wall_id].height ?? 3) + 1e-6)
      expect((o.sill || 0) + o.height).toBeLessThanOrEqual((w[o.wall_id].height ?? 3) - 0.05)
      expect(o.offset - o.width / 2).toBeGreaterThanOrEqual(0); expect(o.offset + o.width / 2).toBeLessThanOrEqual(Math.hypot(w[o.wall_id].b[0] - w[o.wall_id].a[0], w[o.wall_id].b[1] - w[o.wall_id].a[1]) + 1e-6)
    }
  })
  it('upper levels lose more than the ground; ground floor and walls near the cut remain as stumps', () => {
    const { lv, els } = house()
    const r = ruinElements(els, { unit: 'm', levels: lv, seed: 4, severity: 0.7, cutAngle: 90, cutOffset: 0 })
    const per = (id) => r.elements.filter((e) => e.type === 'wall' && e.level_id === id).length
    const before = (id) => els.filter((e) => e.type === 'wall' && e.level_id === id).length
    expect(per(lv[1].id) / before(lv[1].id)).toBeLessThan(per(lv[0].id) / before(lv[0].id) + 0.25)
    expect(r.elements.filter((e) => e.type === 'floor' && e.level_id === lv[0].id).length).toBe(els.filter((e) => e.type === 'floor' && e.level_id === lv[0].id).length)
  })
  it('selection scope leaves other elements untouched', () => {
    const { lv, els } = house()
    const ids = new Set(els.filter((e) => e.level_id === lv[1].id).map((e) => e.id))
    const r = ruinElements(els, { unit: 'm', levels: lv, seed: 2, severity: 0.9, ids })
    const g0 = els.filter((e) => e.level_id === lv[0].id), g1 = r.elements.filter((e) => e.level_id === lv[0].id && !isDebris(e))
    expect(JSON.stringify(g1)).toBe(JSON.stringify(g0))
  })
})
