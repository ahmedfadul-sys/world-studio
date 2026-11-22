import { useState } from 'react'
import { useApp, useJob } from '../store.jsx'
import { api } from '../api.js'
import { Card, Field, JobBox, NeedProject, NumField, Select, Stat, Toggle } from '../ui.jsx'

export default function Export() {
  const app = useApp()
  const { project, t } = app
  const job = useJob()
  const [lv, setLv] = useState(null) // null = all levels
  const [sc, setSc] = useState({ res_dir: '', door_open_deg: 100, player: true, ground: true, props: true, lights: true })
  const [scene, setScene] = useState(false)
  if (!project) return <NeedProject />
  const ex = project.export
  const set = (patch, key) => app.edit((p) => ({ ...p, export: { ...p.export, ...patch } }), key)
  const picked = lv || project.levels.map((l) => l.id)
  const levelsArg = lv && lv.length !== project.levels.length ? lv : undefined
  const run = () => { setScene(false); return job.run(`/api/export/${ex.format}`, { levels: levelsArg }) }
  const runScene = () => { setScene(true); return job.run('/api/export/scene', { levels: levelsArg, scene: { ...sc, res_dir: sc.res_dir.trim() } }) }
  const v = job.result?.validation
  const files = job.result?.outputs || []

  return (
    <div className="page narrow">
      <h2>{t('exp_title')}</h2>
      <Card>
        <Select label={t('exp_format')} value={ex.format} onChange={(f) => set({ format: f })} options={[{ value: 'glb', label: 'GLB (recommended)' }, { value: 'gltf', label: 'glTF + .bin' }, { value: 'fbx', label: 'FBX' }]} />
        {ex.format === 'fbx' && <p className="muted">{t('exp_fbx_note')}</p>}
        <Select label={t('exp_axis')} value={ex.up_axis} onChange={(a) => set({ up_axis: a })} options={[{ value: 'Y', label: 'Y-up (Godot / glTF)' }, { value: 'Z', label: 'Z-up' }]} />
        <Select label={t('exp_rotate')} value={String(ex.rotate_deg || 0)} onChange={(v) => set({ rotate_deg: Number(v) })} options={['0', '90', '180', '270'].map((v) => ({ value: v, label: `${v}°` }))} />
        <label className="toggle"><input type="checkbox" checked={!!ex.mirror_x} onChange={(e) => set({ mirror_x: e.target.checked })} />{t('exp_mirror')}</label>
        <Select label={t('exp_pivot')} value={ex.pivot} onChange={(p) => set({ pivot: p })} options={[['base_center', 'exp_p_base'], ['center', 'exp_p_center'], ['world_origin', 'exp_p_world'], ['min_corner', 'exp_p_min']].map(([x, k]) => ({ value: x, label: t(k) }))} />
        <NumField label={t('exp_scale')} value={ex.scale} min={0.0001} onChange={(s) => set({ scale: s }, 'scale')} />
        <Select label={t('opt_preset')} value={ex.poly_preset} onChange={(x) => set({ poly_preset: x })} options={['low', 'medium', 'high'].map((x) => ({ value: x, label: t('opt_' + x) }))} />
        <Toggle checked={ex.split_per_level} label={t('exp_split')} onChange={(x) => set({ split_per_level: x })} />
        <Toggle checked={ex.keep_blend} label={t('exp_blend')} onChange={(x) => set({ keep_blend: x })} />
        {project.levels.length > 1 && (
          <Field label={t('levels_subset')}>
            <div className="row wrap">{project.levels.map((l) => (
              <Toggle key={l.id} checked={picked.includes(l.id)} label={l.name} onChange={(c) => { const n = c ? [...picked, l.id] : picked.filter((x) => x !== l.id); setLv(n.length ? n : picked) }} />
            ))}</div>
          </Field>
        )}
        <div className="row"><button type="button" className="btn primary" disabled={job.busy} onClick={run}>{job.busy ? t('running') : t('exp_run')}</button></div>
      </Card>
      <Card title={t('sc_title')}>
        <p className="muted small">{t('sc_hint')}</p>
        <Field label={t('sc_resdir')}><input type="text" dir="ltr" value={sc.res_dir} placeholder={`res://bim/${project.name.replace(/[^A-Za-z0-9_-]+/g, '_')}/`} data-testid="sc-resdir" onChange={(e) => setSc({ ...sc, res_dir: e.target.value })} /></Field>
        <NumField label={t('sc_open')} value={sc.door_open_deg} min={30} max={120} step={5} onChange={(v) => setSc({ ...sc, door_open_deg: v })} />
        <div className="row wrap">
          <Toggle checked={sc.player} label={t('sc_player')} onChange={(v) => setSc({ ...sc, player: v })} />
          <Toggle checked={sc.ground} label={t('sc_ground')} onChange={(v) => setSc({ ...sc, ground: v })} />
          <Toggle checked={sc.props} label={t('sc_props')} onChange={(v) => setSc({ ...sc, props: v })} />
          <Toggle checked={sc.lights} label={t('sc_lights')} onChange={(v) => setSc({ ...sc, lights: v })} />
        </div>
        <div className="row"><button type="button" className="btn primary" data-testid="sc-run" disabled={job.busy} onClick={runScene}>{job.busy && scene ? t('running') : t('sc_run')}</button></div>
      </Card>
      <JobBox job={job} />
      {job.result?.scene && <Card title={t('sc_done')}><p className="small">{t('sc_how')} <code dir="ltr">{job.result.scene.res_dir}</code></p><p className="small">{t('sc_doors')}: {job.result.scene.doors}</p></Card>}
      {job.result && v && (
        <Card title={t('exp_valid')}>
          <div className="stats"><Stat label={t('exp_nodes')} value={v.nodes ?? '—'} /><Stat label={t('exp_meshes')} value={v.meshes ?? '—'} /><Stat label={t('exp_mats')} value={v.materials ?? '—'} /><Stat label={t('col_objects')} value={v.collision_nodes?.length ?? '—'} /><Stat label={t('triangles')} value={job.result.triangles.visual} /></div>
          <h4>{t('exp_files')}</h4>
          {files.map((f) => <div key={f} className="row between"><span>{f.split('/').pop()}</span><a className="btn small" href={api.fileUrl(project.id, f)} download>{t('download')}</a></div>)}
          <p className="muted">{t('exp_godot_note')}</p>
        </Card>
      )}
    </div>
  )
}
