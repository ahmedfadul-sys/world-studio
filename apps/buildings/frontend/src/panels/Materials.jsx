import { lazy, Suspense, useEffect, useState } from 'react'
import { useApp } from '../store.jsx'
import { api, formatError } from '../api.js'
import { Card, ErrorBox, Field, NeedProject, NumField, Select } from '../ui.jsx'
const MaterialLab = lazy(() => import('./MaterialLab.jsx')) // pulls in three.js: load it only when a material is opened

export default function Materials() {
  const app = useApp()
  const { project, t, selection } = app
  const [textures, setTextures] = useState([])
  const [err, setErr] = useState(null)
  const [cur, setCur] = useState(null)
  useEffect(() => { if (project) api.textures(project.id).then((r) => setTextures(r.textures)).catch(() => {}) }, [project?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!project) return <NeedProject />
  const m = project.materials.find((x) => x.id === cur) || project.materials[0]
  const patch = (id, o, key) => app.edit((p) => ({ ...p, materials: p.materials.map((x) => (x.id === id ? { ...x, ...o } : x)) }), key)
  const usage = (id) => project.elements.filter((e) => e.material === id || e.material_inner === id).length

  const add = () => {
    const id = `mat_${Date.now().toString(36)}`
    app.edit((p) => ({ ...p, materials: [...p.materials, { id, name: `Material ${p.materials.length + 1}`, color: '#b8b2a7', roughness: 0.8, metallic: 0, texture: null, normal_texture: null, rough_texture: null, lab: null, uv_scale: 1 }] }))
    setCur(id)
  }
  const remove = (id) => app.edit((p) => ({
    ...p,
    materials: p.materials.filter((x) => x.id !== id),
    elements: p.elements.map((e) => ({ ...e, ...(e.material === id ? { material: null } : {}), ...(e.material_inner === id ? { material_inner: null } : {}) })),
  }))
  const upload = async (ev) => {
    const f = ev.target.files[0]; ev.target.value = ''
    if (!f) return
    try {
      if (!(await app.save())) return
      await api.putTexture(project.id, f)
      setTextures((await api.textures(project.id)).textures)
      patch(m.id, { texture: f.name })
      setErr(null)
    } catch (e) { setErr(formatError(e)) }
  }
  const assign = () => app.edit((p) => ({ ...p, elements: p.elements.map((e) => (selection.includes(e.id) && 'material' in e ? { ...e, material: m.id, overrides: [...new Set([...(e.overrides || []), 'material'])] } : e)) }))

  return (
    <div className="page">
      <h2>{t('mat_title')}</h2>
      <div className="grid2">
        <Card title={t('mat_title')} actions={<button type="button" className="btn small" onClick={add}>{t('mat_add')}</button>}>
          {project.materials.map((x) => (
            <button type="button" key={x.id} className={`mrow ${x.id === m?.id ? 'on' : ''}`} onClick={() => setCur(x.id)}>
              <span className="swatch" style={{ background: x.color }} /> <span>{x.name}</span><span className="muted">{usage(x.id)} {t('mat_used')}</span>
            </button>
          ))}
        </Card>
        {m && (
          <Card title={m.name}>
            <ErrorBox error={err} />
            <Field label={t('name')}><input type="text" value={m.name} onChange={(e) => patch(m.id, { name: e.target.value || m.name }, `mn:${m.id}`)} /></Field>
            <Field label={t('mat_color')}><input type="color" value={m.color} onChange={(e) => patch(m.id, { color: e.target.value }, `mc:${m.id}`)} /></Field>
            <Field label={`${t('mat_rough')}: ${m.roughness}`}><input type="range" min={0} max={1} step={0.05} value={m.roughness} onChange={(e) => patch(m.id, { roughness: +e.target.value }, `mr:${m.id}`)} /></Field>
            <Field label={`${t('mat_metal')}: ${m.metallic}`}><input type="range" min={0} max={1} step={0.05} value={m.metallic} onChange={(e) => patch(m.id, { metallic: +e.target.value }, `mm:${m.id}`)} /></Field>
            <NumField label={t('mat_uv')} min={0.001} value={m.uv_scale} onChange={(v) => patch(m.id, { uv_scale: v }, `mu:${m.id}`)} />
            <Select label={t('mat_tex')} value={m.texture} onChange={(v) => patch(m.id, { texture: v })} options={[{ value: null, label: t('mat_no_tex') }, ...textures.map((x) => ({ value: x, label: x }))]} />
            <div className="row wrap">
              <label className="btn small">{t('mat_upload')}<input type="file" accept="image/png,image/jpeg" hidden onChange={upload} /></label>
              {m.texture && <button type="button" className="btn small" onClick={async () => { try { await api.deleteTexture(project.id, m.texture); setTextures((await api.textures(project.id)).textures); patch(m.id, { texture: null }) } catch (e) { setErr(formatError(e)) } }}>{t('remove')} {m.texture}</button>}
            </div>
            <p className="muted">{t('mat_tex_note')}</p>
            <div className="row wrap">
              <button type="button" className="btn primary small" disabled={!selection.length} onClick={assign}>{t('mat_assign')} ({selection.length})</button>
              <button type="button" className="btn danger small" disabled={project.materials.length < 2} onClick={() => remove(m.id)}>{t('delete')}</button>
            </div>
          </Card>
        )}
        {m && <Suspense fallback={<p className="muted">…</p>}><MaterialLab m={m} patch={patch} onChanged={() => api.textures(project.id).then((r) => setTextures(r.textures)).catch(() => {})} /></Suspense>}
      </div>
    </div>
  )
}
