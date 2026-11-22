import { useApp } from '../store.jsx'
import { UNITS, convertUnits } from '../model.js'
import Backups from './Backups.jsx'
import { Card, Field, NeedProject, NumField, Select, Toggle } from '../ui.jsx'

export default function Settings() {
  const app = useApp()
  const { project, t } = app
  if (!project) return <NeedProject />
  const ed = project.editor
  const u = project.units.name
  const setEd = (patch, key) => app.edit((p) => ({ ...p, editor: { ...p.editor, ...patch } }), key)
  return (
    <div className="page narrow">
      <h2>{t('set_title')}</h2>
      <Card>
        <Select label={t('set_units')} value={u} onChange={(n) => app.edit((p) => convertUnits(p, n))} options={Object.keys(UNITS).map((k) => ({ value: k, label: k }))} />
        <p className="muted">{t('set_units_warn')}</p>
        <Field label={`${t('set_grid')} (${u})`}>
          <div className="row"><NumField value={ed.grid_size ?? UNITS[u].grid} min={0.0001} disabled={ed.grid_size == null} onChange={(v) => setEd({ grid_size: v }, 'grid')} />
            <Toggle checked={ed.grid_size == null} label={t('set_auto')} onChange={(c) => setEd({ grid_size: c ? null : UNITS[u].grid })} /></div>
        </Field>
        <Field label={`${t('set_snap')} (${u})`}>
          <div className="row"><NumField value={ed.snap_size ?? UNITS[u].snap} min={0.0001} disabled={ed.snap_size == null} onChange={(v) => setEd({ snap_size: v }, 'snap')} />
            <Toggle checked={ed.snap_size == null} label={t('set_auto')} onChange={(c) => setEd({ snap_size: c ? null : UNITS[u].snap })} /></div>
        </Field>
        <p className="muted">{t('set_precision')}</p>
        <Toggle checked={ed.snap_enabled} label={t('set_snap_on')} onChange={(v) => setEd({ snap_enabled: v })} />
        <Toggle checked={ed.show_dimensions} label={t('set_dims')} onChange={(v) => setEd({ show_dimensions: v })} />
        <Toggle checked={app.autosave} label={t('set_autosave')} onChange={app.setAutosave} />
      </Card>
      <Backups />
    </div>
  )
}
