// الطرق وأعمدة الإنارة: إعدادات الأسطح الجاهزة، والخامات الافتراضية، وتوزيع الأعمدة على طول الطريق.
import { fromM, makeElement, toM } from './model.js'

export const SURFACES = ['asphalt', 'dirt', 'stone', 'gravel', 'paving', 'concrete', 'sand']
// عرض الطريق / عرض الرصيف لكل جانب بالمتر عند اختيار السطح
export const ROAD_PRESETS = {
  asphalt: { width: 7, sidewalk: 1.5 }, dirt: { width: 4, sidewalk: 0 }, stone: { width: 5, sidewalk: 1 }, gravel: { width: 4, sidewalk: 0 },
  paving: { width: 5, sidewalk: 2 }, concrete: { width: 6, sidewalk: 1.5 }, sand: { width: 4, sidewalk: 0 },
}
const MATS = {
  asphalt: ['Asphalt', '#3a3b3e', 0.95], dirt: ['Dirt road', '#8a6a44', 1], stone: ['Stone road', '#8f8a7d', 0.9], gravel: ['Gravel', '#9a9488', 1],
  paving: ['Paving', '#a9998a', 0.85], concrete: ['Concrete road', '#9b9b9b', 0.9], sand: ['Sand', '#d8c690', 1], sidewalk: ['Sidewalk', '#b9b6ae', 0.9],
}
export const surfaceMaterialId = (s) => `mat_road_${s}`

/** Materials list with the road-surface materials this road needs (same ids as the backend defaults). */
export function ensureRoadMaterials(materials, surfaces) {
  const have = new Set(materials.map((m) => m.id))
  const add = []
  for (const s of [...new Set([...surfaces, 'sidewalk'])]) {
    const id = surfaceMaterialId(s)
    if (!have.has(id) && MATS[s]) add.push({ id, name: MATS[s][0], color: MATS[s][1], roughness: MATS[s][2], metallic: 0, texture: null, normal_texture: null, rough_texture: null, uv_scale: 1, lab: null })
  }
  return add.length ? [...materials, ...add] : materials
}

export function makeRoad(path, levelId, unit, { surface = 'asphalt', width, sidewalk } = {}) {
  const pr = ROAD_PRESETS[surface] || ROAD_PRESETS.asphalt
  return makeElement('road', levelId, unit, { path, surface, width: fromM(width ?? pr.width, unit), sidewalk: fromM(sidewalk ?? pr.sidewalk, unit) })
}

/** Points every `spacing` along a polyline, offset sideways by `off` (left > 0). Returns [{p, dir}] (dir = unit tangent). */
export function pointsAlong(path, spacing, off = 0) {
  const out = []
  let carry = spacing / 2   // the first pole stands half a step in, so both ends look balanced
  for (let i = 0; i + 1 < path.length; i++) {
    const a = path[i], b = path[i + 1]
    const L = Math.hypot(b[0] - a[0], b[1] - a[1])
    if (L < 1e-9) continue
    const d = [(b[0] - a[0]) / L, (b[1] - a[1]) / L], n = [-d[1], d[0]]
    let s = carry
    while (s <= L + 1e-9) {
      out.push({ p: [a[0] + d[0] * s + n[0] * off, a[1] + d[1] * s + n[1] * off], dir: d, left: off >= 0 })
      s += spacing
    }
    carry = s - L
  }
  return out
}

/**
 * Lamp elements along a road on the sidewalk centre-line (or just outside the kerb when there is no sidewalk).
 * side: 'both' | 'left' | 'right'. Units: the road's project units; `spacingM` in metres.
 */
export function lampsAlongRoad(road, levelId, unit, { spacingM = 25, side = 'both', staggered = false } = {}) {
  const sp = fromM(spacingM, unit)
  const off = road.width / 2 + (road.sidewalk > 0 ? road.sidewalk / 2 : fromM(0.3, unit))
  const out = []
  const sides = side === 'both' ? ['left', 'right'] : [side]
  for (const sd of sides) {
    const sign = sd === 'left' ? 1 : -1
    const pts = pointsAlong(road.path, sp, sign * off)
    pts.forEach(({ p, dir }, i) => {
      if (staggered && side === 'both' && (i % 2 === (sign > 0 ? 0 : 1))) return
      // الذراع تتجه نحو الطريق: عمودي على المسار باتجاه المنتصف
      const ang = (Math.atan2(dir[1], dir[0]) * 180) / Math.PI + (sign > 0 ? -90 : 90)
      out.push(makeElement('lamp', levelId, unit, { pos: p, arm: fromM(0.8, unit), arm_deg: Math.round(ang * 100) / 100, material: null }))
    })
  }
  return out
}

export const roadLengthM = (road, unit) => {
  let L = 0
  for (let i = 0; i + 1 < road.path.length; i++) L += Math.hypot(road.path[i + 1][0] - road.path[i][0], road.path[i + 1][1] - road.path[i][1])
  return toM(L, unit)
}
