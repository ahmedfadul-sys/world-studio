import { describe, expect, it } from 'vitest'
import { LAB_DEFAULTS, LAB_PRESETS, LAB_USES, presetParams } from './labPresets.js'

describe('lab presets', () => {
  it('every preset has full, valid defaults', () => {
    for (const k of LAB_PRESETS) {
      const d = LAB_DEFAULTS[k], p = presetParams(k)
      expect(d, k).toBeTruthy()
      expect(p.preset).toBe(k)
      expect(d.color1).toMatch(/^#[0-9a-f]{6}$/i)
      expect(d.scale).toBeGreaterThanOrEqual(1); expect(d.scale).toBeLessThanOrEqual(16)
      expect(d.tile_m).toBeGreaterThanOrEqual(0.1); expect(d.tile_m).toBeLessThanOrEqual(20)
      expect([256, 512, 1024, 2048]).toContain(d.resolution)
      expect(LAB_USES[k]).toBeTruthy()
    }
  })
  it('tile scale is even and resolution is kept on switch', () => {
    expect(LAB_DEFAULTS.tile.scale % 2).toBe(0)
    expect(presetParams('wood', { resolution: 2048 }).resolution).toBe(2048)
  })
})
