import { useApp } from '../store.jsx'
import { Card, Field, NumField, Select, Toggle } from '../ui.jsx'
import { fromM, toM } from '../model.js'
import { guideLines, makeGuide } from '../guides.js'
import { ensureRoadMaterials, lampsAlongRoad, ROAD_PRESETS, SURFACES } from '../roads.js'
import { useState } from 'react'

export const SURF_COLOR = { asphalt: '#3a3b3e', dirt: '#8a6a44', stone: '#8f8a7d', gravel: '#9a9488', paving: '#a9998a', concrete: '#9b9b9b', sand: '#d8c690' }

/** Options bar of the road tool (top of the canvas): surface swatches, width, sidewalk. Picking a surface loads its usual widths. */
export function RoadPanel() {
  const app = useApp()
  const { t } = app
  const sp = app.roadSpec || { surface: 'asphalt', width: ROAD_PRESETS.asphalt.width, sidewalk: ROAD_PRESETS.asphalt.sidewalk }
  const up = (patch) => app.set({ roadSpec: { ...sp, ...patch } })
  return (
    <div className="opts road-opts" role="group" aria-label={t('rd_title')} data-testid="road-panel">
      <strong>{t('rd_title')}</strong>
      <div className="swatches" role="radiogroup" aria-label={t('rd_surface')}>
        {SURFACES.map((s) => (
          <button key={s} type="button" role="radio" aria-checked={sp.surface === s} aria-label={t('sf_' + s)} title={t('sf_' + s)} className={`sw ${sp.surface === s ? 'on' : ''}`} style={{ background: SURF_COLOR[s] }} onClick={() => up({ surface: s, ...ROAD_PRESETS[s] })} />
        ))}
      </div>
      <label className="optf"><span>{t('rd_width')}</span><NumField value={sp.width} min={0.5} max={100} onChange={(width) => up({ width })} /><em>m</em></label>
      <label className="optf"><span>{t('rd_sidewalk')}</span><NumField value={sp.sidewalk} min={0} max={20} onChange={(sidewalk) => up({ sidewalk })} /><em>m</em></label>
      <label className="optf"><span>{t('lp_spacing')}</span><NumField value={app.lampSpacing ?? 25} min={3} max={200} onChange={(lampSpacing) => app.set({ lampSpacing })} /><em>m</em></label>
      <span className="opt-hint muted small">{t('hint_road')}</span>
    </div>
  )
}

/** Inspector extras for a selected road: add street lamps along it. */
export function RoadLamps({ road }) {
  const app = useApp()
  const { t, project } = app
  const unit = project.units.name
  const spacing = app.lampSpacing ?? 25
  const setSpacing = (lampSpacing) => app.set({ lampSpacing })
  const [side, setSide] = useState('both')
  const add = () => {
    const lamps = lampsAlongRoad(road, road.level_id, unit, { spacingM: spacing, side })
    app.edit((p) => ({ ...p, materials: ensureRoadMaterials(p.materials, []), elements: [...p.elements, ...lamps] }))
    app.toast(`${t('lp_added')}: ${lamps.length}`, 'info')
  }
  return (
    <div className="stair-tools" data-testid="road-lamps">
      <NumField label={`${t('lp_spacing')} (m)`} value={spacing} min={3} max={200} onChange={setSpacing} />
      <Select label={t('lp_side')} value={side} onChange={setSide} options={['both', 'left', 'right'].map((v) => ({ value: v, label: t('lp_side_' + v) }))} />
      <button type="button" className="btn small primary" data-testid="road-add-lamps" onClick={add}>{t('lp_add_along')}</button>
    </div>
  )
}

const GK = ['grid', 'parallel', 'radial', 'line']

/** City-plan guides (2D editor only): parallel lines / grids / radial plans / single lines. Never reach the 3D preview or exports. */
export function GuidePanel() {
  const app = useApp()
  const { t, project } = app
  const unit = project.units.name
  const guides = project.guides || []
  const [kind, setKind] = useState('grid')
  const set = (fn) => app.edit((p) => ({ ...p, guides: fn(p.guides || []) }))
  const upd = (id, patch) => set((gs) => gs.map((g) => (g.id === id ? { ...g, ...patch } : g)))
  const add = () => {
    const bb = window.__bimView && window.__bimView()
    set((gs) => [...gs, makeGuide(kind, unit, { name: `${t('gd_' + kind)} ${gs.length + 1}`, origin: bb || [0, 0] })])
  }
  return (
    <Card title={t('gd_title')} className="guide-panel" fold="guides" badge={guides.length}>
      <p className="muted small">{t('gd_hint')}</p>
      <div className="row wrap">
        <Select label={t('gd_kind')} value={kind} onChange={setKind} options={GK.map((k) => ({ value: k, label: t('gd_' + k) }))} />
        <button type="button" className="btn small primary" data-testid="gd-add" onClick={add}>{t('gd_add')}</button>
        <button type="button" className="btn small" data-testid="gd-draw" onClick={() => app.set({ tool: 'guide' })}>{t('gd_draw')}</button>
      </div>
      {guides.map((g) => (
        <details key={g.id} className="guide-item" data-testid="gd-item">
          <summary>
            <Toggle checked={g.visible} label={g.name || t('gd_' + g.kind)} onChange={(v) => upd(g.id, { visible: v })} />
          </summary>
          <div className="rw-size">
            <Field label="X"><NumField value={g.origin[0]} onChange={(v) => upd(g.id, { origin: [v, g.origin[1]] })} /></Field>
            <Field label="Y"><NumField value={g.origin[1]} onChange={(v) => upd(g.id, { origin: [g.origin[0], v] })} /></Field>
          </div>
          {g.kind !== 'line' && <NumField label={`${t('gd_angle')} (°)`} value={g.angle_deg} min={-360} max={360} onChange={(v) => upd(g.id, { angle_deg: v })} />}
          {g.kind !== 'line' && (
            <div className="rw-size">
              <Field label={`${t('gd_sx')} (${unit})`}><NumField value={g.spacing_x} min={0.01} onChange={(v) => upd(g.id, { spacing_x: v })} /></Field>
              {(g.kind === 'grid') && <Field label={`${t('gd_sy')} (${unit})`}><NumField value={g.spacing_y} min={0.01} onChange={(v) => upd(g.id, { spacing_y: v })} /></Field>}
            </div>
          )}
          {g.kind !== 'line' && (
            <div className="rw-size">
              <Field label={g.kind === 'radial' ? t('gd_rings') : t('gd_cx')}><NumField value={g.count_x} min={1} max={200} step={1} onChange={(v) => upd(g.id, { count_x: Math.round(v) })} /></Field>
              {(g.kind === 'grid' || g.kind === 'radial') && <Field label={g.kind === 'radial' ? t('gd_spokes') : t('gd_cy')}><NumField value={g.count_y} min={1} max={200} step={1} onChange={(v) => upd(g.id, { count_y: Math.round(v) })} /></Field>}
            </div>
          )}
          {(g.kind === 'parallel') && <NumField label={`${t('gd_len')} (${unit})`} value={g.length} min={0.01} onChange={(v) => upd(g.id, { length: v })} />}
          <button type="button" className="btn small danger" onClick={() => set((gs) => gs.filter((x) => x.id !== g.id))}>{t('delete')}</button>
        </details>
      ))}
      {guides.length > 0 && <button type="button" className="btn small" onClick={() => set(() => [])}>{t('gd_clear')}</button>}
    </Card>
  )
}
