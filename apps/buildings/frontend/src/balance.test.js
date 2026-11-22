import { describe, expect, it } from 'vitest'
import { applyOverrides, attachedWalls, balanceChain, balanceSnap, divideWall, setWallLength, wallChain } from './plan.js'
import { makeElement, wallLength } from './model.js'

const W = (a, b, extra = {}) => makeElement('wall', 'L1', 'm', { a, b, ...extra })

describe('length balancing', () => {
  it('divideWall makes n equal linked walls and re-hosts openings', () => {
    const w = W([0, 0], [500, 0]); const d = makeElement('door', 'L1', 'm', { wall_id: w.id, offset: 420, width: 90 })
    const out = divideWall([w, d], w.id, 4)
    const ws = out.filter((e) => e.type === 'wall')
    expect(ws.length).toBe(4); ws.forEach((x) => expect(wallLength(x)).toBeCloseTo(125, 5))
    for (let i = 1; i < 4; i++) expect(ws[i].a).toEqual(ws[i - 1].b)
    const door = out.find((e) => e.type === 'door')
    expect(door.wall_id).toBe(ws[3].id); expect(door.offset).toBeCloseTo(420 - 375, 5)
    expect(divideWall([w], w.id, 1)).toEqual([w])
  })
  it('balanceSnap pulls the shared point onto the equal-length position (200 | 200)', () => {
    const a = W([0, 0], [200, 0]), b = W([200, 0], [400, 0])
    const r = balanceSnap([a, b], 'L1', [200, 0], [203, 40], 10)
    expect(r.balanced).toBe(true); expect(r.lengths[0]).toBeCloseTo(r.lengths[1], 6); expect(r.p[0]).toBeCloseTo(200, 6)
    const far = balanceSnap([a, b], 'L1', [200, 0], [260, 0], 10)
    expect(far.balanced).toBe(false); expect(far.lengths[0]).toBeCloseTo(260, 6); expect(far.lengths[1]).toBeCloseTo(140, 6)
    expect(balanceSnap([a], 'L1', [200, 0], [210, 0], 10).lengths).toBeNull()
  })
  it('balanceChain equalises a collinear chain and drags attached elements', () => {
    const a = W([0, 0], [100, 0]), b = W([100, 0], [350, 0]), c = W([350, 0], [400, 0]), side = W([100, 0], [100, 80])
    const els = [a, b, c, side]
    const o = balanceChain(els, [a.id, b.id, c.id])
    const res = applyOverrides(els, o)
    const lens = [a, b, c].map((x) => wallLength(res.find((e) => e.id === x.id)))
    lens.forEach((l) => expect(l).toBeCloseTo(400 / 3, 4))
    expect(res.find((e) => e.id === side.id).a[0]).toBeCloseTo(400 / 3, 4)   // a wall attached to the moved point follows
  })
  it('wallChain rejects loops, gaps and branches', () => {
    const a = W([0, 0], [1, 0]), b = W([1, 0], [1, 1]), c = W([1, 1], [0, 0]), g = W([5, 5], [6, 5])
    expect(wallChain([a, b, c], [a.id, b.id, c.id])).toBeNull()
    expect(wallChain([a, g], [a.id, g.id])).toBeNull()
    expect(wallChain([a, b], [a.id, b.id]).points.length).toBe(3)
    expect(balanceChain([a, b, c], [a.id, b.id, c.id])).toEqual({})
  })
  it('setWallLength moves the end along the wall and drags what is attached', () => {
    const a = W([0, 0], [500, 0]), n = W([500, 0], [500, 300])
    const res = applyOverrides([a, n], setWallLength([a, n], a.id, 400))
    expect(res[0].b).toEqual([400, 0]); expect(res[1].a).toEqual([400, 0]); expect(attachedWalls(res, 'L1', [400, 0]).length).toBe(2)
    expect(setWallLength([a], a.id, -1)).toEqual({})
  })
})
