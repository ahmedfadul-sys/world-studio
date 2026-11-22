// Element templates: built-in presets (metres, converted to project units) + user templates saved in the project.
import { fromM, patchElement } from './model.js'

export const TPL_TYPES = ['wall', 'door', 'window', 'opening', 'column', 'beam', 'floor', 'roof', 'stair']
export const TPL_KEYS = {
  wall: ['thickness', 'height', 'material', 'material_inner'], door: ['width', 'height', 'sill', 'material'], window: ['width', 'height', 'sill', 'material'],
  opening: ['width', 'height', 'sill'], column: ['shape', 'width', 'depth', 'height', 'material'], beam: ['width', 'depth', 'material'],
  floor: ['thickness', 'material'], roof: ['kind', 'pitch_deg', 'overhang', 'thickness', 'material'], stair: ['width', 'rise', 'run', 'steps', 'material'],
}
const LEN = new Set(['thickness', 'height', 'width', 'depth', 'sill', 'overhang', 'rise', 'run'])

// id → {type, props in metres}
export const BUILTIN = [
  { id: 'b_wall_ext', type: 'wall', props: { thickness: 0.3, material: 'mat_plaster' } },
  { id: 'b_wall_int', type: 'wall', props: { thickness: 0.15, material: 'mat_plaster' } },
  { id: 'b_wall_part', type: 'wall', props: { thickness: 0.1, height: 2.4, material: 'mat_plaster' } },
  { id: 'b_wall_fence', type: 'wall', props: { thickness: 0.2, height: 2.0, material: 'mat_concrete' } },
  { id: 'b_wall_parapet', type: 'wall', props: { thickness: 0.2, height: 1.0, material: 'mat_concrete' } },
  { id: 'b_door_single', type: 'door', props: { width: 0.9, height: 2.1 } },
  { id: 'b_door_double', type: 'door', props: { width: 1.6, height: 2.2 } },
  { id: 'b_door_main', type: 'door', props: { width: 1.2, height: 2.4 } },
  { id: 'b_win_std', type: 'window', props: { width: 1.2, height: 1.2, sill: 0.9 } },
  { id: 'b_win_wide', type: 'window', props: { width: 2.0, height: 1.4, sill: 0.8 } },
  { id: 'b_win_high', type: 'window', props: { width: 0.8, height: 0.5, sill: 2.0 } },
  { id: 'b_win_full', type: 'window', props: { width: 1.8, height: 2.2, sill: 0 } },
  { id: 'b_open_arch', type: 'opening', props: { width: 1.4, height: 2.4, sill: 0 } },
  { id: 'b_col_sq', type: 'column', props: { shape: 'box', width: 0.3, depth: 0.3 } },
  { id: 'b_col_big', type: 'column', props: { shape: 'box', width: 0.5, depth: 0.5 } },
  { id: 'b_col_round', type: 'column', props: { shape: 'round', width: 0.4, depth: 0.4 } },
  { id: 'b_beam_std', type: 'beam', props: { width: 0.25, depth: 0.4 } },
  { id: 'b_beam_heavy', type: 'beam', props: { width: 0.3, depth: 0.6 } },
  { id: 'b_floor_slab', type: 'floor', props: { thickness: 0.2 } },
  { id: 'b_floor_thin', type: 'floor', props: { thickness: 0.1 } },
  { id: 'b_roof_gable', type: 'roof', props: { kind: 'gable', pitch_deg: 30, overhang: 0.4 } },
  { id: 'b_roof_flat', type: 'roof', props: { kind: 'flat', overhang: 0.3, thickness: 0.2 } },
  { id: 'b_stair_std', type: 'stair', props: { width: 1.0, rise: 0.17, run: 0.28 } },
  { id: 'b_stair_wide', type: 'stair', props: { width: 1.4, rise: 0.16, run: 0.3 } },
]

const conv = (type, props, unit) => Object.fromEntries(Object.entries(props).map(([k, v]) => [k, LEN.has(k) && typeof v === 'number' ? fromM(v, unit) : v]))

/** Templates for one element type: built-ins (in project units) first, then the project's own. */
export function templatesFor(project, type) {
  const unit = project.units.name
  const b = BUILTIN.filter((x) => x.type === type).map((x) => ({ id: x.id, type, builtin: true, props: conv(type, x.props, unit) }))
  return [...b, ...(project.templates || []).filter((x) => x.type === type)]
}
export const findTemplate = (project, type, id) => (id ? templatesFor(project, type).find((x) => x.id === id) || null : null)

/** Fields to merge into a freshly drawn element of `type` (empty when no template is active). */
export function activeFields(project, active, type) {
  const tpl = findTemplate(project, type, active && active[type])
  if (!tpl) return {}
  const mats = new Set(project.materials.map((m) => m.id))
  const out = {}
  for (const [k, v] of Object.entries(tpl.props)) {
    if ((k === 'material' || k === 'material_inner') && v && !mats.has(v)) continue
    out[k] = v
  }
  return out
}

/** Properties of an element worth saving as a template. */
export function templateFromElement(el, name, id) {
  const props = {}
  for (const k of TPL_KEYS[el.type] || []) if (el[k] !== undefined && el[k] !== null) props[k] = el[k]
  return { id, name: name.trim().slice(0, 80), type: el.type, props }
}

/** Apply a template to elements with the given ids (only those of the template's type). Returns {elements, count}. */
export function applyTemplate(elements, ids, tpl) {
  const set = new Set(ids)
  let count = 0
  const out = elements.map((e) => {
    if (!set.has(e.id) || e.type !== tpl.type) return e
    count++
    return patchElement(e, tpl.props)
  })
  return { elements: out, count }
}
