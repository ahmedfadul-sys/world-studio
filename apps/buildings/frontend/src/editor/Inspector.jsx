import { useMemo, useState } from 'react'
import { useApp } from '../store.jsx'
import { api, formatError } from '../api.js'
import { clampOpenings, deleteElements, dist, polygonArea, patchElement, applyModule, moduleFits, applySpecsToAll, POSITIONAL } from '../model.js'
import { Card, ErrorBox, Field, NumField, Select, Toggle, useModules } from '../ui.jsx'
import RoomWizard from './RoomWizard.jsx'
import UnderlayPanel from './UnderlayPanel.jsx'
import TemplatesPanel from './TemplatesPanel.jsx'
import RoomsPanel from './RoomsPanel.jsx'
import BalancePanel from './BalancePanel.jsx'
import { GuidePanel, RoadLamps, RoadPanel } from './CityPanels.jsx'
import { ROOM_TYPES, buildRoomParts, cloneElements, applyOverrides, fitStairSteps, rectInfo, resizeRect, stairFlights } from '../plan.js'

const L = (key, label, extra = {}) => ({ kind: 'num', key, label, min: 0.0001, ...extra })
const SCHEMA = {
  wall: [L('thickness', 'f_thickness'), { kind: 'num', key: 'height', label: 'f_height', min: 0.0001, nullable: true }, { kind: 'mat', key: 'material', label: 'f_material' }, { kind: 'mat', key: 'material_inner', label: 'f_material_inner' }],
  door: [L('offset', 'f_offset', { min: 0 }), L('width', 'f_width'), L('height', 'f_height'), L('sill', 'f_sill', { min: 0 }), { kind: 'sel', key: 'hinge', label: 'f_hinge', options: ['left', 'right'], prefix: 'v_' }, { kind: 'sel', key: 'swing', label: 'f_swing', options: ['left', 'right'], prefix: 'v_' }, { kind: 'mat', key: 'material', label: 'f_material' }],
  window: [L('offset', 'f_offset', { min: 0 }), L('width', 'f_width'), L('height', 'f_height'), L('sill', 'f_sill', { min: 0 }), { kind: 'mat', key: 'material', label: 'f_material' }],
  opening: [L('offset', 'f_offset', { min: 0 }), L('width', 'f_width'), L('height', 'f_height'), L('sill', 'f_sill', { min: 0 }), { kind: 'sel', key: 'shape', label: 'f_shape', options: ['rect', 'arch'], prefix: 'v_' }],
  column: [{ kind: 'sel', key: 'shape', label: 'f_shape', options: ['box', 'round'], prefix: 'v_' }, L('width', 'f_width'), L('depth', 'f_depth'), { kind: 'num', key: 'height', label: 'f_height', min: 0.0001, nullable: true }, { kind: 'mat', key: 'material', label: 'f_material' }],
  beam: [L('width', 'f_width'), L('depth', 'f_depth'), { kind: 'num', key: 'top', label: 'f_top', min: 0.0001, nullable: true }, { kind: 'mat', key: 'material', label: 'f_material' }],
  floor: [{ kind: 'sel', key: 'kind', label: 'f_kind', options: ['floor', 'ceiling', 'balcony'], prefix: 'v_' }, L('thickness', 'f_thickness'), { kind: 'num', key: 'z_offset', label: 'f_z', min: -1e6 }, { kind: 'mat', key: 'material', label: 'f_material' }],
  roof: [{ kind: 'sel', key: 'kind', label: 'f_kind', options: ['flat', 'shed', 'gable', 'hip', 'cone', 'dome', 'barrel'], prefix: 'v_' }, { kind: 'num', key: 'pitch_deg', label: 'f_pitch', min: 0, max: 79.9 }, L('overhang', 'f_overhang', { min: 0 }), L('thickness', 'f_thickness'), { kind: 'sel', key: 'ridge_axis', label: 'f_ridge', options: ['x', 'y'] }, { kind: 'mat', key: 'material', label: 'f_material' }],
  road: [{ kind: 'sel', key: 'surface', label: 'rd_surface', options: ['asphalt', 'dirt', 'stone', 'gravel', 'paving', 'concrete', 'sand'], prefix: 'sf_' }, L('width', 'rd_width'), L('sidewalk', 'rd_sidewalk', { min: 0 }), L('curb_height', 'rd_curb', { min: 0 }), L('thickness', 'f_thickness'), { kind: 'mat', key: 'material', label: 'f_material' }, { kind: 'mat', key: 'sidewalk_material', label: 'rd_sidewalk_mat' }],
  lamp: [L('height', 'f_height'), L('arm', 'lp_arm', { min: 0 }), { kind: 'num', key: 'arm_deg', label: 'lp_arm_deg', min: -360, max: 360 }, L('pole_radius', 'lp_pole_r'), { kind: 'bool', key: 'light', label: 'lp_light' }, { kind: 'color', key: 'color', label: 'lp_color' }, { kind: 'num', key: 'intensity', label: 'lp_intensity', min: 0 }, L('range', 'lp_range'), { kind: 'mat', key: 'material', label: 'f_material' }],
  stair: [{ kind: 'sel', key: 'kind', label: 'f_kind', options: ['straight', 'spiral'], prefix: 'v_' }, { kind: 'num', key: 'steps', label: 'f_steps', min: 1, max: 200, step: 1 }, L('rise', 'f_rise'), L('run', 'f_run'), L('width', 'f_width'), { kind: 'num', key: 'angle_deg', label: 'f_angle', min: -360, max: 360 }, { kind: 'num', key: 'inner_radius', label: 'sp_inner', min: 0 }, { kind: 'num', key: 'turn_deg', label: 'sp_turn', min: 1, max: 1440 }, { kind: 'bool', key: 'clockwise', label: 'tw_cw' }, { kind: 'mat', key: 'material', label: 'f_material' }],
  room: [{ kind: 'sel', key: 'room_type', label: 'f_room_type', options: [...ROOM_TYPES.map((r) => r.id), 'generic'], prefix: 'rt_' }],
  decor: [{ kind: 'sel', key: 'shape', label: 'f_shape', options: ['box', 'cylinder'] }, { kind: 'num', key: 'z', label: 'f_z', min: -1e6 }, { kind: 'num', key: 'rotation_deg', label: 'f_angle', min: -360, max: 360 }, { kind: 'mat', key: 'material', label: 'f_material' }],
}

export default function Inspector() {
  const app = useApp()
  const { project, selection, t, levelId } = app
  const mods = useModules()
  const [issues, setIssues] = useState(null)
  const [err, setErr] = useState(null)
  const [scope, setScope] = useState('all')
  const els = useMemo(() => selection.map((id) => project.elements.find((e) => e.id === id)).filter(Boolean), [selection, project.elements])
  const types = [...new Set(els.map((e) => e.type))]
  const same = types.length === 1 ? types[0] : null
  const first = els[0]
  const ids = selection.join(',')

  const patch = (key, value, coalesce = true) => {
    const set = new Set(selection)
    app.edit((p) => {
      let elements = p.elements.map((e) => (set.has(e.id) ? patchElement(e, { [key]: value }) : e))
      for (const e of elements) if (set.has(e.id) && (e.type === 'door' || e.type === 'window' || e.type === 'opening')) elements = clampOpenings(elements, e.wall_id)
      return { ...p, elements }
    }, coalesce ? `prop:${key}:${ids}` : undefined)
  }

  // "Apply to all": copy spec fields of the (single) selected element to every other element of its type.
  const applyAll = (keys) => {
    const src = els[0]
    let n = 0
    app.edit((p) => {
      const r = applySpecsToAll(p.elements, src, keys, scope)
      n = r.count
      let elements = r.elements
      if (src.type === 'door' || src.type === 'window' || src.type === 'opening') for (const w of new Set(elements.filter((e) => e.wall_id).map((e) => e.wall_id))) elements = clampOpenings(elements, w)
      return { ...p, elements }
    })
    app.toast(`${t('ap_done')}: ${n}`, 'info')
  }

  const moveToLevel = (lid) => {
    const set = new Set(selection)
    app.edit((p) => {
      const hosted = new Set(p.elements.filter((e) => e.type === 'wall' && set.has(e.id)).map((e) => e.id))
      return { ...p, elements: p.elements.map((e) => (set.has(e.id) || hosted.has(e.wall_id) ? { ...e, level_id: lid } : e)) }
    })
    app.set({ levelId: lid })
  }

  const matOpts = [{ value: null, label: t('v_none') }, ...project.materials.map((m) => ({ value: m.id, label: m.name }))]
  const fitting = same ? mods.filter((m) => moduleFits(same, m)) : []

  const validate = async () => {
    setErr(null)
    if (!(await app.save())) return
    try { setIssues((await api.validate(project.id)).issues) } catch (e) { setErr(formatError(e)); setIssues(null) }
  }
  const jump = (id) => {
    const e = project.elements.find((x) => x.id === id)
    if (e) { app.set({ levelId: e.level_id, selection: [id] }) }
  }

  return (
    <div className="inspector">
      {app.tool === 'road' && <RoadPanel />}
      {app.tool === 'roomwiz' && <RoomWizard onPlaceCentre={() => window.__bimPlaceRoomCentre && window.__bimPlaceRoomCentre()} />}
      <Card title={t('insp_title')}>
        {!els.length && <p className="muted">{t('insp_none')}</p>}
        {els.length > 1 && <p className="muted">{els.length} {t('insp_multi')}{same ? ` (${t('tool_' + same)})` : ''}</p>}
        {els.length === 1 && (
          <p className="muted">
            {t('tool_' + first.type)}
            {first.type === 'wall' && ` — ${t('f_length')}: ${Math.round(dist(first.a, first.b) * 1000) / 1000} ${project.units.name}`}
            {first.polygon && first.type !== 'roof' && ` — ${t('f_area')}: ${Math.round(polygonArea(first.polygon) * 100) / 100} ${project.units.name}²`}
          </p>
        )}
        {els.length > 0 && (
          <>
            <Field label={t('f_name')}><input type="text" value={els.length === 1 ? first.name ?? '' : ''} placeholder={els.length > 1 ? '—' : ''} onChange={(e) => patch('name', e.target.value || null)} /></Field>
            <Select label={t('f_level')} value={first.level_id} onChange={moveToLevel} options={project.levels.map((l) => ({ value: l.id, label: l.name }))} />
            {same && els.length === 1 && (
              <div className="apply-all">
                <button type="button" className="btn small primary" data-testid="apply-all" onClick={() => applyAll(SCHEMA[same].map((f) => f.key).filter((k) => !POSITIONAL.has(k)))}>{t('ap_all')} ({t('tool_' + same)})</button>
                <Select label={t('ap_scope')} value={scope} onChange={setScope} options={[{ value: 'all', label: t('ap_scope_all') }, { value: 'level', label: t('ap_scope_level') }]} />
              </div>
            )}
            {same && SCHEMA[same].map((f) => {
              const v = els.every((e) => e[f.key] === first[f.key]) ? first[f.key] : undefined
              let node
              if (f.kind === 'num') {
                node = (
                  <Field label={t(f.label)} hint={f.nullable && v == null ? t('v_none') : undefined}>
                    <NumField value={v ?? undefined} min={f.min} max={f.max} step={f.step} onChange={(n) => patch(f.key, n)} />
                  </Field>
                )
              } else if (f.kind === 'mat') node = <Select label={t(f.label)} value={v ?? null} onChange={(m) => patch(f.key, m)} options={matOpts} />
              else if (f.kind === 'bool') node = <Toggle checked={v === undefined ? false : v} label={t(f.label)} onChange={(b) => patch(f.key, b)} />
              else if (f.kind === 'color') node = <Field label={t(f.label)}><input type="color" value={v ?? '#ffd9a0'} onChange={(ev) => patch(f.key, ev.target.value)} /></Field>
              else if (f.kind === 'sel') node = <Select label={t(f.label)} value={v} onChange={(m) => patch(f.key, m)} options={f.options.map((o) => ({ value: o, label: f.prefix ? t(f.prefix + o) : o }))} />
              else node = <Field label={t(f.label)}><input type="text" value={v ?? ''} onChange={(e) => patch(f.key, e.target.value)} /></Field>
              if (els.length !== 1 || POSITIONAL.has(f.key)) return <div key={f.key}>{node}</div>
              return (
                <div key={f.key} className="fld-row">
                  <div className="grow">{node}</div>
                  <button type="button" className="icon-btn apply-one" data-apply={f.key} title={`${t('ap_field')} (${t('tool_' + same)})`} aria-label={`${t('ap_field')}: ${t(f.label)}`} onClick={() => applyAll([f.key])}>⇉</button>
                </div>
              )
            })}
            {same && fitting.length > 0 && (
              <Select label={t('f_module')} value={first.module ?? null} onChange={(mid) => {
                const set = new Set(selection)
                const mod = mods.find((m) => m.id === mid)
                app.edit((p) => ({ ...p, elements: p.elements.map((e) => (set.has(e.id) ? (mod ? applyModule(e, mod, p.units.name) : { ...e, module: null }) : e)) }))
              }} options={[{ value: null, label: t('v_none') }, ...fitting.map((m) => ({ value: m.id, label: m.name }))]} />
            )}
            {els.length === 1 && first.type === 'road' && <RoadLamps road={first} />}
            {els.length === 1 && first.type === 'wall' && (
              <button type="button" className="btn small primary" data-testid="open-wallface" onClick={() => app.set({ faceWall: first.id })}>{t('wf_open')}{first.features?.length ? ` (${first.features.length})` : ''}</button>
            )}
            {els.length === 1 && first.polygon && first.type !== 'roof' && rectInfo(first.polygon) && (() => {
              const ri = rectInfo(first.polygon)
              const resize = (w, d) => app.edit((p) => ({ ...p, elements: applyOverrides(p.elements, resizeRect(p.elements, first.id, w, d)) }), `size:${first.id}`)
              return (
                <div className="room-size" data-testid="room-size">
                  <b>{t('rm_size')}</b>
                  <div className="rw-size">
                    <Field label={`${t('rw_w')} (${project.units.name})`}><NumField value={ri.w} min={0.01} onChange={(w) => resize(w, ri.d)} /></Field>
                    <Field label={`${t('rw_d')} (${project.units.name})`}><NumField value={ri.d} min={0.01} onChange={(d) => resize(ri.w, d)} /></Field>
                  </div>
                  <small className="muted">{t('rm_side_hint')}</small>
                </div>
              )
            })()}
            {els.length === 1 && first.type === 'room' && (
              <button type="button" className="btn small" data-testid="room-build" onClick={() => app.edit((p) => ({ ...p, elements: [...p.elements, ...buildRoomParts(p.elements, first.id, p.units.name)] }))}>{t('rm_build')}</button>
            )}
            {els.length === 1 && first.type === 'stair' && (() => {
              const lvl = project.levels.find((l) => l.id === first.level_id)
              const swap = (kind) => app.edit((p) => {
                const parts = stairFlights(kind, { start: first.start, angleDeg: first.angle_deg, width: first.width, height: lvl.height, rise: first.rise, run: first.run }, first.level_id, p.units.name)
                return { ...p, elements: [...p.elements.filter((e) => e.id !== first.id), ...parts] }
              })
              return (
                <div className="stair-tools">
                  <button type="button" className="btn small" data-testid="stair-fit" onClick={() => { app.edit((p) => ({ ...p, elements: p.elements.map((e) => (e.id === first.id ? patchElement(e, fitStairSteps(lvl.height, first.rise)) : e)) })); app.toast(t('st_fit_done'), 'info') }}>{t('st_fit')}</button>
                  <button type="button" className="btn small" data-testid="stair-L" onClick={() => swap('L')}>{t('st_L')}</button>
                  <button type="button" className="btn small" data-testid="stair-U" onClick={() => swap('U')}>{t('st_U')}</button>
                </div>
              )
            })()}
            <button type="button" className="btn danger small" onClick={() => app.edit((p) => ({ ...p, elements: deleteElements(p.elements, selection) }))}>{t('delete')}</button>
          </>
        )}
      </Card>
      <Card title={t('pt_title')}>
        <div className="plan-tools">
          <button type="button" className="btn small" data-testid="pt-wizard" onClick={() => app.set({ tool: 'roomwiz' })}>{t('pt_wizard')}</button>
          <button type="button" className="btn small" data-testid="pt-underlay" onClick={() => app.set({ dialog: 'underlay' })}>{t('ul_import')}</button>
          <button type="button" className="btn small" data-testid="pt-villa" onClick={() => app.set({ dialog: 'villa' })}>{t('pt_villa')}</button>
          <button type="button" className="btn small" data-testid="pt-plaza" onClick={() => app.set({ dialog: 'plaza' })}>{t('pt_plaza')}</button>
          <button type="button" className="btn small" data-testid="pt-tower" onClick={() => app.set({ dialog: 'tower' })}>{t('pt_tower')}</button>
          <button type="button" className="btn small" data-testid="pt-ruin" onClick={() => app.set({ dialog: 'ruin' })}>{t('pt_ruin')}</button>
          {project.elements.some((e) => e.props && e.props.debris) && <button type="button" className="btn small" data-testid="pt-cleardebris" onClick={() => app.edit((p) => ({ ...p, elements: p.elements.filter((e) => !(e.props && e.props.debris)) }))}>{t('pt_cleardebris')}</button>}
          <button type="button" className="btn small" data-testid="pt-dxf" onClick={() => app.set({ dialog: 'dxf' })}>{t('pt_dxf')}</button>
          <button type="button" className="btn small" data-testid="pt-array" disabled={!selection.length} onClick={() => app.set({ dialog: 'array' })}>{t('pt_array')}</button>
        </div>
        {project.levels.length > 1 && (
          <>
            <Select label={t('pt_copy_to')} value={null} onChange={(lid) => { if (!lid || !selection.length) return; app.edit((p) => ({ ...p, elements: [...p.elements, ...cloneElements(p.elements, selection, { levelId: lid })] })); app.toast(t('pt_done'), 'info') }} options={[{ value: null, label: '—' }, ...project.levels.filter((l) => l.id !== levelId).map((l) => ({ value: l.id, label: l.name }))]} />
            <Select label={t('pt_copy_level')} value={null} onChange={(lid) => { if (!lid) return; app.edit((p) => ({ ...p, elements: [...p.elements, ...cloneElements(p.elements, p.elements.filter((e) => e.level_id === levelId && !e.wall_id).map((e) => e.id), { levelId: lid })] })); app.toast(t('pt_done'), 'info') }} options={[{ value: null, label: '—' }, ...project.levels.filter((l) => l.id !== levelId).map((l) => ({ value: l.id, label: l.name }))]} />
          </>
        )}
      </Card>
      <GuidePanel />
      <BalancePanel />
          <RoomsPanel />
      <TemplatesPanel />
      <UnderlayPanel />
      <Card title={t('issues')} actions={<button type="button" className="btn small" onClick={validate}>{t('validate')}</button>}>
        <ErrorBox error={err} />
        {issues && !issues.length && <p className="ok">{t('validate_ok')}</p>}
        {issues && issues.map((i, k) => <button key={k} type="button" className={`issue ${i.level}`} onClick={() => jump(i.element_id)}><b>{i.element_id}</b> {i.message}</button>)}
      </Card>
    </div>
  )
}
