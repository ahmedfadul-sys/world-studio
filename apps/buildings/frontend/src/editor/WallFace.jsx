import { useEffect, useMemo, useRef, useState } from 'react'
import { Circle, Group, Layer, Line, Rect, Shape, Stage } from 'react-konva'
import { useApp } from '../store.jsx'
import { Icon, Field, NumField, Select, Toggle } from '../ui.jsx'
import { ALL_SHAPES, GLYPH, arrayPoly, centreOnWall, faceTargets, mirrorPoly, rotatePoly, shapePolygon, snapMove, snapPoint } from '../faceTools.js'
import {
  FACE_SHAPES, battlementFeatures, dist, faceShapePolygon, fitPolyToBBox, frameFeatures, fromM, makeFeature,
  pointInPolygon, polyBBox, snapStep, translatePoly, wallLength,
} from '../model.js'

const KINDS = ['cut', 'recess', 'relief']
const COLORS = {
  cut: { fill: 'rgba(0,0,0,0.55)', stroke: '#e5584f' },
  recess: { fill: 'rgba(40,90,170,0.45)', stroke: '#3da5ff' },
  relief: { fill: 'rgba(80,190,120,0.55)', stroke: '#46c27a' },
}
const TOOLS = ['select', ...ALL_SHAPES, 'polygon']
const ICON = { select: 'select', rect: 'rect', circle: 'circle', arch: 'opening', triangle: 'triangle', star: 'star', polygon: 'poly' }
const flat = (pts) => pts.flatMap((p) => p)
const r6 = (v) => Math.round(v * 1e6) / 1e6

/** Second 2D editor: the face (elevation) of ONE wall. Shapes drawn here become real geometry in 3D. */
export default function WallFace() {
  const app = useApp()
  const { project, t, theme } = app
  const wall = project.elements.find((e) => e.id === app.faceWall && e.type === 'wall')
  const unit = project.units.name
  const step = snapStep(project)
  const wrap = useRef(null)
  const [size, setSize] = useState({ w: 800, h: 520 })
  const [view, setView] = useState(null)
  const [tool, setTool] = useState('select')
  const [newKind, setNewKind] = useState('cut')
  const [sel, setSel] = useState(null)
  const [draft, setDraft] = useState([])
  const [cursor, setCursor] = useState(null)
  const [snapGrid, setSnapGrid] = useState(true)
  const [snapTg, setSnapTg] = useState(true)
  const [angle, setAngle] = useState(0)             // rotation applied to newly drawn shapes
  const [barW, setBarW] = useState(() => fromM(0.1, unit))
  const [guides, setGuides] = useState([])
  const [newFace, setNewFace] = useState(app.faceSide || 'right')
  const [arr, setArr] = useState({ n: 3, du: fromM(1, unit), dv: 0 })
  const [ov, setOv] = useState(null)            // live polygon during a drag: {id, polygon}
  const drag = useRef(null)
  const lastClick = useRef({ t: 0, x: -9, y: -9 })

  const L = wall ? wallLength(wall) : 1
  const lvl = wall ? project.levels.find((l) => l.id === wall.level_id) : null
  const H = wall ? (wall.height || lvl?.height || 3) : 3
  const feats = wall?.features || []
  const openings = useMemo(() => (wall ? project.elements.filter((e) => e.wall_id === wall.id) : []), [project.elements, wall])
  const selF = feats.find((f) => f.id === sel) || null

  useEffect(() => {
    const el = wrap.current
    if (!el) return undefined
    const ro = new ResizeObserver(([e]) => setSize({ w: Math.max(200, Math.round(e.contentRect.width)), h: Math.max(200, Math.round(e.contentRect.height)) }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const fit = () => {
    const pad = 50
    const scale = Math.min((size.w - 2 * pad) / L, (size.h - 2 * pad) / (H * 1.25))
    setView({ scale, x: (size.w - L * scale) / 2, y: size.h - pad - (H * 0.1) * scale })
  }
  useEffect(() => { if (wall && (!view || !view.fitted)) { fit(); setView((v) => v && { ...v, fitted: true }) } }, [wall?.id, size.w, size.h]) // eslint-disable-line react-hooks/exhaustive-deps
  const vw = view || { scale: 40, x: 40, y: size.h - 40 }
  const toS = (p) => [vw.x + p[0] * vw.scale, vw.y - p[1] * vw.scale]
  const toW = (sx, sy) => [(sx - vw.x) / vw.scale, (vw.y - sy) / vw.scale]
  const tol = 9 / vw.scale
  const tg = useMemo(() => faceTargets(L, H, openings, feats, drag.current && drag.current.id), [L, H, openings, feats, ov]) // eslint-disable-line react-hooks/exhaustive-deps
  /** snapped point + guide lines; Alt = free (no snapping at all) */
  const snapAt = (raw, free, anchor) => {
    if (free) { setGuides([]); return raw }
    const r = snapPoint(raw, tg, { tol, step, grid: snapGrid, targets: snapTg, anchor })
    setGuides(r.guides)
    return r.p
  }
  const snap = (raw, free) => snapAt(raw, free, null)

  const MAX_FEATURES = 300      // server limit per wall: never send more (the save would be refused)
  const setFeatures = (fn, key) => {
    const next = fn(wall.features || [])
    if (next.length > MAX_FEATURES) app.toast(t('wf_limit'), 'error')
    app.edit((p) => ({ ...p, elements: p.elements.map((e) => (e.id === wall.id ? { ...e, features: next.slice(0, MAX_FEATURES) } : e)) }), key)
  }
  const patchF = (id, patch, key) => setFeatures((fs) => fs.map((f) => (f.id === id ? { ...f, ...patch } : f)), key)
  const defDepth = (kind) => (kind === 'cut' ? fromM(0.05, unit) : Math.min(fromM(0.05, unit), wall.thickness * 0.5))

  const addFeature = (shape, polygon) => {
    const f = makeFeature(newKind, shape, polygon, defDepth(newKind), newFace)
    setFeatures((fs) => [...fs, f])
    setSel(f.id)
  }

  useEffect(() => {
    if (!wall) return undefined
    const down = (e) => {
      const a = document.activeElement
      if (a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || a.tagName === 'SELECT')) return
      const mod = e.ctrlKey || e.metaKey
      if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); e.shiftKey ? app.redo() : app.undo(); return }
      if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); app.redo(); return }
      if (e.key === 'Escape') { if (draft.length) setDraft([]); else if (sel) setSel(null); else if (tool !== 'select') setTool('select'); else app.set({ faceWall: null }); return }
      if ((e.key === 'Delete' || e.key === 'Backspace') && sel) { setFeatures((fs) => fs.filter((f) => f.id !== sel)); setSel(null); return }
      if (e.key === 'Enter' && tool === 'polygon') finishPoly()
    }
    window.addEventListener('keydown', down)
    return () => window.removeEventListener('keydown', down)
  })

  if (!wall) return null

  const finishPoly = () => {
    if (draft.length >= 3) addFeature('polygon', draft.map((p) => [...p]))
    setDraft([])
  }

  const world = (e) => {
    const st = e.target.getStage(); const pp = st.getPointerPosition()
    return { sp: [pp.x, pp.y], raw: toW(pp.x, pp.y) }
  }
  const poly = (f) => (ov && ov.id === f.id ? ov.polygon : f.polygon)

  const onDown = (e) => {
    const evt = e.evt
    const { sp, raw } = world(e)
    if (evt.button === 1 || evt.button === 2) { drag.current = { kind: 'pan', sp, vx: vw.x, vy: vw.y }; return }
    const p = snapAt(raw, evt.altKey, draft.length && tool !== 'polygon' ? draft[0] : null)
    const now = performance.now()
    const lc = lastClick.current
    const dbl = now - lc.t < 350 && Math.hypot(sp[0] - lc.x, sp[1] - lc.y) < 8
    lastClick.current = { t: now, x: sp[0], y: sp[1] }
    if (tool === 'select') {
      if (selF) {   // handles first: 4 bbox corners (+ vertices of free polygons)
        const bx = polyBBox(poly(selF))
        const corners = [[bx.x0, bx.y0], [bx.x1, bx.y0], [bx.x1, bx.y1], [bx.x0, bx.y1]]
        for (let i = 0; i < 4; i++) { const s = toS(corners[i]); if (Math.hypot(s[0] - sp[0], s[1] - sp[1]) <= 10) { drag.current = { kind: 'corner', id: selF.id, i, bx, orig: selF.polygon }; return } }
        if (selF.shape === 'polygon') for (let i = 0; i < selF.polygon.length; i++) { const s = toS(selF.polygon[i]); if (Math.hypot(s[0] - sp[0], s[1] - sp[1]) <= 8) { drag.current = { kind: 'vertex', id: selF.id, i, orig: selF.polygon }; return } }
      }
      const hit = [...feats].reverse().find((f) => pointInPolygon(raw, f.polygon))
      if (hit) { setSel(hit.id); drag.current = { kind: 'move', id: hit.id, start: raw, orig: hit.polygon, moved: false } } else { setSel(null); drag.current = { kind: 'pan', sp, vx: vw.x, vy: vw.y } }
      return
    }
    if (tool === 'polygon') {
      if (dbl) { finishPoly(); return }
      if (draft.length >= 3 && dist(draft[0], p) < step * 0.5) { finishPoly(); return }
      if (!draft.length || dist(draft[draft.length - 1], p) > 1e-6) setDraft([...draft, p])
      return
    }
    // two-click shapes
    if (!draft.length) { setDraft([p]); return }
    const pg = shapePolygon(tool, draft[0], p, { angle, barWidth: barW })
    if (pg) addFeature(tool, pg)
    setDraft([])
  }

  const onMove = (e) => {
    const { sp, raw } = world(e)
    const free = e.evt.altKey
    const d = drag.current
    const anchor = d && d.kind === 'corner' ? [[d.bx.x1, d.bx.y1], [d.bx.x0, d.bx.y1], [d.bx.x0, d.bx.y0], [d.bx.x1, d.bx.y0]][d.i] : !d && draft.length && tool !== 'polygon' ? draft[0] : null
    const p = d && d.kind === 'move' ? raw : snapAt(raw, free, anchor)
    setCursor(p)
    if (!d) return
    if (d.kind === 'pan') { setView({ ...vw, x: d.vx + sp[0] - d.sp[0], y: d.vy + sp[1] - d.sp[1] }); return }
    if (d.kind === 'move') {
      let du = raw[0] - d.start[0], dv = raw[1] - d.start[1]
      if (free) setGuides([]); else { const m = snapMove(polyBBox(d.orig), du, dv, tg, { tol, step, grid: snapGrid, targets: snapTg }); du = m.du; dv = m.dv; setGuides(m.guides) }
      if (du || dv) { d.moved = true; setOv({ id: d.id, polygon: translatePoly(d.orig, du, dv) }) }
    } else if (d.kind === 'corner') {
      const b = { ...d.bx }
      const opp = [(d.i + 2) % 4]
      const ox = [d.bx.x0, d.bx.x1, d.bx.x1, d.bx.x0][opp], oy = [d.bx.y0, d.bx.y0, d.bx.y1, d.bx.y1][opp]
      b.x0 = Math.min(ox, p[0]); b.x1 = Math.max(ox, p[0]); b.y0 = Math.min(oy, p[1]); b.y1 = Math.max(oy, p[1])
      if (b.x1 - b.x0 > 1e-6 && b.y1 - b.y0 > 1e-6) setOv({ id: d.id, polygon: fitPolyToBBox(d.orig, d.bx, b) })
    } else if (d.kind === 'vertex') {
      setOv({ id: d.id, polygon: d.orig.map((q, i) => (i === d.i ? p : q)) })
    }
  }

  const onUp = () => {
    const d = drag.current
    drag.current = null
    setGuides([])
    if (d && ov && d.id === ov.id) patchF(ov.id, { polygon: ov.polygon })
    setOv(null)
  }

  const onWheel = (e) => {
    e.evt.preventDefault()
    const { sp } = world(e)
    const k = e.evt.deltaY < 0 ? 1.12 : 1 / 1.12
    const scale = Math.min(Math.max(vw.scale * k, 2), 4000)
    const f = scale / vw.scale
    setView({ ...vw, scale, x: sp[0] - (sp[0] - vw.x) * f, y: sp[1] - (sp[1] - vw.y) * f })
  }

  // ------------------------------------------------------------ drawing helpers
  const wallBox = [[0, 0], [L, 0], [L, H], [0, H]]
  const live = []
  if (draft.length && cursor) {
    if (tool === 'polygon') live.push(<Line key="lv" points={flat([...draft, cursor])} stroke={COLORS[newKind].stroke} strokeWidth={1.5} dash={[6, 4]} strokeScaleEnabled={false} />)
    else { const pg = shapePolygon(tool, draft[0], cursor, { angle, barWidth: barW }); if (pg) live.push(<Line key="lv" points={flat(pg)} closed fill={COLORS[newKind].fill} stroke={COLORS[newKind].stroke} strokeWidth={1.5} strokeScaleEnabled={false} />) }
  }
  const dark = theme === 'dark'
  const bx = selF ? polyBBox(poly(selF)) : null
  const r3 = (v) => Math.round(v * 1000) / 1000
  const label = cursor ? `u ${r3(cursor[0])}  v ${r3(cursor[1])} ${unit}` : ''
  const sizeTxt = bx ? `${r3(bx.x1 - bx.x0)} × ${r3(bx.y1 - bx.y0)} ${unit}` : ''

  const addBattlements = () => { setFeatures((fs) => [...fs, ...battlementFeatures(L, H, unit)]); setSel(null) }
  const addFrame = () => {
    const o = openings[0]
    const box = o ? { x0: o.offset - o.width / 2 - fromM(0.1, unit), y0: (o.sill || 0) - fromM(0.05, unit), x1: o.offset + o.width / 2 + fromM(0.1, unit), y1: (o.sill || 0) + o.height + fromM(0.1, unit) }
      : { x0: L * 0.25, y0: H * 0.25, x1: L * 0.75, y1: H * 0.75 }
    box.y0 = Math.max(0, box.y0)
    setFeatures((fs) => [...fs, ...frameFeatures(box, fromM(0.08, unit), fromM(0.03, unit))])
  }

  return (
    <div className="wf-overlay" role="dialog" aria-modal="true" aria-label={t('wf_title')}>
      <div className="wf-dialog">
        <header className="wf-head">
          <h3>{t('wf_title')} — {wall.name || wall.id} <span className="muted">({r6(L)} × {r6(H)} {unit})</span></h3>
          <div className="row">
            <button type="button" className="icon-btn" onClick={app.undo} title={`${t('undo')} (Ctrl+Z)`} aria-label={t('undo')}><Icon name="undo" /></button>
            <button type="button" className="icon-btn" onClick={app.redo} title={`${t('redo')} (Ctrl+Y)`} aria-label={t('redo')}><Icon name="redo" /></button>
            <button type="button" className="icon-btn" onClick={() => { setView(null); setTimeout(fit, 0) }} title={t('zoom_fit')} aria-label={t('zoom_fit')}><Icon name="fit" /></button>
            <button type="button" className="btn primary" data-testid="wf-close" onClick={() => app.set({ faceWall: null })}>{t('wf_close')}</button>
          </div>
        </header>
        <div className="wf-body">
          <div className="toolbar wf-tools" role="toolbar" aria-label={t('wf_title')} style={{ overflowY: 'auto' }}>
            {TOOLS.map((k) => (
              <button key={k} type="button" className={`tool ${tool === k ? 'on' : ''}`} data-wftool={k} aria-pressed={tool === k} title={t('wf_tool_' + k)} aria-label={t('wf_tool_' + k)} onClick={() => { setTool(k); setDraft([]) }}>{ICON[k] ? <Icon name={ICON[k]} /> : <span className="glyph">{GLYPH[k]}</span>}</button>
            ))}
          </div>
          <div className="wf-canvas" ref={wrap} data-testid="wf-canvas">
            <Stage width={size.w} height={size.h} onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp} onWheel={onWheel} onContextMenu={(e) => e.evt.preventDefault()}
              onTouchStart={onDown} onTouchMove={onMove} onTouchEnd={onUp} style={{ cursor: tool === 'select' ? 'default' : 'crosshair' }}>
              <Layer>
                <Shape listening={false} sceneFunc={(ctx) => {
                  let st = step
                  while (st * vw.scale < 12) st *= 5
                  ctx.lineWidth = 1; ctx.strokeStyle = dark ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.08)'
                  const u0 = Math.floor(-vw.x / vw.scale / st) * st, u1 = (size.w - vw.x) / vw.scale
                  for (let u = u0; u <= u1; u += st) { const x = Math.round(u * vw.scale + vw.x) + 0.5; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, size.h); ctx.stroke() }
                  const v0 = Math.floor((vw.y - size.h) / vw.scale / st) * st, v1 = vw.y / vw.scale
                  for (let v = v0; v <= v1; v += st) { const y = Math.round(-v * vw.scale + vw.y) + 0.5; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(size.w, y); ctx.stroke() }
                }} />
                <Group x={vw.x} y={vw.y} scaleX={vw.scale} scaleY={-vw.scale}>
                  <Line points={flat(wallBox)} closed fill={dark ? '#4a5160' : '#cfc9bb'} stroke={dark ? '#aab3c2' : '#5b6370'} strokeWidth={2} strokeScaleEnabled={false} listening={false} />
                  {openings.map((o) => {
                    const w = o.width, h = o.height, sill = o.sill || 0
                    return <Rect key={o.id} x={o.offset - w / 2} y={sill} width={w} height={h} fill={o.type === 'window' ? 'rgba(120,180,220,0.55)' : 'rgba(140,90,50,0.6)'} stroke="#8a5a33" strokeWidth={1} strokeScaleEnabled={false} listening={false} dash={[4, 3]} />
                  })}
                  {feats.map((f) => {
                    const pts = poly(f); const c = COLORS[f.kind]; const on = f.id === sel
                    return <Line key={f.id} points={flat(pts)} closed fill={c.fill} stroke={on ? '#ffffff' : c.stroke} strokeWidth={on ? 2.5 : 1.5} strokeScaleEnabled={false} dash={f.kind === 'recess' ? [5, 3] : undefined} listening={false} />
                  })}
                  {live}
                  {guides.map((g, i) => (g.axis === 'u' ? <Line key={'g' + i} points={[g.value, -L, g.value, H + L]} stroke={g.kind === 'size' ? '#ffb02e' : '#ff4fd8'} strokeWidth={1} dash={[5, 4]} strokeScaleEnabled={false} listening={false} /> : <Line key={'g' + i} points={[-L, g.value, 2 * L, g.value]} stroke={g.kind === 'size' ? '#ffb02e' : '#ff4fd8'} strokeWidth={1} dash={[5, 4]} strokeScaleEnabled={false} listening={false} />))}
                </Group>
                {selF && tool === 'select' && bx && (() => {
                  const cs = [[bx.x0, bx.y0], [bx.x1, bx.y0], [bx.x1, bx.y1], [bx.x0, bx.y1]].map(toS)
                  return (
                    <>
                      <Line points={flat(cs)} closed stroke="#ffffff" strokeWidth={1} dash={[4, 3]} listening={false} />
                      {cs.map((c, i) => <Rect key={i} x={c[0] - 5} y={c[1] - 5} width={10} height={10} fill="#3da5ff" stroke="#fff" strokeWidth={1} listening={false} />)}
                      {selF.shape === 'polygon' && poly(selF).map((q, i) => { const s = toS(q); return <Circle key={'v' + i} x={s[0]} y={s[1]} radius={4} fill="#ffd34d" stroke="#000" strokeWidth={1} listening={false} /> })}
                    </>
                  )
                })()}
              </Layer>
            </Stage>
            <div className="wf-status" dir="ltr">{label}{sizeTxt && `   ·   ${sizeTxt}`}</div>
            <div className="wf-hint">{t(tool === 'select' ? 'wf_hint_select' : tool === 'polygon' ? 'wf_hint_polygon' : tool === 'circle' || tool === 'star' ? 'wf_hint_radius' : tool === 'slot' ? 'wf_hint_slot' : 'wf_hint_box')}</div>
          </div>
          <aside className="wf-side">
            <h4>{t('wf_new_kind')}</h4>
            <div className="seg" role="group">
              {KINDS.map((k) => <button key={k} type="button" data-newkind={k} className={`btn small ${newKind === k ? 'primary' : ''}`} aria-pressed={newKind === k} onClick={() => setNewKind(k)}>{t('wf_' + k)}</button>)}
            </div>
            <p className="muted small">{t('wf_help_' + newKind)}</p>
            <h4>{t('wf_snap')}</h4>
            <Toggle checked={snapTg} label={t('wf_snap_tg')} onChange={setSnapTg} />
            <Toggle checked={snapGrid} label={t('wf_snap_grid')} onChange={setSnapGrid} />
            <p className="muted small">{t('wf_snap_help')}</p>
            <Select label={t('wf_face')} value={newFace} onChange={setNewFace} options={[{ value: 'right', label: t('wf_right') }, { value: 'left', label: t('wf_left') }]} />
            <Field label={`${t('wf_draw_angle')}: ${angle}°`}><input type="range" min={-90} max={90} step={5} value={angle} data-testid="wf-draw-angle" onChange={(e) => setAngle(+e.target.value)} /></Field>
            {tool === 'slot' && <Field label={`${t('wf_bar_w')} (${unit})`}><NumField value={barW} min={0.0001} onChange={(n) => setBarW(n)} /></Field>}
            <h4>{t('wf_presets')}</h4>
            <div className="row wrap">
              <button type="button" className="btn small" onClick={addBattlements}>{t('wf_battlements')}</button>
              <button type="button" className="btn small" onClick={addFrame}>{t('wf_frame')}</button>
            </div>
            <h4>{t('wf_features')} ({feats.length})</h4>
            <div className="wf-list">
              {!feats.length && <p className="muted">{t('wf_none')}</p>}
              {feats.map((f, i) => (
                <button key={f.id} type="button" className={`wf-item ${f.id === sel ? 'on' : ''}`} onClick={() => { setSel(f.id); setTool('select') }}>
                  <span className="wf-dot" style={{ background: COLORS[f.kind].stroke }} />{i + 1}. {t('wf_' + f.kind)} · {f.shape}
                </button>
              ))}
            </div>
            {selF && (
              <div className="wf-props">
                <h4>{t('wf_props')}</h4>
                <Select label={t('wf_kind')} value={selF.kind} onChange={(k) => patchF(selF.id, { kind: k })} options={KINDS.map((k) => ({ value: k, label: t('wf_' + k) }))} />
                {selF.kind !== 'cut' && (
                  <>
                    <Select label={t('wf_face')} value={selF.face} onChange={(v) => patchF(selF.id, { face: v })} options={[{ value: 'right', label: t('wf_right') }, { value: 'left', label: t('wf_left') }]} />
                    <Field label={`${t('wf_depth')} (${unit})`}>
                      <NumField value={selF.depth} min={0.0001} max={selF.kind === 'recess' ? wall.thickness * 0.95 : undefined} onChange={(n) => patchF(selF.id, { depth: n }, `fdepth:${selF.id}`)} />
                    </Field>
                  </>
                )}
                <h4>{t('wf_transform')}</h4>
                <div className="row wrap">
                  {[-45, -15, 15, 45, 90].map((a) => <button key={a} type="button" className="btn small" data-testid={`wf-rot${a}`} onClick={() => patchF(selF.id, { polygon: rotatePoly(selF.polygon, a), shape: selF.shape === 'rect' || selF.shape === 'circle' ? (a % 90 === 0 && selF.shape === 'rect' ? 'rect' : 'polygon') : selF.shape })}>{a > 0 ? '+' : ''}{a}°</button>)}
                </div>
                <Field label={t('wf_angle_to')}><NumField value={0} step={1} onChange={(n) => n && patchF(selF.id, { polygon: rotatePoly(selF.polygon, n), shape: 'polygon' })} /></Field>
                <div className="row wrap">
                  <button type="button" className="btn small" onClick={() => patchF(selF.id, { polygon: mirrorPoly(selF.polygon, 'h') })}>{t('wf_mirror_h')}</button>
                  <button type="button" className="btn small" onClick={() => patchF(selF.id, { polygon: mirrorPoly(selF.polygon, 'v') })}>{t('wf_mirror_v')}</button>
                  <button type="button" className="btn small" data-testid="wf-centre-h" onClick={() => patchF(selF.id, { polygon: centreOnWall(selF.polygon, L, H, 'h') })}>{t('wf_centre_h')}</button>
                  <button type="button" className="btn small" onClick={() => patchF(selF.id, { polygon: centreOnWall(selF.polygon, L, H, 'v') })}>{t('wf_centre_v')}</button>
                </div>
                <h4>{t('wf_array')}</h4>
                <div className="row wrap">
                  <Field label="×"><NumField value={arr.n} min={2} max={60} step={1} onChange={(n) => setArr({ ...arr, n: Math.round(n) })} /></Field>
                  <Field label={`Δu (${unit})`}><NumField value={arr.du} onChange={(n) => setArr({ ...arr, du: n })} /></Field>
                  <Field label={`Δv (${unit})`}><NumField value={arr.dv} onChange={(n) => setArr({ ...arr, dv: n })} /></Field>
                </div>
                <button type="button" className="btn small" data-testid="wf-array" onClick={() => setFeatures((fs) => [...fs, ...Array.from({ length: Math.max(1, arr.n - 1) }, (_, i) => ({ ...selF, id: makeFeature('cut', 'rect', [], 0).id, polygon: arrayPoly(selF.polygon, i + 1, arr.du, arr.dv) }))])}>{t('wf_array_go')}</button>
                <div className="row wrap">
                  <button type="button" className="btn small" onClick={() => { const c = { ...selF, id: makeFeature('cut', 'rect', [], 0).id, polygon: translatePoly(selF.polygon, fromM(0.3, unit), 0) }; setFeatures((fs) => [...fs, c]); setSel(c.id) }}>{t('wf_duplicate')}</button>
                  <button type="button" className="btn small danger" data-testid="wf-delete" onClick={() => { setFeatures((fs) => fs.filter((f) => f.id !== selF.id)); setSel(null) }}>{t('delete')}</button>
                </div>
              </div>
            )}
          </aside>
        </div>
      </div>
    </div>
  )
}
