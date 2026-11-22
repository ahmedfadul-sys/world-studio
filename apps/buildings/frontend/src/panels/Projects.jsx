import { useCallback, useEffect, useRef, useState } from 'react'
import { useApp } from '../store.jsx'
import { api, formatError } from '../api.js'
import { Card, ErrorBox, Field, Select } from '../ui.jsx'

export default function Projects() {
  const app = useApp()
  const { t, project } = app
  const [list, setList] = useState(null)
  const [name, setName] = useState('')
  const [units, setUnits] = useState('m')
  const [err, setErr] = useState(null)
  const file = useRef(null)

  const load = useCallback(() => api.listProjects().then((r) => { setList(r.projects); setErr(null) }).catch((e) => setErr(formatError(e))), [])
  useEffect(() => { load() }, [load])

  const open = async (id) => {
    if (project && app.dirty && !(await app.save())) return
    try { app.open(await api.getProject(id), 'editor') } catch (e) { setErr(formatError(e)) }
  }
  const create = async (e) => {
    e.preventDefault()
    try { const p = await api.createProject(name.trim() || t('proj_name_ph'), units); setName(''); app.open(p, 'editor'); load() } catch (x) { setErr(formatError(x)) }
  }
  const del = async (id) => {
    if (!window.confirm(t('proj_confirm_delete'))) return
    try { await api.deleteProject(id); if (project?.id === id) app.dispatch({ type: 'close' }); load() } catch (e) { setErr(formatError(e)) }
  }
  const download = async (id) => {
    try {
      const p = await api.getProject(id)
      const a = document.createElement('a')
      a.href = URL.createObjectURL(new Blob([JSON.stringify(p, null, 1)], { type: 'application/json' }))
      a.download = `${p.name.replace(/[^\w-]+/g, '_')}.bim.json`
      a.click(); URL.revokeObjectURL(a.href)
    } catch (e) { setErr(formatError(e)) }
  }
  const upload = async (ev) => {
    const f = ev.target.files[0]; ev.target.value = ''
    if (!f) return
    try {
      const data = JSON.parse(await f.text())
      const made = await api.createProject(data.name || 'Imported', data.units?.name || 'm')
      const saved = await api.putProject({ ...data, id: made.id, build_history: [] })
      app.open(saved, 'editor'); load()
    } catch (e) { setErr(e.info ? formatError(e) : { what: 'Cannot import this file', where: f.name, why: String(e.message), fix: 'Use a project exported from this app' }) }
  }

  return (
    <div className="page">
      <h2>{t('proj_title')}</h2>
      <ErrorBox error={err} />
      <Card title={t('proj_new')}>
        <form className="row wrap" onSubmit={create}>
          <Field label={t('name')}><input type="text" value={name} maxLength={120} placeholder={t('proj_name_ph')} onChange={(e) => setName(e.target.value)} /></Field>
          <Select label={t('units')} value={units} onChange={setUnits} options={['m', 'cm', 'mm', 'ft', 'in'].map((u) => ({ value: u, label: u }))} />
          <button className="btn primary" type="submit">{t('create')}</button>
          <button className="btn" type="button" onClick={() => file.current.click()}>{t('proj_import')}</button>
          <input ref={file} type="file" accept="application/json,.json" hidden onChange={upload} />
        </form>
      </Card>
      <Card>
        {list && !list.length && <p className="muted">{t('proj_empty')}</p>}
        <div className="plist">
          {(list || []).map((p) => (
            <div key={p.id} className={`prow ${project?.id === p.id ? 'cur' : ''}`}>
              <div><strong>{p.name}</strong><div className="muted">{p.elements} {t('elements')} · {(p.size_bytes / 1024).toFixed(1)} KB · {new Date(p.updated_at).toLocaleString()}</div></div>
              <div className="row">
                <button type="button" className="btn small primary" onClick={() => open(p.id)}>{t('open')}</button>
                <button type="button" className="btn small" onClick={() => download(p.id)}>{t('proj_export')}</button>
                <button type="button" className="btn small danger" onClick={() => del(p.id)}>{t('delete')}</button>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
