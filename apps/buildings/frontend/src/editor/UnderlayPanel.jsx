import { useState } from 'react'
import { useApp } from '../store.jsx'
import { Card, Field, NumField, Toggle } from '../ui.jsx'
import { calibrateUnderlay } from '../plan.js'
import { deleteUnderlayFile } from '../underlay.js'
import { dist } from '../model.js'

/** Properties of the scanned-plan underlays + the two-click scale calibration. */
export default function UnderlayPanel() {
  const app = useApp()
  const { t, project, levelId } = app
  const unit = project.units.name
  const list = project.underlays || []
  const [real, setReal] = useState(10)
  const [align, setAlign] = useState('none')
  const cal = app.calib
  const patch = (id, ch) => app.edit((p) => ({ ...p, underlays: p.underlays.map((u) => (u.id === id ? { ...u, ...ch } : u)) }), `ul:${id}`)
  const remove = (u) => { app.edit((p) => ({ ...p, underlays: p.underlays.filter((x) => x.id !== u.id) })); deleteUnderlayFile(project.id, u.file); if (cal?.id === u.id) app.set({ calib: null }) }
  const apply = () => {
    const u = list.find((x) => x.id === cal.id)
    if (u && cal.pts.length === 2) app.edit((p) => ({ ...p, underlays: p.underlays.map((x) => (x.id === u.id ? calibrateUnderlay(x, cal.pts[0], cal.pts[1], real, align === 'none' ? null : align) : x)) }))
    app.set({ calib: null })
    app.set({ view: null })
  }
  if (!list.length) return null
  return (
    <Card title={t('ul_title')}>
      {list.map((u) => (
        <div key={u.id} className="ul-item" data-testid="underlay-item">
          <div className="row between">
            <b>{u.name || u.file}</b>
            <span className="muted small">{u.level_id ? (project.levels.find((l) => l.id === u.level_id)?.name || '') : t('ul_all')}{u.level_id && u.level_id !== levelId ? ' ·' : ''}</span>
          </div>
          <Toggle checked={u.visible} label={t('ul_visible')} onChange={(v) => patch(u.id, { visible: v })} />
          <label className="field"><span>{t('ul_opacity')}: {Math.round(u.opacity * 100)}%</span>
            <input type="range" min={5} max={100} value={Math.round(u.opacity * 100)} onChange={(e) => patch(u.id, { opacity: Number(e.target.value) / 100 })} /></label>
          <div className="rw-size">
            <Field label={`${t('ul_x')} (${unit})`}><NumField value={u.x} min={-1e6} onChange={(x) => patch(u.id, { x })} /></Field>
            <Field label={`${t('ul_y')} (${unit})`}><NumField value={u.y} min={-1e6} onChange={(y) => patch(u.id, { y })} /></Field>
          </div>
          <div className="rw-size">
            <Field label={`${t('ul_width')} (${unit})`}><NumField value={u.width} min={0.01} onChange={(width) => patch(u.id, { width })} /></Field>
            <Field label={t('ul_rot')}><NumField value={u.rotation_deg} min={-360} max={360} onChange={(rotation_deg) => patch(u.id, { rotation_deg })} /></Field>
          </div>
          <div className="plan-tools">
            <button type="button" className="btn small" data-testid="ul-calibrate" onClick={() => app.set({ calib: { id: u.id, pts: [] }, tool: 'select' })}>{t('ul_cal')}</button>
            <button type="button" className="btn danger small" onClick={() => remove(u)}>{t('ul_del')}</button>
          </div>
        </div>
      ))}
      {cal && (
        <div className="ul-cal" data-testid="ul-cal-panel" role="group" aria-label={t('ul_cal')}>
          {cal.pts.length < 2 ? (
            <p className="muted">{t('ul_cal_hint')} ({cal.pts.length}/2)</p>
          ) : (
            <>
              <p className="muted">{t('ul_measured')}: {Math.round(dist(cal.pts[0], cal.pts[1]) * 1000) / 1000} {unit}</p>
              <Field label={`${t('ul_cal_dist')} (${unit})`}><NumField value={real} min={0.0001} onChange={setReal} /></Field>
              <label className="field"><span>{t('ul_align')}</span>
                <select value={align} onChange={(e) => setAlign(e.target.value)} data-testid="ul-align">
                  <option value="none">{t('ul_align_none')}</option><option value="h">{t('ul_align_h')}</option><option value="v">{t('ul_align_v')}</option>
                </select></label>
              <button type="button" className="btn primary small" data-testid="ul-apply" onClick={apply}>{t('ul_apply')}</button>
            </>
          )}
          <button type="button" className="btn small" onClick={() => app.set({ calib: null })}>{t('ul_cancel')}</button>
        </div>
      )}
    </Card>
  )
}
