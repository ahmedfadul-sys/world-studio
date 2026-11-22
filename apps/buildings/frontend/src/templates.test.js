import { describe, expect, it } from 'vitest'
import { activeFields, applyTemplate, BUILTIN, templateFromElement, templatesFor, TPL_KEYS } from './templates.js'
import { makeElement } from './model.js'

const proj = (unit = 'm', extra = {}) => ({ units: { name: unit }, materials: [{ id: 'mat_plaster' }, { id: 'mat_concrete' }], templates: [], ...extra })

describe('templates', () => {
  it('built-ins only use keys allowed for their type', () => {
    for (const b of BUILTIN) for (const k of Object.keys(b.props)) expect(TPL_KEYS[b.type], b.id).toContain(k)
  })
  it('lengths are converted to project units, non-lengths are not', () => {
    const w = templatesFor(proj('cm'), 'wall').find((x) => x.id === 'b_wall_part')
    expect(w.props.thickness).toBe(10); expect(w.props.height).toBe(240)
    const r = templatesFor(proj('cm'), 'roof').find((x) => x.id === 'b_roof_gable')
    expect(r.props.pitch_deg).toBe(30); expect(r.props.overhang).toBe(40)
  })
  it('active template fields skip unknown materials', () => {
    const p = proj('m', { materials: [], templates: [{ id: 't1', name: 'x', type: 'wall', props: { thickness: 0.4, material: 'mat_gone' } }] })
    expect(activeFields(p, { wall: 't1' }, 'wall')).toEqual({ thickness: 0.4 })
    expect(activeFields(p, {}, 'wall')).toEqual({})
  })
  it('saves from an element and applies to selection of the same type only', () => {
    const w = makeElement('wall', 'L1', 'm', { a: [0, 0], b: [3, 0], thickness: 0.35, height: 3.1 })
    const t = templateFromElement(w, ' Thick ', 't9')
    expect(t.props).toMatchObject({ thickness: 0.35, height: 3.1 }); expect(t.name).toBe('Thick')
    const w2 = makeElement('wall', 'L1', 'm', { a: [0, 1], b: [3, 1] }), c = makeElement('column', 'L1', 'm', { pos: [1, 1] })
    const r = applyTemplate([w2, c], [w2.id, c.id], t)
    expect(r.count).toBe(1); expect(r.elements[0].thickness).toBe(0.35); expect(r.elements[0].overrides).toContain('height')
    expect(r.elements[1]).toBe(c)
  })
})
