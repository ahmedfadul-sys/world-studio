import { useEffect } from 'react'
import { useApp } from '../store.jsx'
import { Field, NumField, Select, Toggle } from '../ui.jsx'
import { fromM } from '../model.js'
import { ROOM_TYPES } from '../plan.js'

export const defaultRoomSpec = (type, unit) => {
  const rt = ROOM_TYPES.find((r) => r.id === type) || ROOM_TYPES[0]
  return { type: rt.id, name: '', w: fromM(rt.w, unit), d: fromM(rt.d, unit), walls: true, floor: true, ceiling: false, door: true, anchor: 'sw' }
}

/** Floating panel of the "room wizard" tool: pick a room type, type its size, then click on the plan. */
export default function RoomWizard({ onPlaceCentre }) {
  const app = useApp()
  const { t, project } = app
  const unit = project.units.name
  const sp = app.roomSpec
  useEffect(() => { if (!sp) app.set({ roomSpec: defaultRoomSpec('living', unit) }) }, [sp]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!sp) return null
  const up = (patch) => app.set({ roomSpec: { ...sp, ...patch } })
  return (
    <div className="room-wiz" role="group" aria-label={t('rw_title')} data-testid="room-wizard">
      <h4>{t('rw_title')}</h4>
      <div className="rw-types">
        {ROOM_TYPES.map((r) => (
          <button key={r.id} type="button" className={`btn small ${sp.type === r.id ? 'primary' : ''}`} aria-pressed={sp.type === r.id} data-room-type={r.id}
            onClick={() => up({ ...defaultRoomSpec(r.id, unit), name: '', door: sp.door, walls: sp.walls, floor: sp.floor, ceiling: sp.ceiling, anchor: sp.anchor })}>{t('rt_' + r.id)}</button>
        ))}
      </div>
      <Field label={t('rw_name')}><input type="text" data-testid="rw-name" value={sp.name} placeholder={`${t('rt_' + sp.type)} 1…`} onChange={(e) => up({ name: e.target.value })} /></Field>
      <div className="rw-size">
        <Field label={`${t('rw_w')} (${unit})`}><NumField value={sp.w} min={0.01} onChange={(w) => up({ w })} /></Field>
        <button type="button" className="btn small" title={t('rw_swap')} aria-label={t('rw_swap')} onClick={() => up({ w: sp.d, d: sp.w })}>⇄</button>
        <Field label={`${t('rw_d')} (${unit})`}><NumField value={sp.d} min={0.01} onChange={(d) => up({ d })} /></Field>
      </div>
      <div className="rw-opts">
        <Toggle checked={sp.walls} label={t('rw_walls')} onChange={(v) => up({ walls: v })} />
        <Toggle checked={sp.floor} label={t('rw_floor')} onChange={(v) => up({ floor: v })} />
        <Toggle checked={sp.ceiling} label={t('rw_ceiling')} onChange={(v) => up({ ceiling: v })} />
        <Toggle checked={sp.door} label={t('rw_door')} onChange={(v) => up({ door: v })} />
      </div>
      <Select label={t('rw_anchor')} value={sp.anchor} onChange={(v) => up({ anchor: v })} options={['sw', 'se', 'nw', 'ne'].map((k) => ({ value: k, label: t('anc_' + k) }))} />
      <button type="button" className="btn small" data-testid="rw-centre" onClick={onPlaceCentre}>{t('rw_centre')}</button>
      <p className="muted small">{t('rw_hint')}</p>
    </div>
  )
}
