import { useState } from 'react'
import { useApp } from '../store.jsx'
import { Card, Field, Select } from '../ui.jsx'
import { mergeRooms, splitRoom } from '../rooms.js'

/** Merge two selected rooms, or split one selected room with a new interior wall + door. */
export default function RoomsPanel() {
  const app = useApp()
  const { project, selection, t } = app
  const unit = project.units.name
  const [axis, setAxis] = useState('x')
  const [frac, setFrac] = useState(0.5)
  const [msg, setMsg] = useState('')
  // a selected room, or a floor lying inside a room (floors sit on top of rooms in the plan, so clicking a room selects its floor)
  const inside = (pt, poly) => { let c = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) if ((poly[i][1] > pt[1]) !== (poly[j][1] > pt[1]) && pt[0] < ((poly[j][0] - poly[i][0]) * (pt[1] - poly[i][1])) / (poly[j][1] - poly[i][1]) + poly[i][0]) c = !c; return c }
  const rooms = []
  for (const id of selection) {
    const e = project.elements.find((x) => x.id === id)
    if (!e) return null
    let r = null
    if (e.type === 'room') r = e
    else if (e.type === 'floor') { const c = [e.polygon.reduce((a, q) => a + q[0], 0) / e.polygon.length, e.polygon.reduce((a, q) => a + q[1], 0) / e.polygon.length]; r = project.elements.find((x) => x.type === 'room' && x.level_id === e.level_id && inside(c, x.polygon)) }
    if (!r) return null
    if (!rooms.includes(r)) rooms.push(r)
  }
  if (!rooms.length || rooms.length > 2) return null
  const merge = () => {
    const r = mergeRooms(project.elements, rooms[0].id, rooms[1].id, unit)
    if (!r) { setMsg(t('rm_nomerge')); return }
    app.edit((p) => ({ ...p, elements: r.elements })); app.set({ selection: [rooms[0].id] }); setMsg(`${t('rm_merged')} (${r.removedWalls})`)
  }
  const split = () => {
    const R = rooms[0], i = axis === 'x' ? 0 : 1
    const v = R.polygon.map((p) => p[i]), pos = Math.min(...v) + (Math.max(...v) - Math.min(...v)) * frac
    const r = splitRoom(project.elements, R.id, axis, Math.round(pos * 1e4) / 1e4, unit)
    if (!r) { setMsg(t('rm_nosplit')); return }
    app.edit((p) => ({ ...p, elements: r.elements })); app.set({ selection: r.roomIds }); setMsg(t('rm_split_done'))
  }
  return (
    <Card title={t('rm_title')}>
      {rooms.length === 2 && <button type="button" className="btn small" data-testid="rm-merge" onClick={merge}>{t('rm_merge')}</button>}
      {rooms.length === 1 && <>
        <Select label={t('rm_axis')} value={axis} onChange={setAxis} options={[{ value: 'x', label: t('rm_axis_x') }, { value: 'y', label: t('rm_axis_y') }]} />
        <Field label={`${t('rm_pos')}: ${Math.round(frac * 100)}%`}><input type="range" min={0.1} max={0.9} step={0.05} value={frac} onChange={(e) => setFrac(+e.target.value)} /></Field>
        <button type="button" className="btn small" data-testid="rm-split" onClick={split}>{t('rm_split')}</button>
      </>}
      {msg && <p className="muted small" data-testid="rm-msg">{msg}</p>}
    </Card>
  )
}
