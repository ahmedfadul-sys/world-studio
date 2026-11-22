import { describe, expect, it } from 'vitest'
import { buildPlaza, PLAZA_SHAPES, unitOutline } from './plaza.js'

const area = (poly) => Math.abs(poly.reduce((s, p, i) => { const q = poly[(i + 1) % poly.length]; return s + (p[0] * q[1] - q[0] * p[1]) }, 0) / 2)

describe('plaza', () => {
  it('every shape gives a valid outline', () => {
    for (const s of PLAZA_SHAPES) { const o = unitOutline(s, [[0, 0], [4, 0], [3, 5]]); expect(o.length, s).toBeGreaterThanOrEqual(3); expect(area(o), s).toBeGreaterThan(0.2) }
  })
  it('circle plaza: tiers step down outward, top is at the requested height, sizes match', () => {
    const els = buildPlaza({ shape: 'circle', width: 30, height: 0.9, tiers: 3, tierRun: 0.5, dais: { on: false }, columns: { n: 0 } }, [10, 5], 'L', 'm')
    const f = els.filter((e) => e.type === 'floor')
    expect(f.length).toBe(4)
    const top = f.find((e) => e.name === 'Plaza')
    expect(top.z_offset).toBeCloseTo(0.9, 6); expect(top.thickness).toBeCloseTo(0.9, 6)
    expect(area(top.polygon)).toBeGreaterThan(Math.PI * 14.9 ** 2 * 0.99); expect(area(top.polygon)).toBeLessThan(Math.PI * 15 ** 2)
    const tops = f.map((e) => e.z_offset); for (let i = 1; i < tops.length; i++) expect(tops[i]).toBeGreaterThan(tops[i - 1])    // outer → inner = low → high
    const areas = f.map((e) => area(e.polygon)); for (let i = 1; i < areas.length; i++) expect(areas[i]).toBeLessThan(areas[i - 1])
    const cx = top.polygon.reduce((s, p) => s + p[0], 0) / top.polygon.length
    expect(cx).toBeCloseTo(10, 1)
  })
  it('dais and columns', () => {
    const els = buildPlaza({ shape: 'octagon', width: 24, height: 0.6, tiers: 2, dais: { on: true, frac: 0.3, height: 0.8 }, columns: { n: 8, height: 5, frac: 0.9 } }, [0, 0], 'L', 'm')
    expect(els.filter((e) => e.name === 'Dais').length).toBe(1)
    expect(Math.max(...els.filter((e) => e.type === 'floor').map((e) => e.z_offset))).toBeCloseTo(1.4, 6)
    expect(els.filter((e) => e.type === 'column').length).toBe(8)
    expect(els.filter((e) => e.type === 'column').every((c) => c.height === 5.6 && c.shape === 'round')).toBe(true)
  })
  it('units are converted', () => {
    const els = buildPlaza({ shape: 'square', width: 10, height: 1, tiers: 0, dais: { on: false } }, [0, 0], 'L', 'cm')
    expect(els[0].z_offset).toBe(100); expect(Math.max(...els[0].polygon.map((p) => p[0]))).toBe(500)
  })
})
