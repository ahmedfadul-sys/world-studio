// برج دائري متعدد الطوابق مع سلّم لولبي: جدران حلقية، شبابيك، باب، أرضيات بفتحة السلّم، وسقف مخروطي/قبة/مسطح.
import { arcPoints, arcSegments, arcWalls, fromM, makeElement, toM, uid } from './model.js'
import { fitStairSteps } from './plan.js'

export const TOWER_DEFAULTS = {
  floors: 4, floorHeightM: 3.2, radiusM: 5, wallThicknessM: 0.4, windowsEvery: 2, windowW: 1.0, windowH: 1.4, sillM: 0.9,
  doorW: 1.2, doorH: 2.2, stairWidthM: 1.0, stairTurnDeg: 360, clockwise: false, centreHole: true, roof: 'cone',
}

/** Existing levels are reused untouched; missing ones are appended with the tower's floor height. */
export function ensureLevels(levels, count, floorHeightM, unit) {
  const out = levels.map((l) => ({ ...l }))
  while (out.length < count) {
    const prev = out[out.length - 1]
    out.push({ id: uid('lvl'), name: `Level ${out.length}`, elevation: prev ? prev.elevation + prev.height : 0, height: fromM(floorHeightM, unit) })
  }
  return out
}

export function towerProblems(o) {
  const out = []
  const rOut = 0.3 + o.stairWidthM
  if (o.radiusM - o.wallThicknessM / 2 - rOut < 0.6) out.push('stair_too_wide')
  if (o.radiusM < 2) out.push('radius_small')
  return out
}

/** `levels` = the tower's levels bottom-up (length >= floors). Returns {elements, stats}. Positions/sizes in project units. */
export function buildTower(o0, centre, levels, unit) {
  const o = { ...TOWER_DEFAULTS, ...o0 }
  const u = (m) => fromM(m, unit)
  const r = u(o.radiusM), t = u(o.wallThicknessM)
  const inner = r - t / 2
  const stairIn = u(0.3)
  const stairW = Math.min(u(o.stairWidthM), Math.max(u(0.5), inner - stairIn - u(0.6)))
  const hole = stairIn + stairW + u(0.05)
  const elements = []
  const stats = { floors: o.floors, walls: 0, windows: 0, stairs: 0, steps: 0 }
  const nFloor = Math.max(32, arcSegments(r, 2 * Math.PI, unit, { min: 12 }))
  const ring = (rad, n = nFloor) => arcPoints(centre, rad, 0, 2 * Math.PI, n).slice(0, n)
  const lv = levels.slice(0, o.floors)
  lv.forEach((level, i) => {
    const top = i === lv.length - 1
    const walls = arcWalls({ c: centre, r, a0: 0, sweep: 2 * Math.PI }, level.id, unit, { thickness: t, material: 'mat_plaster' })
    elements.push(...walls); stats.walls += walls.length
    walls.forEach((w, j) => {
      const L = Math.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1])
      if (i === 0 && j === 0) {
        const width = Math.min(u(o.doorW), L * 0.8)
        elements.push(makeElement('door', level.id, unit, { wall_id: w.id, offset: L / 2, width, height: Math.min(u(o.doorH), level.height * 0.85), material: 'mat_wood' }))
      } else if (o.windowsEvery > 0 && j % o.windowsEvery === 0) {
        const width = Math.min(u(o.windowW), L * 0.7)
        elements.push(makeElement('window', level.id, unit, { wall_id: w.id, offset: L / 2, width, height: Math.min(u(o.windowH), level.height * 0.6), sill: u(o.sillM), material: 'mat_wood' }))
        stats.windows++
      }
    })
    // أرضية كل طابق؛ الطوابق العليا بفتحة لممر السلّم القادم من الأسفل
    const floor = makeElement('floor', level.id, unit, { polygon: ring(inner + t / 2), material: 'mat_concrete', thickness: u(0.2), holes: i > 0 && o.centreHole ? [ring(hole, 24)] : [] })
    elements.push(floor)
    if (!top) {
      const { steps, rise } = fitStairSteps(level.height, u(0.18))
      const ang = (i * o.stairTurnDeg) % 360
      elements.push(makeElement('stair', level.id, unit, { kind: 'spiral', start: [...centre], angle_deg: ang, width: stairW, inner_radius: stairIn, steps, rise, turn_deg: o.stairTurnDeg, clockwise: o.clockwise, material: 'mat_concrete' }))
      stats.stairs++; stats.steps += steps
    }
    if (top && o.roof !== 'none') {
      const kind = o.roof === 'dome' ? 'dome' : o.roof === 'flat' ? 'flat' : 'cone'
      elements.push(makeElement('roof', level.id, unit, { kind, polygon: ring(r + t / 2 + u(0.3), Math.max(nFloor, 32)), pitch_deg: kind === 'cone' ? 55 : 30, overhang: 0, thickness: u(0.15), material: 'mat_roof' }))
    }
  })
  return { elements, stats }
}

export const towerHeightM = (o, levels, unit) => levels.slice(0, o.floors).reduce((s, l) => s + toM(l.height, unit), 0)
