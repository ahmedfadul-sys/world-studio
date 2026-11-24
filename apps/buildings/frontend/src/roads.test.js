import { describe, expect, it } from 'vitest'
import { lampsAlongRoad, makeRoad, ensureRoadMaterials, pointsAlong, ROAD_PRESETS } from './roads.js'
import { guideLines, guideSnap, makeGuide, guidePoints } from './guides.js'
import { buildTower, ensureLevels, towerProblems } from './tower.js'
import { bbox, convertUnits, hitTest, moveElements } from './model.js'

describe('roads', () => {
  it('uses the preset width and sidewalk', () => {
    const r = makeRoad([[0, 0], [50, 0]], 'L0', 'm', { surface: 'dirt' })
    expect(r.width).toBe(ROAD_PRESETS.dirt.width); expect(r.sidewalk).toBe(0); expect(r.type).toBe('road')
  })
  it('adds only the missing surface materials', () => {
    const a = ensureRoadMaterials([], ['stone']); expect(a.map((m) => m.id).sort()).toEqual(['mat_road_sidewalk', 'mat_road_stone'])
    expect(ensureRoadMaterials(a, ['stone'])).toBe(a)
  })
  it('spaces points along a bend', () => {
    const pts = pointsAlong([[0, 0], [30, 0], [30, 30]], 10, 0)
    expect(pts.length).toBe(6); expect(pts[0].p).toEqual([5, 0])
  })
  it('places lamps on both sides, arm facing the road', () => {
    const r = makeRoad([[0, 0], [100, 0]], 'L0', 'm', { surface: 'asphalt' })
    const l = lampsAlongRoad(r, 'L0', 'm', { spacingM: 25 })
    expect(l.length).toBe(8)
    const left = l.filter((x) => x.pos[1] > 0), right = l.filter((x) => x.pos[1] < 0)
    expect(left.length).toBe(4); expect(left[0].pos[1]).toBeCloseTo(3.5 + 0.75)
    expect(left[0].arm_deg).toBeCloseTo(-90); expect(right[0].arm_deg).toBeCloseTo(90)
  })
  it('hit-test, move, bbox and unit conversion handle road paths', () => {
    const r = makeRoad([[0, 0], [20, 0]], 'L0', 'm')
    expect(hitTest([10, 2], [r], 'L0', 0.1)).toBe(r.id)
    expect(hitTest([10, 9], [r], 'L0', 0.1)).toBeNull()
    expect(moveElements([r], [r.id], 5, 3)[0].path[1]).toEqual([25, 3])
    expect(bbox([r]).x1).toBe(20)
    const cm = convertUnits({ units: { name: 'm' }, levels: [], editor: { grid_size: null, snap_size: null }, elements: [r], guides: [] }, 'cm')
    expect(cm.elements[0].path[1][0]).toBe(2000); expect(cm.elements[0].width).toBe(700)
  })
})

describe('guides', () => {
  it('a grid has (cols+1)+(rows+1) lines and snaps to its nodes', () => {
    const g = makeGuide('grid', 'm', { count_x: 4, count_y: 3, spacing_x: 20, spacing_y: 10 })
    expect(guideLines(g).length).toBe(5 + 4)
    expect(guidePoints(g).length).toBe(5 * 4)
    expect(guideSnap([40.5, 9.7], [g], 2).p).toEqual([40, 10])
    expect(guideSnap([41, 5], [g], 2).kind).toBe('wall')
    expect(guideSnap([500, 500], [g], 2)).toBeNull()
  })
  it('hidden guides do not snap; parallel lines are spaced', () => {
    const g = makeGuide('parallel', 'm', { count_x: 3, spacing_x: 30, length: 100, visible: false })
    expect(guideSnap([0, 0], [g], 2)).toBeNull()
    expect(guideLines({ ...g, visible: true })[2][0]).toEqual([0, 60])
  })
})

describe('tower', () => {
  const lv = ensureLevels([], 4, 3.2, 'm')
  const { elements, stats } = buildTower({ floors: 4, radiusM: 5 }, [0, 0], lv, 'm')
  it('creates one spiral stair per floor but the top, and floors with stairwell holes', () => {
    expect(stats.stairs).toBe(3)
    expect(elements.filter((e) => e.type === 'stair').every((s) => s.kind === 'spiral' && Math.abs(s.steps * s.rise - 3.2) < 1e-4)).toBe(true)
    expect(elements.filter((e) => e.type === 'floor' && e.holes.length).length).toBe(3)
    expect(elements.filter((e) => e.type === 'roof').length).toBe(1)
    expect(elements.filter((e) => e.type === 'door').length).toBe(1)
  })
  it('every opening is hosted on a wall of the same level and fits it', () => {
    const w = new Map(elements.filter((e) => e.type === 'wall').map((x) => [x.id, x]))
    for (const o of elements.filter((e) => e.type === 'door' || e.type === 'window')) {
      const wall = w.get(o.wall_id); expect(wall.level_id).toBe(o.level_id)
      expect(o.width).toBeLessThanOrEqual(Math.hypot(wall.b[0] - wall.a[0], wall.b[1] - wall.a[1]))
    }
  })
  it('keeps existing levels untouched and flags a stair that cannot fit', () => {
    const ex = [{ id: 'a', name: 'G', elevation: 0, height: 4 }]
    const l2 = ensureLevels(ex, 3, 3, 'm'); expect(l2[0].height).toBe(4); expect(l2.length).toBe(3); expect(l2[1].elevation).toBe(4)
    expect(towerProblems({ radiusM: 2.2, wallThicknessM: 0.4, stairWidthM: 1.5 })).toContain('stair_too_wide')
  })
})
