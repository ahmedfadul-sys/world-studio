import { describe, expect, it } from 'vitest'
import { DxfError, dxfToWalls, parseDxf } from './dxf.js'

const dxf = (header, ents) => `0\nSECTION\n2\nHEADER\n${header}0\nENDSEC\n0\nSECTION\n2\nENTITIES\n${ents}0\nENDSEC\n0\nEOF\n`
const line = (a, b, layer = 'WALLS') => `0\nLINE\n8\n${layer}\n10\n${a[0]}\n20\n${a[1]}\n30\n0\n11\n${b[0]}\n21\n${b[1]}\n31\n0\n`
const lw = (pts, closed, layer = 'WALLS', bulges = []) => `0\nLWPOLYLINE\n8\n${layer}\n90\n${pts.length}\n70\n${closed ? 1 : 0}\n${pts.map((p, i) => `10\n${p[0]}\n20\n${p[1]}\n${bulges[i] ? `42\n${bulges[i]}\n` : ''}`).join('')}`
const opts = { fromUnit: 'm', levelId: 'lvl_0', unit: 'm', thickness: 0.2 }

describe('DXF import', () => {
  it('reads LINE entities and layers', () => {
    const p = parseDxf(dxf('', line([0, 0], [4, 0]) + line([4, 0], [4, 3]) + line([0, 0], [0, 1], 'FURN')))
    expect(p.entities).toHaveLength(3)
    expect(p.layers).toEqual({ WALLS: 2, FURN: 1 })
    const r = dxfToWalls(p, { ...opts, layers: new Set(['WALLS']) })
    expect(r.walls).toHaveLength(2)
    expect(r.walls[0]).toMatchObject({ type: 'wall', thickness: 0.2, level_id: 'lvl_0' })
  })
  it('closed LWPOLYLINE becomes a closed wall loop', () => {
    const p = parseDxf(dxf('', lw([[0, 0], [5, 0], [5, 4], [0, 4]], true)))
    const r = dxfToWalls(p, opts)
    expect(r.walls).toHaveLength(4)
    expect(r.walls[3].b).toEqual(r.walls[0].a)
  })
  it('scales from the drawing unit (INSUNITS in header) and moves to the origin', () => {
    const p = parseDxf(dxf('9\n$INSUNITS\n70\n4\n', line([1000, 2000], [5000, 2000])))
    expect(p.units).toBe('mm')
    const r = dxfToWalls(p, { ...opts, fromUnit: p.units })
    expect(r.walls[0].a).toEqual([0, 0])
    expect(r.walls[0].b).toEqual([4, 0])
    const keep = dxfToWalls(p, { ...opts, fromUnit: 'mm', origin: false })
    expect(keep.walls[0].a).toEqual([1, 2])
  })
  it('circles and arcs become short chords; bulged polylines too', () => {
    const c = parseDxf(dxf('', '0\nCIRCLE\n8\nC\n10\n0\n20\n0\n40\n3\n'))
    const rc = dxfToWalls(c, opts)
    expect(rc.walls.length).toBeGreaterThanOrEqual(12)
    for (const w of rc.walls) expect(Math.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1])).toBeLessThanOrEqual(1.6)
    const b = parseDxf(dxf('', lw([[0, 0], [2, 0]], false, 'W', [1])))   // bulge 1 = half circle of radius 1
    expect(b.entities[0].t).toBe('arc')
    expect(b.entities[0].r).toBeCloseTo(1, 6)
    expect(b.entities[0].c[0]).toBeCloseTo(1, 6)
    const rb = dxfToWalls(b, { ...opts, origin: false })
    for (const w of rb.walls) for (const q of [w.a, w.b]) expect(Math.hypot(q[0] - 1, q[1])).toBeCloseTo(1, 4)
    expect(Math.min(...rb.walls.flatMap((w) => [w.a[1], w.b[1]]))).toBeCloseTo(-1, 2)   // +bulge = counter-clockwise: the arc swings below the chord
  })
  it('joins near ends, drops tiny and duplicate segments', () => {
    const p = parseDxf(dxf('', line([0, 0], [4, 0]) + line([4.004, 0], [4.004, 3]) + line([0, 0], [4, 0]) + line([1, 1], [1.01, 1])))
    const r = dxfToWalls(p, { ...opts, snap: 0.02, minLen: 0.05 })
    expect(r.walls).toHaveLength(2)
    expect(r.walls[0].b).toEqual(r.walls[1].a)
    expect(r.dropped).toBe(2)
  })
  it('reports binary / empty files', () => {
    expect(() => parseDxf('AutoCAD Binary DXF\r\n\x1a\0')).toThrow(DxfError)
    expect(() => parseDxf(dxf('', ''))).toThrow(DxfError)
  })
  it('counts what it cannot read', () => {
    const p = parseDxf(dxf('', line([0, 0], [1, 0]) + '0\nINSERT\n8\n0\n2\nDOOR\n10\n0\n20\n0\n'))
    expect(p.skipped).toEqual({ INSERT: 1 })
  })
})
