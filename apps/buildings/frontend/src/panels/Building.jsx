import { useApp } from '../store.jsx'
import { Card, Field, NeedProject, NumField, Stat } from '../ui.jsx'

export default function Building() {
  const app = useApp()
  const { project, t } = app
  if (!project) return <NeedProject />
  const set = (fn, key) => app.edit(fn, key)
  const meta = (k, v) => set((p) => ({ ...p, meta: { ...p.meta, [k]: v } }), `meta:${k}`)
  const style = project.meta.style
  const params = Object.entries(style.params || {})
  const setParams = (obj) => set((p) => ({ ...p, meta: { ...p.meta, style: { ...p.meta.style, params: obj } } }))
  const lvl = (id, patch, key) => set((p) => ({ ...p, levels: p.levels.map((l) => (l.id === id ? { ...l, ...patch } : l)) }), key)
  const count = (type) => project.elements.filter((e) => e.type === type).length
  const used = (lid) => project.elements.some((e) => e.level_id === lid)

  return (
    <div className="page">
      <h2>{t('bld_title')}</h2>
      <div className="grid2">
        <Card title={project.name}>
          <Field label={t('name')}><input type="text" value={project.name} maxLength={120} onChange={(e) => set((p) => ({ ...p, name: e.target.value || p.name }), 'name')} /></Field>
          <Field label={t('bld_desc')}><textarea rows={3} value={project.meta.description} onChange={(e) => meta('description', e.target.value)} /></Field>
          <Field label={t('bld_author')}><input type="text" value={project.meta.author} onChange={(e) => meta('author', e.target.value)} /></Field>
          <Field label={t('bld_style')}><input type="text" list="styles" placeholder={t('bld_style_ph')} value={style.name} onChange={(e) => set((p) => ({ ...p, meta: { ...p.meta, style: { ...p.meta.style, name: e.target.value } } }), 'style')} /></Field>
          <datalist id="styles">{['modern', 'traditional', 'historical', 'medieval', 'fantasy', 'industrial', 'sci-fi', 'futuristic'].map((s) => <option key={s} value={s} />)}</datalist>
          <h4>{t('bld_style_params')}</h4>
          {params.map(([k, v]) => (
            <div className="row" key={k}>
              <input type="text" value={k} aria-label={t('bld_param_key')} onChange={(e) => { const o = {}; params.forEach(([kk, vv]) => { o[kk === k ? e.target.value : kk] = vv }); setParams(o) }} />
              <input type="text" value={String(v)} aria-label={t('bld_param_val')} onChange={(e) => setParams({ ...style.params, [k]: e.target.value })} />
              <button type="button" className="btn small" onClick={() => { const o = { ...style.params }; delete o[k]; setParams(o) }} aria-label={t('remove')}>✕</button>
            </div>
          ))}
          <button type="button" className="btn small" onClick={() => setParams({ ...style.params, [`param${params.length + 1}`]: '' })}>{t('add')}</button>
        </Card>
        <div>
          <Card title={t('bld_levels')} actions={<button type="button" className="btn small" onClick={() => set((p) => { const l = p.levels[p.levels.length - 1]; return { ...p, levels: [...p.levels, { id: `lvl_${Date.now().toString(36)}`, name: `Level ${p.levels.length}`, elevation: l.elevation + l.height, height: l.height }] } })}>{t('bld_add_level')}</button>}>
            {project.levels.map((l) => (
              <div className="levelrow" key={l.id}>
                <input type="text" value={l.name} aria-label={t('bld_level_name')} onChange={(e) => lvl(l.id, { name: e.target.value }, `ln:${l.id}`)} />
                <NumField label={t('bld_elevation')} value={l.elevation} min={-1e6} onChange={(v) => lvl(l.id, { elevation: v }, `le:${l.id}`)} />
                <NumField label={t('bld_height')} value={l.height} min={0.0001} onChange={(v) => lvl(l.id, { height: v }, `lh:${l.id}`)} />
                <button type="button" className="btn small danger" disabled={project.levels.length < 2} title={used(l.id) ? t('remove') + ' + ' + t('elements') : t('remove')}
                  onClick={() => { if (used(l.id) && !window.confirm(`${t('remove')}: ${l.name} (${project.elements.filter((e) => e.level_id === l.id).length} ${t('elements')})`)) return; set((p) => ({ ...p, levels: p.levels.filter((x) => x.id !== l.id), elements: p.elements.filter((e) => e.level_id !== l.id) })) }}>✕</button>
              </div>
            ))}
          </Card>
          <Card title={t('bld_stats')}>
            <div className="stats">
              {['wall', 'door', 'window', 'column', 'beam', 'floor', 'roof', 'stair', 'room'].map((k) => <Stat key={k} label={t('tool_' + k)} value={count(k)} />)}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
