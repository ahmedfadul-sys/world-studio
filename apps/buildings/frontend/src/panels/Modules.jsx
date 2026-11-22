import { useState } from 'react'
import { useApp } from '../store.jsx'
import { applyModule, defaultKindFor, moduleFits, moduleFromElement, reapplyModule } from '../model.js'
import { Card, Field, NeedProject, useModules } from '../ui.jsx'

export default function Modules() {
  const app = useApp()
  const { project, t, selection } = app
  const mods = useModules()
  const [name, setName] = useState('')
  if (!project) return <NeedProject />
  const sel = selection.map((id) => project.elements.find((e) => e.id === id)).filter(Boolean)
  const custom = new Set(project.modules.map((m) => m.id))
  const applyTo = (mod) => {
    const set = new Set(sel.filter((e) => moduleFits(e.type, mod)).map((e) => e.id))
    if (!set.size) return app.toast(t('mod_none_sel'))
    app.edit((p) => ({ ...p, elements: p.elements.map((e) => (set.has(e.id) ? applyModule(e, mod, p.units.name) : e)) }))
  }
  const create = () => {
    const el = sel[0]
    const kind = el && defaultKindFor(el.type)
    if (!el || !kind) return app.toast(t('mod_none_sel'))
    const mod = moduleFromElement(el, kind, name.trim() || `${t('tool_' + el.type)} ${project.modules.length + 1}`, project.units.name)
    app.edit((p) => ({ ...p, modules: [...p.modules, mod], elements: p.elements.map((e) => (e.id === el.id ? { ...e, module: mod.id } : e)) }))
    setName('')
  }
  const editDefault = (mod, key, val) => {
    const next = { ...mod, defaults: { ...mod.defaults, [key]: val } }
    app.edit((p) => reapplyModule({ ...p, modules: p.modules.map((m) => (m.id === mod.id ? next : m)) }, mod.id, next), `mod:${mod.id}:${key}`)
  }
  const users = (id) => project.elements.filter((e) => e.module === id).length

  return (
    <div className="page">
      <h2>{t('mod_title')}</h2>
      <p className="muted">{t('mod_note')}</p>
      <Card title={t('mod_create')}>
        <div className="row wrap">
          <Field label={t('mod_name')}><input type="text" value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <button type="button" className="btn primary" disabled={!sel.length} onClick={create}>{t('mod_create')} ({sel.length})</button>
        </div>
      </Card>
      <div className="mgrid">
        {mods.map((m) => (
          <Card key={m.id} title={m.name} actions={<span className="badge">{custom.has(m.id) ? t('mod_custom') : t('mod_builtin')}</span>}>
            <div className="muted">{m.kind} · {users(m.id)} {t('mat_used')}</div>
            <ul className="defs">
              {Object.entries(m.defaults).map(([k, v]) => (
                <li key={k}><span>{k}</span>
                  {custom.has(m.id) && typeof v === 'number'
                    ? <input type="number" step="any" value={v} onChange={(e) => Number.isFinite(parseFloat(e.target.value)) && editDefault(project.modules.find((x) => x.id === m.id), k, parseFloat(e.target.value))} />
                    : <b>{String(v)}</b>}</li>
              ))}
            </ul>
            <button type="button" className="btn small" disabled={!sel.some((e) => moduleFits(e.type, m))} onClick={() => applyTo(m)}>{t('mod_apply')}</button>
          </Card>
        ))}
      </div>
    </div>
  )
}
