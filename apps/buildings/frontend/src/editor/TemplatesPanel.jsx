import { useState } from 'react'
import { useApp } from '../store.jsx'
import { clampOpenings, uid } from '../model.js'
import { Card, Field } from '../ui.jsx'
import { TPL_TYPES, applyTemplate, templateFromElement, templatesFor } from '../templates.js'

const fmt = (p) => Object.entries(p).filter(([k]) => !k.startsWith('material') && k !== 'kind' && k !== 'shape').map(([k, v]) => `${k.replace('_deg', '°')} ${v}`).join(' · ')

/** Templates card: pick a template to use for new elements, apply it to the selection, save the selected element as a template. */
export default function TemplatesPanel() {
  const app = useApp()
  const { project, selection, tool, t } = app
  const [name, setName] = useState('')
  const els = selection.map((id) => project.elements.find((e) => e.id === id)).filter(Boolean)
  const selType = els.length && els.every((e) => e.type === els[0].type) ? els[0].type : null
  const type = TPL_TYPES.includes(selType) ? selType : TPL_TYPES.includes(tool) ? tool : null
  if (!type) return null
  const list = templatesFor(project, type)
  const active = (app.tpl || {})[type] || null
  const setActive = (id) => app.set({ tpl: { ...(app.tpl || {}), [type]: id === active ? null : id } })
  const label = (x) => (x.builtin ? t('tpl_' + x.id) : x.name)

  const apply = (tpl) => {
    let n = 0
    app.edit((p) => {
      const r = applyTemplate(p.elements, selection, tpl)
      n = r.count
      let elements = r.elements
      if (['door', 'window', 'opening'].includes(tpl.type)) for (const w of new Set(elements.filter((e) => e.wall_id).map((e) => e.wall_id))) elements = clampOpenings(elements, w)
      return { ...p, elements }
    })
    app.toast(`${t('tpl_applied')}: ${n}`, 'info')
  }
  const save = () => {
    if (!name.trim() || !selType) return
    const tpl = templateFromElement(els[0], name, uid('tpl'))
    app.edit((p) => ({ ...p, templates: [...(p.templates || []), tpl] }))
    app.set({ tpl: { ...(app.tpl || {}), [type]: tpl.id } })
    setName('')
    app.toast(t('tpl_saved'), 'info')
  }
  const remove = (id) => {
    app.edit((p) => ({ ...p, templates: (p.templates || []).filter((x) => x.id !== id) }))
    if (active === id) app.set({ tpl: { ...(app.tpl || {}), [type]: null } })
  }

  return (
    <Card title={`${t('tpl_title')} — ${t('tool_' + type)}`}>
      <p className="muted small">{selType ? t('tpl_hint_sel') : t('tpl_hint_draw')}</p>
      <ul className="tpl-list" data-testid="tpl-list">
        {list.map((x) => (
          <li key={x.id} className={`tpl ${active === x.id ? 'on' : ''}`}>
            <button type="button" className="tpl-pick" aria-pressed={active === x.id} data-tpl={x.id} onClick={() => setActive(x.id)} title={t('tpl_use')}>
              <b>{label(x)}</b><span className="muted small">{fmt(x.props)}</span>
            </button>
            {selType && <button type="button" className="btn small" data-tpl-apply={x.id} onClick={() => apply(x)}>{t('tpl_apply')}</button>}
            {!x.builtin && <button type="button" className="btn small" aria-label={t('delete')} onClick={() => remove(x.id)}>✕</button>}
          </li>
        ))}
      </ul>
      {active && <p className="small">{t('tpl_active')}: <b>{label(list.find((x) => x.id === active) || { name: '—' })}</b> <button type="button" className="btn small" onClick={() => setActive(active)}>{t('tpl_none')}</button></p>}
      {selType && els.length === 1 && (
        <Field label={t('tpl_save_from')}>
          <div className="row">
            <input type="text" value={name} maxLength={80} placeholder={t('tpl_name')} data-testid="tpl-name" onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { e.stopPropagation(); if (e.key === 'Enter') save() }} />
            <button type="button" className="btn small primary" disabled={!name.trim()} data-testid="tpl-save" onClick={save}>{t('tpl_save')}</button>
          </div>
        </Field>
      )}
    </Card>
  )
}
