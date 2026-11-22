import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Circle, Group, Layer, Line, Rect, Shape, Stage, Text } from 'react-konva'
import { useApp } from '../store.jsx'
import { activeFields } from '../templates.js'
import UnderlayLayer from './UnderlayLayer.jsx'
import {
  bbox, clampOpenings, deleteElements, dist, fmtLen, gridStep, handlesOf, hitTest, levelEndpoints, makeElement, moveElements,
  moveHandle, openingRect, orthoPoint, placeOpening, polygonArea, snapPoint, snapStep, stairRect, wallExtensions,
  arcPoints, arcThrough, arcWalls, shapePolygon,
} from '../model.js'
import {
  anchorOrigin, applyOverrides, balanceSnap, centroid, cloneElements, edgeMidpoints, edgeMovePairs, fitStairSteps, linkedMove, nextRoomName,
  parseDimInput, pointByDim, remapPoints, roomElements, underlayCorners,
} from '../plan.js'

let CLIP = null   // copied elements survive tab switches: {elements, ids, n}

const PALETTE = {
  dark: { bg: '#14171c', grid: '#1f242b', major: '#2c333d', wall: '#8c95a3', wallS: '#d5dbe4', floor: 'rgba(79,127,181,0.14)', floorS: '#4f7fb5',
    column: '#c9a36a', beam: '#b58cd6', roof: '#d17a5a', stair: '#7fb98a', room: 'rgba(120,200,160,0.10)', roomS: '#5fa783', sel: '#3da5ff',
    ghost: '#3a424e', door: '#e7b04a', win: '#5fc3e8', text: '#d5dbe4', textBg: 'rgba(20,23,28,0.82)', decor: '#9aa3b2', snap: '#ffd24a' },
  light: { bg: '#f6f3ec', grid: '#e7e3d9', major: '#d6d1c4', wall: '#6d7684', wallS: '#2d333c', floor: 'rgba(60,110,170,0.12)', floorS: '#3d6ea8',
    column: '#a47a38', beam: '#8e5eb3', roof: '#bb5a39', stair: '#4a9a5c', room: 'rgba(60,160,120,0.12)', roomS: '#2f8b66', sel: '#0a72d6',
    ghost: '#c9c4b6', door: '#b9791a', win: '#1b8cb5', text: '#2d333c', textBg: 'rgba(246,243,236,0.85)', decor: '#6d7684', snap: '#d98a00' },
}

const flat = (pts) => pts.flatMap((p) => p)
// numbers/units must keep their left-to-right order inside Arabic (RTL) pages: isolate them with LRI … PDI
const LTR = (txt) => `\u2066${txt}\u2069`
const rotAngle = (d) => Math.atan2(d[1], d[0])

function wallPoly(w, ea = 0, eb = 0) {
  const L = dist(w.a, w.b)
  const d = [(w.b[0] - w.a[0]) / L, (w.b[1] - w.a[1]) / L], n = [-d[1], d[0]], h = w.thickness / 2
  const a = [w.a[0] - d[0] * ea, w.a[1] - d[1] * ea], b = [w.b[0] + d[0] * eb, w.b[1] + d[1] * eb]
  return [[a[0] + n[0] * h, a[1] + n[1] * h], [b[0] + n[0] * h, b[1] + n[1] * h], [b[0] - n[0] * h, b[1] - n[1] * h], [a[0] - n[0] * h, a[1] - n[1] * h]]
}

function GridShape({ view, size, step, pal }) {
  return (
    <Shape
      listening={false}
      sceneFunc={(ctx) => {
        const { x, y, scale } = view
        let st = step
        while (st * scale < 14) st *= 5 // never draw a grid denser than ~14 px
        const x0 = Math.floor((0 - x) / scale / st) * st, x1 = (size.w - x) / scale
        const yTop = (y - 0) / scale, yBot = (y - size.h) / scale
        const y0 = Math.floor(yBot / st) * st
        ctx.lineWidth = 1
        for (let gx = x0, i = Math.round(x0 / st); gx <= x1; gx += st, i++) {
          const sx = Math.round(gx * scale + x) + 0.5
          ctx.strokeStyle = i % 5 === 0 ? pal.major : pal.grid
          ctx.beginPath(); ctx.moveTo(sx, 0); ctx.lineTo(sx, size.h); ctx.stroke()
        }
        for (let gy = y0, j = Math.round(y0 / st); gy <= yTop; gy += st, j++) {
          const sy = Math.round(-gy * scale + y) + 0.5
          ctx.strokeStyle = j % 5 === 0 ? pal.major : pal.grid
          ctx.beginPath(); ctx.moveTo(0, sy); ctx.lineTo(size.w, sy); ctx.stroke()
        }
        ctx.strokeStyle = pal.snap; ctx.globalAlpha = 0.5
        ctx.beginPath(); ctx.moveTo(Math.round(x) + 0.5, 0); ctx.lineTo(Math.round(x) + 0.5, size.h); ctx.moveTo(0, Math.round(y) + 0.5); ctx.lineTo(size.w, Math.round(y) + 0.5); ctx.stroke()
        ctx.globalAlpha = 1
      }}
    />
  )
}

function Elem({ e, byId, ext, pal, selected, ghost }) {
  const sel = selected ? pal.sel : null
  const sw = selected ? 2 : 1
  const op = ghost ? 0.35 : 1
  switch (e.type) {
    case 'wall': {
      const [ea, eb] = ext[e.id] || [0, 0]
      return <Line points={flat(wallPoly(e, ea, eb))} closed fill={ghost ? pal.ghost : sel ? pal.sel : pal.wall} stroke={ghost ? pal.ghost : sel || pal.wallS} strokeWidth={sw} strokeScaleEnabled={false} opacity={op} listening={false} perfectDrawEnabled={false} />
    }
    case 'door': case 'window': case 'opening': {
      const w = byId.get(e.wall_id); if (!w) return null
      const r = openingRect(e, w)
      const ang = rotAngle(r.dir), n = [-r.dir[1], r.dir[0]]
      const c = e.type === 'door' ? pal.door : e.type === 'window' ? pal.win : pal.text
      const half = r.len / 2, t = r.thick / 2
      const corners = [[-half, -t], [half, -t], [half, t], [-half, t]].map(([u, v]) => [r.c[0] + r.dir[0] * u + n[0] * v, r.c[1] + r.dir[1] * u + n[1] * v])
      const swing = []
      if (e.type === 'door') {
        for (let i = 0; i <= 10; i++) { const a = (Math.PI / 2) * (i / 10); const u = -half + Math.cos(a) * e.width, v = Math.sin(a) * e.width; swing.push([r.c[0] + r.dir[0] * u + n[0] * v, r.c[1] + r.dir[1] * u + n[1] * v]) }
        swing.unshift([r.c[0] - r.dir[0] * half, r.c[1] - r.dir[1] * half])
      }
      return (
        <Group listening={false} opacity={ghost ? 0.3 : 1}>
          <Line points={flat(corners)} closed fill={pal.bg} stroke={sel || c} strokeWidth={sw} strokeScaleEnabled={false} />
          {e.type === 'window' && <Line points={flat([[r.c[0] - r.dir[0] * half, r.c[1] - r.dir[1] * half], [r.c[0] + r.dir[0] * half, r.c[1] + r.dir[1] * half]])} stroke={sel || c} strokeWidth={1} strokeScaleEnabled={false} />}
          {e.type === 'door' && <Line points={flat(swing)} stroke={sel || c} strokeWidth={1} strokeScaleEnabled={false} dash={[4, 3]} />}
          <Rect x={0} y={0} width={0} height={0} rotation={(ang * 180) / Math.PI} />
        </Group>
      )
    }
    case 'column': {
      const hw = e.width / 2, hd = (e.shape === 'round' ? e.width : e.depth) / 2
      return e.shape === 'round'
        ? <Circle x={e.pos[0]} y={e.pos[1]} radius={hw} fill={ghost ? pal.ghost : pal.column} stroke={sel || pal.wallS} strokeWidth={sw} strokeScaleEnabled={false} opacity={op} listening={false} />
        : <Rect x={e.pos[0] - hw} y={e.pos[1] - hd} width={e.width} height={e.depth} fill={ghost ? pal.ghost : pal.column} stroke={sel || pal.wallS} strokeWidth={sw} strokeScaleEnabled={false} opacity={op} listening={false} />
    }
    case 'beam': return <Line points={flat([e.a, e.b])} stroke={sel || (ghost ? pal.ghost : pal.beam)} strokeWidth={Math.max(sw, 2)} dash={[8, 5]} strokeScaleEnabled={false} opacity={op} listening={false} />
    case 'floor': return <Line points={flat(e.polygon)} closed fill={ghost ? 'transparent' : pal.floor} stroke={sel || (ghost ? pal.ghost : pal.floorS)} strokeWidth={sw} strokeScaleEnabled={false} opacity={op} listening={false} />
    case 'roof': return <Line points={flat(e.polygon)} closed stroke={sel || pal.roof} strokeWidth={sw} dash={[2, 6]} strokeScaleEnabled={false} opacity={ghost ? 0.2 : 0.9} listening={false} />
    case 'room': return <Line points={flat(e.polygon)} closed fill={pal.room} stroke={sel || pal.roomS} strokeWidth={sw} strokeScaleEnabled={false} opacity={ghost ? 0.3 : 1} listening={false} />
    case 'stair': {
      const r = stairRect(e)
      const lines = []
      for (let i = 1; i < e.steps; i++) { const f = i / e.steps; lines.push(flat([[r[0][0] + (r[1][0] - r[0][0]) * f, r[0][1] + (r[1][1] - r[0][1]) * f], [r[3][0] + (r[2][0] - r[3][0]) * f, r[3][1] + (r[2][1] - r[3][1]) * f]])) }
      const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
      const m0 = mid(r[0], r[3]), m1 = mid(r[1], r[2])
      return (
        <Group listening={false} opacity={ghost ? 0.3 : 1}>
          <Line points={flat(r)} closed fill={pal.bg} stroke={sel || pal.stair} strokeWidth={sw} strokeScaleEnabled={false} />
          {lines.map((l, i) => <Line key={i} points={l} stroke={sel || pal.stair} strokeWidth={1} strokeScaleEnabled={false} />)}
          <Line points={flat([m0, m1])} stroke={sel || pal.stair} strokeWidth={1.5} strokeScaleEnabled={false} />
        </Group>
      )
    }
    case 'decor': {
      const [sx, sy] = e.size
      return e.shape === 'cylinder'
        ? <Circle x={e.pos[0]} y={e.pos[1]} radius={sx / 2} stroke={sel || pal.decor} strokeWidth={sw} fill={pal.decor} opacity={0.5 * (ghost ? 0.5 : 1)} strokeScaleEnabled={false} listening={false} />
        : <Rect x={e.pos[0] - sx / 2} y={e.pos[1] - sy / 2} width={sx} height={sy} rotation={e.rotation_deg} stroke={sel || pal.decor} strokeWidth={sw} fill={pal.decor} opacity={0.5 * (ghost ? 0.5 : 1)} strokeScaleEnabled={false} listening={false} />
    }
    default: return null
  }
}

const TOOL_HINT = { wall: 'hint_wall', circle: 'hint_circle', arc: 'hint_arc', floor: 'hint_poly', roof: 'hint_poly', room: 'hint_poly', beam: 'hint_beam', door: 'hint_host', window: 'hint_host', opening: 'hint_host', column: 'hint_place', decor: 'hint_place', stair: 'hint_beam', roomwiz: 'hint_roomwiz', select: 'hint_select', move: 'hint_select', delete: 'hint_select', hand: 'hint_pan' }
const POLY_TOOLS = ['floor', 'roof', 'room']

/** TerrainForge site footprint (centre = 0,0; metres): where the buildings of this project will stand on the terrain pad. */
function SiteGuide({ site, k, pal, u }) {
  const common = { stroke: pal.accent || '#e0a030', strokeWidth: 2 / k, dash: [10 / k, 6 / k], listening: false, opacity: 0.9 }
  if (site.shape === 'circle') return <><Circle radius={(site.diameter_m * u) / 2} {...common} /><Circle radius={4 / k} fill={common.stroke} listening={false} /></>
  return <Group rotation={site.rotation_deg || 0} listening={false}><Rect x={(-site.width_m * u) / 2} y={(-site.length_m * u) / 2} width={site.width_m * u} height={site.length_m * u} {...common} /><Circle radius={4 / k} fill={common.stroke} listening={false} /></Group>
}

export default function Canvas2D({ onGhostChange, showGhost, onNotice }) {
  const app = useApp()
  const { project, levelId, tool, selection, theme, t } = app
  const pal = PALETTE[theme]
  const wrap = useRef(null)
  const stageRef = useRef(null)
  const [size, setSize] = useState({ w: 800, h: 560 })
  const [draft, setDraft] = useState([])          // points of the shape being drawn
  const [cursor, setCursor] = useState(null)      // {p, kind}
  const [ov, setOv] = useState(null)              // live (uncommitted) element overrides during a drag
  const [panning, setPanning] = useState(false)
  const drag = useRef(null)
  const space = useRef(false)
  const lastClick = useRef({ t: 0, x: -99, y: -99 })
  const [measured, setMeasured] = useState(false)
  const shift = useRef(false)
  const [typed, setTyped] = useState('')            // length typed with the keyboard while drawing ("4.5", "4.5<30", "4x3")
  const linked = app.linked !== false
  // No early return anywhere (hook order must be stable): until fit() runs we render one frame with a placeholder view.
  const view = app.view || { x: 0, y: size.h, scale: 40 }

  useEffect(() => {
    const el = wrap.current
    if (!el) return undefined
    const ro = new ResizeObserver(([e]) => { setMeasured(true); setSize({ w: Math.max(100, Math.round(e.contentRect.width)), h: Math.max(100, Math.round(e.contentRect.height)) }) })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const level = project.levels.find((l) => l.id === levelId)
  const gstep = gridStep(project), sstep = snapStep(project)
  const unit = project.units.name

  const fit = useCallback(() => {
    let bb = bbox(project.elements, levelId) || bbox(project.elements)
    const uls = (project.underlays || []).filter((u) => u.visible && (u.level_id == null || u.level_id === levelId))
    if (uls.length) {
      const q = uls.flatMap(underlayCorners)
      const ub = { x0: Math.min(...q.map((a) => a[0])), x1: Math.max(...q.map((a) => a[0])), y0: Math.min(...q.map((a) => a[1])), y1: Math.max(...q.map((a) => a[1])) }
      bb = bb ? { x0: Math.min(bb.x0, ub.x0), x1: Math.max(bb.x1, ub.x1), y0: Math.min(bb.y0, ub.y0), y1: Math.max(bb.y1, ub.y1) } : ub
    }
    const unitM = { m: 1, cm: 100, mm: 1000, ft: 3.28084, in: 39.3701 }[unit]
    if (project.site) {   // a site project always frames its whole footprint (centre = origin, metres)
      const sx = (project.site.shape === 'circle' ? project.site.diameter_m : Math.max(project.site.width_m, project.site.length_m)) * unitM / 2
      bb = bb ? { x0: Math.min(bb.x0, -sx), x1: Math.max(bb.x1, sx), y0: Math.min(bb.y0, -sx), y1: Math.max(bb.y1, sx) } : { x0: -sx, x1: sx, y0: -sx, y1: sx }
    }
    let w = bb ? bb.x1 - bb.x0 : 20 * unitM, h = bb ? bb.y1 - bb.y0 : 12 * unitM
    w = Math.max(w, 4 * unitM); h = Math.max(h, 3 * unitM)
    const scale = Math.min((size.w - 80) / w, (size.h - 80) / h)
    const cx = bb ? (bb.x0 + bb.x1) / 2 : 6 * unitM, cy = bb ? (bb.y0 + bb.y1) / 2 : 4 * unitM
    app.set({ view: { scale, x: size.w / 2 - cx * scale, y: size.h / 2 + cy * scale } })
  }, [project.elements, project.underlays, project.site, levelId, size, unit, app])

  useEffect(() => { if (!app.view && measured) fit() }, [app.view, measured]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { window.__bimFit = fit; return () => { delete window.__bimFit } }, [fit])
  useEffect(() => { window.__bimToS = (p) => [p[0] * view.scale + view.x, -p[1] * view.scale + view.y]; return () => { delete window.__bimToS } })

  const base = project.elements
  const elements = useMemo(() => (ov ? base.map((e) => ov[e.id] || e) : base), [base, ov])
  const byId = useMemo(() => new Map(elements.map((e) => [e.id, e])), [elements])
  const here = useMemo(() => elements.filter((e) => e.level_id === levelId), [elements, levelId])
  const walls = useMemo(() => here.filter((e) => e.type === 'wall'), [here])
  const ext = useMemo(() => wallExtensions(walls), [walls])
  const idx = project.levels.findIndex((l) => l.id === levelId)
  const below = showGhost && idx > 0 ? elements.filter((e) => e.level_id === project.levels[idx - 1].id) : []
  const belowWalls = useMemo(() => below.filter((e) => e.type === 'wall'), [below])
  const belowExt = useMemo(() => wallExtensions(belowWalls), [belowWalls])
  const belowById = useMemo(() => new Map(below.map((e) => [e.id, e])), [below])

  const toW = (sx, sy) => [(sx - view.x) / view.scale, -(sy - view.y) / view.scale]
  const toS = (p) => [p[0] * view.scale + view.x, -p[1] * view.scale + view.y]
  const tol = 10 / view.scale
  // corner handles of a wall / beam / polygon plus, for polygons, one diamond per side (drag = move that side)
  const allHandles = (el) => (el ? [...handlesOf(el), ...(el.polygon ? edgeMidpoints(el.polygon) : [])] : [])

  const pointer = () => {
    const pos = stageRef.current.getPointerPosition()
    return pos ? [pos.x, pos.y] : null
  }

  const snapAt = (raw, extra = []) => {
    let p = raw
    const prev = draft.length && (tool === 'wall' || tool === 'beam' || tool === 'stair') ? draft[draft.length - 1] : null
    if (prev && shift.current) p = orthoPoint(prev, raw)
    return snapPoint(p, { step: sstep, enabled: project.editor.snap_enabled, endpoints: [...levelEndpoints(base, levelId), ...extra], walls: tool === 'wall' || tool === 'beam' ? walls : [], tol })
  }

  const edit = (fn, key) => app.edit(fn, key)

  // fields of the active template (if any) are applied to every new element of that type
  const mk = (type, lv, un, f) => makeElement(type, lv, un, { ...f, ...activeFields(project, app.tpl, type) })
  const add = (el) => { edit((p) => ({ ...p, elements: [...p.elements, el] })); app.select([el.id]) }

  const shape = POLY_TOOLS.includes(tool) ? (app.shape || 'poly') : 'poly'

  const finishPoly = () => {
    if (draft.length >= 3 && POLY_TOOLS.includes(tool)) {
      const type = tool
      const el = mk(type, levelId, unit, { polygon: draft.map((p) => [...p]) })
      if (type === 'floor') el.material = 'mat_concrete'
      if (type === 'roof') el.material = 'mat_roof'
      add(el)
    }
    setDraft([])
  }

  const wallTo = (p) => {
    if (!draft.length) { setDraft([p]); return }
    const prev = draft[draft.length - 1]
    if (dist(prev, p) < 1e-6) return
    const w = mk('wall', levelId, unit, { a: prev, b: p, material: 'mat_plaster' })
    edit((pr) => ({ ...pr, elements: [...pr.elements, w] }))
    app.select([w.id])
    const closed = draft.length >= 2 && dist(draft[0], p) < 1e-6
    setDraft(closed ? [] : [p])
  }

  // room wizard: the chosen corner of the w×d room goes to p
  const placeRoomAt = (p) => {
    const sp = app.roomSpec
    if (!sp || !(sp.w > 0) || !(sp.d > 0)) return
    const [x, y] = anchorOrigin(sp.anchor, p, sp.w, sp.d)
    const label = t('rt_' + sp.type)
    const name = sp.name || nextRoomName(base, levelId, label)
    const tw = activeFields(project, app.tpl, 'wall')
    const els = roomElements({ ...sp, x, y, name }, levelId, unit, base).map((e) => (e.type === 'wall' ? { ...e, ...tw, overrides: [...new Set([...(e.overrides || []), ...Object.keys(tw)])] } : e))
    edit((pr) => ({ ...pr, elements: [...pr.elements, ...els] }))
    app.select(els.filter((e) => e.type === 'room').map((e) => e.id))
    onNotice(`${t('rw_placed')}: ${name}`)
  }
  useEffect(() => { window.__bimPlaceRoomCentre = () => { const c = toW(size.w / 2, size.h / 2); placeRoomAt(snapPoint(c, { step: sstep, enabled: project.editor.snap_enabled, endpoints: [], walls: [], tol: 0 }).p) }; return () => { delete window.__bimPlaceRoomCentre } })

  // typed length: where the next point goes (direction = towards the cursor unless an angle was typed)
  const typedResult = () => {
    const d = parseDimInput(typed)
    if (!d || !draft.length) return null
    const last = draft[draft.length - 1]
    if (d.kind === 'len' && (tool === 'wall' || tool === 'beam' || tool === 'circle' || (POLY_TOOLS.includes(tool) && shape === 'circle'))) return { d, p: pointByDim(last, d.len, d.ang, cursor?.p) }
    if (d.kind === 'wh' && POLY_TOOLS.includes(tool) && shape === 'rect') {
      const sx = cursor && cursor.p[0] < last[0] ? -1 : 1, sy = cursor && cursor.p[1] < last[1] ? -1 : 1
      return { d, p: [last[0] + sx * d.w, last[1] + sy * d.h] }
    }
    return null
  }
  const commitTyped = () => {
    const r = typedResult()
    if (!r) return false
    const p = r.p
    if (tool === 'wall') wallTo(p)
    else if (tool === 'beam') { if (dist(draft[0], p) > 1e-6) { add(mk('beam', levelId, unit, { a: draft[0], b: p, material: 'mat_wood' })); setDraft([]) } }
    else if (tool === 'circle') {
      const ws = arcWalls({ c: draft[0], r: r.d.len, a0: 0, sweep: 2 * Math.PI }, levelId, unit)
      edit((pr) => ({ ...pr, elements: [...pr.elements, ...ws] })); app.select(ws.map((w) => w.id)); setDraft([])
    } else if (POLY_TOOLS.includes(tool)) {
      const poly = shapePolygon(shape, draft[0], p, tool, unit)
      if (poly) {
        const el = mk(tool, levelId, unit, { polygon: poly })
        if (tool === 'floor') el.material = 'mat_concrete'
        if (tool === 'roof') { el.material = 'mat_roof'; if (shape === 'circle') el.kind = 'cone' }
        add(el); setDraft([])
      }
    }
    setTyped('')
    return true
  }

  // ------------------------------------------------------------------ pointer handlers
  const onDown = (e) => {
    const evt = e.evt
    if (evt.touches && evt.touches.length >= 2) { startPinch(evt); return }
    const sp = pointer(); if (!sp) return
    const mid = evt.button === 1 || (evt.button === 0 && (tool === 'hand' || space.current))
    if (mid || (evt.button === 2)) { drag.current = { kind: 'pan', sx: sp[0], sy: sp[1], vx: view.x, vy: view.y }; setPanning(true); return }
    const raw = toW(sp[0], sp[1])
    if (app.calib) {   // scale calibration of an underlay: two clicks on the image, no snapping
      if (app.calib.pts.length < 2) app.set({ calib: { ...app.calib, pts: [...app.calib.pts, raw] } })
      return
    }
    const sn = snapAt(raw)
    const p = sn.p
    // double-click = two clicks close in time AND in place (Konva's own dblclick ignores position, which cut wall chains short)
    const now = Date.now(), lc = lastClick.current
    const dbl = now - lc.t < 400 && Math.hypot(sp[0] - lc.x, sp[1] - lc.y) < 8
    lastClick.current = dbl ? { t: 0, x: -99, y: -99 } : { t: now, x: sp[0], y: sp[1] }
    if (dbl && tool === 'wall') { setDraft([]); return }
    if (dbl && POLY_TOOLS.includes(tool) && shape === 'poly') { finishPoly(); return }

    if (tool === 'select' || tool === 'move') {
      // handle drag has priority (single selected wall/beam/polygon)
      if (selection.length === 1) {
        const el = byId.get(selection[0])
        const hs = allHandles(el)
        for (let i = 0; i < hs.length; i++) {
          const s = toS(hs[i])
          if (Math.hypot(s[0] - sp[0], s[1] - sp[1]) <= 12) { drag.current = { kind: 'handle', id: el.id, i }; return }
        }
      }
      const hit = hitTest(raw, here, levelId, tol)
      if (hit && dbl && byId.get(hit)?.type === 'wall') { app.select([hit]); app.set({ faceWall: hit }); return }
      if (hit) {
        let sel = selection
        if (evt.shiftKey) sel = selection.includes(hit) ? selection.filter((x) => x !== hit) : [...selection, hit]
        else if (!selection.includes(hit)) sel = [hit]
        app.select(sel)
        if (sel.includes(hit)) drag.current = { kind: 'move', start: raw, ids: sel, moved: false }
      } else if (!evt.shiftKey) {
        app.select([])
        drag.current = { kind: 'pan', sx: sp[0], sy: sp[1], vx: view.x, vy: view.y, soft: true }
      }
      return
    }
    if (tool === 'delete') {
      const hit = hitTest(raw, here, levelId, tol)
      if (hit) edit((pr) => ({ ...pr, elements: deleteElements(pr.elements, [hit]) }))
      return
    }
    if (tool === 'wall') { wallTo(p); return }
    if (tool === 'roomwiz') { placeRoomAt(p); return }
    if (tool === 'circle') {
      if (!draft.length) { setDraft([p]); return }
      const r = dist(draft[0], p)
      if (r < 1e-6) return
      const ws = arcWalls({ c: draft[0], r, a0: 0, sweep: 2 * Math.PI }, levelId, unit)
      edit((pr) => ({ ...pr, elements: [...pr.elements, ...ws] }))
      app.select(ws.map((w) => w.id)); setDraft([])
      return
    }
    if (tool === 'arc') {
      if (draft.length < 2) { if (!draft.length || dist(draft[draft.length - 1], p) > 1e-6) setDraft([...draft, p]); return }
      const g = arcThrough(draft[0], draft[1], p)
      if (!g) { onNotice(t('err_arc_collinear')); return }
      const ws = arcWalls(g, levelId, unit)
      edit((pr) => ({ ...pr, elements: [...pr.elements, ...ws] }))
      app.select(ws.map((w) => w.id)); setDraft([])
      return
    }
    if (tool === 'door' || tool === 'window' || tool === 'opening') {
      const r = placeOpening(tool, raw, base, levelId, unit, tol, project.editor.snap_enabled ? sstep : 0)
      if (r.error) onNotice(r.error === 'no_wall' ? t('err_no_wall') : t('err_wall_short'))
      else { const el = { ...r.element, ...activeFields(project, app.tpl, tool) }; edit((pr) => ({ ...pr, elements: clampOpenings([...pr.elements, el], el.wall_id) })); app.select([el.id]) }
      return
    }
    if (tool === 'column' || tool === 'decor') { add(mk(tool, levelId, unit, { pos: p, ...(tool === 'column' ? { material: 'mat_concrete' } : {}) })); return }
    if (tool === 'beam') {
      if (!draft.length) setDraft([p])
      else if (dist(draft[0], p) > 1e-6) { add(mk('beam', levelId, unit, { a: draft[0], b: p, material: 'mat_wood' })); setDraft([]) }
      return
    }
    if (tool === 'stair') {
      if (!draft.length) setDraft([p])
      else {
        const d = [p[0] - draft[0][0], p[1] - draft[0][1]]
        const ang = Math.round(((Math.atan2(d[1], d[0]) * 180) / Math.PI) / 5) * 5
        const st = mk('stair', levelId, unit, { start: draft[0], angle_deg: ang, material: 'mat_concrete' })
        if (level) Object.assign(st, fitStairSteps(level.height, st.rise))   // reach exactly the next floor
        add(st); setDraft([])
      }
      return
    }
    if (POLY_TOOLS.includes(tool) && shape !== 'poly') {
      if (!draft.length) { setDraft([p]); return }
      const poly = shapePolygon(shape, draft[0], p, tool, unit)
      if (!poly) return
      const el = mk(tool, levelId, unit, { polygon: poly })
      if (tool === 'floor') el.material = 'mat_concrete'
      if (tool === 'roof') { el.material = 'mat_roof'; if (shape === 'circle') el.kind = 'cone' }
      add(el); setDraft([])
      return
    }
    if (POLY_TOOLS.includes(tool)) {
      if (draft.length && dist(draft[draft.length - 1], p) < 1e-6) return
      if (draft.length >= 3 && dist(draft[0], p) < tol) { finishPoly(); return }
      setDraft([...draft, p])
    }
  }

  const onMove = (e) => {
    const evt = e.evt
    if (evt.touches && evt.touches.length >= 2) { movePinch(evt); return }
    const sp = pointer(); if (!sp) return
    const raw = toW(sp[0], sp[1])
    const d = drag.current
    if (d && d.kind === 'pan') { app.set({ view: { ...view, x: d.vx + (sp[0] - d.sx), y: d.vy + (sp[1] - d.sy) } }); return }
    if (d && d.kind === 'move') {
      let dx = raw[0] - d.start[0], dy = raw[1] - d.start[1]
      if (project.editor.snap_enabled) { dx = Math.round(dx / sstep) * sstep; dy = Math.round(dy / sstep) * sstep }
      if (!d.moved && Math.hypot(dx, dy) * view.scale < 3) return
      d.moved = true; d.dx = dx; d.dy = dy
      const moved = moveElements(base, d.ids, dx, dy)
      const o = {}
      moved.forEach((el, i) => { if (el !== base[i]) o[el.id] = el })
      setOv(o); return
    }
    if (d && d.kind === 'handle') {
      const own = byId.get(d.id)
      const nv = handlesOf(own).length
      if (d.i >= nv) {   // side of a polygon: slide it parallel to itself
        d.pairs = edgeMovePairs(own.polygon, d.i - nv, raw, project.editor.snap_enabled ? sstep : 0)
        setOv(linked ? remapPoints(base, own.level_id, d.pairs) : { [own.id]: { ...own, polygon: own.polygon.map((q) => { const m = d.pairs.find(([o]) => dist(o, q) < 1e-6); return m ? m[1] : q }) } })
        return
      }
      const sn = snapPoint(raw, { step: sstep, enabled: project.editor.snap_enabled, endpoints: levelEndpoints(base, levelId).filter((q) => !handlesOf(own).some((h) => h === q)), walls: own.type === 'wall' || own.type === 'beam' ? walls.filter((w) => w.id !== d.id) : [], tol })
      // "balance" magnet: when two walls meet at this corner, pull it to where both are equally long
      const o0 = base.find((e) => e.id === d.id)
      const old = o0 && handlesOf(o0)[d.i]
      const bs = old && own.type === 'wall' && sn.kind !== 'point' ? balanceSnap(base, own.level_id, old, sn.p, tol * 0.8) : { p: sn.p, balanced: false, lengths: null }
      d.p = bs.p; d.info = { balanced: bs.balanced, lengths: bs.lengths }
      setOv(linked ? linkedMove(base, d.id, d.i, bs.p) : moveHandle(base, d.id, d.i, bs.p)); setCursor(sn); return
    }
    setCursor(snapAt(raw))
  }

  const onUp = () => {
    const d = drag.current
    drag.current = null
    if (d && d.kind === 'pan') setPanning(false)
    if (d && d.kind === 'move' && d.moved) edit((pr) => ({ ...pr, elements: moveElements(pr.elements, d.ids, d.dx, d.dy) }))
    if (d && d.kind === 'handle' && (d.p || d.pairs)) {
      edit((pr) => {
        const own = pr.elements.find((x) => x.id === d.id)
        let o
        if (d.pairs) o = linked ? remapPoints(pr.elements, own.level_id, d.pairs) : { [own.id]: { ...own, polygon: own.polygon.map((q) => { const m = d.pairs.find(([oo]) => dist(oo, q) < 1e-6); return m ? m[1] : q }) } }
        else o = linked ? linkedMove(pr.elements, d.id, d.i, d.p) : moveHandle(pr.elements, d.id, d.i, d.p)
        let els = applyOverrides(pr.elements, o)
        for (const id of Object.keys(o)) if (o[id].type === 'wall') els = clampOpenings(els, id)
        return { ...pr, elements: els }
      })
    }
    setOv(null)
  }

  const onWheel = (e) => {
    e.evt.preventDefault()
    const sp = pointer(); if (!sp) return
    const f = Math.exp(-e.evt.deltaY * 0.0015)
    zoomAt(sp, f)
  }
  const zoomAt = (sp, f) => {
    const scale = Math.min(Math.max(view.scale * f, 0.0005), 5000)
    const k = scale / view.scale
    app.set({ view: { scale, x: sp[0] - (sp[0] - view.x) * k, y: sp[1] - (sp[1] - view.y) * k } })
  }

  const startPinch = (evt) => {
    const [a, b] = evt.touches
    const r = stageRef.current.container().getBoundingClientRect()
    drag.current = { kind: 'pinch', d: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY), cx: (a.clientX + b.clientX) / 2 - r.left, cy: (a.clientY + b.clientY) / 2 - r.top }
  }
  const movePinch = (evt) => {
    const d = drag.current
    if (!d || d.kind !== 'pinch') { startPinch(evt); return }
    evt.preventDefault()
    const [a, b] = evt.touches
    const r = stageRef.current.container().getBoundingClientRect()
    const nd = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)
    const cx = (a.clientX + b.clientX) / 2 - r.left, cy = (a.clientY + b.clientY) / 2 - r.top
    const f = nd / d.d
    const scale = Math.min(Math.max(view.scale * f, 0.0005), 5000), k = scale / view.scale
    app.set({ view: { scale, x: cx - (d.cx - view.x) * k - (d.cx - cx) * 0, y: cy - (d.cy - view.y) * k } })
    drag.current = { ...d, d: nd, cx, cy }
  }

  // keyboard ---------------------------------------------------------------------------
  useEffect(() => {
    const typing = () => { const a = document.activeElement; return a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || a.tagName === 'SELECT' || a.isContentEditable) }
    const down = (e) => {
      if (e.key === 'Shift') shift.current = true
      if (app.faceWall) return   // the wall-face editor owns the keyboard while open
      if (typing()) return
      if (e.code === 'Space') { space.current = true; e.preventDefault() }
      const mod = e.ctrlKey || e.metaKey
      if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); e.shiftKey ? app.redo() : app.undo(); return }
      if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); app.redo(); return }
      if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); app.save(); return }
      if (mod && e.key.toLowerCase() === 'c') { if (selection.length) { e.preventDefault(); CLIP = { elements: base, ids: [...selection], n: 0 }; onNotice(`${t('pt_copied')}: ${selection.length}`) } return }
      if (mod && (e.key.toLowerCase() === 'v' || e.key.toLowerCase() === 'd')) {
        const kd = e.key.toLowerCase()
        const src = kd === 'd' ? (selection.length ? { elements: base, ids: [...selection], n: 0 } : null) : CLIP
        if (!src) return
        e.preventDefault()
        src.n += 1
        const c0 = centroid(src.elements, src.ids)
        const atCursor = kd === 'v' && cursor && src.n === 1   // first paste lands on the cursor, further ones step aside
        const dx = atCursor ? cursor.p[0] - c0[0] : sstep * 4 * src.n, dy = atCursor ? cursor.p[1] - c0[1] : -sstep * 4 * src.n
        const made = cloneElements(src.elements, src.ids, { dx, dy, levelId })
        if (made.length) { edit((pr) => ({ ...pr, elements: [...pr.elements, ...made] })); app.select(made.filter((x) => !x.wall_id).map((x) => x.id)); onNotice(`${t('pt_pasted')}: ${made.length}`) }
        return
      }
      if (mod && e.key.toLowerCase() === 'a') { e.preventDefault(); app.select(here.filter((x) => x.type !== 'room').map((x) => x.id)); return }
      if (e.key === 'Escape' && app.calib) { app.set({ calib: null }); return }
      // typed dimensions while drawing
      const drawing = draft.length > 0 && (tool === 'wall' || tool === 'beam' || tool === 'circle' || (POLY_TOOLS.includes(tool) && shape !== 'poly'))
      if (drawing && !mod) {
        if (/^[0-9٠-٩.٫,<;*×-]$/.test(e.key) || (typed && (e.key === 'x' || e.key === 'X' || e.key === ' '))) { e.preventDefault(); setTyped(typed + (e.key === 'X' ? 'x' : e.key)); return }
        if (typed && e.key === 'Backspace') { e.preventDefault(); setTyped(typed.slice(0, -1)); return }
        if (typed && e.key === 'Enter') { e.preventDefault(); if (!commitTyped()) onNotice(t('typed_hint')); return }
        if (typed && e.key === 'Escape') { setTyped(''); return }
      }
      if (e.key === 'Delete' || e.key === 'Backspace') { if (selection.length) { e.preventDefault(); const sel = selection; edit((pr) => ({ ...pr, elements: deleteElements(pr.elements, sel) })) } return }
      if (e.key === 'Escape') { if (draft.length) setDraft([]); else if (selection.length) app.select([]); else app.set({ tool: 'select' }); return }
      if (e.key === 'Enter') { if (POLY_TOOLS.includes(tool)) finishPoly(); else if (tool === 'wall') setDraft([]); return }
      if (mod) return
      const map = { t: 'roomwiz', v: 'select', m: 'move', h: 'hand', w: 'wall', d: 'door', n: 'window', c: 'column', b: 'beam', f: 'floor', r: 'roof', s: 'stair', o: 'opening', g: 'room', x: 'delete', q: 'circle', a: 'arc' }
      const nt = map[e.key.toLowerCase()]
      if (nt) { app.set({ tool: nt }); setDraft([]) }
    }
    const up = (e) => { if (e.key === 'Shift') shift.current = false; if (e.code === 'Space') space.current = false }
    window.addEventListener('keydown', down); window.addEventListener('keyup', up)
    return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up) }
  })

  useEffect(() => { setDraft([]); setTyped('') }, [tool, levelId])
  useEffect(() => { if (!draft.length) setTyped('') }, [draft.length])

  // ------------------------------------------------------------------ render
  const selEls = selection.map((id) => byId.get(id)).filter(Boolean)
  const handles = selection.length === 1 && (tool === 'select' || tool === 'move') ? handlesOf(selEls[0]) : []
  const sideHandles = selection.length === 1 && (tool === 'select' || tool === 'move') && selEls[0]?.polygon ? edgeMidpoints(selEls[0].polygon) : []
  const labels = []
  if (project.editor.show_dimensions) {
    for (const w of walls) {
      const L = dist(w.a, w.b), s0 = toS(w.a), s1 = toS(w.b)
      if (L * view.scale < 70 || (ov && ov[w.id] && drag.current && drag.current.kind === 'handle')) continue
      const m = [(s0[0] + s1[0]) / 2, (s0[1] + s1[1]) / 2]
      const nx = -(s1[1] - s0[1]), ny = s1[0] - s0[0], nl = Math.hypot(nx, ny) || 1
      const off = (w.thickness * view.scale) / 2 + 12
      labels.push({ k: w.id, x: m[0] + (nx / nl) * off, y: m[1] + (ny / nl) * off, text: LTR(fmtLen(L, unit)) })
    }
  }
  // while a corner is dragged: show every changed wall's length with its change, and a badge when the two sides are equal
  const dh = drag.current && drag.current.kind === 'handle' && ov ? drag.current : null
  if (dh) {
    for (const w of Object.values(ov)) {
      if (w.type !== 'wall') continue
      const w0 = base.find((e) => e.id === w.id)
      const L = dist(w.a, w.b), dL = w0 ? L - dist(w0.a, w0.b) : 0
      const s0 = toS(w.a), s1 = toS(w.b)
      const m = [(s0[0] + s1[0]) / 2, (s0[1] + s1[1]) / 2]
      const nx = -(s1[1] - s0[1]), ny = s1[0] - s0[0], nl = Math.hypot(nx, ny) || 1
      const off = (w.thickness * view.scale) / 2 + 14
      const delta = Math.abs(dL) > 1e-6 ? `  (${dL > 0 ? '+' : '−'}${fmtLen(Math.abs(dL), unit)})` : ''
      labels.push({ k: 'dl' + w.id, x: m[0] + (nx / nl) * off, y: m[1] + (ny / nl) * off, text: LTR(`${fmtLen(L, unit)}${delta}${dh.info?.balanced ? '  =' : ''}`), strong: true })
    }
  }
  for (const e of here) if (e.type === 'room') {
    const c = e.polygon.reduce((a, p) => [a[0] + p[0] / e.polygon.length, a[1] + p[1] / e.polygon.length], [0, 0]); const s = toS(c)
    labels.push({ k: e.id, x: s[0], y: s[1], text: LTR(`${e.name || t('rt_' + e.room_type)} · ${Math.round(polygonArea(e.polygon) * 100) / 100}${unit}²`) })
  }
  // live drawing feedback
  const live = []
  let liveText = null
  if (app.calib) {
    const cp = app.calib.pts
    cp.forEach((q, i) => live.push(<Circle key={'cal' + i} x={q[0]} y={q[1]} radius={6 / view.scale} fill="#ff5a5a" stroke="#fff" strokeWidth={1.5} strokeScaleEnabled={false} listening={false} />))
    if (cp.length === 2) live.push(<Line key="calline" points={flat(cp)} stroke="#ff5a5a" strokeWidth={2} strokeScaleEnabled={false} listening={false} />)
  }
  const tr = typed ? typedResult() : null
  const lc = tr && cursor ? { ...cursor, p: tr.p } : cursor   // while typing, the preview follows the typed length
  if (tool === 'roomwiz' && cursor && app.roomSpec && app.roomSpec.w > 0 && app.roomSpec.d > 0) {
    const sp = app.roomSpec
    const [x, y] = anchorOrigin(sp.anchor, cursor.p, sp.w, sp.d)
    live.push(<Line key="lrw" points={flat([[x, y], [x + sp.w, y], [x + sp.w, y + sp.d], [x, y + sp.d]])} closed stroke={pal.sel} strokeWidth={2} strokeScaleEnabled={false} fill={pal.floor} opacity={0.8} listening={false} />)
    liveText = LTR(`${sp.name || t('rt_' + sp.type)}  ${fmtLen(sp.w, unit)} × ${fmtLen(sp.d, unit)}`)
  }
  if (cursor && draft.length) {
    const last = draft[draft.length - 1]
    if (tool === 'wall') {
      live.push(<Line key="lw" points={flat([last, lc.p])} stroke={pal.sel} strokeWidth={Math.max(1, 0.2 * view.scale)} strokeScaleEnabled={false} opacity={0.6} listening={false} lineCap="butt" />)
      const L = dist(last, lc.p); const ang = (Math.atan2(lc.p[1] - last[1], lc.p[0] - last[0]) * 180) / Math.PI
      liveText = LTR(`${fmtLen(L, unit)}  ∠${ang.toFixed(0)}°`)
    } else if (tool === 'circle') {
      const rr = dist(last, lc.p)
      const pts = arcPoints(last, rr, 0, 2 * Math.PI, 72)
      live.push(<Line key="lc" points={flat(pts)} closed stroke={pal.sel} strokeWidth={Math.max(1, 0.2 * view.scale)} strokeScaleEnabled={false} opacity={0.6} listening={false} />)
      liveText = LTR(`R ${fmtLen(rr, unit)}`)
    } else if (tool === 'arc') {
      if (draft.length === 1) live.push(<Line key="la" points={flat([last, lc.p])} stroke={pal.sel} strokeWidth={1.5} dash={[6, 4]} strokeScaleEnabled={false} listening={false} />)
      else {
        const g = arcThrough(draft[0], draft[1], lc.p)
        if (g) {
          live.push(<Line key="la" points={flat(arcPoints(g.c, g.r, g.a0, g.sweep, 48))} stroke={pal.sel} strokeWidth={Math.max(1, 0.2 * view.scale)} strokeScaleEnabled={false} opacity={0.6} listening={false} />)
          liveText = LTR(`R ${fmtLen(g.r, unit)}`)
        }
      }
    } else if (tool === 'beam') {
      live.push(<Line key="lb" points={flat([last, lc.p])} stroke={pal.beam} strokeWidth={2} dash={[8, 5]} strokeScaleEnabled={false} listening={false} />)
      liveText = fmtLen(dist(last, lc.p), unit)
    } else if (tool === 'stair') {
      const d = [lc.p[0] - last[0], lc.p[1] - last[1]]
      const ang = Math.round(((Math.atan2(d[1], d[0]) * 180) / Math.PI) / 5) * 5
      const demo = mk('stair', levelId, unit, { start: last, angle_deg: ang })
      live.push(<Line key="ls" points={flat(stairRect(demo))} closed stroke={pal.stair} strokeWidth={1.5} strokeScaleEnabled={false} listening={false} />)
      liveText = `${ang}°`
    } else if (POLY_TOOLS.includes(tool) && shape !== 'poly') {
      const pg = shapePolygon(shape, last, lc.p, tool, unit)
      if (pg) live.push(<Line key="lsh" points={flat(pg)} closed stroke={pal.sel} strokeWidth={1.5} strokeScaleEnabled={false} fill={pal.floor} listening={false} />)
      liveText = shape === 'circle' ? LTR(`R ${fmtLen(dist(last, lc.p), unit)}`) : LTR(`${fmtLen(Math.abs(lc.p[0] - last[0]), unit)} × ${fmtLen(Math.abs(lc.p[1] - last[1]), unit)}`)
    } else if (POLY_TOOLS.includes(tool)) {
      const pts = [...draft, lc.p]
      live.push(<Line key="lp" points={flat(pts)} closed={false} stroke={pal.sel} strokeWidth={1.5} strokeScaleEnabled={false} fill={pal.floor} listening={false} />)
      if (draft.length >= 2) liveText = `${polygonArea([...draft, lc.p]).toFixed(2)} ${unit}²`
    }
  }
  if (typed) liveText = `⌨ ${typed}${liveText ? `  →  ${liveText}` : ''}`
  const cs = cursor ? toS(cursor.p) : null

  const cursorCss = tool === 'hand' || space.current || panning ? (panning ? 'grabbing' : 'grab') : tool === 'select' || tool === 'move' ? 'default' : 'crosshair'

  return (
    <div ref={wrap} className="canvas-wrap" style={{ cursor: cursorCss }} onContextMenu={(e) => e.preventDefault()} data-testid="canvas-wrap">
      <Stage ref={stageRef} width={size.w} height={size.h}
        onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={() => { onUp(); setCursor(null) }}
        onTouchStart={(e) => { e.evt.preventDefault(); onDown(e) }} onTouchMove={(e) => { e.evt.preventDefault(); onMove(e) }} onTouchEnd={() => { onUp() }}
        onWheel={onWheel} style={{ touchAction: 'none' }}>
        <Layer listening={false}>
          <Rect x={0} y={0} width={size.w} height={size.h} fill={pal.bg} />
          <GridShape view={view} size={size} step={gstep} pal={pal} />
        </Layer>
        <UnderlayLayer underlays={project.underlays} pid={project.id} levelId={levelId} view={view} />
        <Layer listening={false}>
          <Group x={view.x} y={view.y} scaleX={view.scale} scaleY={-view.scale}>
            {project.site && <SiteGuide site={project.site} k={view.scale} pal={pal} u={{ m: 1, cm: 100, mm: 1000, ft: 3.28084, in: 39.3701 }[unit]} />}
            {below.map((e) => <Elem key={e.id} e={e} byId={belowById} ext={belowExt} pal={pal} ghost />)}
            {here.filter((e) => e.type === 'floor' || e.type === 'room' || e.type === 'roof').map((e) => <Elem key={e.id} e={e} byId={byId} ext={ext} pal={pal} selected={selection.includes(e.id)} />)}
            {here.filter((e) => !['floor', 'room', 'roof', 'door', 'window', 'opening'].includes(e.type)).map((e) => <Elem key={e.id} e={e} byId={byId} ext={ext} pal={pal} selected={selection.includes(e.id)} />)}
            {here.filter((e) => ['door', 'window', 'opening'].includes(e.type)).map((e) => <Elem key={e.id} e={e} byId={byId} ext={ext} pal={pal} selected={selection.includes(e.id)} />)}
            {live}
          </Group>
        </Layer>
        <Layer listening={false}>
          {labels.map((l) => (
            <Group key={l.k} x={l.x} y={l.y}>
              <Text text={l.text} fontSize={l.strong ? 13 : 11} fontStyle={l.strong ? 'bold' : 'normal'} fill={l.strong ? pal.sel : pal.text} offsetX={(l.text.length - 2) * (l.strong ? 3.4 : 3)} offsetY={6} />
            </Group>
          ))}
          {handles.map((h, i) => { const s = toS(h); return <Rect key={i} x={s[0] - 5} y={s[1] - 5} width={10} height={10} fill={pal.bg} stroke={pal.sel} strokeWidth={2} /> })}
          {sideHandles.map((h, i) => { const s = toS(h); return <Rect key={'s' + i} x={s[0]} y={s[1] - 5} width={9} height={9} rotation={45} fill={pal.sel} stroke={pal.bg} strokeWidth={1} /> })}
          {cs && !panning && (tool !== 'select' && tool !== 'move' && tool !== 'hand' && tool !== 'delete') && (
            cursor.kind === 'point' ? <Circle x={cs[0]} y={cs[1]} radius={7} stroke={pal.snap} strokeWidth={2} />
              : cursor.kind === 'wall' ? <Rect x={cs[0] - 5} y={cs[1] - 5} width={10} height={10} rotation={45} offsetX={0} offsetY={0} stroke={pal.snap} strokeWidth={2} />
                : <Rect x={cs[0] - 4} y={cs[1] - 4} width={8} height={8} stroke={pal.sel} strokeWidth={1.5} />
          )}
          {cs && liveText && <Text x={cs[0] + 14} y={cs[1] + 12} text={liveText} fontSize={12} fill={pal.text} padding={3} />}
        </Layer>
      </Stage>
      <div className="canvas-status" aria-live="polite">
        <span dir="ltr">{cursor ? `${(Math.round(cursor.p[0] * 1000) / 1000)}, ${(Math.round(cursor.p[1] * 1000) / 1000)} ${unit}` : ''}</span>
        <span>{level ? level.name : ''}</span>
        <span>{t(POLY_TOOLS.includes(tool) && shape !== 'poly' ? 'hint_shape_' + shape : (TOOL_HINT[tool] || 'hint_select'))}</span>
      </div>
      <div className="zoom-box">
        <button type="button" onClick={() => zoomAt([size.w / 2, size.h / 2], 1.25)} aria-label="+">+</button>
        <button type="button" onClick={() => zoomAt([size.w / 2, size.h / 2], 0.8)} aria-label="−">−</button>
        <button type="button" onClick={fit} title={t('zoom_fit')} aria-label={t('zoom_fit')}>⤢</button>
      </div>
    </div>
  )
}
