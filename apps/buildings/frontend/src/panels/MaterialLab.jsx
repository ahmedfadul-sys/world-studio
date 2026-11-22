import { useEffect, useState } from 'react'
import { useApp, useJob } from '../store.jsx'
import { Card, Field, JobBox, NumField, Select } from '../ui.jsx'
import { LAB_PRESETS, LAB_USES, presetParams } from '../labPresets.js'
import MatPreview from './MatPreview.jsx'

const FIELDS = ['preset', 'color1', 'color2', 'joint', 'scale', 'roughness', 'metallic', 'bump', 'variation', 'seed', 'resolution', 'tile_m']
const fromMat = (m) => (m.lab ? Object.fromEntries(FIELDS.map((k) => [k, m.lab[k]])) : presetParams('brick'))

/** Material Lab: pick a preset, tweak a few sliders, Blender bakes tileable PBR maps (colour, normal, roughness / metal). */
export default function MaterialLab({ m, patch, onChanged }) {
  const app = useApp()
  const { t, project } = app
  const job = useJob()
  const [P, setP] = useState(() => fromMat(m))
  useEffect(() => { setP(fromMat(m)) }, [m.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const up = (o) => setP((x) => ({ ...x, ...o }))
  const uses = LAB_USES[P.preset] || {}
  const has = !!(m.texture || m.normal_texture || m.rough_texture)

  const generate = async () => {
    const res = await job.run('/api/materials/generate', { material_id: m.id, lab: P })
    if (!res) return
    const f = res.files
    patch(m.id, { texture: f.texture, normal_texture: f.normal_texture, rough_texture: f.rough_texture, uv_scale: res.uv_scale, lab: res.lab, color: P.color1, roughness: P.roughness, metallic: P.metallic })
    onChanged && onChanged()
    app.toast(t('lab_done'), 'info')
  }
  const clear = () => patch(m.id, { texture: null, normal_texture: null, rough_texture: null, lab: null })

  return (
    <Card title={t('lab_title')}>
      <MatPreview pid={project.id} mat={m} />
      <p className="muted small">{t('lab_hint')}</p>
      <div className="lab-presets" role="group" aria-label={t('lab_preset')}>
        {LAB_PRESETS.map((k) => (
          <button key={k} type="button" className={`btn small ${P.preset === k ? 'primary' : ''}`} aria-pressed={P.preset === k} data-lab-preset={k} onClick={() => setP(presetParams(k, P))}>{t('lab_p_' + k)}</button>
        ))}
      </div>
      <div className="lab-colors">
        <Field label={t('lab_c1')}><input type="color" value={P.color1} onChange={(e) => up({ color1: e.target.value })} /></Field>
        <Field label={t('lab_c2')}><input type="color" value={P.color2} onChange={(e) => up({ color2: e.target.value })} /></Field>
        {uses.joint && <Field label={t(uses.joint)}><input type="color" value={P.joint} onChange={(e) => up({ joint: e.target.value })} /></Field>}
      </div>
      {uses.scale && <Field label={`${t(uses.scale)}: ${P.scale}`}><input type="range" min={uses.even ? 2 : 1} max={16} step={uses.even ? 2 : 1} value={P.scale} onChange={(e) => up({ scale: +e.target.value })} /></Field>}
      <Field label={`${t('mat_rough')}: ${P.roughness}`}><input type="range" min={0} max={1} step={0.05} value={P.roughness} onChange={(e) => up({ roughness: +e.target.value })} /></Field>
      <Field label={`${t('mat_metal')}: ${P.metallic}`}><input type="range" min={0} max={1} step={0.05} value={P.metallic} onChange={(e) => up({ metallic: +e.target.value })} /></Field>
      <Field label={`${t('lab_bump')}: ${P.bump}`}><input type="range" min={0} max={3} step={0.1} value={P.bump} onChange={(e) => up({ bump: +e.target.value })} /></Field>
      <Field label={`${t('lab_var')}: ${P.variation}`}><input type="range" min={0} max={1} step={0.05} value={P.variation} onChange={(e) => up({ variation: +e.target.value })} /></Field>
      <div className="rw-size">
        <Field label={t('lab_seed')}><NumField value={P.seed} min={0} max={999} step={1} onChange={(v) => up({ seed: Math.round(v) })} /></Field>
        <button type="button" className="btn small" title={t('lab_random')} aria-label={t('lab_random')} onClick={() => up({ seed: Math.floor(Math.random() * 1000) })}>🎲</button>
        <Field label={t('lab_tile')}><NumField value={P.tile_m} min={0.1} max={20} onChange={(v) => up({ tile_m: v })} /></Field>
      </div>
      <Select label={t('lab_res')} value={P.resolution} onChange={(v) => up({ resolution: Number(v) })} options={[512, 1024, 2048].map((r) => ({ value: r, label: `${r} × ${r}` }))} />
      <div className="row wrap">
        <button type="button" className="btn primary" data-testid="lab-generate" disabled={job.busy} onClick={generate}>{t('lab_generate')}</button>
        {has && <button type="button" className="btn small" onClick={clear}>{t('lab_clear')}</button>}
      </div>
      <JobBox job={job} />
      <p className="muted small">{t('lab_note')}</p>
    </Card>
  )
}
